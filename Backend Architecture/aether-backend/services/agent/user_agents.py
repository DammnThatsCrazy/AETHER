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
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, ForbiddenError, NotFoundError
from shared.events.events import Event, EventEnvelopeV2, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_cache, get_graph, get_producer
from repositories.repos import (
    AgentConfigRepository,
    AgentExecutionRepository,
    DelegationRepository,
)
from services.delegation.engine import DelegationEngine

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
    payload: dict[str, Any] = Field(default_factory=dict)
    triggered_by_event_id: Optional[str] = None
    # Optional: if the agent already produced reasoning/confidence at the
    # caller layer, pass it through so it lands on the execution record.
    reasoning: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


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
    await graph.upsert_vertex(Vertex(
        vertex_type=VertexType.AGENT,
        vertex_id=agent_id,
        properties={
            "tenant_id": tenant.tenant_id,
            "owner_entity_id": body.owner_entity_id,
            "model": body.model,
            "risk_tolerance": body.risk_tolerance,
        },
    ))
    await graph.add_edge(Edge(
        edge_type=EdgeType.OWNS,
        from_vertex_id=body.owner_entity_id,
        to_vertex_id=agent_id,
        properties={"tenant_id": tenant.tenant_id, "kind": "agent"},
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

    decision = await engine.evaluate(
        grantee_entity_id=agent_id,
        action=body.action,
        resource=body.resource,
        amount=body.amount,
    )
    if not decision.allowed:
        # Reject is recorded as a failed execution row so the timeline is complete.
        rejected_id = str(uuid.uuid4())
        await _executions.record(
            execution_id=rejected_id,
            agent_id=agent_id,
            tenant_id=tenant.tenant_id,
            delegation_id=None,
            triggered_by_event_id=body.triggered_by_event_id,
            status="revoked",
            reasoning="rejected by delegation engine: " + decision.reason,
            confidence=0.0,
            input_snapshot={
                "action": body.action,
                "resource": body.resource,
                "amount": body.amount,
            },
            error={"code": decision.reason},
        )
        await producer.publish(Event(
            topic=Topic.AGENT_EXECUTION_FAILED,
            tenant_id=tenant.tenant_id,
            source_service="agents",
            payload={
                "agent_id": agent_id,
                "execution_id": rejected_id,
                "reason": decision.reason,
                "action": body.action,
                "resource": body.resource,
            },
        ))
        raise ForbiddenError(
            f"Delegation check failed for action={body.action} resource={body.resource} "
            f"reason={decision.reason}"
        )

    execution_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    # Execution started — emit event with v2 envelope so consumers see the full context.
    started = Event(
        topic=Topic.AGENT_EXECUTION_STARTED,
        tenant_id=tenant.tenant_id,
        source_service="agents",
        payload={
            "agent_id": agent_id,
            "execution_id": execution_id,
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
    await producer.publish(started)

    # The actual execution runtime is out of scope for this layer — Profile 360
    # only owns the bookkeeping. Callers may follow up with `/executions/{id}`
    # PATCH-style updates as the runtime progresses; v1 here records the
    # synchronous "started" row, treating the immediate response as the result
    # of a succeeded planning step.
    record = await _executions.record(
        execution_id=execution_id,
        agent_id=agent_id,
        tenant_id=tenant.tenant_id,
        delegation_id=decision.delegation_id,
        triggered_by_event_id=body.triggered_by_event_id,
        status="running",
        reasoning=body.reasoning,
        confidence=body.confidence,
        policy_log={
            "delegation_check": decision.to_dict(),
            "constraints": config.get("constraints"),
        },
        input_snapshot={
            "action": body.action,
            "resource": body.resource,
            "amount": body.amount,
            "payload": body.payload,
        },
        started_at=started_at,
    )

    try:
        await graph.add_edge(Edge(
            edge_type=EdgeType.EXECUTED,
            from_vertex_id=agent_id,
            to_vertex_id=execution_id,
            properties={
                "tenant_id": tenant.tenant_id,
                "delegation_id": decision.delegation_id or "",
                "action": body.action,
            },
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
    rows = await _executions.list_for_agent(agent_id, limit=min(limit, 500))
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
