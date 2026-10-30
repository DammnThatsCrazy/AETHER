"""
User/Org-owned LLM agents — Profile 360 layer.

This is distinct from the existing AgentController workers (WEB_CRAWLER,
ENTITY_RESOLVER, …) which are *system* workers. User agents have:
  - a config (model, tools, constraints, risk_tolerance)
  - explicit ownership (owner_entity_id)
  - executions logged with reasoning + confidence + policy log
  - delegation validation enforced before each execution

Endpoints (mounted under /v1/agents — distinct from the singular /v1/agent):
    POST  /v1/agents                                  Register
    GET   /v1/agents/{agent_id}
    PATCH /v1/agents/{agent_id}
    POST  /v1/agents/{agent_id}/execute               Run (delegation-validated)
    GET   /v1/agents/{agent_id}/executions
    GET   /v1/agents/{agent_id}/executions/{execution_id}
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from shared.common.common import APIResponse, BadRequestError, ConflictError, ForbiddenError, NotFoundError
from shared.events.events import Event, EventEnvelopeV2, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_cache, get_graph, get_producer
from repositories.repos import (
    AgentConfigRepository,
    AgentExecutionRepository,
    DelegationRepository,
)
from actions.delegation.engine import DelegationEngine
from actions.agent.action_associations import (
    JourneyActionReference,
    RiskActionReference,
    validate_action_association,
)

logger = get_logger("aether.service.agent.user")
router = APIRouter(prefix="/v1/agents", tags=["Profile 360 / Agents"])

_configs = AgentConfigRepository()
_executions = AgentExecutionRepository()
_delegations: Optional[DelegationRepository] = None
_engine: Optional[DelegationEngine] = None


def _get_delegations(cache=Depends(get_cache)) -> DelegationRepository:
    global _delegations
    if _delegations is None:
        _delegations = DelegationRepository(cache=cache)
    return _delegations


def _get_engine(repo: DelegationRepository = Depends(_get_delegations)) -> DelegationEngine:
    global _engine
    if _engine is None:
        _engine = DelegationEngine(repo)
    return _engine


# ── Request models ─────────────────────────────────────────────────────

class AgentRegister(BaseModel):
    agent_id: str = ""
    owner_entity_id: str
    model: str
    tools: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    risk_tolerance: str = Field(default="medium", pattern="^(low|medium|high)$")


class AgentUpdate(BaseModel):
    model: Optional[str] = None
    tools: Optional[list[str]] = None
    constraints: Optional[dict[str, Any]] = None
    risk_tolerance: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")


class AgentExecute(BaseModel):
    action: str = Field(..., min_length=1)
    resource: str = Field(..., min_length=1)
    amount: Optional[str] = None
    approval_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    # Optional stable execution ID. A workflow link is accepted only when the
    # canonical AI invocation fact explicitly carries this value as action_id.
    execution_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    journey_action_reference: Optional[JourneyActionReference] = None
    risk_action_reference: Optional[RiskActionReference] = None
    # This is a caller-reported association with a registered definition,
    # never evidence that the definition's triggers or steps executed.
    workflow_definition_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    workflow_definition_revision: Optional[int] = Field(default=None, ge=1)
    workflow_definition_digest: Optional[str] = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    triggered_by_event_id: Optional[str] = None
    # Optional: if the agent already produced reasoning/confidence at the
    # caller layer, pass it through so it lands on the execution record.
    reasoning: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def complete_workflow_definition_reference(self) -> "AgentExecute":
        reference = (
            self.workflow_definition_id,
            self.workflow_definition_revision,
            self.workflow_definition_digest,
        )
        if any(value is not None for value in reference) and not all(
            value is not None for value in reference
        ):
            raise ValueError("workflow definition reference requires id, revision and digest")
        return self


async def _canonical_workflow_run_link(
    *, tenant_id: str, agent_id: str, execution_id: str
) -> tuple[Optional[str], list[str]]:
    """Resolve only an explicit canonical invocation action_id → execution ID link.

    The caller-provided execution ID is only a lookup key. It is never used as
    workflow evidence by itself. Every returned invocation must match the exact
    tenant, agent, action ID and one unambiguous workflow run.
    """
    if not tenant_id or not agent_id or not execution_id:
        return None, []
    try:
        from config.settings import settings
        from value.economic.ai_aggregation import list_facts

        if not settings.ai_economics.execution_facts_enabled:
            return None, []
        facts = await list_facts(tenant_id, action_id=execution_id, limit=201)
    except Exception:  # noqa: BLE001 - optional telemetry cannot block execution
        logger.debug("workflow execution linkage unavailable", exc_info=True)
        return None, []

    if not isinstance(facts, list) or len(facts) > 200:
        return None, []
    workflow_run_ids: set[str] = set()
    invocation_ids: set[str] = set()
    for fact in facts:
        if (
            not isinstance(fact, dict)
            or fact.get("tenant_id") != tenant_id
            or fact.get("action_id") != execution_id
            or fact.get("agent_id") != agent_id
        ):
            return None, []
        workflow_run_id = fact.get("workflow_run_id")
        invocation_id = fact.get("invocation_id")
        if (
            not isinstance(workflow_run_id, str)
            or not workflow_run_id.strip()
            or len(workflow_run_id) > 256
            or not isinstance(invocation_id, str)
            or not invocation_id.strip()
            or len(invocation_id) > 256
        ):
            return None, []
        workflow_run_ids.add(workflow_run_id)
        invocation_ids.add(invocation_id)
    if not facts or len(workflow_run_ids) != 1 or not invocation_ids:
        return None, []
    return next(iter(workflow_run_ids)), sorted(invocation_ids)


async def _validate_reported_workflow_definition_link(
    *,
    tenant_id: str,
    agent_id: str,
    workflow_run_id: Optional[str],
    body: AgentExecute,
    anchor: datetime,
    repository: Any = None,
) -> Optional[dict[str, Any]]:
    """Bind a caller's exact definition reference to one registered revision.

    The AI invocation run link and canonical definition are checked separately.
    This still records only what the caller reported, not workflow execution.
    """
    if body.workflow_definition_id is None:
        return None
    if not workflow_run_id:
        raise BadRequestError("Workflow definition reference requires an exact run link")
    from intelligence.workflow.definitions import (
        WorkflowDefinitionRepository,
        WorkflowDefinitionRevision,
        workflow_definition_evidence,
    )

    try:
        read = await (repository or WorkflowDefinitionRepository()).read_as_of(
            tenant_id, body.workflow_definition_id, anchor
        )
    except Exception as exc:  # noqa: BLE001 - unavailable definition fails closed
        raise ConflictError("Workflow definition authority is unavailable") from exc
    if not read.available or not read.complete or read.reason or len(read.rows) != 1:
        raise ConflictError("Exact workflow definition revision is unavailable")
    raw = read.rows[0]
    if not isinstance(raw, dict):
        raise ConflictError("Exact workflow definition revision is unavailable")
    try:
        definition = WorkflowDefinitionRevision.model_validate(
            {key: raw[key] for key in WorkflowDefinitionRevision.model_fields if key in raw}
        )
    except Exception as exc:  # noqa: BLE001 - malformed authority fails closed
        raise ConflictError("Exact workflow definition revision is invalid") from exc
    evidence = workflow_definition_evidence(definition)
    if (
        definition.tenant_id != tenant_id
        or definition.workflow_id != body.workflow_definition_id
        or definition.revision != body.workflow_definition_revision
        or definition.definition_digest != body.workflow_definition_digest
        or definition.status != "active"
        or definition.created_at > anchor
        or (definition.effective_at is not None and definition.effective_at > anchor)
        or raw.get("tenant_id") != tenant_id
        or raw.get("subject_ref") != definition.workflow_id
        or raw.get("record_id") != definition.record_id
        or raw.get("definition_digest") != definition.definition_digest
        or evidence is None
        or not any(step.kind == "agent" and step.agent_ref == agent_id for step in definition.steps)
    ):
        raise BadRequestError("Workflow definition reference does not match this agent and run")
    return {
        "association_kind": "caller_reported_exact_definition_reference",
        "workflow_run_id": workflow_run_id,
        "workflow_id": definition.workflow_id,
        "revision": definition.revision,
        "definition_record_id": definition.record_id,
        "definition_digest": definition.definition_digest,
        "definition_evidence_ref": evidence.model_dump(mode="json"),
        "reference_checked_at": anchor.isoformat(),
    }


async def _validate_execution_approval(
    *, tenant_id: str, agent_id: str, body: AgentExecute
) -> tuple[Optional[str], Optional[str]]:
    """Resolve an exact current x402 approval before recording a linked run."""
    if body.approval_id is None:
        return None, None

    from value.x402.commerce_models import ApprovalStatus
    from value.x402.commerce_store import get_commerce_store

    store = get_commerce_store()
    approval = await store.get_approval(tenant_id, body.approval_id)
    if (
        approval is None
        or approval.tenant_id != tenant_id
        or approval.execution_id is None
        or approval.execution_action != body.action
        or approval.resource_id != body.resource
        or approval.requester_type != "agent"
        or approval.requester_id != agent_id
        or approval.status != ApprovalStatus.APPROVED
        or not approval.last_decision_id
    ):
        raise ForbiddenError("Approval is not valid for this exact agent execution")

    try:
        requested_amount = Decimal(body.amount) if body.amount is not None else None
        approved_amount = Decimal(str(approval.amount_usd))
    except (InvalidOperation, ValueError):
        raise BadRequestError("A numeric amount matching the approval is required")
    if requested_amount is None or not requested_amount.is_finite() or requested_amount != approved_amount:
        raise ForbiddenError("Execution amount does not match the approved amount")

    decision = await store.get_approval_decision(tenant_id, approval.last_decision_id)
    if (
        decision is None
        or decision.tenant_id != tenant_id
        or decision.approval_id != approval.approval_id
        or decision.execution_id != approval.execution_id
        or decision.action != "approve"
        or decision.decision_id != approval.last_decision_id
    ):
        raise ForbiddenError("Canonical approval decision evidence is unavailable or conflicted")

    existing = await _executions.find_by_id(approval.execution_id)
    if existing is not None:
        raise ConflictError("This approved execution ID has already been recorded")
    return approval.execution_id, decision.decision_id


class AgentExecutionOutcome(BaseModel):
    """Trusted executor callback for a previously started user-agent run."""

    status: str = Field(..., pattern="^(completed|failed)$")
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)


class AgentToolInvocation(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("")
async def register(
    body: AgentRegister,
    request: Request,
    graph: GraphClient = Depends(get_graph),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    agent_id = body.agent_id or str(uuid.uuid4())
    record = await _configs.register(
        agent_id=agent_id,
        owner_entity_id=body.owner_entity_id,
        tenant_id=tenant.tenant_id,
        model=body.model,
        tools=body.tools,
        constraints=body.constraints,
        risk_tolerance=body.risk_tolerance,
    )
    # Project agent + ownership.
    gateway = GraphMutationGateway(graph_client=graph)
    await gateway.apply(vertex_intent(
        Vertex(
            vertex_type=VertexType.AGENT,
            vertex_id=agent_id,
            properties={
                "tenant_id": tenant.tenant_id,
                "owner_entity_id": body.owner_entity_id,
                "model": body.model,
                "risk_tolerance": body.risk_tolerance,
            },
        ),
        operation="node_versioned", tenant_id=tenant.tenant_id,
        actor_kind="human", actor_id="user_agents_api",
    ))
    await gateway.apply(edge_intent(
        Edge(
            edge_type=EdgeType.OWNS,
            from_vertex_id=body.owner_entity_id,
            to_vertex_id=agent_id,
            # OWNS is an H2A ownership edge — consent_purpose required in enforce.
            properties={
                "tenant_id": tenant.tenant_id,
                "kind": "agent",
                "consent_purpose": "agent",
            },
        ),
        operation="edge_created", tenant_id=tenant.tenant_id,
        actor_kind="human", actor_id="user_agents_api",
        subject_kind="entity", subject_id=body.owner_entity_id,
    ))
    metrics.increment("user_agents_registered")
    return APIResponse(data=record).to_dict()


@router.get("/{agent_id}")
async def read(agent_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _configs.find_by_id(agent_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")
    return APIResponse(data=record).to_dict()


@router.patch("/{agent_id}")
async def update(agent_id: str, body: AgentUpdate, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    existing = await _configs.find_by_id(agent_id)
    if existing is None or existing.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "tools" in patch or "constraints" in patch or "risk_tolerance" in patch:
        patch["policy_version"] = (existing.get("policy_version") or 1) + 1
    updated = await _configs.update(agent_id, patch)
    return APIResponse(data=updated).to_dict()


@router.post("/{agent_id}/execute")
async def execute(
    agent_id: str,
    body: AgentExecute,
    request: Request,
    engine: DelegationEngine = Depends(_get_engine),
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    """Run an agent with delegation validation enforced before execution."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    config = await _configs.find_by_id(agent_id)
    if config is None or config.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")

    approval_execution_id, approval_decision_id = await _validate_execution_approval(
        tenant_id=tenant.tenant_id,
        agent_id=agent_id,
        body=body,
    )
    if (
        approval_execution_id is not None
        and body.execution_id is not None
        and body.execution_id != approval_execution_id
    ):
        raise BadRequestError("Execution ID does not match the approved execution")
    execution_id = approval_execution_id or body.execution_id or str(uuid.uuid4())
    try:
        action_association = await validate_action_association(
            tenant_id=tenant.tenant_id, action=body.action, resource=body.resource,
            journey=body.journey_action_reference, risk=body.risk_action_reference,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    workflow_run_id, workflow_run_invocation_ids = await _canonical_workflow_run_link(
        tenant_id=tenant.tenant_id,
        agent_id=agent_id,
        execution_id=execution_id,
    )
    definition_link = await _validate_reported_workflow_definition_link(
        tenant_id=tenant.tenant_id,
        agent_id=agent_id,
        workflow_run_id=workflow_run_id,
        body=body,
        anchor=datetime.now(timezone.utc),
    )

    decision = await engine.evaluate(
        grantee_entity_id=agent_id,
        action=body.action,
        resource=body.resource,
        amount=body.amount,
        tenant_id=tenant.tenant_id,
    )
    if not decision.allowed:
        # Reject is recorded as a failed execution row so the timeline is complete.
        rejected_id = execution_id
        await _executions.record(
            execution_id=rejected_id,
            agent_id=agent_id,
            tenant_id=tenant.tenant_id,
            initiating_principal_user_id=getattr(tenant, "user_id", None),
            workflow_run_id=workflow_run_id,
            workflow_run_invocation_ids=workflow_run_invocation_ids,
            workflow_definition_link=definition_link,
            delegation_id=decision.delegation_id,
            triggered_by_event_id=body.triggered_by_event_id,
            status="revoked",
            reasoning="rejected by delegation engine: " + decision.reason,
            confidence=0.0,
            policy_log={
                "delegation_check": decision.to_dict(),
                "delegation_check_tenant_id": tenant.tenant_id,
                "constraints": config.get("constraints"),
            },
            input_snapshot={
                "action": body.action,
                "resource": body.resource,
                "amount": body.amount,
            },
            error={"code": decision.reason},
            approval_id=body.approval_id,
            approval_decision_id=approval_decision_id,
            action_association=action_association,
            create_only=approval_execution_id is not None or body.execution_id is not None or action_association is not None,
        )
        await producer.publish(Event(
            topic=Topic.AGENT_EXECUTION_FAILED,
            tenant_id=tenant.tenant_id,
            source_service="agents",
            payload={
                "agent_id": agent_id,
                "execution_id": rejected_id,
                "approval_id": body.approval_id,
                "approval_decision_id": approval_decision_id,
                "reason": decision.reason,
                "action": body.action,
                "resource": body.resource,
            },
        ))
        raise ForbiddenError(
            f"Delegation check failed for action={body.action} resource={body.resource} "
            f"reason={decision.reason}"
        )

    started_at = datetime.now(timezone.utc).isoformat()

    # Execution started — emit event with v2 envelope so consumers see the full context.
    started = Event(
        topic=Topic.AGENT_EXECUTION_STARTED,
        tenant_id=tenant.tenant_id,
        source_service="agents",
        payload={
            "agent_id": agent_id,
            "execution_id": execution_id,
            "approval_id": body.approval_id,
            "approval_decision_id": approval_decision_id,
            "action": body.action,
            "resource": body.resource,
        },
    ).with_v2(EventEnvelopeV2(
        actor={"entity_id": agent_id, "entity_type": "agent"},
        beneficiary={"entity_id": config["owner_entity_id"], "entity_type": "human"},
        delegation={
            "delegation_id": decision.delegation_id,
            "scope": decision.matched_scope,
            "granted_by_entity_id": config["owner_entity_id"],
        },
        agent_intelligence={
            "agent_id": agent_id,
            "reasoning": body.reasoning,
            "confidence": body.confidence,
            "policy_log_ref": None,
        },
        causality={"triggered_by_event_id": body.triggered_by_event_id},
    ))
    # This route owns admission and bookkeeping only; it does not invoke an
    # agent tool or resource operation. The returned AgentExecution and its
    # later worker callback therefore cannot serve as an invocation receipt.
    # A receipt producer must be wired into the runtime's actual tool/resource
    # call boundary before Agent360 or Workflow360 can report those claims.
    record = await _executions.record(
        execution_id=execution_id,
        agent_id=agent_id,
        tenant_id=tenant.tenant_id,
        initiating_principal_user_id=getattr(tenant, "user_id", None),
        workflow_run_id=workflow_run_id,
        workflow_run_invocation_ids=workflow_run_invocation_ids,
        workflow_definition_link=definition_link,
        delegation_id=decision.delegation_id,
        triggered_by_event_id=body.triggered_by_event_id,
        status="running",
        reasoning=body.reasoning,
        confidence=body.confidence,
        policy_log={
            "delegation_check": decision.to_dict(),
            "delegation_check_tenant_id": tenant.tenant_id,
            "constraints": config.get("constraints"),
        },
        input_snapshot={
            "action": body.action,
            "resource": body.resource,
            "amount": body.amount,
            "payload": body.payload,
        },
        started_at=started_at,
        approval_id=body.approval_id,
        approval_decision_id=approval_decision_id,
        action_association=action_association,
        create_only=approval_execution_id is not None or body.execution_id is not None or action_association is not None,
    )

    await producer.publish(started)

    try:
        await GraphMutationGateway(graph_client=graph).apply(edge_intent(
            Edge(
                edge_type=EdgeType.EXECUTED,
                from_vertex_id=agent_id,
                to_vertex_id=execution_id,
                properties={
                    "tenant_id": tenant.tenant_id,
                    "delegation_id": decision.delegation_id or "",
                    "action": body.action,
                },
            ),
            operation="edge_created", tenant_id=tenant.tenant_id,
            actor_kind="agent", actor_id=agent_id,
            subject_kind="agent", subject_id=agent_id,
        ))
    except Exception as e:  # pragma: no cover
        logger.warning(f"Graph projection failed for execution {execution_id}: {e}")

    metrics.increment("user_agent_executions_started")
    return APIResponse(data=record).to_dict()


@router.get("/{agent_id}/executions")
async def list_executions(
    agent_id: str,
    request: Request,
    limit: int = 50,
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    config = await _configs.find_by_id(agent_id)
    if config is None or config.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Agent")
    rows = await _executions.list_for_agent(agent_id, tenant.tenant_id, limit=min(limit, 500))
    return APIResponse(data={
        "agent_id": agent_id,
        "executions": rows,
        "count": len(rows),
    }).to_dict()


@router.get("/{agent_id}/executions/{execution_id}")
async def read_execution(agent_id: str, execution_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _executions.find_by_id(execution_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id \
            or record.get("agent_id") != agent_id:
        raise NotFoundError("Execution")
    return APIResponse(data=record).to_dict()


@router.post("/{agent_id}/executions/{execution_id}/tools/{tool_name}/invoke")
async def invoke_agent_tool(agent_id: str, execution_id: str, tool_name: str,
                            body: AgentToolInvocation, request: Request,
                            engine: DelegationEngine = Depends(_get_engine)):
    """Authenticated server-side MCP invocation; receipts come from the provider call."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    tenant.require_permission("dispatch")
    principal = getattr(tenant, "user_id", None)
    if not isinstance(principal, str) or not principal or principal != principal.strip():
        raise ForbiddenError("Tool invocation requires an authenticated principal")
    config = await _configs.find_by_id(agent_id)
    execution = await _executions.find_by_id(execution_id)
    if (config is None or config.get("tenant_id") != tenant.tenant_id
            or execution is None or execution.get("tenant_id") != tenant.tenant_id
            or execution.get("agent_id") != agent_id):
        raise NotFoundError("Execution")
    if execution.get("status") != "running":
        raise ConflictError("Tool invocation requires a running execution")
    from actions.agent.invocation_runtime import invoke_observed_mcp_tool
    receipt = await invoke_observed_mcp_tool(
        tenant_id=tenant.tenant_id, agent_id=agent_id, execution_id=execution_id,
        tool_name=tool_name, arguments=body.arguments, config=config, engine=engine,
        workflow_run_id=execution.get("workflow_run_id"),
        workflow_definition_link=execution.get("workflow_definition_link"),
        initiating_principal_user_id=principal,
    )
    return APIResponse(data=receipt).to_dict()


@router.post("/{agent_id}/executions/{execution_id}/status")
async def update_execution_status(
    agent_id: str,
    execution_id: str,
    body: AgentExecutionOutcome,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Persist and publish an authoritative executor outcome.

    Only a worker credential with ``agent:run_update`` may finalize a run.
    Repeated callbacks for the same terminal state are idempotent; a terminal
    outcome cannot be rewritten to a conflicting state.
    """
    tenant = request.state.tenant
    tenant.require_permission("agent:run_update")

    record = await _executions.find_by_id(execution_id)
    if (
        record is None
        or record.get("tenant_id") != tenant.tenant_id
        or record.get("agent_id") != agent_id
    ):
        raise NotFoundError("Execution")
    terminal = record.get("status") in {"completed", "failed"}
    if terminal:
        if record.get("status") != body.status:
            raise ConflictError("Execution already has a different terminal outcome")
        if record.get("outcome_event_published"):
            return APIResponse(data=record).to_dict()
    elif record.get("status") != "running":
        raise ConflictError("Only a running execution can be finalized")

    from actions.agent.runtime_repository import sanitize_payload, utc_now

    if not terminal:
        now = utc_now()
        output = sanitize_payload(body.output)
        error = sanitize_payload(body.error)
        outcome_event_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"aether:agent-execution:{tenant.tenant_id}:{execution_id}:{body.status}",
        ))
        record = await _executions.update(execution_id, {
            "status": body.status,
            "output": output,
            "error": error if body.status == "failed" else None,
            "ended_at": now,
            "outcome_event_id": outcome_event_id,
            "outcome_event_published": False,
        })
    else:
        error = dict(record.get("error") or {})
        if not record.get("outcome_event_id"):
            record = await _executions.update(execution_id, {
                "outcome_event_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"aether:agent-execution:{tenant.tenant_id}:{execution_id}:{body.status}",
                )),
                "outcome_event_published": False,
            })
    config = await _configs.find_by_id(agent_id) or {}
    owner_entity_id = str(config.get("owner_entity_id") or "")
    failed = body.status == "failed"
    lifecycle = Event(
        topic=Topic.AGENT_EXECUTION_FAILED if failed else Topic.AGENT_EXECUTION_COMPLETED,
        tenant_id=tenant.tenant_id,
        event_id=record.get("outcome_event_id"),
        source_service="agents",
        payload={
            "agent_id": agent_id,
            "execution_id": execution_id,
            "delegation_id": record.get("delegation_id"),
            "action": (record.get("input_snapshot") or {}).get("action"),
            "resource": (record.get("input_snapshot") or {}).get("resource"),
            "outcome": "failure" if failed else "success",
            "failure_reason": error.get("code", "executor_failed") if failed else None,
        },
    )
    if owner_entity_id:
        lifecycle = lifecycle.with_v2(EventEnvelopeV2(
            actor={"entity_id": agent_id, "entity_type": "agent"},
            beneficiary={"entity_id": owner_entity_id, "entity_type": "human"},
            delegation={
                "delegation_id": record.get("delegation_id"),
                "granted_by_entity_id": owner_entity_id,
            },
            causality={"triggered_by_event_id": record.get("triggered_by_event_id")},
        ))
    await producer.publish(lifecycle)
    record = await _executions.update(execution_id, {"outcome_event_published": True})
    return APIResponse(data=record).to_dict()
