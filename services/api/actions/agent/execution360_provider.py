"""Read-only Execution360 projection over the current agent execution authorities.

The provider joins two distinct kinds of evidence:

* ``agent_executions`` contains AETHER-authored application lifecycle records.
  A terminal row may have been updated by a worker callback, but it is not an
  independent receipt that an external action or business effect occurred.
* ``silver_agent_execution_facts`` contains source-reported telemetry. Actor
  and delegation references are included only after the tenant deployment,
  identity binding, and delegation authorities resolve them.

The system worker-run ledger (``AgentRuntimeRepository.worker_runs``) is
objective/controller bookkeeping. It currently has no canonical join to
``agent_executions`` or external agent runs, so this provider never treats a
queued/completed worker run as an agent execution.

This slice is deliberately read-only and bounded. It omits reasoning, payload,
output, and error bodies, and does not claim business outcomes without the
independent outcome/economic providers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional, Protocol
from urllib.parse import quote

from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    TimeRangeFilter,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry
from graph.operational_intelligence.models import EvidenceRef
from actions.agent.execution360_provenance import (
    ExecutionSourceProvenanceRead,
    read_execution_source_provenance,
)


PROJECTION_ID = "execution360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "evidence",
    "interactions",
    "outcomes",
    "state",
    "summary",
    "timeline",
    "episode_context",
)

# These are the Execution360 product catalog slots and the slots to which this
# provider is bound. Keep in sync with the canonical JSON catalog, not inferred
# from whichever dependency happens to be available.
SLOT_ACTOR_ATTRIBUTION = "actor_attribution"
SLOT_AUTHORITY_CHECK = "authority_check"
SLOT_AGENT_AUTHORITY_ENVELOPE = "authority_envelope"
SLOT_EVIDENCE = "evidence_trace"
SLOT_EXECUTION_STATE = "execution_summary"
SLOT_AGENT_EXECUTION_HISTORY = "execution_history"
SLOT_AGENT_TOOL_USAGE = "tool_usage"
SLOT_TEMPORAL_EPISODE = "plan_steps"
SLOT_LATENCY_COST = "latency_cost"
SLOT_INPUTS_OUTPUTS = "inputs_outputs"
SLOT_FAILURES = "failures"
SLOT_TOOL_CALLS = "tool_calls"
SLOT_APPROVAL_CHAIN = "approval_chain"
SLOT_RISK_EVENTS = "risk_events"

_SERVER_FAILURE_STATUSES = frozenset({"failed", "revoked"})
_SOURCE_REPORTED_FAILURE_STATUSES = frozenset({"failed", "error", "denied", "revoked"})

_MAX_ROWS = 500
_MAX_TOOL_EDGE_SCAN = 10_000
_MAX_EXECUTION_RISK_SIGNAL_SCAN = 1000
_MAX_EXECUTION_RISK_ASSESSMENT_SCAN = 500
_MAX_EXECUTION_APPROVAL_DECISION_SCAN = 5000
_MAX_EXECUTION_COST_SUBJECT_SCAN = 100
_MAX_EXECUTION_COST_FACT_SCAN = 1000
_MAX_EXECUTION_COST_FACTS_PER_SUBJECT = 200
_MAX_PRINCIPAL_IDENTITY_ALIAS_SCAN = 50
_SILVER_QUERY_LIMIT = 1000
_MAX_EPISODE_AGENT_SCAN = 200
_SILVER_SOURCE = "silver_agent_execution_facts"
_INTERNAL_SOURCE = "agent_executions"


async def _resolve_agent_identity_map(
    tenant_id: str, source_agent_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], bool, bool]:
    """Resolve source config IDs through the shared Agent360 identity authority."""
    from actions.agent.deployments import get_deployment_repository
    from actions.agent.identity_resolution import resolve_agent_identities
    from actions.agent_marketplace.identity_binding import (
        AgentDeploymentIdentityBindingRepository,
    )
    from repositories.repos import EntityRepository

    result = await resolve_agent_identities(
        tenant_id,
        source_agent_ids,
        deployments=get_deployment_repository(),
        identity_bindings=AgentDeploymentIdentityBindingRepository(),
        entities=EntityRepository(),
        limit=_MAX_EPISODE_AGENT_SCAN,
    )
    mapping = {
        row["agent_id"]: row
        for row in result.rows
        if isinstance(row.get("agent_id"), str)
        and isinstance(row.get("canonical_agent_entity_id"), str)
    }
    return mapping, result.scope_mismatch, result.truncated


@dataclass(frozen=True)
class ExecutionEpisodeContextRead:
    """Bounded canonical episode context joined to an agent identity."""

    state: Literal["available", "empty", "unknown", "degraded", "unavailable"]
    items: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    identity_evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionToolCallRead:
    """Exact execution-linked AETHER tool-call lifecycle observations."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionRiskEventRead:
    """Bounded canonical RiskSignal read for one exact execution subject."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None
    assessment_read: Optional["ExecutionRiskAssessmentRead"] = None


@dataclass(frozen=True)
class ExecutionRiskAssessmentRead:
    """Bounded RiskAssessment snapshots keyed to exact execution subjects."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionCostRead:
    """Exact action-linked canonical AI invocation facts for executions."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None

    @property
    def state(self) -> Literal["available", "degraded", "unavailable"]:
        if not self.available:
            return "unavailable"
        if self.truncated or not self.scope_known:
            return "degraded"
        return "available"


@dataclass(frozen=True)
class ExecutionApprovalRead:
    """Exact tenant-scoped commerce approval records for admitted runs."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None
    approval_requests: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ExecutionWorkflowRunInvocationRead:
    """Bounded exact AI invocation facts used to validate run links."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionApprovalContext:
    """Evidence-backed x402 approval requests and decisions for executions."""

    state: Literal["partial", "empty", "unknown", "degraded", "unavailable"]
    decisions: tuple[dict[str, Any], ...] = ()
    approval_requests: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None
    source_read_state: Literal["available", "unavailable", "not_read"] = "not_read"
    scope_known: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class ExecutionAuthorityContext:
    """Recorded request-time delegation decisions joined to lifecycle evidence."""

    state: Literal["partial", "unknown", "degraded", "unavailable"]
    decisions: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None
    source_read_state: Literal["available", "unavailable"] = "available"
    scope_known: bool = False
    truncated: bool = False
    ambiguous_execution_ids: tuple[str, ...] = ()
    temporal_selection: str = "execution_lifecycle_rows"
    decision_timestamp_coverage: Literal["persisted", "partial", "not_persisted"] = (
        "not_persisted"
    )


@dataclass(frozen=True)
class ExecutionRiskEventContext:
    """Validated, evidence-backed execution risk signals and coverage state."""

    state: Literal["partial", "empty", "unknown", "degraded", "unavailable"]
    signals: tuple[Any, ...] = ()
    assessments: tuple[Any, ...] = ()
    reason: Optional[str] = None
    source_read_state: Literal["available", "unavailable", "not_read"] = "not_read"
    truncated: bool = False
    scope_known: bool = False
    assessment_state: Literal[
        "partial", "empty", "unknown", "degraded", "unavailable", "not_read"
    ] = "not_read"
    assessment_source_read_state: Literal["available", "unavailable", "not_read"] = "not_read"
    assessment_reason: Optional[str] = None
    assessment_truncated: bool = False
    assessment_scope_known: bool = False


@dataclass(frozen=True)
class ExecutionRead:
    """One source read with explicit availability and subject-scope certainty."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None
    # Canonical tenant agent IDs that the reader proved are bound to the
    # requested scope. This remains useful for an entity with no executions.
    agent_ids: tuple[str, ...] = ()
    # Exact canonical event IDs carried by a journey/episode subject record.
    # They are join keys, not source assertions about actor identity.
    subject_event_ids: tuple[str, ...] = ()
    # Agent requests may carry an additional bounded episode read. Other
    # subjects leave this unset because their product slots use Episode360.
    episode_context: Optional[ExecutionEpisodeContextRead] = None
    # Authenticated principals are canonical Humans only when the tenant USER_ID
    # alias and active surviving subject both resolve without ambiguity.
    principal_identity_read: Optional["ExecutionPrincipalIdentityRead"] = None
    # Lifecycle graph calls are attached only after exact execution, tenant,
    # and canonical actor joins. Their completeness is still source-unknown.
    tool_calls: Optional[ExecutionToolCallRead] = None


@dataclass(frozen=True)
class ExecutionPrincipalIdentityRead:
    """Bounded exact tenant USER_ID alias to active Human subject read."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class EpisodeExecutionScope:
    """Tenant-scoped event and actor bindings persisted on one episode."""

    available: bool
    event_ids: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    complete: bool = False
    reason: Optional[str] = None


async def _read_workflow_run_invocation_facts(
    tenant_id: str, workflow_run_id: str, limit: int
) -> ExecutionWorkflowRunInvocationRead:
    """Read exact tenant/run invocation facts for validating stored run links."""
    if not tenant_id or not workflow_run_id:
        return ExecutionWorkflowRunInvocationRead(
            [], False, False, reason="exact_tenant_workflow_run_scope_required"
        )
    try:
        from config.settings import settings

        if not settings.ai_economics.execution_facts_enabled:
            return ExecutionWorkflowRunInvocationRead(
                [], False, False, reason="ai_execution_facts_disabled"
            )
        from value.economic.ai_aggregation import list_facts

        bounded_limit = min(
            max(1, int(limit)), _MAX_EXECUTION_COST_FACTS_PER_SUBJECT
        )
        facts = await list_facts(
            tenant_id,
            workflow_run_id=workflow_run_id,
            limit=bounded_limit + 1,
        )
    except Exception:  # noqa: BLE001 - optional canonical source stays unknown
        return ExecutionWorkflowRunInvocationRead(
            [], False, False, reason="workflow_run_ai_invocation_source_unavailable"
        )

    if not isinstance(facts, list):
        return ExecutionWorkflowRunInvocationRead(
            [], False, False, reason="workflow_run_ai_invocation_read_invalid"
        )
    truncated = len(facts) > bounded_limit
    scoped: list[dict[str, Any]] = []
    scope_known = True
    for row in facts[:bounded_limit]:
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("workflow_run_id") != workflow_run_id
        ):
            scope_known = False
            continue
        scoped.append(row)
    return ExecutionWorkflowRunInvocationRead(
        scoped,
        True,
        scope_known and not truncated,
        truncated=truncated,
        reason=(
            "workflow_run_ai_invocation_scope_mismatch"
            if not scope_known
            else "workflow_run_ai_invocation_read_truncated"
            if truncated
            else None
        ),
    )


class Execution360Source(Protocol):
    """Narrow injectable read seam for tenant-scoped execution authorities."""

    async def server_executions(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        """Read AETHER-authored user-agent lifecycle records for the subject."""

    async def observed_facts(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        """Read telemetry facts whose actor has been canonically resolved."""

    async def source_provenance(
        self, *, tenant_id: str, events: tuple[tuple[str, str], ...]
    ) -> ExecutionSourceProvenanceRead:
        """Read exact Bronze provenance for admitted source telemetry events."""

    async def execution_risk_events(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskEventRead:
        """Read canonical RiskSignals for admitted exact execution subjects."""

    async def execution_approval_decisions(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionApprovalRead:
        """Read x402 decisions by exact tenant and execution IDs."""

    async def execution_cost_facts(
        self,
        *,
        tenant_id: str,
        executions: tuple[tuple[str, str], ...],
        limit: int,
    ) -> ExecutionCostRead:
        """Read AI facts linked by exact tenant, execution action ID, and agent ID."""


class RepositoryExecution360Source:
    """Defensive adapter over existing agent repositories and Silver facts."""

    def __init__(
        self,
        *,
        episode_store: Any = None,
        graph_client: Any = None,
        commerce_store: Any = None,
        principal_identity_repository: Any = None,
        ai_execution_facts_reader: Any = None,
    ) -> None:
        self._episode_store = episode_store
        self._graph_client = graph_client
        self._commerce_store = commerce_store
        self._principal_identity_repository = principal_identity_repository
        self._ai_execution_facts_reader = ai_execution_facts_reader

    async def execution_cost_facts(
        self,
        *,
        tenant_id: str,
        executions: tuple[tuple[str, str], ...],
        limit: int,
    ) -> ExecutionCostRead:
        """Join only AI facts whose explicit action_id names an admitted execution."""
        if not tenant_id:
            return ExecutionCostRead(
                [], False, False, reason="exact_tenant_execution_scope_required"
            )
        requested: dict[str, str] = {}
        conflict_ids: set[str] = set()
        for execution_id, agent_id in executions:
            execution_id = _safe_text(execution_id) or ""
            agent_id = _safe_text(agent_id) or ""
            if not execution_id or not agent_id:
                continue
            existing = requested.get(execution_id)
            if existing is not None and existing != agent_id:
                conflict_ids.add(execution_id)
            else:
                requested[execution_id] = agent_id
        for execution_id in conflict_ids:
            requested.pop(execution_id, None)
        if not requested:
            return ExecutionCostRead(
                [],
                True,
                not conflict_ids,
                reason=(
                    "execution_cost_subject_agent_conflict"
                    if conflict_ids
                    else "no_exact_execution_cost_subjects"
                ),
            )

        try:
            from config.settings import settings

            if not settings.ai_economics.execution_facts_enabled:
                return ExecutionCostRead(
                    [], False, False, reason="ai_execution_facts_disabled"
                )
            reader = self._ai_execution_facts_reader
            if reader is None:
                from value.economic.ai_aggregation import list_facts

                reader = list_facts
        except Exception:  # noqa: BLE001 - optional canonical source stays unknown
            return ExecutionCostRead(
                [], False, False, reason="ai_execution_fact_repository_unavailable"
            )

        max_subjects = min(
            _MAX_EXECUTION_COST_SUBJECT_SCAN,
            max(1, int(limit)),
        )
        subject_ids = sorted(requested)
        queried_ids = subject_ids[:max_subjects]
        truncated = len(queried_ids) < len(subject_ids)
        scope_known = not conflict_ids
        result: list[dict[str, Any]] = []
        try:
            for execution_id in queried_ids:
                remaining = _MAX_EXECUTION_COST_FACT_SCAN - len(result)
                if remaining <= 0:
                    truncated = True
                    break
                fact_limit = min(_MAX_EXECUTION_COST_FACTS_PER_SUBJECT, remaining)
                facts = await reader(
                    tenant_id,
                    action_id=execution_id,
                    limit=fact_limit + 1,
                )
                if not isinstance(facts, list):
                    return ExecutionCostRead(
                        result,
                        False,
                        False,
                        truncated=True,
                        reason="ai_execution_fact_read_invalid",
                    )
                if len(facts) > fact_limit:
                    truncated = True
                    facts = facts[:fact_limit]
                expected_agent_id = requested[execution_id]
                for fact in facts:
                    if (
                        not isinstance(fact, dict)
                        or fact.get("tenant_id") != tenant_id
                        or fact.get("action_id") != execution_id
                        or fact.get("agent_id") != expected_agent_id
                    ):
                        scope_known = False
                        continue
                    invocation_id = _safe_text(fact.get("invocation_id"))
                    if invocation_id is None:
                        scope_known = False
                        continue
                    result.append(
                        {
                            "tenant_id": tenant_id,
                            "execution_id": execution_id,
                            "action_id": fact.get("action_id"),
                            "agent_id": expected_agent_id,
                            "invocation_id": invocation_id,
                            "observed_at": _safe_text(fact.get("observed_at")),
                            "latency_ms": fact.get("latency_ms"),
                            "selected_cost": fact.get("selected_cost"),
                            "cost_basis": _safe_text(fact.get("cost_basis")),
                            "currency": _safe_text(fact.get("currency")),
                        }
                    )
                    if len(result) >= _MAX_EXECUTION_COST_FACT_SCAN:
                        truncated = True
                        break
                if len(result) >= _MAX_EXECUTION_COST_FACT_SCAN:
                    break
        except Exception:  # noqa: BLE001 - source internals must not escape the frame
            return ExecutionCostRead(
                result,
                False,
                False,
                truncated=truncated,
                reason="ai_execution_fact_read_unavailable",
            )

        return ExecutionCostRead(
            result,
            True,
            scope_known and not truncated,
            truncated=truncated,
            reason=(
                "ai_execution_fact_read_truncated"
                if truncated
                else "ai_execution_fact_execution_or_agent_link_mismatch"
                if not scope_known
                else None
            ),
        )

    async def server_executions(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        episode_scope: Optional[EpisodeExecutionScope] = None
        if subject.kind == "episode":
            episode_scope = await _episode_execution_scope(tenant_id, subject.id)
            if not episode_scope.available or not episode_scope.event_ids:
                return ExecutionRead(
                    rows=[],
                    available=episode_scope.available,
                    scope_known=False,
                    truncated=not episode_scope.complete,
                    reason=episode_scope.reason or "episode_execution_event_link_unavailable",
                    subject_event_ids=episode_scope.event_ids,
                )
        try:
            from repositories.repos import (
                AgentConfigRepository,
                AgentExecutionRepository,
                DelegationRepository,
            )

            configs = AgentConfigRepository()
            executions = AgentExecutionRepository()
            source_truncated = bool(episode_scope and not episode_scope.complete)
            source_scope_mismatch = False
            if subject.kind == "agent":
                config = await configs.find_by_id(subject.id)
                if not _tenant_agent_config(config, tenant_id, subject.id):
                    # The agent may be external-only or outside this server
                    # registry. This is unknown coverage, not a known zero.
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="server_agent_configuration_not_found",
                    )
                rows = await executions.list_for_agent(subject.id, tenant_id, limit=limit + 1)
                if len(rows) > limit:
                    source_truncated = True
                    rows = rows[:limit]
                agent_ids = {subject.id}
                owner_by_agent = {subject.id: config.get("owner_entity_id")}
            elif subject.kind == "execution":
                execution = await executions.find_by_id(subject.id)
                if execution is None:
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=True,
                        reason="tenant_execution_not_found",
                    )
                if (
                    not isinstance(execution, dict)
                    or execution.get("tenant_id") != tenant_id
                    or _safe_text(execution.get("execution_id")) != subject.id
                ):
                    # A globally keyed row from another tenant is intentionally
                    # indistinguishable from an unresolved subject here.
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="execution_subject_scope_unresolved",
                    )
                source_agent_id = _safe_text(execution.get("agent_id"))
                if source_agent_id is None:
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="execution_agent_binding_unavailable",
                    )
                config = await configs.find_by_id(source_agent_id)
                if not _tenant_agent_config(config, tenant_id, source_agent_id):
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="execution_agent_configuration_not_tenant_bound",
                    )
                rows = [execution]
                agent_ids = {source_agent_id}
                owner_by_agent = {source_agent_id: config.get("owner_entity_id")}
            elif subject.kind == "workflow_run":
                # A workflow run may include only lifecycle rows that carry
                # the exact tenant-scoped workflow_run_id. The canonical
                # AgentExecution writer stores this reference only after its
                # AI invocation facts resolve to one exact run, action ID, and
                # agent. This does not establish workflow-wide step coverage.
                workflow_run_id = _safe_text(subject.id)
                if workflow_run_id is None:
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="workflow_run_subject_id_invalid",
                    )
                raw_rows = await executions.find_many(
                    filters={
                        "tenant_id": tenant_id,
                        "workflow_run_id": workflow_run_id,
                    },
                    limit=limit + 1,
                )
                if not isinstance(raw_rows, list):
                    return ExecutionRead(
                        rows=[],
                        available=False,
                        scope_known=False,
                        reason="workflow_run_execution_read_invalid",
                    )
                if len(raw_rows) > limit:
                    source_truncated = True
                    raw_rows = raw_rows[:limit]

                invocation_read = await _read_workflow_run_invocation_facts(
                    tenant_id,
                    workflow_run_id,
                    _MAX_EXECUTION_COST_FACTS_PER_SUBJECT,
                )
                if not invocation_read.available:
                    return ExecutionRead(
                        rows=[],
                        available=False,
                        scope_known=False,
                        reason=(
                            invocation_read.reason
                            or "workflow_run_ai_invocation_source_unavailable"
                        ),
                    )
                if invocation_read.truncated:
                    source_truncated = True
                if not invocation_read.scope_known:
                    source_scope_mismatch = True
                invocations_by_id: dict[str, Optional[dict[str, Any]]] = {}
                for fact in invocation_read.rows:
                    invocation_id = _safe_text(fact.get("invocation_id"))
                    if invocation_id is None:
                        source_scope_mismatch = True
                        continue
                    if invocation_id in invocations_by_id:
                        invocations_by_id[invocation_id] = None
                        source_scope_mismatch = True
                        continue
                    invocations_by_id[invocation_id] = fact

                rows = []
                agent_ids = set()
                owner_by_agent = {}
                seen_execution_ids: set[str] = set()
                for row in raw_rows:
                    if (
                        not isinstance(row, dict)
                        or row.get("tenant_id") != tenant_id
                        or row.get("workflow_run_id") != workflow_run_id
                        or row.get("event_type") is not None
                    ):
                        source_scope_mismatch = True
                        continue
                    execution_id = _safe_text(row.get("execution_id"))
                    source_agent_id = _safe_text(row.get("agent_id"))
                    if (
                        execution_id is None
                        or source_agent_id is None
                        or execution_id in seen_execution_ids
                    ):
                        source_scope_mismatch = True
                        continue
                    seen_execution_ids.add(execution_id)
                    config = await configs.find_by_id(source_agent_id)
                    if not _tenant_agent_config(config, tenant_id, source_agent_id):
                        source_scope_mismatch = True
                        continue

                    raw_invocation_ids = row.get("workflow_run_invocation_ids")
                    invocation_ids = (
                        [
                            value
                            for raw_id in raw_invocation_ids
                            if (value := _safe_text(raw_id)) is not None
                        ]
                        if isinstance(raw_invocation_ids, list)
                        else []
                    )
                    if (
                        not invocation_ids
                        or len(invocation_ids) != len(raw_invocation_ids or [])
                        or len(set(invocation_ids)) != len(invocation_ids)
                    ):
                        source_scope_mismatch = True
                        continue
                    linked_facts = [
                        invocations_by_id.get(invocation_id)
                        for invocation_id in invocation_ids
                    ]
                    if any(
                        not isinstance(fact, dict)
                        or fact.get("tenant_id") != tenant_id
                        or fact.get("workflow_run_id") != workflow_run_id
                        or fact.get("action_id") != execution_id
                        or fact.get("agent_id") != source_agent_id
                        for fact in linked_facts
                    ):
                        source_scope_mismatch = True
                        continue
                    invocation_evidence_refs = [
                        evidence_ref.model_dump(
                            mode="json", by_alias=True, exclude_none=True
                        )
                        for fact in linked_facts
                        if isinstance(fact, dict)
                        and (
                            evidence_ref := _evidence_ref(
                                evidence_id=fact.get("invocation_id"),
                                source="ai_execution_facts",
                                observed_at=fact.get("observed_at"),
                                store="ai_execution_facts",
                            )
                        )
                        is not None
                    ]
                    if len(invocation_evidence_refs) != len(invocation_ids):
                        source_scope_mismatch = True
                        continue
                    rows.append(
                        {
                            **row,
                            "workflow_run_invocation_evidence_refs": (
                                invocation_evidence_refs
                            ),
                        }
                    )
                    agent_ids.add(source_agent_id)
                    owner_by_agent[source_agent_id] = config.get("owner_entity_id")
            elif subject.kind == "entity":
                owner_configs = await configs.find_many(
                    filters={"tenant_id": tenant_id, "owner_entity_id": subject.id},
                    limit=_MAX_EPISODE_AGENT_SCAN + 1,
                )
                if len(owner_configs) > _MAX_EPISODE_AGENT_SCAN:
                    source_truncated = True
                    owner_configs = owner_configs[:_MAX_EPISODE_AGENT_SCAN]
                owned = [
                    row
                    for row in owner_configs
                    if _tenant_agent_config(row, tenant_id, row.get("agent_id"))
                    and row.get("owner_entity_id") == subject.id
                ]
                rows = []
                agent_ids = {str(row["agent_id"]) for row in owned}
                owner_by_agent = {str(row["agent_id"]): row.get("owner_entity_id") for row in owned}
                for agent_id in sorted(agent_ids):
                    remaining = limit - len(rows)
                    if remaining <= 0:
                        source_truncated = True
                        break
                    agent_rows = await executions.list_for_agent(
                        agent_id, tenant_id, limit=remaining + 1
                    )
                    if len(agent_rows) > remaining:
                        source_truncated = True
                        agent_rows = agent_rows[:remaining]
                    rows.extend(agent_rows)
            elif subject.kind == "episode" and episode_scope is not None:
                rows = []
                agent_ids = set(episode_scope.agent_ids)
                owner_by_agent = {}
                for agent_id in sorted(agent_ids):
                    remaining = max(0, limit - len(rows))
                    if remaining == 0:
                        source_truncated = True
                        break
                    agent_rows = await executions.list_for_agent(
                        agent_id, tenant_id, limit=remaining + 1
                    )
                    if len(agent_rows) > remaining:
                        source_truncated = True
                        agent_rows = agent_rows[:remaining]
                    matching_lifecycle = [
                        row
                        for row in agent_rows
                        if isinstance(row, dict)
                        and row.get("tenant_id") == tenant_id
                        and row.get("agent_id") == agent_id
                        and row.get("event_type") is None
                        and _safe_text(row.get("triggered_by_event_id")) in episode_scope.event_ids
                    ]
                    matching_execution_ids = {
                        execution_id
                        for row in matching_lifecycle
                        if (execution_id := _safe_text(row.get("execution_id"))) is not None
                    }
                    rows.extend(matching_lifecycle)
                    rows.extend(
                        row
                        for row in agent_rows
                        if isinstance(row, dict)
                        and row.get("tenant_id") == tenant_id
                        and row.get("agent_id") == agent_id
                        and row.get("event_type") == "task_decomposed"
                        and _safe_text(row.get("execution_id")) in matching_execution_ids
                    )
            else:
                return ExecutionRead(
                    rows=[],
                    available=True,
                    scope_known=False,
                    reason="subject_kind_not_bound_to_agent_executions",
                )
        except Exception:  # noqa: BLE001 - provider reports typed degradation
            return ExecutionRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="server_execution_source_unavailable",
            )

        identity_map, identity_mismatch, identity_truncated = await _resolve_agent_identity_map(
            tenant_id, agent_ids
        )
        complete_identity_scope = (
            set(identity_map) == agent_ids
            and not identity_mismatch
            and not identity_truncated
            and not source_scope_mismatch
            and (episode_scope is None or episode_scope.complete)
        )

        scoped = [
            {
                **row,
                "canonical_agent_identity": source_id in identity_map,
                "canonical_agent_entity_id": (
                    identity_map[source_id]["canonical_agent_entity_id"]
                    if source_id in identity_map
                    else None
                ),
                "canonical_owner_entity_id": owner_by_agent.get(str(row.get("agent_id") or "")),
            }
            for row in rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and (source_id := str(row.get("agent_id") or "")) in agent_ids
        ]
        delegation_repo = DelegationRepository()
        for row in scoped:
            try:
                row.update(
                    await _resolve_server_delegation_reference(
                        row, tenant_id=tenant_id, repository=delegation_repo
                    )
                )
            except Exception:  # noqa: BLE001 - unresolved authority stays absent
                row["canonical_delegation_resolution_status"] = "source_unavailable"
        episode_context = None
        if subject.kind == "agent":
            canonical_agent_ids = {
                row["canonical_agent_entity_id"]
                for row in identity_map.values()
                if isinstance(row.get("canonical_agent_entity_id"), str)
            }
            episode_context = await _read_agent_episode_context(
                tenant_id,
                canonical_agent_ids,
                episode_store=self._episode_store,
                identity_rows=list(identity_map.values()),
                execution_rows=scoped,
            )
        principal_ids = {
            principal_id
            for row in scoped
            if (principal_id := _safe_text(row.get("initiating_principal_user_id"))) is not None
        }
        principal_identity_read = await _read_execution_principal_identities(
            tenant_id,
            principal_ids,
            repository=self._principal_identity_repository,
        )
        tool_calls = await self._read_execution_tool_calls(tenant_id, scoped)
        return ExecutionRead(
            rows=scoped[:limit],
            available=True,
            scope_known=complete_identity_scope,
            truncated=source_truncated or identity_truncated or len(scoped) > limit,
            reason=(
                "workflow_run_execution_scope_mismatch"
                if source_scope_mismatch
                else "agent_identity_binding_incomplete"
                if not complete_identity_scope
                else None
            ),
            subject_event_ids=(episode_scope.event_ids if episode_scope is not None else ()),
            agent_ids=tuple(
                sorted(
                    {
                        row["canonical_agent_entity_id"]
                        for row in identity_map.values()
                        if isinstance(row.get("canonical_agent_entity_id"), str)
                    }
                )
            ),
            episode_context=episode_context,
            principal_identity_read=principal_identity_read,
            tool_calls=tool_calls,
        )

    async def _read_execution_tool_calls(
        self, tenant_id: str, execution_rows: list[dict[str, Any]]
    ) -> ExecutionToolCallRead:
        """Join lifecycle tool edges only to exact tenant execution records."""
        execution_scope: dict[str, str] = {}
        ambiguous_execution_ids: set[str] = set()
        for row in execution_rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("event_type") is not None
                or row.get("canonical_agent_identity") is not True
            ):
                continue
            execution_id = _safe_text(row.get("execution_id"))
            source_agent_id = _safe_text(row.get("agent_id"))
            canonical_agent_id = _safe_text(row.get("canonical_agent_entity_id"))
            if execution_id and source_agent_id and canonical_agent_id:
                prior_source_agent_id = execution_scope.get(execution_id)
                if prior_source_agent_id is not None and prior_source_agent_id != source_agent_id:
                    ambiguous_execution_ids.add(execution_id)
                else:
                    execution_scope[execution_id] = source_agent_id
        for execution_id in ambiguous_execution_ids:
            execution_scope.pop(execution_id, None)
        if not execution_scope:
            return ExecutionToolCallRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=(
                    "execution_identity_ambiguous_for_tool_join"
                    if ambiguous_execution_ids
                    else "canonical_execution_agent_binding_unavailable_for_tool_join"
                ),
            )

        try:
            if self._graph_client is None:
                from shared.graph.graph import GraphClient

                graph = GraphClient()
            else:
                graph = self._graph_client
            from shared.graph.graph import EdgeType

            edges, truncated = await graph.get_edges_for_tenant(
                tenant_id,
                limit=_MAX_TOOL_EDGE_SCAN,
                edge_types=[EdgeType.CALLED_TOOL],
            )
        except Exception:  # noqa: BLE001 - optional source failure remains explicit
            return ExecutionToolCallRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_tool_call_graph_source_unavailable",
            )
        if not isinstance(edges, list):
            return ExecutionToolCallRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_tool_call_graph_read_invalid",
            )

        items: list[dict[str, Any]] = []
        scope_known = not ambiguous_execution_ids
        for edge in edges:
            props = getattr(edge, "properties", None)
            if (
                getattr(edge, "edge_type", None) != EdgeType.CALLED_TOOL
                or not isinstance(props, dict)
            ):
                scope_known = False
                continue
            if _safe_text(props.get("tenant_id") or props.get("tenantId")) != tenant_id:
                scope_known = False
                continue
            execution_id = _safe_text(props.get("execution_id"))
            if execution_id is None or execution_id not in execution_scope:
                continue
            source_agent_id = execution_scope[execution_id]
            expected_agent_vertex = f"{tenant_id}:agent:{source_agent_id}"
            if getattr(edge, "from_vertex_id", None) != expected_agent_vertex:
                scope_known = False
                continue
            target_vertex_id = _safe_text(getattr(edge, "to_vertex_id", None))
            target_prefix = f"{tenant_id}:tool:"
            if not target_vertex_id or not target_vertex_id.startswith(target_prefix):
                scope_known = False
                continue
            tool_id = _safe_text(target_vertex_id[len(target_prefix) :])
            # The lifecycle mapper keeps its source-event key on the mutation
            # intent and persists the resulting idempotency key on the graph
            # edge. Use that exact edge key as evidence when the original
            # source event id is not projected into edge properties.
            graph_edge_id = _safe_text(
                props.get("source_event_id") or props.get("idempotency_key")
            )
            called_at = _safe_text(props.get("called_at"))
            if not tool_id or not graph_edge_id or _parse_aware_instant(called_at) is None:
                scope_known = False
                continue
            try:
                tool_vertex = await graph.get_vertex_for_tenant(tenant_id, target_vertex_id)
            except Exception:  # noqa: BLE001 - unresolved tool identity is not a call claim
                scope_known = False
                continue
            tool_properties = getattr(tool_vertex, "properties", None)
            if (
                tool_vertex is None
                or getattr(tool_vertex, "vertex_type", None) != "Tool"
                or not isinstance(tool_properties, dict)
                or _safe_text(tool_properties.get("tenant_id") or tool_properties.get("tenantId"))
                != tenant_id
                or _safe_text(tool_properties.get("tool_id")) != tool_id
            ):
                scope_known = False
                continue
            evidence = _evidence_ref(
                evidence_id=graph_edge_id,
                source="graph_edges",
                observed_at=called_at,
                store="graph_edges",
            )
            if evidence is None:
                scope_known = False
                continue
            items.append(
                {
                    "executionId": execution_id,
                    "toolId": tool_id,
                    "calledAt": called_at,
                    "observationKind": "server_recorded_agent_tool_call_lifecycle_edge",
                    "externalExecutionReceipt": "unknown",
                    "authorityDecision": "not_established_by_tool_call_edge",
                    "evidenceRef": evidence.model_dump(mode="json", by_alias=True, exclude_none=True),
                }
            )
        return ExecutionToolCallRead(
            rows=items,
            available=True,
            scope_known=scope_known,
            truncated=bool(truncated),
            reason=(
                "execution_tool_call_graph_scan_truncated"
                if truncated
                else "execution_identity_ambiguous_for_tool_join"
                if ambiguous_execution_ids
                else "execution_tool_call_edge_scope_or_evidence_incomplete"
                if not scope_known
                else None
            ),
        )

    async def observed_facts(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        if subject.kind == "workflow_run":
            # Provider-reported run_id values in source telemetry are not a
            # canonical workflow_run_id crosswalk. Keep this source unknown
            # instead of assigning telemetry to a run by identifier shape.
            return ExecutionRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="source_reported_run_id_not_canonically_linked_to_workflow_run",
            )
        if subject.kind == "execution":
            # Source telemetry has run/task references but no canonical join
            # from those references to this AETHER execution ID yet.
            return ExecutionRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="execution_source_telemetry_join_unavailable",
            )
        if subject.kind == "episode":
            scope = await _episode_execution_scope(tenant_id, subject.id)
            if not scope.available or not scope.event_ids:
                return ExecutionRead(
                    rows=[],
                    available=scope.available,
                    scope_known=False,
                    truncated=not scope.complete,
                    reason=scope.reason or "episode_execution_event_link_unavailable",
                    agent_ids=scope.agent_ids,
                    subject_event_ids=scope.event_ids,
                )
            source_agent_ids = set(scope.agent_ids)
            episode_event_ids = set(scope.event_ids)
        else:
            scope = None
        try:
            from actions.agent_marketplace.authority import AgentRunAuthorityResolver
            from dependencies.providers import get_cache
            from actions.agent.deployments import get_deployment_repository
            from actions.agent.identity_resolution import resolve_agent_identities
            from actions.agent_marketplace.identity_binding import (
                AgentDeploymentIdentityBindingRepository,
            )
            from repositories.repos import (
                AgentConfigRepository,
                AnalyticsRepository,
                EntityRepository,
            )

            if subject.kind == "agent":
                source_agent_ids = {subject.id}
                owner_roster_truncated = False
            elif subject.kind == "entity":
                configs = await AgentConfigRepository().list_for_owner(
                    subject.id, limit=_MAX_EPISODE_AGENT_SCAN + 1, tenant_id=tenant_id
                )
                owner_roster_truncated = len(configs) > _MAX_EPISODE_AGENT_SCAN
                source_agent_ids = {
                    str(row.get("agent_id"))
                    for row in configs[:_MAX_EPISODE_AGENT_SCAN]
                    if _tenant_agent_config(row, tenant_id, row.get("agent_id"))
                    and row.get("owner_entity_id") == subject.id
                }
                if not source_agent_ids:
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="no_tenant_owned_agents_for_entity",
                        agent_ids=(),
                    )
            elif subject.kind == "episode":
                owner_roster_truncated = False
                if not source_agent_ids:
                    return ExecutionRead(
                        rows=[],
                        available=True,
                        scope_known=False,
                        reason="episode_has_no_tenant_agent_binding",
                        subject_event_ids=tuple(sorted(episode_event_ids)),
                    )
            else:
                return ExecutionRead(
                    rows=[],
                    available=True,
                    scope_known=False,
                    reason="subject_kind_not_bound_to_execution_facts",
                )

            identity_read = await resolve_agent_identities(
                tenant_id,
                source_agent_ids,
                deployments=get_deployment_repository(),
                identity_bindings=AgentDeploymentIdentityBindingRepository(),
                entities=EntityRepository(),
                limit=_MAX_EPISODE_AGENT_SCAN,
            )
            identity_map = {
                row["agent_id"]: row["canonical_agent_entity_id"]
                for row in identity_read.rows
                if isinstance(row.get("agent_id"), str)
                and isinstance(row.get("canonical_agent_entity_id"), str)
            }
            allowed_agent_ids = set(identity_map.values())
            identity_scope_complete = (
                set(identity_map) == source_agent_ids
                and not identity_read.scope_mismatch
                and not identity_read.truncated
                and not owner_roster_truncated
                and (scope is None or scope.complete)
            )
            if not allowed_agent_ids:
                return ExecutionRead(
                    rows=[],
                    available=True,
                    scope_known=False,
                    reason="agent_identity_binding_unresolved",
                    subject_event_ids=scope.event_ids if scope is not None else (),
                )

            raw_rows = await AnalyticsRepository(get_cache()).query_silver(
                _SILVER_SOURCE,
                {"tenant_id": tenant_id},
                limit=_SILVER_QUERY_LIMIT,
            )
            resolver = AgentRunAuthorityResolver()
        except Exception:  # noqa: BLE001 - provider reports typed degradation
            return ExecutionRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="observed_execution_source_unavailable",
            )

        result: list[dict[str, Any]] = []
        unresolved_actor_seen = False
        for row in raw_rows:
            if not isinstance(row, dict) or row.get("tenant_id") != tenant_id:
                continue
            if (
                subject.kind == "episode"
                and _safe_text(
                    row.get("source_event_id") or row.get("source_event_ref") or row.get("event_id")
                )
                not in episode_event_ids
            ):
                continue
            delegation_id = _safe_text(row.get("delegation_id"))
            if not delegation_id:
                # A raw source agent_id is a claim, not a canonical subject
                # binding. Without a delegation path the row remains unscoped.
                unresolved_actor_seen = True
                continue
            try:
                resolution = await resolver.resolve(row)
            except Exception:  # noqa: BLE001 - one bad resolution cannot widen scope
                unresolved_actor_seen = True
                continue
            actor_resolution = resolution.get("delegation_resolution") or {}
            authorization = resolution.get("delegation_authorization") or {}
            actor_id = _safe_text(authorization.get("actor_entity_id"))
            if actor_resolution.get("actor_identity_status") != "matched" or not actor_id:
                unresolved_actor_seen = True
                continue
            if actor_id not in allowed_agent_ids:
                # The actor is canonically resolved to a different agent.
                continue
            fact = _safe_observed_fact(row, resolution)
            if fact is not None:
                result.append(fact)

        truncated = len(raw_rows) >= _SILVER_QUERY_LIMIT
        return ExecutionRead(
            rows=result[:limit],
            available=True,
            scope_known=(
                not unresolved_actor_seen
                and not truncated
                and identity_scope_complete
                and (scope is None or scope.complete)
            ),
            truncated=(
                truncated
                or owner_roster_truncated
                or len(result) > limit
                or (scope is not None and not scope.complete)
            ),
            reason=(
                "some_tenant_facts_have_unresolved_actor_binding"
                if unresolved_actor_seen
                else "owner_agent_roster_read_truncated"
                if owner_roster_truncated
                else "agent_identity_binding_incomplete"
                if not identity_scope_complete
                else scope.reason
                if scope is not None and not scope.complete
                else None
            ),
            agent_ids=tuple(sorted(allowed_agent_ids)),
            subject_event_ids=scope.event_ids if scope is not None else (),
        )

    async def source_provenance(
        self, *, tenant_id: str, events: tuple[tuple[str, str], ...]
    ) -> ExecutionSourceProvenanceRead:
        return await read_execution_source_provenance(tenant_id=tenant_id, events=events)

    async def execution_risk_events(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskEventRead:
        """Read exact execution RiskSignals and RiskAssessment snapshots."""
        admitted_ids = sorted(
            {value for raw in execution_ids if (value := _safe_text(raw)) is not None}
        )
        if not admitted_ids:
            return ExecutionRiskEventRead(
                rows=[],
                available=True,
                scope_known=True,
                assessment_read=ExecutionRiskAssessmentRead(
                    rows=[], available=True, scope_known=True
                ),
            )

        # RiskSignalRepository exposes an exact tenant + subject lookup. Use it
        # for every admitted execution instead of scanning all execution signals
        # for the tenant and relying on a post-query subject filter. Divide the
        # bounded source scan across subjects so a large execution set cannot
        # turn this read into an unbounded fan-out.
        query_ids = admitted_ids[: max(1, _MAX_EXECUTION_RISK_SIGNAL_SCAN // 2)]
        per_subject_scan_limit = min(
            max(1, limit),
            max(1, _MAX_EXECUTION_RISK_SIGNAL_SCAN // len(query_ids) - 1),
        )
        exact_rows: list[dict[str, Any]] = []
        mismatch = False
        scan_truncated = len(query_ids) < len(admitted_ids)
        signal_available = True
        signal_reason: Optional[str] = None
        try:
            from intelligence.risk360.store import RiskSignalRepository

            repository = RiskSignalRepository()
            for execution_id in query_ids:
                rows = await repository.list_by_subject(
                    tenant_id,
                    "execution",
                    execution_id,
                    limit=per_subject_scan_limit + 1,
                )
                if not isinstance(rows, list):
                    signal_available = False
                    signal_reason = "execution_risk_signal_read_invalid"
                    exact_rows = []
                    break
                if len(rows) > per_subject_scan_limit:
                    scan_truncated = True
                for row in rows[:per_subject_scan_limit]:
                    if (
                        not isinstance(row, dict)
                        or row.get("tenant_id") != tenant_id
                        or row.get("subject_kind") != "execution"
                        or row.get("subject_id") != execution_id
                    ):
                        mismatch = True
                        continue
                    exact_rows.append(
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"id", "created_at", "updated_at"}
                        }
                    )
        except Exception:  # noqa: BLE001 - optional canonical source failure is isolated
            signal_available = False
            signal_reason = "execution_risk_signal_source_unavailable"
            exact_rows = []

        truncated = scan_truncated or len(exact_rows) > limit
        exact_rows = exact_rows[:limit]
        assessment_read = await self._read_execution_risk_assessments(
            tenant_id=tenant_id,
            execution_ids=tuple(admitted_ids),
            limit=limit,
        )
        return ExecutionRiskEventRead(
            rows=exact_rows,
            available=signal_available,
            scope_known=signal_available and not mismatch,
            truncated=truncated,
            reason=(
                signal_reason
                if signal_reason is not None
                else "execution_risk_signal_scope_mismatch"
                if mismatch
                else "execution_risk_signal_read_truncated"
                if truncated
                else None
            ),
            assessment_read=assessment_read,
        )

    async def _read_execution_risk_assessments(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskAssessmentRead:
        """Read assessments with exact tenant + execution-subject repository keys."""
        if not tenant_id:
            return ExecutionRiskAssessmentRead(
                [], False, False, reason="exact_tenant_execution_scope_required"
            )
        admitted_ids = sorted(
            {value for raw in execution_ids if (value := _safe_text(raw)) is not None}
        )
        if not admitted_ids:
            return ExecutionRiskAssessmentRead([], True, True)

        query_ids = admitted_ids[:_MAX_EXECUTION_RISK_ASSESSMENT_SCAN]
        per_subject_scan_limit = min(
            max(1, limit),
            max(1, _MAX_EXECUTION_RISK_ASSESSMENT_SCAN // len(query_ids)),
        )
        exact_rows: list[dict[str, Any]] = []
        mismatch = False
        truncated = len(query_ids) < len(admitted_ids)
        try:
            from intelligence.risk360.store import RiskAssessmentRepository

            repository = RiskAssessmentRepository()
            for execution_id in query_ids:
                rows = await repository.list_by_subject(
                    tenant_id,
                    "execution",
                    execution_id,
                    limit=per_subject_scan_limit + 1,
                )
                if not isinstance(rows, list):
                    return ExecutionRiskAssessmentRead(
                        [],
                        False,
                        False,
                        reason="execution_risk_assessment_read_invalid",
                    )
                if len(rows) > per_subject_scan_limit:
                    truncated = True
                for row in rows[:per_subject_scan_limit]:
                    if (
                        not isinstance(row, dict)
                        or row.get("tenant_id") != tenant_id
                        or row.get("subject_kind") != "execution"
                        or row.get("subject_id") != execution_id
                    ):
                        mismatch = True
                        continue
                    exact_rows.append(
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"id", "created_at", "updated_at"}
                        }
                    )
        except Exception:  # noqa: BLE001 - optional canonical source stays explicit
            return ExecutionRiskAssessmentRead(
                [],
                False,
                False,
                reason="execution_risk_assessment_source_unavailable",
            )

        return ExecutionRiskAssessmentRead(
            rows=exact_rows,
            available=True,
            scope_known=not mismatch,
            truncated=truncated,
            reason=(
                "execution_risk_assessment_scope_mismatch"
                if mismatch
                else "execution_risk_assessment_read_truncated"
                if truncated
                else None
            ),
        )

    async def execution_approval_decisions(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionApprovalRead:
        """Read x402 decision history by exact tenant and admitted run IDs."""
        admitted_ids = sorted(
            {value for raw in execution_ids if (value := _safe_text(raw)) is not None}
        )
        if not admitted_ids:
            return ExecutionApprovalRead(rows=[], available=True, scope_known=True)
        if len(admitted_ids) > 500:
            return ExecutionApprovalRead(
                rows=[],
                available=False,
                scope_known=False,
                truncated=True,
                reason="execution_approval_execution_scope_truncated",
            )
        try:
            if self._commerce_store is None:
                from value.x402.commerce_store import get_commerce_store

                store = get_commerce_store()
            else:
                store = self._commerce_store
            scan_limit = min(
                max(max(1, limit), len(admitted_ids) * 4),
                _MAX_EXECUTION_APPROVAL_DECISION_SCAN,
            )
            decisions = await store.list_approval_decisions_for_executions(
                tenant_id, admitted_ids, scan_limit + 1
            )
            approval_scan_limit = min(
                max(max(1, limit), len(admitted_ids) * 4),
                _MAX_EXECUTION_APPROVAL_DECISION_SCAN,
            )
            approval_requests: list[Any] = []
            approval_truncated = False
            for execution_id in admitted_ids:
                remaining = approval_scan_limit - len(approval_requests)
                if remaining <= 0:
                    approval_truncated = True
                    break
                request_limit = min(remaining + 1, 500)
                requests = await store.list_approvals_for_execution(
                    tenant_id, execution_id, request_limit
                )
                if not isinstance(requests, list):
                    return ExecutionApprovalRead(
                        rows=[],
                        available=False,
                        scope_known=False,
                        reason="execution_approval_request_read_invalid",
                    )
                if len(requests) > remaining or len(requests) >= request_limit == 500:
                    approval_truncated = True
                approval_requests.extend(requests[:remaining])
        except Exception:  # noqa: BLE001 - optional canonical source failure is isolated
            return ExecutionApprovalRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_approval_authority_source_unavailable",
            )
        if not isinstance(decisions, list):
            return ExecutionApprovalRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_approval_decision_read_invalid",
            )
        truncated = len(decisions) > scan_limit
        rows = [
            decision.model_dump(mode="json")
            for decision in decisions[:scan_limit]
            if hasattr(decision, "model_dump")
        ]
        mismatch = len(rows) != min(len(decisions), scan_limit) or any(
            row.get("tenant_id") != tenant_id
            or row.get("execution_id") not in admitted_ids
            for row in rows
        )
        rows = [
            row
            for row in rows
            if row.get("tenant_id") == tenant_id
            and row.get("execution_id") in admitted_ids
        ]
        approval_rows = [
            approval.model_dump(mode="json")
            for approval in approval_requests
            if hasattr(approval, "model_dump")
        ]
        approval_mismatch = len(approval_rows) != len(approval_requests) or any(
            row.get("tenant_id") != tenant_id
            or row.get("execution_id") not in admitted_ids
            for row in approval_rows
        )
        approval_rows = [
            row
            for row in approval_rows
            if row.get("tenant_id") == tenant_id
            and row.get("execution_id") in admitted_ids
        ]
        return ExecutionApprovalRead(
            rows=rows,
            available=True,
            scope_known=not mismatch and not approval_mismatch,
            truncated=truncated or approval_truncated,
            reason=(
                "execution_approval_decision_scope_mismatch"
                if mismatch
                else "execution_approval_request_scope_mismatch"
                if approval_mismatch
                else "execution_approval_decision_read_truncated"
                if truncated or approval_truncated
                else None
            ),
            approval_requests=tuple(approval_rows),
        )


def _tenant_agent_config(row: Any, tenant_id: str, agent_id: Any) -> bool:
    return bool(
        isinstance(row, dict)
        and row.get("tenant_id") == tenant_id
        and isinstance(agent_id, str)
        and agent_id
        and row.get("agent_id") == agent_id
    )


async def _read_execution_principal_identities(
    tenant_id: str,
    principal_user_ids: set[str],
    *,
    repository: Any = None,
) -> ExecutionPrincipalIdentityRead:
    """Resolve authenticated user references through active tenant USER_ID aliases."""
    requested = sorted(
        {value.strip() for value in principal_user_ids if isinstance(value, str) and value.strip()}
    )
    if not requested:
        return ExecutionPrincipalIdentityRead(rows=[], available=True, scope_known=True)
    if not tenant_id:
        return ExecutionPrincipalIdentityRead(
            rows=[], available=True, scope_known=False, reason="principal_identity_tenant_missing"
        )
    if len(requested) > _MAX_ROWS:
        requested = requested[:_MAX_ROWS]
        requested_truncated = True
    else:
        requested_truncated = False

    try:
        if repository is None:
            from identity.identity.repository import IdentityResolutionRepository

            repository = IdentityResolutionRepository()
        from identity.identity.hashing import hash_value
        from identity.identity.models import IdentitySignalType

        rows: list[dict[str, Any]] = []
        truncated = requested_truncated
        scope_known = True
        for principal_user_id in requested:
            alias_hash = hash_value(principal_user_id, scope=f"user:{tenant_id}")
            aliases = await repository.find_aliases_by_signal(
                tenant_id,
                IdentitySignalType.USER_ID,
                alias_hash,
                limit=_MAX_PRINCIPAL_IDENTITY_ALIAS_SCAN + 1,
            )
            if not isinstance(aliases, list):
                scope_known = False
                continue
            if len(aliases) > _MAX_PRINCIPAL_IDENTITY_ALIAS_SCAN:
                truncated = True
            surviving_ids: set[str] = set()
            for alias in aliases[:_MAX_PRINCIPAL_IDENTITY_ALIAS_SCAN]:
                if (
                    not isinstance(alias, dict)
                    or alias.get("tenant_id") != tenant_id
                    or alias.get("alias_type") != IdentitySignalType.USER_ID.value
                    or alias.get("alias_value_hash") != alias_hash
                    or alias.get("revoked_at")
                    or alias.get("confidence_tier") != "deterministic"
                    or not isinstance(alias.get("canonical_entity_id"), str)
                ):
                    scope_known = False
                    continue
                original_entity_id = alias["canonical_entity_id"]
                canonical_entity_id = await repository.resolve_surviving_canonical_entity_id(
                    tenant_id, original_entity_id
                )
                subject = await repository.get_subject_by_canonical_entity_id(
                    tenant_id, canonical_entity_id
                )
                if (
                    not isinstance(subject, dict)
                    or subject.get("tenant_id") != tenant_id
                    or subject.get("canonical_entity_id") != canonical_entity_id
                    or subject.get("entity_type") != "human"
                    or subject.get("status") != "active"
                ):
                    scope_known = False
                    continue
                alias_id = _safe_text(alias.get("id"))
                subject_id = _safe_text(subject.get("id"))
                if alias_id is None or subject_id is None:
                    scope_known = False
                    continue
                surviving_ids.add(canonical_entity_id)
                rows.append(
                    {
                        "tenant_id": tenant_id,
                        "principal_user_id": principal_user_id,
                        "canonical_human_entity_id": canonical_entity_id,
                        "identity_evidence_refs": [
                            EvidenceRef(
                                id=alias_id,
                                type="entity",
                                source="identity_aliases",
                                observedAt=_safe_text(
                                    alias.get("last_seen_at") or alias.get("updated_at")
                                ),
                            ).model_dump(mode="json", by_alias=True, exclude_none=True),
                            EvidenceRef(
                                id=subject_id,
                                type="entity",
                                source="identity_subjects",
                                observedAt=_safe_text(
                                    subject.get("last_seen_at") or subject.get("updated_at")
                                ),
                            ).model_dump(mode="json", by_alias=True, exclude_none=True),
                        ],
                    }
                )
            if len(surviving_ids) > 1:
                scope_known = False
        return ExecutionPrincipalIdentityRead(
            rows=rows,
            available=True,
            scope_known=scope_known,
            truncated=truncated,
            reason=(
                "principal_identity_scope_or_subject_mismatch"
                if not scope_known
                else "principal_identity_read_truncated"
                if truncated
                else None
            ),
        )
    except Exception:  # noqa: BLE001 - identity outage remains unknown
        return ExecutionPrincipalIdentityRead(
            rows=[],
            available=False,
            scope_known=False,
            reason="principal_identity_authority_unavailable",
        )


def _execution_principal_identity_bindings(
    read: Optional[ExecutionPrincipalIdentityRead],
    *,
    tenant_id: str,
    principal_user_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], str, Optional[str]]:
    """Accept only a complete, typed, exact tenant principal identity read."""
    if read is None:
        return {}, "unknown", "principal_identity_authority_not_read"
    if not read.available:
        return {}, "unknown", read.reason or "principal_identity_authority_unavailable"
    if not read.scope_known or read.truncated:
        return {}, "unknown", read.reason or "principal_identity_read_incomplete"

    grouped: dict[str, dict[str, Any]] = {}
    mismatch = False
    for row in read.rows:
        if not isinstance(row, dict):
            mismatch = True
            continue
        principal_id = _safe_text(row.get("principal_user_id"))
        canonical_id = _safe_text(row.get("canonical_human_entity_id"))
        raw_refs = row.get("identity_evidence_refs")
        refs: list[EvidenceRef] = []
        sources: set[str] = set()
        if isinstance(raw_refs, list):
            for raw_ref in raw_refs:
                try:
                    ref = EvidenceRef.model_validate(raw_ref)
                except Exception:  # noqa: BLE001 - malformed provenance fails closed
                    mismatch = True
                    continue
                if ref.type != "entity" or ref.source not in {
                    "identity_aliases",
                    "identity_subjects",
                }:
                    mismatch = True
                    continue
                sources.add(ref.source)
                refs.append(ref)
        if (
            row.get("tenant_id") != tenant_id
            or principal_id not in principal_user_ids
            or canonical_id is None
            or len(sources) != 2
            or sources != {"identity_aliases", "identity_subjects"}
            or len(refs) != len(raw_refs or [])
        ):
            mismatch = True
            continue
        entry = grouped.setdefault(
            principal_id,
            {"canonical_human_entity_ids": set(), "evidence_refs": []},
        )
        entry["canonical_human_entity_ids"].add(canonical_id)
        entry["evidence_refs"].extend(refs)
    if mismatch:
        return {}, "unknown", "principal_identity_scope_or_evidence_mismatch"

    bindings: dict[str, dict[str, Any]] = {}
    for principal_id in principal_user_ids:
        entry = grouped.get(principal_id, {"canonical_human_entity_ids": set(), "evidence_refs": []})
        canonical_ids = entry["canonical_human_entity_ids"]
        deduped_refs = {
            (ref.source, ref.id): ref for ref in entry["evidence_refs"]
        }
        if len(canonical_ids) == 1:
            state = "resolved"
            canonical_id = next(iter(canonical_ids))
            evidence_refs = list(deduped_refs.values())
        elif len(canonical_ids) > 1:
            state = "ambiguous"
            canonical_id = None
            evidence_refs = []
        else:
            state = "unresolved"
            canonical_id = None
            evidence_refs = []
        bindings[principal_id] = {
            "state": state,
            "canonical_human_entity_id": canonical_id,
            "evidence_refs": evidence_refs,
        }
    return bindings, "available", None


async def _episode_execution_scope(tenant_id: str, episode_id: str) -> EpisodeExecutionScope:
    """Resolve an episode only through its tenant-scoped persisted event links."""
    try:
        from shared.backend_interpretation.stores import EpisodeStore

        episode = await EpisodeStore().get(tenant_id, episode_id)
    except Exception:  # noqa: BLE001 - source failure stays unavailable
        return EpisodeExecutionScope(
            available=False,
            reason="episode_authority_unavailable",
        )
    if (
        episode is None
        or getattr(episode, "tenant_id", None) != tenant_id
        or getattr(episode, "episode_id", None) != episode_id
    ):
        return EpisodeExecutionScope(
            available=True,
            reason="tenant_scoped_episode_not_found",
        )

    raw_event_ids = [getattr(episode, "source_event_id", None)]
    raw_observations = getattr(episode, "observation_ids", [])
    if isinstance(raw_observations, list):
        raw_event_ids.extend(raw_observations)
    event_ids = {value for raw in raw_event_ids if (value := _safe_text(raw)) is not None}
    if not event_ids:
        return EpisodeExecutionScope(
            available=True,
            reason="episode_execution_event_link_unavailable",
        )

    try:
        from repositories.repos import AgentConfigRepository

        raw_configs = await AgentConfigRepository().find_many(
            filters={"tenant_id": tenant_id},
            limit=_MAX_EPISODE_AGENT_SCAN + 1,
        )
    except Exception:  # noqa: BLE001 - source failure stays unavailable
        return EpisodeExecutionScope(
            available=False,
            event_ids=tuple(sorted(event_ids)),
            reason="tenant_agent_registry_unavailable",
        )
    if not isinstance(raw_configs, list):
        return EpisodeExecutionScope(
            available=False,
            event_ids=tuple(sorted(event_ids)),
            reason="tenant_agent_registry_invalid",
        )

    scoped_configs = [
        row for row in raw_configs if _tenant_agent_config(row, tenant_id, row.get("agent_id"))
    ]
    agent_ids = {str(row["agent_id"]) for row in scoped_configs[:_MAX_EPISODE_AGENT_SCAN]}
    complete = len(raw_configs) <= _MAX_EPISODE_AGENT_SCAN
    if len(scoped_configs) != len(raw_configs):
        complete = False
    return EpisodeExecutionScope(
        available=True,
        event_ids=tuple(sorted(event_ids)),
        agent_ids=tuple(sorted(agent_ids)),
        complete=complete,
        reason=None if complete else "tenant_agent_registry_scan_truncated_or_unscoped",
    )


async def _read_agent_episode_context(
    tenant_id: str,
    canonical_agent_ids: set[str],
    *,
    episode_store: Any = None,
    identity_rows: Optional[list[dict[str, Any]]] = None,
    execution_rows: Optional[list[dict[str, Any]]] = None,
) -> ExecutionEpisodeContextRead:
    """Read exact agent-subject episodes from one bounded tenant page."""
    if not canonical_agent_ids:
        return ExecutionEpisodeContextRead(
            "unknown", reason="canonical_agent_identity_unavailable_for_episode_join"
        )
    try:
        if episode_store is None:
            from shared.backend_interpretation.stores import EpisodeStore

            episode_store = EpisodeStore()
        page = await episode_store.list_page_by_tenant(
            tenant_id,
            limit=_MAX_EPISODE_AGENT_SCAN + 1,
        )
    except Exception:  # noqa: BLE001 - episode authority is fail-isolated
        return ExecutionEpisodeContextRead(
            "unavailable", reason="agent_episode_authority_unavailable"
        )

    records = getattr(page, "records", None)
    if not isinstance(records, (list, tuple)):
        return ExecutionEpisodeContextRead(
            "unavailable", reason="agent_episode_authority_invalid_contract"
        )
    page_truncated = (
        getattr(page, "truncated", True) is True or len(records) > _MAX_EPISODE_AGENT_SCAN
    )
    page_invalid = getattr(page, "invalid_records", False) is True
    episodes: list[dict[str, Any]] = []
    evidence_refs: list[EvidenceRef] = []
    identity_evidence_refs: list[EvidenceRef] = []
    seen_refs: set[tuple[str, str]] = set()
    seen_identity_refs: set[tuple[str, str]] = set()

    for identity in identity_rows or []:
        if not isinstance(identity, dict):
            page_invalid = True
            continue
        if identity.get("tenant_id") != tenant_id:
            page_invalid = True
            continue
        canonical_agent_id = _safe_text(identity.get("canonical_agent_entity_id"))
        source = _safe_text(identity.get("identity_evidence_source"))
        evidence_id = _safe_text(identity.get("identity_evidence_id"))
        if canonical_agent_id not in canonical_agent_ids or not source or not evidence_id:
            page_invalid = True
            continue
        identity_ref = _evidence_ref(
            evidence_id=evidence_id,
            source=source,
            observed_at=identity.get("identity_bound_at"),
            store=source,
        )
        if identity_ref is None:
            page_invalid = True
            continue
        key = (identity_ref.source, identity_ref.id)
        if key not in seen_identity_refs:
            seen_identity_refs.add(key)
            identity_evidence_refs.append(identity_ref)

    execution_event_links: dict[str, dict[str, dict[str, Any]]] = {}
    for execution in execution_rows or []:
        if not isinstance(execution, dict):
            page_invalid = True
            continue
        if execution.get("tenant_id") != tenant_id:
            page_invalid = True
            continue
        canonical_agent_id = _safe_text(execution.get("canonical_agent_entity_id"))
        execution_id = _safe_text(execution.get("execution_id"))
        event_id = _safe_text(execution.get("triggered_by_event_id"))
        if (
            execution.get("canonical_agent_identity") is True
            and canonical_agent_id in canonical_agent_ids
            and execution_id
            and event_id
        ):
            execution_event_links.setdefault(canonical_agent_id, {})[event_id] = execution

    for record in records[:_MAX_EPISODE_AGENT_SCAN]:
        if getattr(record, "tenant_id", None) != tenant_id:
            page_invalid = True
            continue
        subject = getattr(record, "subject", None)
        subject_kind = getattr(subject, "kind", None)
        subject_id = getattr(subject, "id", None)
        episode_id = _safe_text(getattr(record, "episode_id", None))
        if subject_kind != "agent" or subject_id not in canonical_agent_ids or not episode_id:
            continue

        raw_links = [getattr(record, "source_event_id", None)]
        observations = getattr(record, "observation_ids", [])
        if isinstance(observations, list):
            raw_links.extend(observations)
        event_ids = sorted({value for raw in raw_links if (value := _safe_text(raw)) is not None})
        refs: list[EvidenceRef] = [
            EvidenceRef(
                id=episode_id,
                type="event",
                source="episode_records",
                observedAt=_safe_text(getattr(record, "created_at", None)),
                uri=f"store://episode_records/{quote(episode_id, safe='')}",
            )
        ]
        raw_evidence_refs = getattr(record, "evidence_refs", [])
        if isinstance(raw_evidence_refs, list):
            refs.extend(ref for ref in raw_evidence_refs if isinstance(ref, EvidenceRef))
        for ref in refs:
            key = (ref.source, ref.id)
            if key not in seen_refs:
                seen_refs.add(key)
                evidence_refs.append(ref)
        matched_executions = []
        for event_id in sorted(
            set(event_ids).intersection(execution_event_links.get(subject_id, {}))
        ):
            execution = execution_event_links[subject_id][event_id]
            execution_id = _safe_text(execution.get("execution_id"))
            if not execution_id:
                continue
            matched_executions.append({"executionId": execution_id, "triggeredByEventId": event_id})
            execution_ref = _evidence_ref(
                evidence_id=execution_id,
                source=_INTERNAL_SOURCE,
                observed_at=execution.get("ended_at") or execution.get("started_at"),
                store=_INTERNAL_SOURCE,
            )
            if execution_ref is not None:
                key = (execution_ref.source, execution_ref.id)
                if key not in seen_refs:
                    seen_refs.add(key)
                    evidence_refs.append(execution_ref)
        episodes.append(
            {
                "episodeId": episode_id,
                "agentEntityId": subject_id,
                "kind": _safe_text(getattr(record, "kind", None)),
                "status": _safe_text(getattr(record, "status", None)) or "unknown",
                "occurredFrom": _safe_text(getattr(record, "occurred_from", None)),
                "occurredTo": _safe_text(getattr(record, "occurred_to", None)),
                "sourceEventIds": event_ids,
                "matchedExecutions": matched_executions,
                "evidenceRefs": [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True) for ref in refs
                ],
            }
        )

    episodes.sort(
        key=lambda item: (
            str(item.get("occurredFrom") or ""),
            str(item.get("episodeId") or ""),
        )
    )
    if page_truncated or page_invalid:
        return ExecutionEpisodeContextRead(
            "degraded" if episodes else "unknown",
            items=tuple(episodes),
            evidence_refs=tuple(evidence_refs),
            identity_evidence_refs=tuple(identity_evidence_refs),
            reason=(
                "agent_episode_scan_truncated"
                if page_truncated
                else "agent_episode_record_scope_conflict"
            ),
        )
    return ExecutionEpisodeContextRead(
        "available" if episodes else "empty",
        items=tuple(episodes),
        evidence_refs=tuple(evidence_refs),
        identity_evidence_refs=tuple(identity_evidence_refs),
    )


def _safe_text(value: Any, *, limit: int = 256) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return None
    return text


def _project_tool_call_read(
    read: Optional[ExecutionToolCallRead],
    *,
    admitted_execution_ids: set[str],
    time_range: Any = None,
    temporal_unavailable: bool = False,
) -> ExecutionToolCallRead:
    """Sanitize graph call edges against the already admitted execution scope."""
    if temporal_unavailable:
        return ExecutionToolCallRead(
            rows=[],
            available=bool(read and read.available),
            scope_known=False,
            truncated=bool(read and read.truncated),
            reason="temporal_anchor_not_reconstructable_from_current_sources",
        )
    if read is None:
        return ExecutionToolCallRead(
            rows=[],
            available=False,
            scope_known=False,
            reason="execution_tool_call_exact_join_not_available",
        )

    rows: list[dict[str, Any]] = []
    scope_known = read.scope_known
    seen: set[str] = set()
    lower = _parse_aware_instant(getattr(time_range, "from_", None)) if time_range else None
    upper = _parse_aware_instant(getattr(time_range, "to", None)) if time_range else None
    if time_range and (
        (getattr(time_range, "from_", None) is not None and lower is None)
        or (getattr(time_range, "to", None) is not None and upper is None)
        or (lower is not None and upper is not None and upper < lower)
    ):
        return ExecutionToolCallRead(
            rows=[],
            available=read.available,
            scope_known=False,
            truncated=read.truncated,
            reason="execution_time_window_invalid",
        )

    for raw in read.rows:
        if not isinstance(raw, dict):
            scope_known = False
            continue
        execution_id = _safe_text(raw.get("executionId"))
        tool_id = _safe_text(raw.get("toolId"))
        called_at = _safe_text(raw.get("calledAt"))
        instant = _parse_aware_instant(called_at)
        if not execution_id or execution_id not in admitted_execution_ids:
            # A reader-supplied foreign execution reference cannot broaden a
            # projection whose server lifecycle rows were already filtered.
            scope_known = False
            continue
        if (
            not tool_id
            or instant is None
            or raw.get("observationKind") != "server_recorded_agent_tool_call_lifecycle_edge"
            or raw.get("externalExecutionReceipt") != "unknown"
            or raw.get("authorityDecision") != "not_established_by_tool_call_edge"
        ):
            scope_known = False
            continue
        if (lower is not None and instant < lower) or (upper is not None and instant > upper):
            continue
        try:
            evidence = EvidenceRef.model_validate(raw.get("evidenceRef"))
        except Exception:  # noqa: BLE001 - evidence contract fails closed
            scope_known = False
            continue
        if (
            evidence.source != "graph_edges"
            or evidence.type != "event"
            or evidence.observedAt != called_at
            or evidence.uri != f"store://graph_edges/{quote(evidence.id, safe='')}"
        ):
            scope_known = False
            continue
        if evidence.id in seen:
            continue
        seen.add(evidence.id)
        rows.append(
            {
                "executionId": execution_id,
                "toolId": tool_id,
                "calledAt": called_at,
                "observationKind": "server_recorded_agent_tool_call_lifecycle_edge",
                "externalExecutionReceipt": "unknown",
                "authorityDecision": "not_established_by_tool_call_edge",
                "evidenceRef": evidence.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            }
        )

    reason = read.reason
    if rows and not reason:
        reason = "execution_tool_call_source_completeness_unknown"
    elif not rows and not reason:
        reason = (
            "execution_tool_call_graph_source_unavailable"
            if not read.available
            else "execution_tool_call_edge_scope_or_evidence_incomplete"
            if not scope_known or read.truncated
            else "execution_tool_call_exact_join_not_available"
        )
    return ExecutionToolCallRead(
        rows=rows,
        available=read.available,
        scope_known=scope_known,
        truncated=read.truncated,
        reason=reason,
    )


async def _resolve_server_delegation_reference(
    row: dict[str, Any], *, tenant_id: str, repository: Any
) -> dict[str, Any]:
    """Join a recorded decision to the exact tenant grant and canonical grantee.

    The current mutable grant row cannot prove historical scope or revocation
    state at execution time. This resolver establishes reference/party identity
    only; the execution's policy log remains the source for its recorded
    action-scoped decision.
    """
    if row.get("tenant_id") != tenant_id:
        return {"canonical_delegation_resolution_status": "execution_scope_mismatch"}
    recorded_ref = _safe_text(row.get("delegation_id"))
    if recorded_ref is None:
        return {"canonical_delegation_resolution_status": "not_recorded"}
    policy = row.get("policy_log")
    policy = policy if isinstance(policy, dict) else {}
    if policy.get("delegation_check_tenant_id") != tenant_id:
        return {"canonical_delegation_resolution_status": "policy_tenant_scope_unverified"}
    decision = policy.get("delegation_check")
    decision = decision if isinstance(decision, dict) else {}
    if not isinstance(decision.get("allowed"), bool):
        return {"canonical_delegation_resolution_status": "policy_decision_missing"}
    policy_ref = _safe_text(decision.get("delegation_id"))
    if policy_ref is None:
        return {"canonical_delegation_resolution_status": "policy_reference_missing"}
    if policy_ref != recorded_ref:
        return {"canonical_delegation_resolution_status": "conflicted_policy_reference"}
    canonical_agent_id = (
        _safe_text(row.get("canonical_agent_entity_id"))
        if row.get("canonical_agent_identity") is True
        else None
    )
    if canonical_agent_id is None:
        return {"canonical_delegation_resolution_status": "canonical_agent_unresolved"}

    delegation = await repository.find_by_id(recorded_ref)
    if not isinstance(delegation, dict):
        return {"canonical_delegation_resolution_status": "grant_not_found"}
    if (
        delegation.get("tenant_id") != tenant_id
        or _safe_text(delegation.get("delegation_id")) != recorded_ref
    ):
        return {"canonical_delegation_resolution_status": "grant_scope_mismatch"}
    if (
        _safe_text(delegation.get("grantor_entity_id")) is None
        or not isinstance(delegation.get("scope"), dict)
    ):
        return {"canonical_delegation_resolution_status": "grant_record_incomplete"}
    if _safe_text(delegation.get("grantee_entity_id")) != canonical_agent_id:
        return {"canonical_delegation_resolution_status": "grant_party_mismatch"}
    observed_at = next(
        (
            parsed.isoformat()
            for value in (delegation.get("updated_at"), delegation.get("created_at"))
            if (parsed := _parse_aware_instant(value)) is not None
        ),
        None,
    )
    return {
        "canonical_delegation_matched": True,
        "canonical_delegation_id": recorded_ref,
        "canonical_delegation_resolution_status": "matched_current_grant_reference_and_grantee",
        "canonical_delegation_evidence_observed_at": observed_at,
    }


def _safe_observed_fact(
    row: dict[str, Any], resolution: dict[str, Any]
) -> Optional[dict[str, Any]]:
    source_event_id = _safe_text(row.get("source_event_id") or row.get("fact_id"))
    if not source_event_id:
        return None
    delegation = resolution.get("delegation_record") or {}
    authorization = resolution.get("delegation_authorization") or {}
    actor_resolution = resolution.get("delegation_resolution") or {}
    delegation_ref = _safe_text(row.get("delegation_id"))
    delegation_is_canonical = bool(
        delegation_ref
        and delegation.get("tenant_id") == row.get("tenant_id")
        and delegation.get("delegation_id") == delegation_ref
    )
    parties_resolved = bool(
        delegation_is_canonical
        and actor_resolution.get("party_identity_status") == "matched"
        and authorization.get("binding_authority") == "tenant_admin_explicit"
        and authorization.get("actor_entity_id") == actor_resolution.get("grantor_entity_id")
        and authorization.get("target_entity_id") == actor_resolution.get("grantee_entity_id")
        and delegation.get("grantor_entity_id") == actor_resolution.get("grantor_entity_id")
        and delegation.get("grantee_entity_id") == actor_resolution.get("grantee_entity_id")
    )
    raw_scope = delegation.get("scope")
    delegation_scope: list[str] = []
    if isinstance(raw_scope, dict):
        for category in ("actions", "resources"):
            values = raw_scope.get(category)
            if not isinstance(values, list):
                continue
            delegation_scope.extend(
                f"{category[:-1]}:{text}"
                for value in values[:100]
                if (text := _safe_text(value)) is not None
            )
    raw_status = _safe_text(actor_resolution.get("state_at_event"))
    delegation_status = (
        "granted"
        if raw_status == "active"
        else raw_status
        if raw_status in {"revoked", "expired"}
        else "unknown"
    )
    end_values = [
        value
        for value in (delegation.get("ends_at"), delegation.get("revoked_at"))
        if _parse_aware_instant(value) is not None
    ]
    valid_until = (
        min(end_values, key=lambda value: _parse_aware_instant(value)) if end_values else None
    )
    evidence_observed_at = next(
        (
            parsed.isoformat()
            for value in (delegation.get("updated_at"), delegation.get("created_at"))
            if (parsed := _parse_aware_instant(value)) is not None
        ),
        None,
    )
    return {
        "tenantId": _safe_text(row.get("tenant_id")),
        "sourceEventId": source_event_id,
        "occurredAt": _safe_text(row.get("occurred_at")),
        # Postgres rows carry the type as ``source_event_type`` (no ``event_name`` column).
        "eventName": _safe_text(
            row.get("source_event_type") or row.get("event_name") or row.get("event_type")
        ),
        "runId": _safe_text(row.get("run_id")),
        "actorAgentId": _safe_text(authorization.get("actor_entity_id")),
        "actorIdentityStatus": _safe_text(actor_resolution.get("actor_identity_status")),
        "delegationId": delegation_ref if delegation_is_canonical else None,
        "delegationResolutionStatus": _safe_text(actor_resolution.get("status")),
        "delegationPartyBindingStatus": ("matched" if parties_resolved else "unknown"),
        "delegatorAgentId": (
            _safe_text(actor_resolution.get("grantor_entity_id")) if parties_resolved else None
        ),
        "delegateeAgentId": (
            _safe_text(actor_resolution.get("grantee_entity_id")) if parties_resolved else None
        ),
        "delegationScope": delegation_scope if parties_resolved else [],
        "delegationValidFrom": (
            _safe_text(delegation.get("starts_at")) if parties_resolved else None
        ),
        "delegationValidUntil": (_safe_text(valid_until) if parties_resolved else None),
        "delegationStatus": delegation_status if parties_resolved else "unknown",
        "delegationEvidenceId": delegation_ref if parties_resolved else None,
        "delegationEvidenceObservedAt": (evidence_observed_at if parties_resolved else None),
        "authorizationStatus": _safe_text(authorization.get("status")),
        "actionType": _safe_text(row.get("action_type")),
        "resourceRef": _safe_text(row.get("resource_ref")),
        "toolName": _safe_text(row.get("tool_name")),
        "reportedStatus": _safe_text(row.get("status")),
        "executionOccurrence": "source_reported",
        "executionVerified": False,
        "executionEvidenceReason": "no_server_authoritative_external_execution_receipt",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_aware_instant(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _filter_window(
    internal: list[dict[str, Any]],
    external: list[dict[str, Any]],
    start: Optional[str],
    end: Optional[str],
) -> Optional[tuple[list[dict[str, Any]], list[dict[str, Any]], bool]]:
    """Filter an explicit window and flag rows whose occurrence time is unknown.

    A malformed bound makes the request unsatisfied. Rows with no usable event
    time are excluded and mark the result incomplete instead of leaking into a
    bounded view.
    """
    lower = _parse_aware_instant(start) if start is not None else None
    upper = _parse_aware_instant(end) if end is not None else None
    if (start is not None and lower is None) or (end is not None and upper is None):
        return None
    if lower is not None and upper is not None and upper < lower:
        return None

    undated = False

    def select(rows: list[dict[str, Any]], *, internal_rows: bool) -> list[dict[str, Any]]:
        nonlocal undated
        selected: list[dict[str, Any]] = []
        for row in rows:
            timestamp = (
                row.get("endedAt") or row.get("startedAt")
                if internal_rows
                else row.get("occurredAt")
            )
            instant = _parse_aware_instant(timestamp)
            if instant is None:
                undated = True
                continue
            if lower is not None and instant < lower:
                continue
            if upper is not None and instant > upper:
                continue
            selected.append(row)
        return selected

    return select(internal, internal_rows=True), select(external, internal_rows=False), undated


def _evidence_ref(
    *, evidence_id: Any, source: str, observed_at: Any, store: str
) -> Optional[EvidenceRef]:
    ref_id = _safe_text(evidence_id)
    if not ref_id:
        return None
    timestamp = _safe_text(observed_at)
    return EvidenceRef(
        id=ref_id,
        type="event",
        source=source,
        observedAt=timestamp,
        uri=f"store://{store}/{quote(ref_id, safe='')}",
    )


def _internal_record(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = row.get("input_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    raw_policy = row.get("policy_log")
    policy = raw_policy
    policy = policy if isinstance(policy, dict) else {}
    raw_decision = policy.get("delegation_check")
    decision = (
        raw_decision if isinstance(raw_decision, dict) and row.get("tenant_id")
        and policy.get("delegation_check_tenant_id") == row["tenant_id"] else {}
    )
    recorded_delegation_id = _safe_text(row.get("delegation_id"))
    canonical_delegation_id = _safe_text(row.get("canonical_delegation_id"))
    policy_delegation_id = _safe_text(decision.get("delegation_id"))
    delegation_matched = (
        row.get("canonical_delegation_matched") is True
        and row.get("canonical_delegation_resolution_status")
        == "matched_current_grant_reference_and_grantee"
        and recorded_delegation_id is not None
        and recorded_delegation_id == policy_delegation_id == canonical_delegation_id
        and isinstance(decision.get("allowed"), bool)
    )
    resolution_status = (
        _safe_text(row.get("canonical_delegation_resolution_status")) or "unresolved"
        if recorded_delegation_id
        else "not_recorded"
    )
    if resolution_status == "matched_current_grant_reference_and_grantee" and not delegation_matched:
        resolution_status = "unverified_join_metadata"
    return {
        "executionId": _safe_text(row.get("execution_id")),
        "_tenantId": _safe_text(row.get("tenant_id")),
        "workflowRunId": _safe_text(row.get("workflow_run_id")),
        "workflowRunInvocationEvidenceRefs": (
            row.get("workflow_run_invocation_evidence_refs")
            if isinstance(row.get("workflow_run_invocation_evidence_refs"), list)
            else []
        ),
        "approvalId": _safe_text(row.get("approval_id")),
        "approvalDecisionId": _safe_text(row.get("approval_decision_id")),
        "agentId": (
            _safe_text(row.get("canonical_agent_entity_id"))
            if row.get("canonical_agent_identity") is True
            else None
        ),
        "initiatingPrincipalUserId": _safe_text(row.get("initiating_principal_user_id")),
        "delegationId": (
            canonical_delegation_id
            if delegation_matched
            else None
        ),
        "delegationEvidenceObservedAt": (
            _safe_text(row.get("canonical_delegation_evidence_observed_at"))
            if delegation_matched
            else None
        ),
        "canonicalActorResolved": row.get("canonical_agent_identity") is True,
        "ownerEntityId": _safe_text(row.get("canonical_owner_entity_id")),
        "status": _safe_text(row.get("status")) or "unknown",
        "startedAt": _safe_text(row.get("started_at")),
        "endedAt": _safe_text(row.get("ended_at")),
        "recordCreatedAt": _safe_text(row.get("created_at")),
        "triggeredByEventId": _safe_text(row.get("triggered_by_event_id")),
        "requestedAction": _safe_text(snapshot.get("action")),
        "requestedResource": _safe_text(snapshot.get("resource")),
        "_delegationDecisionPresent": (
            "delegation_check" in policy
            or (raw_policy is not None and not isinstance(raw_policy, dict))
        ),
        "_delegationReferenceConflict": (
            recorded_delegation_id is not None
            and policy_delegation_id is not None
            and recorded_delegation_id != policy_delegation_id
        ),
        "recordedDelegationDecision": (
            decision.get("allowed") if isinstance(decision.get("allowed"), bool) else None
        ),
        "recordedDelegationDecisionEvaluatedAt": _safe_text(decision.get("evaluated_at")),
        "delegationDecisionReason": _safe_text(decision.get("reason")),
        "delegationResolutionStatus": resolution_status,
        "outcomeEventId": _safe_text(row.get("outcome_event_id")),
        "outcomeEventPublished": (
            row.get("outcome_event_published")
            if isinstance(row.get("outcome_event_published"), bool)
            else None
        ),
        "externalExecutionReceipt": "unknown",
        "businessOutcome": "unknown",
        "source": _INTERNAL_SOURCE,
    }


def _execution_authority_context(
    internal: list[dict[str, Any]],
    *,
    tenant_id: str,
    source_read: ExecutionRead,
    execution_inventory_complete: bool,
    temporal_unavailable: bool,
    time_range: Optional[TimeRangeFilter],
) -> ExecutionAuthorityContext:
    """Project stored policy outcomes without replaying the authority engine.

    The delegation check and its action/resource are co-recorded on one
    tenant-scoped ``agent_executions`` row. Time windows select the parent
    lifecycle row only, even when the policy check has a recorded timestamp.
    """
    if temporal_unavailable:
        return ExecutionAuthorityContext(
            state="unknown",
            reason="temporal_anchor_not_reconstructable_from_current_sources",
            source_read_state="available" if source_read.available else "unavailable",
            temporal_selection="unsupported_historical_or_comparison_request",
        )
    if not source_read.available:
        return ExecutionAuthorityContext(
            state="unavailable",
            reason=source_read.reason or "execution_authority_lifecycle_source_unavailable",
            source_read_state="unavailable",
            truncated=source_read.truncated,
            temporal_selection=(
                "execution_lifecycle_time_window" if time_range else "execution_lifecycle_rows"
            ),
        )

    execution_counts: dict[str, int] = {}
    for row in internal:
        execution_id = _safe_text(row.get("executionId"))
        if execution_id:
            execution_counts[execution_id] = execution_counts.get(execution_id, 0) + 1
    ambiguous_ids = tuple(sorted(
        execution_id for execution_id, count in execution_counts.items() if count > 1
    ))
    ambiguous = set(ambiguous_ids)
    invalid_record = bool(ambiguous_ids)
    decisions: list[dict[str, Any]] = []
    evidence_refs: list[EvidenceRef] = []
    decision_timestamps: list[str] = []

    for row in internal:
        execution_id = _safe_text(row.get("executionId"))
        if execution_id is None or execution_id in ambiguous:
            continue
        if row.get("_delegationReferenceConflict") is True:
            invalid_record = True
            continue
        if not isinstance(row.get("recordedDelegationDecision"), bool):
            if row.get("_delegationDecisionPresent") is True:
                invalid_record = True
            continue
        action = _safe_text(row.get("requestedAction"))
        resource = _safe_text(row.get("requestedResource"))
        evidence = _lifecycle_evidence(row)
        if (
            row.get("_tenantId") != tenant_id
            or not action
            or not resource
            or evidence is None
            or evidence.source != _INTERNAL_SOURCE
            or evidence.id != execution_id
            or _parse_aware_instant(evidence.observedAt) is None
        ):
            invalid_record = True
            continue

        raw_decision_time = row.get("recordedDelegationDecisionEvaluatedAt")
        parsed_decision_time = _parse_aware_instant(raw_decision_time)
        if raw_decision_time is None:
            decision_time: dict[str, Any] = {
                "state": "unknown",
                "reason": "delegation_decision_timestamp_not_persisted",
            }
        elif parsed_decision_time is None:
            invalid_record = True
            decision_time = {
                "state": "unknown",
                "reason": "delegation_decision_timestamp_invalid",
            }
        else:
            record_created_at = _parse_aware_instant(row.get("recordCreatedAt"))
            if record_created_at is not None and parsed_decision_time > record_created_at:
                invalid_record = True
                decision_time = {
                    "state": "unknown",
                    "reason": "delegation_decision_timestamp_after_execution_record",
                }
            else:
                evaluated_at = parsed_decision_time.isoformat()
                decision_timestamps.append(evaluated_at)
                decision_time = {
                    "state": "recorded",
                    "evaluatedAt": evaluated_at,
                    "source": "agent_executions.policy_log.delegation_check.evaluated_at",
                }

        serialized_evidence = evidence.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        evidence_refs.append(evidence)
        decisions.append(
            {
                "tenantId": tenant_id,
                "executionId": execution_id,
                "action": action,
                "resource": resource,
                "decision": "allow" if row["recordedDelegationDecision"] else "deny",
                "delegationId": row.get("delegationId"),
                "reasonCode": row.get("delegationDecisionReason"),
                "authority": "agent_executions.policy_log.delegation_check",
                "lifecycleTimestamps": {
                    "startedAt": row.get("startedAt"),
                    "endedAt": row.get("endedAt"),
                    "recordCreatedAt": row.get("recordCreatedAt"),
                },
                "decisionTime": {
                    **decision_time,
                },
                "evidenceRef": serialized_evidence,
            }
        )

    complete_scope = (
        source_read.scope_known
        and not source_read.truncated
        and execution_inventory_complete
        and not invalid_record
    )
    if decisions and complete_scope:
        state: Literal["partial", "unknown", "degraded", "unavailable"] = "partial"
        reason = "recorded_delegation_checks_only_effective_authority_remains_unknown"
    elif decisions or invalid_record or not complete_scope:
        state = "degraded"
        reason = (
            "execution_authority_record_scope_or_evidence_ambiguous"
            if invalid_record
            else source_read.reason
            or "execution_authority_inventory_or_scope_incomplete"
        )
    else:
        state = "unknown"
        reason = "no_exact_recorded_delegation_decision_for_admitted_execution_scope"

    decision_timestamp_coverage = (
        "persisted"
        if decisions and len(decision_timestamps) == len(decisions)
        else "partial"
        if decision_timestamps
        else "not_persisted"
    )

    return ExecutionAuthorityContext(
        state=state,
        decisions=tuple(decisions),
        evidence_refs=tuple(evidence_refs),
        reason=reason,
        source_read_state="available",
        scope_known=complete_scope,
        truncated=source_read.truncated,
        ambiguous_execution_ids=ambiguous_ids,
        temporal_selection=(
            "execution_lifecycle_time_window" if time_range else "execution_lifecycle_rows"
        ),
        decision_timestamp_coverage=decision_timestamp_coverage,
    )


def _task_decomposition_record(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Validate a persisted task-decomposition observation, without metadata.

    ``AgentLifecycleMapper`` writes these to the execution repository with an
    exact ``execution_id:decomposition`` record ID. They are not lifecycle
    rows and are meaningful here only after joining to that execution ID.
    """
    if row.get("event_type") != "task_decomposed":
        return None
    execution_id = _safe_text(row.get("execution_id"))
    record_id = _safe_text(row.get("record_id"))
    root_task_id = _safe_text(row.get("root_task_id"))
    occurred_at = _safe_text(row.get("occurred_at"))
    subtask_values = row.get("subtask_ids")
    if (
        not execution_id
        or record_id != f"{execution_id}:decomposition"
        or not root_task_id
        or _parse_aware_instant(occurred_at) is None
        or not isinstance(subtask_values, list)
    ):
        return None
    subtask_ids = [
        text
        for value in subtask_values[:_MAX_ROWS]
        if (text := _safe_text(value)) is not None
    ]
    if len(subtask_ids) != len(set(subtask_ids)):
        return None
    return {
        "recordId": record_id,
        "executionId": execution_id,
        "agentId": (
            _safe_text(row.get("canonical_agent_entity_id"))
            if row.get("canonical_agent_identity") is True
            else None
        ),
        "ownerEntityId": _safe_text(row.get("canonical_owner_entity_id")),
        "rootTaskId": root_task_id,
        "subtaskIds": subtask_ids,
        "subtaskIdsTruncated": len(subtask_values) > _MAX_ROWS,
        "occurredAt": occurred_at,
    }


def _observed_record(row: dict[str, Any]) -> dict[str, Any]:
    # Re-sanitize the reader contract. Test doubles and future readers must not
    # be able to smuggle arbitrary raw telemetry into the projection response.
    raw_delegation_scope = row.get("delegationScope")
    return {
        "tenantId": _safe_text(row.get("tenantId")),
        "sourceEventId": _safe_text(row.get("sourceEventId")),
        "occurredAt": _safe_text(row.get("occurredAt")),
        "eventName": _safe_text(row.get("eventName")),
        "runId": _safe_text(row.get("runId")),
        "actorAgentId": _safe_text(row.get("actorAgentId")),
        "actorIdentityStatus": _safe_text(row.get("actorIdentityStatus")),
        "delegationId": _safe_text(row.get("delegationId")),
        "delegationResolutionStatus": _safe_text(row.get("delegationResolutionStatus")),
        "delegationPartyBindingStatus": _safe_text(row.get("delegationPartyBindingStatus")),
        "delegatorAgentId": _safe_text(row.get("delegatorAgentId")),
        "delegateeAgentId": _safe_text(row.get("delegateeAgentId")),
        "delegationScope": (
            [
                text
                for value in raw_delegation_scope[:200]
                if (text := _safe_text(value)) is not None
            ]
            if isinstance(raw_delegation_scope, list)
            else []
        ),
        "delegationValidFrom": _safe_text(row.get("delegationValidFrom")),
        "delegationValidUntil": _safe_text(row.get("delegationValidUntil")),
        "delegationStatus": _safe_text(row.get("delegationStatus")),
        "delegationEvidenceId": _safe_text(row.get("delegationEvidenceId")),
        "delegationEvidenceObservedAt": _safe_text(row.get("delegationEvidenceObservedAt")),
        "authorizationStatus": _safe_text(row.get("authorizationStatus")),
        "actionType": _safe_text(row.get("actionType")),
        "resourceRef": _safe_text(row.get("resourceRef")),
        "toolName": _safe_text(row.get("toolName")),
        "reportedStatus": _safe_text(row.get("reportedStatus")),
        "executionOccurrence": "source_reported",
        "executionVerified": False,
        "executionEvidenceReason": "no_server_authoritative_external_execution_receipt",
    }


def _lifecycle_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    return _evidence_ref(
        evidence_id=row.get("executionId"),
        source=_INTERNAL_SOURCE,
        observed_at=row.get("endedAt") or row.get("startedAt"),
        store=_INTERNAL_SOURCE,
    )


def _task_decomposition_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    return _evidence_ref(
        evidence_id=row.get("recordId"),
        source=_INTERNAL_SOURCE,
        observed_at=row.get("occurredAt"),
        store=_INTERNAL_SOURCE,
    )


def _internal_delegation_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    evidence_id = _safe_text(row.get("delegationId"))
    if (
        not evidence_id
        or row.get("delegationResolutionStatus")
        != "matched_current_grant_reference_and_grantee"
    ):
        return None
    return EvidenceRef(
        id=evidence_id,
        type="relationship",
        source="delegations",
        observedAt=_safe_text(row.get("delegationEvidenceObservedAt")),
        uri=f"store://delegations/{quote(evidence_id, safe='')}",
    )


def _fact_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    return _evidence_ref(
        evidence_id=row.get("sourceEventId"),
        source=_SILVER_SOURCE,
        observed_at=row.get("occurredAt"),
        store=_SILVER_SOURCE,
    )


def _delegation_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    evidence_id = _safe_text(row.get("delegationEvidenceId"))
    if not evidence_id:
        return None
    return EvidenceRef(
        id=evidence_id,
        type="relationship",
        source="delegations",
        observedAt=_safe_text(row.get("delegationEvidenceObservedAt")),
        uri=f"store://delegations/{quote(evidence_id, safe='')}",
    )


class Execution360Provider:
    """Governed, read-only Execution360 provider with explicit lineage."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, sources: Optional[Execution360Source] = None) -> None:
        self._sources = sources if sources is not None else RepositoryExecution360Source()

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        tenant_id = request.tenantId
        limit = min(max(request.page.limit if request.page else 50, 1), _MAX_ROWS)
        if context.tenantId != tenant_id:
            server = ExecutionRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="tenant_scope_mismatch",
            )
            observed = server
        else:
            server = await self._safe_read("server_executions", tenant_id, request.subject, limit)
            observed = await self._safe_read("observed_facts", tenant_id, request.subject, limit)

        # A source adapter (or injected reader) cannot certify a complete
        # tenant read while returning out-of-scope rows. Keep those rows out of
        # the frame and downgrade coverage so a foreign-only batch never
        # becomes an apparently complete empty result.
        if any(
            not isinstance(row, dict) or row.get("tenant_id") != tenant_id
            for row in server.rows
        ):
            server = replace(
                server,
                scope_known=False,
                reason="server_execution_scope_mismatch",
            )
        if request.subject.kind == "workflow_run" and any(
            not isinstance(row, dict)
            or row.get("workflow_run_id") != request.subject.id
            or row.get("event_type") is not None
            for row in server.rows
        ):
            server = replace(
                server,
                scope_known=False,
                reason="workflow_run_execution_scope_mismatch",
            )
        if any(
            not isinstance(row, dict)
            or _safe_text(row.get("tenantId")) != tenant_id
            for row in observed.rows
        ):
            observed = replace(
                observed,
                scope_known=False,
                reason="observed_execution_scope_mismatch",
            )

        malformed_task_decomposition = any(
            isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("event_type") == "task_decomposed"
            and _task_decomposition_record(row) is None
            for row in server.rows
        )
        plan_decompositions = [
            item
            for row in server.rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("agent_id")
            and (item := _task_decomposition_record(row)) is not None
        ]
        internal = [
            _internal_record(row)
            for row in server.rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("agent_id")
            and row.get("event_type") is None
            and _safe_text(row.get("execution_id"))
        ]
        principal_user_ids = {
            principal_id
            for row in internal
            if (principal_id := _safe_text(row.get("initiatingPrincipalUserId"))) is not None
        }
        principal_bindings, principal_identity_read_state, principal_identity_reason = (
            _execution_principal_identity_bindings(
                server.principal_identity_read,
                tenant_id=tenant_id,
                principal_user_ids=principal_user_ids,
            )
        )
        for row in internal:
            principal_id = _safe_text(row.get("initiatingPrincipalUserId"))
            binding = principal_bindings.get(principal_id) if principal_id else None
            row["initiatingPrincipalIdentityState"] = (
                binding["state"]
                if binding
                else "not_recorded"
                if principal_id is None
                else "unknown"
            )
            row["canonicalInitiatingPrincipalHumanEntityId"] = (
                binding.get("canonical_human_entity_id") if binding else None
            )
            row["initiatingPrincipalIdentityEvidenceRefs"] = (
                [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for ref in binding.get("evidence_refs", [])
                ]
                if binding
                else []
            )
        external = [
            item
            for row in observed.rows
            if isinstance(row, dict)
            and (item := _observed_record(row)).get("sourceEventId")
            and item.get("tenantId") == tenant_id
            and item.get("actorIdentityStatus") == "matched"
            and item.get("delegationResolutionStatus") == "matched_reference"
            and item.get("actorAgentId")
        ]

        temporal_mode = request.temporalMode or "window"
        temporal_unavailable = bool(request.asOf or temporal_mode != "window")
        window_undated = False
        if request.timeRange is not None and not temporal_unavailable:
            window_result = _filter_window(
                internal,
                external,
                request.timeRange.from_,
                request.timeRange.to,
            )
            if window_result is None:
                temporal_unavailable = True
                internal = []
                external = []
            else:
                internal, external, window_undated = window_result

        # Exact tenant + owner-agent backstop. An injected/default source may
        # return extra rows; the provider drops any row not bound to the subject.
        allowed_agent_ids = set(server.agent_ids) | set(observed.agent_ids)
        internal = [
            row
            for row in internal
            if (
                (
                    row.get("executionId") == request.subject.id
                    and request.subject.kind == "execution"
                )
                or (
                    row.get("workflowRunId") == request.subject.id
                    and request.subject.kind == "workflow_run"
                )
                or (
                    request.subject.kind in {"agent", "entity", "episode"}
                    and row.get("agentId") in allowed_agent_ids
                    and row.get("canonicalActorResolved") is True
                )
            )
            and (request.subject.kind != "entity" or row.get("ownerEntityId") == request.subject.id)
        ]
        plan_decompositions = [
            row
            for row in plan_decompositions
            if (
                (
                    row.get("executionId") == request.subject.id
                    and request.subject.kind == "execution"
                )
                or (
                    row.get("workflowRunId") == request.subject.id
                    and request.subject.kind == "workflow_run"
                )
                or (
                    request.subject.kind in {"agent", "entity", "episode"}
                    and row.get("agentId") in allowed_agent_ids
                )
            )
            and (
                request.subject.kind != "entity"
                or row.get("ownerEntityId") == request.subject.id
            )
        ]
        episode_event_binding_mismatch = False
        for row in internal:
            # The config owner ref is used for the tenant-scoped join; it is
            # not independently resolved entity identity for the response.
            row.pop("ownerEntityId", None)
        if request.subject.kind == "entity":
            # Internal rows are source-filtered through tenant-owned configs;
            # external resolved actors need the same owner binding. The source
            # has already checked this before returning its facts.
            external = [item for item in external if item.get("actorAgentId") in allowed_agent_ids]
        elif request.subject.kind == "agent":
            external = [item for item in external if item.get("actorAgentId") in allowed_agent_ids]
        elif request.subject.kind == "episode":
            server_event_ids = set(server.subject_event_ids)
            observed_event_ids = set(observed.subject_event_ids)
            episode_event_ids = server_event_ids & observed_event_ids
            internal = [
                row for row in internal if row.get("triggeredByEventId") in episode_event_ids
            ]
            external = [item for item in external if item.get("sourceEventId") in episode_event_ids]
            episode_event_binding_mismatch = server_event_ids != observed_event_ids
        elif request.subject.kind == "execution":
            internal = [row for row in internal if row.get("executionId") == request.subject.id]
            # No source telemetry is attached unless a canonical execution/run
            # crosswalk is available; this provider deliberately leaves it out.
            external = []
        elif request.subject.kind == "workflow_run":
            internal = [
                row for row in internal if row.get("workflowRunId") == request.subject.id
            ]
            # Telemetry run_id values lack a canonical workflow_run_id
            # crosswalk, so only exact lifecycle references are admitted.
            external = []
        else:
            internal = []
            external = []
            plan_decompositions = []

        # A task observation must join to a lifecycle row already admitted by
        # this request's tenant, subject, episode, and time-window filters.
        # The shared execution ID alone is insufficient to bypass those gates.
        admitted_execution_ids = {
            row["executionId"] for row in internal if row.get("executionId")
        }
        plan_decompositions = [
            row
            for row in plan_decompositions
            if row.get("executionId") in admitted_execution_ids
        ]
        if request.timeRange is not None and not temporal_unavailable:
            lower = _parse_aware_instant(request.timeRange.from_)
            upper = _parse_aware_instant(request.timeRange.to)
            plan_decompositions = [
                row
                for row in plan_decompositions
                if (instant := _parse_aware_instant(row.get("occurredAt"))) is not None
                and (lower is None or instant >= lower)
                and (upper is None or instant <= upper)
            ]

        if temporal_unavailable:
            # Do not expose current mutable lifecycle/source rows as an answer
            # to an unsupported historical or comparison request.
            internal = []
            external = []
            plan_decompositions = []

        source_provenance = await self._safe_source_provenance_read(
            tenant_id,
            tuple(
                (row["sourceEventId"], row["eventName"])
                for row in external
                if row.get("sourceEventId") and row.get("eventName")
            ),
        )

        admitted_execution_ids = {
            row["executionId"] for row in internal if row.get("executionId")
        }
        execution_inventory_complete = (
            server.available
            and server.scope_known
            and not server.truncated
            and not episode_event_binding_mismatch
            and not temporal_unavailable
        )
        cost_subjects_by_execution: dict[str, set[str]] = {}
        internal_by_execution = {
            row["executionId"]: row
            for row in internal
            if row.get("executionId")
        }
        for raw in server.rows:
            if (
                not isinstance(raw, dict)
                or raw.get("tenant_id") != tenant_id
                or raw.get("event_type") is not None
            ):
                continue
            execution_id = _safe_text(raw.get("execution_id"))
            source_agent_id = _safe_text(raw.get("agent_id"))
            lifecycle = internal_by_execution.get(execution_id or "")
            if (
                execution_id not in admitted_execution_ids
                or source_agent_id is None
                or lifecycle is None
                or lifecycle.get("canonicalActorResolved") is not True
                or _safe_text(raw.get("canonical_agent_entity_id"))
                != lifecycle.get("agentId")
            ):
                continue
            cost_subjects_by_execution.setdefault(execution_id, set()).add(source_agent_id)
        execution_cost_subjects = tuple(
            sorted(
                (execution_id, next(iter(agent_ids)))
                for execution_id, agent_ids in cost_subjects_by_execution.items()
                if len(agent_ids) == 1
            )
        )
        execution_cost_subjects_complete = (
            {execution_id for execution_id, _ in execution_cost_subjects}
            == admitted_execution_ids
        )
        if temporal_unavailable:
            execution_cost_read = ExecutionCostRead(
                [],
                True,
                False,
                reason="temporal_anchor_not_reconstructable_from_current_sources",
            )
        elif not admitted_execution_ids:
            execution_cost_read = ExecutionCostRead(
                [],
                True,
                execution_inventory_complete,
                reason="no_admitted_execution_ids_in_subject_scope",
            )
        elif not execution_cost_subjects_complete:
            execution_cost_read = ExecutionCostRead(
                [],
                True,
                False,
                reason="exact_execution_agent_binding_unavailable",
            )
        elif request.includeSections is not None and not (
            {"state", "summary"} & set(request.includeSections)
        ):
            execution_cost_read = ExecutionCostRead(
                [],
                False,
                False,
                reason="latency_cost_sections_not_requested",
            )
        else:
            execution_cost_read = await self._safe_execution_cost_read(
                tenant_id, execution_cost_subjects, limit
            )

        tool_calls = _project_tool_call_read(
            server.tool_calls,
            admitted_execution_ids=admitted_execution_ids,
            time_range=request.timeRange,
            temporal_unavailable=temporal_unavailable,
        )
        if admitted_execution_ids and not temporal_unavailable:
            risk_event_read = await self._safe_execution_risk_read(
                tenant_id, tuple(sorted(admitted_execution_ids)), limit
            )
            risk_events = _execution_risk_event_context(
                risk_event_read,
                tenant_id=tenant_id,
                execution_ids=admitted_execution_ids,
                execution_inventory_complete=execution_inventory_complete,
                time_range=request.timeRange,
            )
        elif (
            request.subject.kind != "execution"
            and not temporal_unavailable
            and execution_inventory_complete
        ):
            risk_events = ExecutionRiskEventContext(
                state="empty",
                reason="no_admitted_execution_ids_in_subject_scope",
                source_read_state="not_read",
                scope_known=True,
            )
        else:
            risk_events = ExecutionRiskEventContext(
                state="unknown",
                reason=(
                    "temporal_anchor_not_reconstructable_from_current_sources"
                    if temporal_unavailable
                    else "execution_subject_not_admitted_from_server_lifecycle"
                    if request.subject.kind == "execution"
                    else "agent_risk_records_do_not_carry_a_canonical_agent_execution_id"
                ),
                source_read_state="not_read",
            )

        if admitted_execution_ids and not temporal_unavailable:
            approval_read = await self._safe_execution_approval_read(
                tenant_id,
                tuple(sorted(admitted_execution_ids)),
                limit,
            )
        else:
            approval_read = ExecutionApprovalRead(
                rows=[],
                available=True,
                scope_known=execution_inventory_complete,
            )
        approval_chain = _execution_approval_context(
            approval_read,
            tenant_id=tenant_id,
            execution_ids=admitted_execution_ids,
            internal=internal,
            execution_inventory_complete=execution_inventory_complete,
            temporal_unavailable=temporal_unavailable,
        )
        authority_check = _execution_authority_context(
            internal,
            tenant_id=tenant_id,
            source_read=server,
            execution_inventory_complete=execution_inventory_complete,
            temporal_unavailable=temporal_unavailable,
            time_range=request.timeRange,
        )

        reasons: list[str] = []
        if not server.available:
            reasons.append("server_execution_source_unavailable")
        if server.reason and "unavailable" not in server.reason:
            reasons.append(server.reason)
        if not observed.available:
            reasons.append("observed_execution_source_unavailable")
        if observed.reason and "unavailable" not in observed.reason:
            reasons.append(observed.reason)
        if (not server.scope_known or not observed.scope_known) and not reasons:
            reasons.append("execution_subject_binding_incomplete")
        if server.truncated or observed.truncated:
            reasons.append("execution_source_truncated")
        if principal_user_ids and principal_identity_read_state != "available":
            reasons.append(principal_identity_reason or "principal_identity_read_incomplete")
        if any(
            row.get("initiatingPrincipalIdentityState") == "ambiguous" for row in internal
        ):
            reasons.append("principal_identity_ambiguous")
        if temporal_unavailable:
            reasons.append("temporal_anchor_not_reconstructable_from_current_sources")
        if window_undated:
            reasons.append("execution_window_omitted_rows_without_event_time")
        if malformed_task_decomposition:
            reasons.append("task_decomposition_record_invalid")
        if any(row["subtaskIdsTruncated"] for row in plan_decompositions):
            reasons.append("task_decomposition_subtask_list_truncated")
        if risk_events.state in {"degraded", "unavailable"} and risk_events.reason:
            reasons.append(risk_events.reason)
        if approval_chain.state in {"degraded", "unavailable"} and approval_chain.reason:
            reasons.append(approval_chain.reason)
        if authority_check.state == "degraded" and authority_check.reason:
            reasons.append(authority_check.reason)
        if request.subject.kind == "episode" and episode_event_binding_mismatch:
            reasons.append("episode_execution_event_binding_conflict")

        latency_cost = _latency_cost_summary(
            internal,
            server,
            execution_cost_read,
            execution_inventory_complete=(
                execution_inventory_complete and execution_cost_subjects_complete
            ),
            temporal_unavailable=temporal_unavailable,
        )
        state = _section_state(server, observed, internal, external, temporal_unavailable)
        evidence = self._all_evidence(
            tenant_id,
            internal,
            external,
            plan_decompositions,
            tool_calls,
            risk_events,
            approval_chain,
            authority_check,
            latency_cost,
            source_provenance,
        )
        claims = (
            self._claims(
                tenant_id,
                request.subject,
                internal,
                external,
                plan_decompositions,
                tool_calls,
                risk_events,
                approval_chain,
                authority_check,
                latency_cost,
            )
            if request.includeClaims is not False
            else []
        )
        sections = self._sections(
            tenant_id,
            request.subject,
            internal,
            external,
            plan_decompositions,
            state,
            evidence,
            server,
            observed,
            temporal_unavailable,
            tool_calls,
            risk_events,
            approval_chain,
            authority_check,
            latency_cost,
            source_provenance,
        )

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            # The mutable internal lifecycle table cannot reconstruct a past
            # state; omit asOf so the frame runtime cannot mistake it as served.
            asOf=None,
            generatedAt=_now_iso(),
            page=None,
            degradedReasons=sorted(set(reasons)),
        )

    async def _safe_read(
        self, method: str, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        try:
            reader = getattr(self._sources, method)
            result = await reader(tenant_id=tenant_id, subject=subject, limit=limit)
            if not isinstance(result, ExecutionRead):
                return ExecutionRead(
                    rows=[],
                    available=False,
                    scope_known=False,
                    reason=f"{method}_returned_invalid_contract",
                )
            return result
        except Exception:  # noqa: BLE001 - fail-isolate source adapters
            return ExecutionRead(
                rows=[],
                available=False,
                scope_known=False,
                reason=f"{method}_unavailable",
            )

    async def _safe_source_provenance_read(
        self, tenant_id: str, events: tuple[tuple[str, str], ...]
    ) -> ExecutionSourceProvenanceRead:
        if not events:
            return ExecutionSourceProvenanceRead(
                [], True, False, reason="no_admitted_source_telemetry"
            )
        reader = getattr(self._sources, "source_provenance", None)
        if reader is None:
            return ExecutionSourceProvenanceRead(
                [], False, False, reason="source_provenance_reader_unavailable"
            )
        try:
            read = await reader(tenant_id=tenant_id, events=events)
        except Exception:  # noqa: BLE001 - optional authority is fail isolated
            return ExecutionSourceProvenanceRead(
                [], False, False, reason="source_provenance_read_unavailable"
            )
        if not isinstance(read, ExecutionSourceProvenanceRead):
            return ExecutionSourceProvenanceRead(
                [], False, False, reason="source_provenance_read_invalid"
            )
        expected = set(events)
        seen: set[tuple[str, str]] = set()
        scoped: list[dict[str, Any]] = []
        mismatch = False
        for raw in read.rows:
            if not isinstance(raw, dict):
                mismatch = True
                continue
            event_id = _safe_text(raw.get("sourceEventId"))
            event_name = _safe_text(raw.get("eventName"))
            key = (event_id or "", event_name or "")
            try:
                ref = EvidenceRef.model_validate(raw.get("evidenceRef"))
            except Exception:  # noqa: BLE001 - invalid Bronze evidence is omitted
                mismatch = True
                continue
            if (
                raw.get("tenantId") != tenant_id
                or key not in expected
                or key in seen
                or ref.id != event_id
                or ref.source != "bronze_sdk_events"
                or not (ref.uri or "").startswith("store://bronze_sdk_events/")
                or ref.observedAt != raw.get("observedAt")
            ):
                mismatch = True
                continue
            seen.add(key)
            scoped.append(
                {
                    "tenantId": tenant_id,
                    "sourceEventId": event_id,
                    "eventName": event_name,
                    "bronzeSchemaVersion": _safe_text(raw.get("bronzeSchemaVersion")),
                    "sourceId": _safe_text(raw.get("sourceId")),
                    "sourceProviderClaim": _safe_text(raw.get("sourceProviderClaim")),
                    "sourceTrust": _safe_text(raw.get("sourceTrust")),
                    "credentialClass": _safe_text(raw.get("credentialClass")),
                    "signatureStatus": _safe_text(raw.get("signatureStatus")),
                    "adapter": _safe_text(raw.get("adapter")),
                    "adapterVersion": _safe_text(raw.get("adapterVersion")),
                    "observedAt": raw.get("observedAt"),
                    "evidenceRef": ref.model_dump(mode="json", by_alias=True, exclude_none=True),
                    "classification": "bronze_recorded_ingress_envelope",
                    "sourceIdentityVerified": False,
                    "externalExecutionVerified": False,
                }
            )
        complete = read.scope_known and not mismatch and seen == expected
        return ExecutionSourceProvenanceRead(
            scoped,
            read.available,
            complete,
            truncated=read.truncated,
            reason=(
                "source_provenance_response_scope_mismatch"
                if mismatch
                else read.reason
                if read.reason
                else "source_provenance_exact_join_incomplete"
                if seen != expected
                else None
            ),
            unmatched_count=len(expected - seen),
        )

    async def _safe_execution_risk_read(
        self, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskEventRead:
        try:
            reader = getattr(self._sources, "execution_risk_events")
            result = await reader(
                tenant_id=tenant_id,
                execution_ids=execution_ids,
                limit=limit,
            )
            if not isinstance(result, ExecutionRiskEventRead):
                return ExecutionRiskEventRead(
                    rows=[],
                    available=False,
                    scope_known=False,
                    reason="execution_risk_event_source_returned_invalid_contract",
                )
            if result.assessment_read is not None and not isinstance(
                result.assessment_read, ExecutionRiskAssessmentRead
            ):
                return replace(
                    result,
                    assessment_read=ExecutionRiskAssessmentRead(
                        rows=[],
                        available=False,
                        scope_known=False,
                        reason="execution_risk_assessment_source_returned_invalid_contract",
                    ),
                )
            return result
        except Exception:  # noqa: BLE001 - fail-isolate optional canonical source
            return ExecutionRiskEventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_risk_event_source_unavailable",
            )

    async def _safe_execution_approval_read(
        self, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionApprovalRead:
        try:
            reader = getattr(self._sources, "execution_approval_decisions")
            result = await reader(
                tenant_id=tenant_id,
                execution_ids=execution_ids,
                limit=limit,
            )
            if not isinstance(result, ExecutionApprovalRead):
                return ExecutionApprovalRead(
                    rows=[],
                    available=False,
                    scope_known=False,
                    reason="execution_approval_decision_source_returned_invalid_contract",
                )
            return result
        except Exception:  # noqa: BLE001 - fail-isolate optional canonical source
            return ExecutionApprovalRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_approval_decision_source_unavailable",
            )

    async def _safe_execution_cost_read(
        self,
        tenant_id: str,
        executions: tuple[tuple[str, str], ...],
        limit: int,
    ) -> ExecutionCostRead:
        try:
            reader = getattr(self._sources, "execution_cost_facts")
            result = await reader(
                tenant_id=tenant_id,
                executions=executions,
                limit=limit,
            )
            if not isinstance(result, ExecutionCostRead):
                return ExecutionCostRead(
                    [],
                    False,
                    False,
                    reason="execution_cost_source_returned_invalid_contract",
                )
        except Exception:  # noqa: BLE001 - fail-isolate optional canonical source
            return ExecutionCostRead(
                [],
                False,
                False,
                reason="execution_cost_source_unavailable",
            )

        allowed_subjects = set(executions)
        rows: list[dict[str, Any]] = []
        invalid_row_seen = False
        seen_invocations: dict[tuple[str, str], dict[str, Any]] = {}
        for row in result.rows:
            if not isinstance(row, dict):
                invalid_row_seen = True
                continue
            key = (
                _safe_text(row.get("execution_id")) or "",
                _safe_text(row.get("agent_id")) or "",
            )
            invocation_id = _safe_text(row.get("invocation_id"))
            if (
                row.get("tenant_id") != tenant_id
                or key not in allowed_subjects
                or row.get("action_id") != key[0]
                or invocation_id is None
            ):
                invalid_row_seen = True
                continue
            dedupe_key = (key[0], invocation_id)
            existing = seen_invocations.get(dedupe_key)
            if existing is not None:
                if existing != row:
                    invalid_row_seen = True
                    rows = [
                        candidate
                        for candidate in rows
                        if not (
                            candidate.get("execution_id") == key[0]
                            and candidate.get("invocation_id") == invocation_id
                        )
                    ]
                    seen_invocations.pop(dedupe_key, None)
                continue
            seen_invocations[dedupe_key] = row
            rows.append(row)

        return ExecutionCostRead(
            rows,
            result.available,
            result.scope_known and not invalid_row_seen,
            truncated=result.truncated,
            reason=(
                result.reason
                or "execution_cost_row_scope_or_invocation_conflict"
                if invalid_row_seen
                else result.reason
            ),
        )

    @staticmethod
    def _all_evidence(
        tenant_id: str,
        internal: list[dict[str, Any]],
        external: list[dict[str, Any]],
        plan_decompositions: list[dict[str, Any]],
        tool_calls: ExecutionToolCallRead,
        risk_events: ExecutionRiskEventContext,
        approval_chain: ExecutionApprovalContext,
        authority_check: ExecutionAuthorityContext,
        latency_cost: dict[str, Any],
        source_provenance: ExecutionSourceProvenanceRead,
    ) -> list[EvidenceRef]:
        refs: list[EvidenceRef] = []
        seen: set[tuple[str, str]] = set()
        for builder, rows in (
            (_lifecycle_evidence, internal),
            (_internal_delegation_evidence, internal),
            (_fact_evidence, external),
            (_delegation_evidence, external),
            (_task_decomposition_evidence, plan_decompositions),
        ):
            for row in rows:
                ref = builder(row)
                if ref is None or (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        for row in tool_calls.rows:
            try:
                ref = EvidenceRef.model_validate(row.get("evidenceRef"))
            except Exception:  # noqa: BLE001 - malformed source evidence is omitted
                continue
            if (ref.id, ref.source) in seen:
                continue
            seen.add((ref.id, ref.source))
            refs.append(ref)
        for row in internal:
            raw_refs = row.get("initiatingPrincipalIdentityEvidenceRefs")
            if not isinstance(raw_refs, list):
                continue
            for raw_ref in raw_refs:
                try:
                    ref = EvidenceRef.model_validate(raw_ref)
                except Exception:  # noqa: BLE001 - malformed identity evidence is omitted
                    continue
                if (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        for row in internal:
            raw_refs = row.get("workflowRunInvocationEvidenceRefs")
            if not isinstance(raw_refs, list):
                continue
            for raw_ref in raw_refs:
                try:
                    ref = EvidenceRef.model_validate(raw_ref)
                except Exception:  # noqa: BLE001 - malformed run evidence is omitted
                    continue
                if ref.source != "ai_execution_facts" or (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        for signal in risk_events.signals:
            for ref in signal.evidence_refs:
                if (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        for assessment in risk_events.assessments:
            for ref in _risk_assessment_evidence(assessment, tenant_id):
                if (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        for ref in approval_chain.evidence_refs:
            if (ref.id, ref.source) in seen:
                continue
            seen.add((ref.id, ref.source))
            refs.append(ref)
        for ref in authority_check.evidence_refs:
            if (ref.id, ref.source) in seen:
                continue
            seen.add((ref.id, ref.source))
            refs.append(ref)
        for invocation in latency_cost.get("cost", {}).get("invocations", []):
            for raw_ref in invocation.get("evidenceRefs", []):
                try:
                    ref = EvidenceRef.model_validate(raw_ref)
                except Exception:  # noqa: BLE001 - malformed AI fact evidence is omitted
                    continue
                if (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        for record in source_provenance.rows:
            try:
                ref = EvidenceRef.model_validate(record.get("evidenceRef"))
            except Exception:  # noqa: BLE001 - malformed provenance cannot back evidence
                continue
            if (ref.id, ref.source) not in seen:
                seen.add((ref.id, ref.source))
                refs.append(ref)
        return refs

    @staticmethod
    def _claims(
        tenant_id: str,
        subject: ProjectionSubject,
        internal: list[dict[str, Any]],
        external: list[dict[str, Any]],
        plan_decompositions: list[dict[str, Any]],
        tool_calls: ExecutionToolCallRead,
        risk_events: ExecutionRiskEventContext,
        approval_chain: ExecutionApprovalContext,
        authority_check: ExecutionAuthorityContext,
        latency_cost: dict[str, Any],
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for row in internal:
            evidence = _lifecycle_evidence(row)
            if evidence is None:
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:server:{row['executionId']}",
                    kind="server_recorded_execution_lifecycle",
                    subject=subject,
                    evidenceRefs=[evidence],
                    claims=[
                        f"AETHER recorded agent execution lifecycle status '{row['status']}' for execution {row['executionId']}; this lifecycle record does not establish an external action effect."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[
                        SLOT_EXECUTION_STATE,
                        SLOT_AGENT_EXECUTION_HISTORY,
                        SLOT_EVIDENCE,
                    ],
                )
            )
            if (
                subject.kind == "workflow_run"
                and row.get("workflowRunId") == subject.id
            ):
                linked_evidence = [evidence]
                raw_invocation_refs = row.get("workflowRunInvocationEvidenceRefs")
                if isinstance(raw_invocation_refs, list):
                    for raw_ref in raw_invocation_refs:
                        try:
                            invocation_ref = EvidenceRef.model_validate(raw_ref)
                        except Exception:  # noqa: BLE001 - malformed run evidence is omitted
                            continue
                        if invocation_ref.source == "ai_execution_facts":
                            linked_evidence.append(invocation_ref)
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:workflow-run-reference:{row['executionId']}",
                        kind="server_recorded_workflow_run_execution_reference",
                        subject=subject,
                        evidenceRefs=linked_evidence,
                        claims=[
                            f"AETHER's canonical execution record {row['executionId']} stores the exact requested workflow_run_id {subject.id}; this stored reference does not establish workflow-wide step coverage, workflow completion, or an external action effect."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_EXECUTION_STATE, SLOT_EVIDENCE],
                    )
                )
            elapsed_ms = _lifecycle_elapsed_ms(row)
            if elapsed_ms is not None:
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:lifecycle-duration:{row['executionId']}",
                        kind="server_recorded_lifecycle_elapsed_time",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER's recorded lifecycle timestamps for execution {row['executionId']} span {elapsed_ms:g} milliseconds; this is server-recorded lifecycle elapsed time, not a provider or tool latency measurement."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_LATENCY_COST, SLOT_EVIDENCE],
                    )
                )
            principal_user_id = row.get("initiatingPrincipalUserId")
            if isinstance(principal_user_id, str) and principal_user_id:
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:principal:{row['executionId']}",
                        kind="authenticated_execution_principal",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER recorded authenticated tenant user reference {principal_user_id} as the initiating principal for execution {row['executionId']}; the reference alone does not make that principal the acting agent or establish canonical human identity."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_ACTOR_ATTRIBUTION, SLOT_EVIDENCE],
                    )
                )
                canonical_human_id = _safe_text(
                    row.get("canonicalInitiatingPrincipalHumanEntityId")
                )
                if (
                    canonical_human_id
                    and row.get("initiatingPrincipalIdentityState") == "resolved"
                ):
                    identity_refs: list[EvidenceRef] = []
                    raw_identity_refs = row.get("initiatingPrincipalIdentityEvidenceRefs")
                    if isinstance(raw_identity_refs, list):
                        for raw_ref in raw_identity_refs:
                            try:
                                identity_refs.append(EvidenceRef.model_validate(raw_ref))
                            except Exception:  # noqa: BLE001 - malformed identity evidence fails closed
                                identity_refs = []
                                break
                    if {ref.source for ref in identity_refs} == {
                        "identity_aliases",
                        "identity_subjects",
                    }:
                        claims.append(
                            ClaimEnvelope(
                                id=f"execution360:principal-identity:{row['executionId']}",
                                kind="canonically_resolved_execution_principal_identity",
                                subject=subject,
                                evidenceRefs=[evidence, *identity_refs],
                                claims=[
                                    f"The authenticated principal reference recorded for execution {row['executionId']} resolves through an active tenant USER_ID alias and active surviving identity subject to canonical Human {canonical_human_id}; this identity link does not establish action authorization or delegation authority."
                                ],
                                claimState=EpistemicStatus.RESOLVED,
                                domainSlotIds=[SLOT_ACTOR_ATTRIBUTION, SLOT_EVIDENCE],
                            )
                        )
            if row.get("canonicalActorResolved") is True and row.get("agentId"):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:server-actor:{row['executionId']}",
                        kind="canonically_resolved_server_agent_actor",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER's tenant-scoped agent configuration binds execution {row['executionId']} to canonical agent {row['agentId']}."
                        ],
                        claimState=EpistemicStatus.RESOLVED,
                        domainSlotIds=[SLOT_ACTOR_ATTRIBUTION],
                    )
                )
            authority_execution_ids = {
                check["executionId"] for check in authority_check.decisions
            }
            grant_evidence = _internal_delegation_evidence(row)
            if (
                row.get("executionId") in authority_execution_ids
                and grant_evidence is not None
                and isinstance(row.get("recordedDelegationDecision"), bool)
            ):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:server-delegation-reference:{row['executionId']}",
                        kind="canonically_joined_server_delegation_reference",
                        subject=subject,
                        evidenceRefs=[evidence, grant_evidence],
                        claims=[
                            f"The recorded delegation decision for execution {row['executionId']} references tenant grant {row['delegationId']}, whose current record names canonical agent {row['agentId']} as grantee; the current grant record does not establish its historical validity, scope, or standing authority at execution time."
                        ],
                        claimState=EpistemicStatus.RESOLVED,
                        domainSlotIds=[SLOT_AUTHORITY_CHECK, SLOT_EVIDENCE],
                    )
                )
            if any(
                row.get(field)
                for field in ("requestedAction", "requestedResource", "triggeredByEventId")
            ):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:request-metadata:{row['executionId']}",
                        kind="server_recorded_execution_request_metadata",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER recorded bounded request metadata for execution {row['executionId']}; the input payload is withheld and the record does not prove an external effect."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_INPUTS_OUTPUTS, SLOT_EVIDENCE],
                    )
                )
            if row.get("outcomeEventId"):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:result-reference:{row['executionId']}",
                        kind="server_recorded_result_event_reference",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER recorded an outcome event reference for execution {row['executionId']}; the referenced event and an external action receipt are not joined here."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_INPUTS_OUTPUTS, SLOT_EVIDENCE],
                    )
                )
            if row.get("status") in _SERVER_FAILURE_STATUSES:
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:server-failure:{row['executionId']}",
                        kind="server_recorded_execution_failure",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER recorded lifecycle status {row['status']} for execution {row['executionId']}; error details and external effects are not inferred."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_FAILURES, SLOT_EVIDENCE],
                    )
                )
        for decision in authority_check.decisions:
            evidence_ref = EvidenceRef.model_validate(decision["evidenceRef"])
            outcome = "allowed" if decision["decision"] == "allow" else "denied"
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:delegation:{decision['executionId']}",
                    kind="server_recorded_delegation_decision",
                    subject=subject,
                    evidenceRefs=[evidence_ref],
                    claims=[
                        f"AETHER's tenant-scoped agent_executions record stores a {outcome} delegation-engine decision for action {decision['action']} on resource {decision['resource']} in execution {decision['executionId']}. The decision timestamp is reported separately when persisted; lifecycle timestamps locate the parent execution record. This request-time result does not establish current or standing authority or prove external execution."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[
                        SLOT_AUTHORITY_CHECK,
                        SLOT_AGENT_AUTHORITY_ENVELOPE,
                        SLOT_EVIDENCE,
                    ],
                )
            )
        for row in external:
            evidence = _fact_evidence(row)
            if evidence is None:
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:observed:{row['sourceEventId']}",
                    kind="source_reported_agent_telemetry_fact",
                    subject=subject,
                    evidenceRefs=[evidence],
                    claims=[
                        f"A tenant source reported agent-related telemetry in event {row['sourceEventId']}; it has no exact join to an AETHER execution ID or independent external execution receipt."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_EVIDENCE],
                )
            )
            if row.get("toolName"):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:tool-observation:{row['sourceEventId']}",
                        kind="source_reported_tool_invocation",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"A tenant source reported a tool-related event {row['sourceEventId']}; it has no exact canonical join to an AETHER execution ID or independent tool receipt."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_AGENT_TOOL_USAGE, SLOT_EVIDENCE],
                    )
                )
            if row.get("reportedStatus") in _SOURCE_REPORTED_FAILURE_STATUSES:
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:reported-failure:{row['sourceEventId']}",
                        kind="source_reported_agent_failure_telemetry",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"A tenant source reported status {row['reportedStatus']} in event {row['sourceEventId']}; without an exact execution ID this telemetry is not assigned to an AETHER execution failure."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_EVIDENCE],
                    )
                )
            if row.get("actorAgentId") and row.get("actorIdentityStatus") == "matched":
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:actor:{row['sourceEventId']}",
                        kind="canonically_resolved_execution_actor",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"The reported actor for event {row['sourceEventId']} resolves through tenant deployment identity bindings to canonical agent {row['actorAgentId']}."
                        ],
                        claimState=EpistemicStatus.RESOLVED,
                        domainSlotIds=[SLOT_ACTOR_ATTRIBUTION],
                    )
                )
            delegation_evidence = _delegation_evidence(row)
            if (
                row.get("delegationPartyBindingStatus") == "matched"
                and row.get("delegationId")
                and row.get("delegationEvidenceId") == row.get("delegationId")
                and row.get("delegatorAgentId")
                and row.get("delegateeAgentId")
                and delegation_evidence is not None
            ):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:delegation-parties:{row['sourceEventId']}",
                        kind="canonically_resolved_delegation_parties",
                        subject=subject,
                        evidenceRefs=[evidence, delegation_evidence],
                        claims=[
                            f"The tenant-scoped canonical delegation record {row['delegationId']} identifies delegator {row['delegatorAgentId']} and delegatee {row['delegateeAgentId']} after both source identities resolved through explicit tenant bindings."
                        ],
                        claimState=EpistemicStatus.RESOLVED,
                        domainSlotIds=[SLOT_ACTOR_ATTRIBUTION, SLOT_EVIDENCE],
                    )
                )
            if (
                row.get("delegationId")
                and row.get("delegationResolutionStatus") == "matched_reference"
            ):
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:delegation-reference:{row['sourceEventId']}",
                        kind="canonically_resolved_delegation_reference",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"The telemetry delegation reference for event {row['sourceEventId']} matched a tenant delegation record; authorization and external execution remain separately classified."
                        ],
                        claimState=EpistemicStatus.RESOLVED,
                        domainSlotIds=[SLOT_ACTOR_ATTRIBUTION],
                    )
                )
        lifecycle_evidence_by_id = {
            row["executionId"]: ref
            for row in internal
            if row.get("executionId")
            and (ref := _lifecycle_evidence(row)) is not None
        }
        for row in plan_decompositions:
            task_evidence = _task_decomposition_evidence(row)
            lifecycle_evidence = lifecycle_evidence_by_id.get(row["executionId"])
            if task_evidence is None or lifecycle_evidence is None:
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:task-decomposition:{row['recordId']}",
                    kind="observed_execution_task_decomposition",
                    subject=subject,
                    evidenceRefs=[task_evidence, lifecycle_evidence],
                    claims=[
                        f"AETHER recorded a task-decomposition observation linked to execution {row['executionId']}; it identifies task references but does not establish step order, completion, or external effects."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_TEMPORAL_EPISODE, SLOT_EVIDENCE],
                )
            )
        for row in tool_calls.rows:
            try:
                evidence = EvidenceRef.model_validate(row.get("evidenceRef"))
            except Exception:  # noqa: BLE001 - source evidence validation is fail closed
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:tool-call:{evidence.id}",
                    kind="server_recorded_execution_tool_call_observation",
                    subject=subject,
                    evidenceRefs=[evidence],
                    claims=[
                        f"AETHER recorded a tenant-scoped tool-call lifecycle edge for tool {row['toolId']} linked to execution {row['executionId']}; the record does not establish an external tool receipt or authorization decision."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_TOOL_CALLS, SLOT_EVIDENCE],
                )
            )
        for decision in approval_chain.decisions:
            try:
                evidence = EvidenceRef.model_validate(decision.get("evidenceRef"))
            except Exception:  # noqa: BLE001 - invalid canonical evidence is omitted
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:approval:{decision['decisionId']}",
                    kind="canonically_linked_commerce_approval_decision",
                    subject=subject,
                    evidenceRefs=[evidence],
                    claims=[
                        f"The tenant-scoped x402 approval authority recorded {decision['action']} decision {decision['decisionId']} for approval {decision['approvalId']} linked to exact execution {decision['executionId']}; this records approval workflow evidence and does not prove an external action occurred."
                    ],
                    claimState=EpistemicStatus.RESOLVED,
                    domainSlotIds=[SLOT_APPROVAL_CHAIN, SLOT_EVIDENCE],
                )
            )
        for approval in approval_chain.approval_requests:
            try:
                evidence = EvidenceRef.model_validate(approval.get("evidenceRef"))
            except Exception:  # noqa: BLE001 - invalid canonical evidence is omitted
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:approval-request:{approval['approvalId']}",
                    kind="canonically_linked_commerce_approval_request",
                    subject=subject,
                    evidenceRefs=[evidence],
                    claims=[
                        f"The tenant-scoped x402 commerce authority recorded approval request {approval['approvalId']} for action {approval['action']} on resource {approval['resourceId']} linked to exact execution {approval['executionId']}; this is request metadata and does not establish authorization or an external effect."
                    ],
                    claimState=EpistemicStatus.RESOLVED,
                    domainSlotIds=[SLOT_APPROVAL_CHAIN, SLOT_EVIDENCE],
                )
            )
        cost = latency_cost.get("cost", {})
        for currency_total in cost.get("byCurrency", []):
            evidence_refs: list[EvidenceRef] = []
            for raw_ref in currency_total.get("evidenceRefs", []):
                try:
                    evidence_refs.append(EvidenceRef.model_validate(raw_ref))
                except Exception:  # noqa: BLE001 - malformed AI fact evidence is omitted
                    evidence_refs = []
                    break
            if not evidence_refs:
                continue
            currency = currency_total["currency"]
            amount = currency_total["total"]
            claim_currency_id = quote(str(currency), safe="")
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:ai-invocation-cost:{claim_currency_id}",
                    kind="source_reported_execution_invocation_cost_total",
                    subject=subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"Canonical tenant AI invocation facts explicitly linked to admitted execution action IDs report selected invocation cost totaling {amount:g} {currency} across {currency_total['factCount']} fact(s); this is model invocation cost, not business value, and other currencies are reported separately."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_LATENCY_COST, SLOT_EVIDENCE],
                )
            )
        for signal in risk_events.signals:
            claims.append(
                ClaimEnvelope(
                    id=f"execution360:risk-signal:{signal.signal_id}",
                    kind="execution_subject_risk_signal_context",
                    # Claims must retain the exact subject of the projection
                    # request so frame composition can enforce its subject
                    # contract. The linked execution stays explicit in the
                    # claim text, interaction payload, and evidence.
                    subject=subject,
                    evidenceRefs=list(signal.evidence_refs),
                    claims=[
                        f"Canonical Risk360 signal {signal.signal_id!r} records {signal.risk_dimension!r} context for execution {signal.subject_id!r} with claim state {signal.claim_state.value}; it does not establish that the execution caused the signal or provide a complete risk assessment."
                    ],
                    confidence=signal.confidence,
                    claimState=signal.claim_state,
                    domainSlotIds=[SLOT_RISK_EVENTS, SLOT_EVIDENCE],
                )
            )
        for assessment in risk_events.assessments:
            assessed_at = (
                assessment.assessed_at.astimezone(timezone.utc).isoformat()
                if assessment.assessed_at is not None
                else "an unrecorded time"
            )
            claims.append(
                ClaimEnvelope(
                    id=(
                        "execution360:risk-assessment:"
                        f"{quote(f'{assessment.subject_id}:{assessment.assessment_id}', safe='')}"
                    ),
                    kind="execution_subject_risk_assessment_snapshot",
                    subject=subject,
                    evidenceRefs=_risk_assessment_evidence(assessment, tenant_id),
                    claims=[
                        f"Canonical Risk360 assessment {assessment.assessment_id!r} records {len(assessment.vector.components)} dimension(s) for exact execution {assessment.subject_id!r}, with claim state {assessment.claim_state.value}, assessed at {assessed_at}; this snapshot does not establish causality, current standing risk, or complete assessment history."
                    ],
                    confidence=assessment.confidence,
                    claimState=assessment.claim_state,
                    domainSlotIds=[SLOT_RISK_EVENTS, SLOT_EVIDENCE],
                )
            )
        return claims

    @staticmethod
    def _sections(
        tenant_id: str,
        subject: ProjectionSubject,
        internal: list[dict[str, Any]],
        external: list[dict[str, Any]],
        plan_decompositions: list[dict[str, Any]],
        state: str,
        evidence: list[EvidenceRef],
        server: ExecutionRead,
        observed: ExecutionRead,
        temporal_unavailable: bool,
        tool_calls: ExecutionToolCallRead,
        risk_events: ExecutionRiskEventContext,
        approval_chain: ExecutionApprovalContext,
        authority_check: ExecutionAuthorityContext,
        latency_cost: dict[str, Any],
        source_provenance: ExecutionSourceProvenanceRead,
    ) -> list[ProjectionSection]:
        episode_context = server.episode_context or ExecutionEpisodeContextRead(
            "degraded" if not server.available else "unknown",
            reason=(
                server.reason or "agent_episode_authority_unavailable"
                if not server.available
                else "agent_episode_context_not_read"
            ),
        )
        if temporal_unavailable:
            episode_context = ExecutionEpisodeContextRead(
                "unknown",
                reason="temporal_anchor_not_reconstructable_from_current_sources",
            )
        timeline = [
            {
                "occurredAt": row.get("endedAt") or row.get("startedAt"),
                "source": _INTERNAL_SOURCE,
                "executionId": row.get("executionId"),
                "lifecycleStatus": row.get("status"),
                "occurrenceBoundary": "server_recorded_lifecycle",
                "externalExecutionReceipt": "unknown",
            }
            for row in internal
        ] + [
            {
                "occurredAt": row.get("occurredAt"),
                "source": _SILVER_SOURCE,
                "sourceEventId": row.get("sourceEventId"),
                "eventName": row.get("eventName"),
                "reportedStatus": row.get("reportedStatus"),
                "occurrenceBoundary": "source_reported_telemetry",
                "externalExecutionReceipt": "not_provided",
            }
            for row in external
        ] + [
            {
                "occurredAt": row.get("occurredAt"),
                "source": _INTERNAL_SOURCE,
                "recordId": row.get("recordId"),
                "executionId": row.get("executionId"),
                "eventName": "task_decomposed",
                "rootTaskId": row.get("rootTaskId"),
                "subtaskIds": row.get("subtaskIds"),
                "occurrenceBoundary": "persisted_task_decomposition_observation",
                "externalExecutionReceipt": "unknown",
            }
            for row in plan_decompositions
        ]
        timeline.sort(key=lambda item: str(item.get("occurredAt") or ""))
        interactions = [
            {
                "source": _INTERNAL_SOURCE,
                "executionId": row.get("executionId"),
                "requestedAction": row.get("requestedAction"),
                "requestedResource": row.get("requestedResource"),
                "actionBoundary": "server_recorded_request_fields_not_execution_receipt",
            }
            for row in internal
        ] + [
            {
                "source": _SILVER_SOURCE,
                "sourceEventId": row.get("sourceEventId"),
                "eventName": row.get("eventName"),
                "actionType": row.get("actionType"),
                "resourceRef": row.get("resourceRef"),
                "toolName": row.get("toolName"),
                "runId": row.get("runId"),
                "reportedStatus": row.get("reportedStatus"),
                "actorAgentId": row.get("actorAgentId"),
                "delegationId": row.get("delegationId"),
                "delegationResolutionStatus": row.get("delegationResolutionStatus"),
                "delegationPartyBindingStatus": row.get("delegationPartyBindingStatus"),
                "delegatorAgentId": row.get("delegatorAgentId"),
                "delegateeAgentId": row.get("delegateeAgentId"),
                "delegationScope": row.get("delegationScope", []),
                "delegationValidFrom": row.get("delegationValidFrom"),
                "delegationValidUntil": row.get("delegationValidUntil"),
                "delegationStatus": row.get("delegationStatus"),
                "delegationEvidenceId": row.get("delegationEvidenceId"),
                "delegationEvidenceObservedAt": row.get("delegationEvidenceObservedAt"),
                "authorizationComparisonStatus": row.get("authorizationStatus"),
                "authorizationBoundary": "canonical_scope_comparison_does_not_verify_external_action",
                "executionOccurrence": "source_reported",
                "executionVerified": False,
            }
            for row in external
        ]
        counts: dict[str, int] = {}
        for row in internal:
            status = row.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        executor_callbacks = []
        for row in internal:
            if row.get("status") not in {"completed", "failed"}:
                continue
            evidence_ref = _lifecycle_evidence(row)
            executor_callbacks.append(
                {
                    "executionId": row.get("executionId"),
                    "recordedStatus": row.get("status"),
                    "recordedAt": row.get("endedAt"),
                    "outcomeEventId": row.get("outcomeEventId"),
                    "outcomeEventReferenceKind": (
                        "event_id_recorded_on_agent_execution"
                        if row.get("outcomeEventId")
                        else "not_recorded"
                    ),
                    "eventPublicationState": (
                        "published"
                        if row.get("outcomeEventPublished") is True
                        else "not_published"
                        if row.get("outcomeEventPublished") is False
                        else "unknown"
                    ),
                    "evidenceRefs": (
                        [
                            evidence_ref.model_dump(
                                mode="json", by_alias=True, exclude_none=True
                            )
                        ]
                        if evidence_ref is not None
                        else []
                    ),
                    "outcomeKind": "server_recorded_executor_run_terminal_status",
                    "businessEffect": "not_established",
                }
            )

        source_states = {
            "serverRecordedLifecycle": _read_state(server),
            "sourceReportedTelemetry": _read_state(observed),
        }
        general = {
            "scope": {"kind": subject.kind, "id": subject.id},
            "sourceStates": source_states,
            "externalExecutionReceipt": {
                "state": "unknown",
                "reason": "no_server_authoritative_external_execution_receipt_is_joined_by_this_provider",
            },
        }
        provenance_content = {
            "state": (
                "unavailable"
                if not source_provenance.available
                else "degraded"
                if source_provenance.truncated
                or (not source_provenance.scope_known and source_provenance.rows)
                else "partial"
                if source_provenance.rows
                else "unknown"
            ),
            "readAuthority": "bronze_sdk_events.observation_envelope",
            "join": "exact_tenant_and_bronze_event_id_to_admitted_silver_telemetry",
            "records": source_provenance.rows,
            "count": (
                len(source_provenance.rows)
                if source_provenance.available and source_provenance.scope_known
                else None
            ),
            "unmatchedAdmittedEventCount": source_provenance.unmatched_count,
            "truncated": source_provenance.truncated,
            "reason": source_provenance.reason,
            "sourceCoverage": "unknown",
            "externalExecutionReceipt": "unknown",
            "freshness": {
                "state": "unknown",
                "reason": "no_execution_source_provenance_freshness_threshold_is_configured",
            },
        }
        worker_linkage = {
            "state": "unknown",
            "reason": "system_worker_runs_are_objective_scoped_and_have_no_canonical_link_to_agent_execution_records",
        }
        tool_related_facts = [row for row in external if row.get("toolName")]
        tool_fact_evidence: list[EvidenceRef] = []
        for row in tool_related_facts:
            evidence_ref = _fact_evidence(row)
            if evidence_ref is not None:
                tool_fact_evidence.append(evidence_ref)
        tool_call_evidence: list[EvidenceRef] = []
        for row in tool_calls.rows:
            try:
                tool_call_evidence.append(EvidenceRef.model_validate(row.get("evidenceRef")))
            except Exception:  # noqa: BLE001 - malformed source evidence is omitted
                continue
        tool_invocation_linkage = {
            "state": "partial" if tool_calls.rows else "unknown",
            "reason": (
                tool_calls.reason
                or "execution_tool_call_source_completeness_unknown"
                if tool_calls.rows
                else tool_calls.reason
                or "execution_tool_call_exact_join_not_available"
            ),
            "sourceReadState": (
                "available"
                if tool_calls.available
                else "unavailable"
            ),
            "completeness": "unknown",
            "sourceReportedToolRelatedFactCount": (
                len(tool_related_facts)
                if observed.available and observed.scope_known and not observed.truncated
                else None
            ),
            "joinedExecutionToolCalls": list(tool_calls.rows),
            "evidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in tool_call_evidence
            ],
            "sourceReportedEvidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in tool_fact_evidence
            ],
        }
        approval_chain_linkage = {
            "state": approval_chain.state,
            "reason": approval_chain.reason,
            "sourceReadState": approval_chain.source_read_state,
            "completeness": "x402_commerce_approval_requests_and_decisions_only",
            "scopeKnown": approval_chain.scope_known,
            "truncated": approval_chain.truncated,
            "effectiveAuthorization": {
                "state": "unknown",
                "reason": "commerce_approval_evidence_does_not_evaluate_effective_agent_action_authority",
            },
            "freshness": {
                "state": "unknown",
                "latestObservedAt": _latest_approval_observed_at(approval_chain),
                "reason": "no_execution_approval_freshness_threshold_is_configured",
            },
            "otherApprovalAuthorityCoverage": {
                "state": "unknown",
                "reason": "non_commerce_approval_authorities_are_not_joined",
            },
            "joinedExecutionApprovalRequests": list(approval_chain.approval_requests),
            "joinedExecutionApprovals": list(approval_chain.decisions),
            "evidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in approval_chain.evidence_refs
            ],
        }
        authority_check_linkage = {
            "state": authority_check.state,
            "reason": authority_check.reason,
            "sourceReadState": authority_check.source_read_state,
            "coverage": "recorded_delegation_engine_decisions_only",
            "scopeKnown": authority_check.scope_known,
            "truncated": authority_check.truncated,
            "ambiguousExecutionIds": list(authority_check.ambiguous_execution_ids),
            "joinedActionScopedDecisions": list(authority_check.decisions),
            "effectiveAuthorization": {
                "state": "unknown",
                "reason": "a_recorded_request_time_decision_does_not_establish_current_or_standing_authority",
            },
            "freshness": {
                "state": "unknown",
                "reason": "no_execution_authority_decision_freshness_threshold_is_configured",
            },
            "temporalScope": {
                "selection": authority_check.temporal_selection,
                "decisionTimestamp": authority_check.decision_timestamp_coverage,
                "limitation": (
                    "the timestamp is recorded in the application execution policy log; "
                    "the decision remains request-time evidence and does not establish "
                    "current or standing authority"
                    if authority_check.decision_timestamp_coverage == "persisted"
                    else "legacy policy logs without an evaluation timestamp are bounded "
                    "only by the parent execution lifecycle timestamps"
                ),
            },
            "otherAuthorityCoverage": {
                "state": "unknown",
                "reason": "x402_approval_workflow_is_projected_separately_and_other_authority_sources_are_not_joined",
            },
            "evidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in authority_check.evidence_refs
            ],
        }
        risk_assessment_evidence = [
            ref
            for assessment in risk_events.assessments
            for ref in _risk_assessment_evidence(assessment, tenant_id)
        ]
        risk_event_timestamps = [
            signal.observed_at.astimezone(timezone.utc).isoformat()
            for signal in risk_events.signals
            if signal.observed_at is not None
        ] + [
            assessment.assessed_at.astimezone(timezone.utc).isoformat()
            for assessment in risk_events.assessments
            if assessment.assessed_at is not None
        ]
        risk_event_linkage = {
            "state": risk_events.state,
            "reason": risk_events.reason,
            "sourceReadState": risk_events.source_read_state,
            "completeness": "bounded_recorded_execution_subject_signals_and_assessments",
            "scopeKnown": risk_events.scope_known,
            "producerCoverage": {
                "state": "unknown",
                "reason": "execution_risk_signal_producer_inventory_not_connected",
            },
            "riskAssessmentCoverage": {
                "state": risk_events.assessment_state,
                "sourceReadState": risk_events.assessment_source_read_state,
                "authority": "risk_assessments",
                "reason": risk_events.assessment_reason,
                "scopeKnown": risk_events.assessment_scope_known,
                "completeness": "exact_execution_subject_snapshots_only_history_and_producer_coverage_unknown",
                "assessmentCount": (
                    len(risk_events.assessments)
                    if risk_events.assessment_source_read_state == "available"
                    else None
                ),
                "joinedExecutionRiskAssessments": [
                    _execution_risk_assessment_payload(assessment, tenant_id)
                    for assessment in risk_events.assessments
                ],
                "evidenceRefs": [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for ref in risk_assessment_evidence
                ],
                "truncated": risk_events.assessment_truncated,
            },
            "joinedExecutionRiskEvents": [
                {
                    "executionId": signal.subject_id,
                    "signalId": signal.signal_id,
                    "riskDimension": signal.risk_dimension,
                    "source": signal.source,
                    "detectorVersion": signal.detector_version,
                    "claimState": signal.claim_state.value,
                    "confidence": signal.confidence,
                    "score": signal.score,
                    "value": signal.value,
                    "observedAt": (
                        signal.observed_at.astimezone(timezone.utc).isoformat()
                        if signal.observed_at is not None
                        else None
                    ),
                    "evidenceRefs": [
                        ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for ref in signal.evidence_refs
                    ],
                }
                for signal in risk_events.signals
            ],
            "evidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in [
                    *(
                        evidence_ref
                        for signal in risk_events.signals
                        for evidence_ref in signal.evidence_refs
                    ),
                    *risk_assessment_evidence,
                ]
            ],
            "freshness": {
                "state": "unknown",
                "latestObservedAt": max(risk_event_timestamps, default=None),
                "reason": "no_execution_risk_freshness_threshold_is_configured",
            },
            "truncated": risk_events.truncated,
        }
        inputs_outputs = _inputs_outputs_summary(
            internal,
            server,
            temporal_unavailable=temporal_unavailable,
        )
        failures = _failure_summary(
            internal,
            external,
            server,
            observed,
            temporal_unavailable=temporal_unavailable,
        )
        plan_steps = _plan_steps_summary(
            plan_decompositions,
            internal,
            server,
            temporal_unavailable=temporal_unavailable,
        )
        episode_context_content = {
            "state": episode_context.state,
            "episodes": list(episode_context.items),
            "count": len(episode_context.items)
            if episode_context.state in {"available", "empty"}
            else None,
            "coverage": episode_context.state,
            "readAuthority": "tenant_scoped_episode_records+canonical_agent_identity",
            "evidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in episode_context.evidence_refs
            ],
            "identityBindingEvidenceRefs": [
                ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                for ref in episode_context.identity_evidence_refs
            ],
            "reason": episode_context.reason,
        }
        return [
            ProjectionSection(
                id="evidence",
                state=_content_state(server, observed, internal, external),
                title="Execution evidence and lineage",
                content={
                    **general,
                    "count": len(evidence),
                    "evidence": [
                        ref.model_dump(by_alias=True, exclude_none=True) for ref in evidence
                    ],
                    "sourceProvenance": provenance_content,
                    "sourceLineage": [
                        _INTERNAL_SOURCE if internal else None,
                        _SILVER_SOURCE if external else None,
                        "bronze_sdk_events" if source_provenance.rows else None,
                        "ai_execution_facts"
                        if latency_cost.get("cost", {}).get("invocations")
                        else None,
                    ],
                },
            ),
            ProjectionSection(
                id="interactions",
                state=_content_state(server, observed, internal, external),
                title="Execution interactions",
                content={
                    **general,
                    "count": len(interactions),
                    "interactions": interactions,
                    "workerRunLinkage": worker_linkage,
                    "toolInvocationLinkage": tool_invocation_linkage,
                    "approvalChainLinkage": approval_chain_linkage,
                    "riskEventLinkage": risk_event_linkage,
                },
            ),
            ProjectionSection(
                id="outcomes",
                state="unknown",
                title="Execution outcomes",
                content={
                    **general,
                    "businessOutcome": {
                        "state": "unknown",
                        "reason": "business_outcome_requires_independent_outcome_or_economic_authority",
                    },
                    "executionOutcomeAuthority": {
                        "source": _INTERNAL_SOURCE,
                        "readState": _read_state(server),
                        "recordMeaning": "server_recorded_run_lifecycle_callback",
                        "eventPayloadRead": False,
                    },
                    "executorCallbacks": executor_callbacks,
                    "businessOutcomeAuthorityRead": False,
                },
            ),
            ProjectionSection(
                id="state",
                state=state,
                title="Execution lifecycle state",
                warnings=["temporal_state_not_reconstructable"] if temporal_unavailable else None,
                content={
                    **general,
                    "serverRecordedExecutions": [
                        {
                            k: v
                            for k, v in row.items()
                            if k not in {"source", "_tenantId", "_delegationDecisionPresent"}
                        }
                        for row in internal
                    ],
                    "sourceReportedRuns": [
                        {
                            "sourceEventId": row.get("sourceEventId"),
                            "runId": row.get("runId"),
                            "reportedStatus": row.get("reportedStatus"),
                            "occurrence": "source_reported",
                            "verified": False,
                        }
                        for row in external
                    ],
                    "inputsOutputs": inputs_outputs,
                    "failures": failures,
                    "planSteps": plan_steps,
                    "latencyCost": latency_cost,
                    "workerRunLinkage": worker_linkage,
                    "authorityCheck": authority_check_linkage,
                },
            ),
            ProjectionSection(
                id="summary",
                state=state,
                title="Execution summary",
                warnings=["temporal_state_not_reconstructable"] if temporal_unavailable else None,
                content={
                    **general,
                    "serverRecordedExecutionCount": len(internal),
                    "sourceReportedFactCount": len(external),
                    "serverLifecycleStatusCounts": counts,
                    "latencyCost": latency_cost,
                    "failureState": failures["state"],
                    "failureCount": failures["count"],
                    "planStepState": plan_steps["state"],
                    "observedTaskDecompositionCount": plan_steps["observedCount"],
                    "freshness": {
                        "state": "unknown",
                        "reason": "no_execution360_max_age_threshold_is_configured",
                    },
                },
            ),
            ProjectionSection(
                id="timeline",
                state=_content_state(server, observed, internal, external),
                title="Execution timeline",
                warnings=["timeline_order_is_not_causal"] if timeline else None,
                content={
                    **general,
                    "order": "occurred_at_ascending",
                    "causalRelationsDeclared": False,
                    "count": len(timeline),
                    "entries": timeline,
                    "workerRunLinkage": worker_linkage,
                },
            ),
            ProjectionSection(
                id="episode_context",
                state=episode_context.state,
                title="Agent episode context",
                content=episode_context_content,
                warnings=[episode_context.reason] if episode_context.reason else None,
            ),
        ]


def _read_state(read: ExecutionRead) -> str:
    if not read.available:
        return "unavailable"
    if not read.scope_known:
        return "unknown"
    if read.truncated:
        return "degraded"
    return "available"


def _execution_risk_event_context(
    read: ExecutionRiskEventRead,
    *,
    tenant_id: str,
    execution_ids: set[str],
    execution_inventory_complete: bool,
    time_range: Optional[TimeRangeFilter],
) -> ExecutionRiskEventContext:
    """Validate exact execution-scoped RiskSignals and assessments before projection.

    A recorded signal is risk context, not a complete risk assessment or proof
    that the execution caused the signal. Signals without evidence or with
    invalid subject/time scope are omitted and downgrade the coverage state.
    """
    lower = _parse_aware_instant(time_range.from_) if time_range and time_range.from_ else None
    upper = _parse_aware_instant(time_range.to) if time_range and time_range.to else None
    if (
        time_range is not None
        and (
            (time_range.from_ is not None and lower is None)
            or (time_range.to is not None and upper is None)
            or (lower is not None and upper is not None and upper < lower)
        )
    ):
        return ExecutionRiskEventContext(
            state="unknown",
            reason="execution_risk_event_time_window_invalid",
            source_read_state="available",
            truncated=read.truncated,
            scope_known=False,
        )

    from intelligence.risk360.contracts import RiskAssessment, RiskSignal

    signals: list[Any] = []
    seen_ids: set[str] = set()
    invalid_record_seen = False
    for raw in read.rows if read.available else ():
        if (
            not isinstance(raw, dict)
            or raw.get("tenant_id") != tenant_id
            or raw.get("subject_kind") != "execution"
            or raw.get("subject_id") not in execution_ids
        ):
            invalid_record_seen = True
            continue
        try:
            signal = RiskSignal.model_validate(raw)
        except Exception:  # noqa: BLE001 - invalid canonical row is not evidence
            invalid_record_seen = True
            continue
        if (
            not signal.signal_id.strip()
            or not signal.source.strip()
            or signal.signal_id in seen_ids
            or not signal.evidence_refs
        ):
            invalid_record_seen = True
            continue
        if any(not ref.id.strip() or not ref.source.strip() for ref in signal.evidence_refs):
            invalid_record_seen = True
            continue

        observed_at = signal.observed_at
        if observed_at is not None:
            if observed_at.tzinfo is None:
                invalid_record_seen = True
                continue
            observed_at = observed_at.astimezone(timezone.utc)
        if time_range is not None:
            if observed_at is None:
                invalid_record_seen = True
                continue
            if lower is not None and observed_at < lower:
                continue
            if upper is not None and observed_at > upper:
                continue
        seen_ids.add(signal.signal_id)
        signals.append(signal)

    assessment_read = read.assessment_read
    assessments: list[Any] = []
    assessment_state: Literal[
        "partial", "empty", "unknown", "degraded", "unavailable", "not_read"
    ] = "not_read"
    assessment_source_read_state: Literal["available", "unavailable", "not_read"] = (
        "not_read"
    )
    assessment_reason: Optional[str] = None
    assessment_truncated = False
    assessment_scope_known = False
    invalid_assessment_seen = False
    if assessment_read is not None:
        assessment_source_read_state = "available" if assessment_read.available else "unavailable"
        assessment_truncated = assessment_read.truncated
        assessment_scope_known = assessment_read.scope_known
        assessment_reason = assessment_read.reason
        if not assessment_read.available:
            assessment_state = "unavailable"
            assessment_reason = assessment_reason or "execution_risk_assessment_source_unavailable"
        else:
            seen_assessment_ids: set[str] = set()
            for raw in assessment_read.rows:
                if (
                    not isinstance(raw, dict)
                    or raw.get("tenant_id") != tenant_id
                    or raw.get("subject_kind") != "execution"
                    or raw.get("subject_id") not in execution_ids
                ):
                    invalid_assessment_seen = True
                    continue
                try:
                    assessment = RiskAssessment.model_validate(raw)
                except Exception:  # noqa: BLE001 - malformed assessment is not evidence
                    invalid_assessment_seen = True
                    continue
                assessed_at = assessment.assessed_at
                if assessed_at is not None:
                    if assessed_at.tzinfo is None:
                        invalid_assessment_seen = True
                        continue
                    assessed_at = assessed_at.astimezone(timezone.utc)
                if (
                    not assessment.assessment_id.strip()
                    or assessment.assessment_id in seen_assessment_ids
                    or any(
                        not ref.id.strip() or not ref.source.strip()
                        for ref in _risk_assessment_evidence(assessment, tenant_id)
                    )
                ):
                    invalid_assessment_seen = True
                    continue
                if time_range is not None:
                    if assessed_at is None:
                        invalid_assessment_seen = True
                        continue
                    if lower is not None and assessed_at < lower:
                        continue
                    if upper is not None and assessed_at > upper:
                        continue
                seen_assessment_ids.add(assessment.assessment_id)
                assessments.append(assessment)

            assessment_complete = (
                assessment_read.scope_known
                and not assessment_read.truncated
                and execution_inventory_complete
                and not invalid_assessment_seen
            )
            if assessments:
                assessment_state = "partial" if assessment_complete else "degraded"
                assessment_reason = (
                    "bounded_exact_execution_subject_assessment_snapshots_history_and_freshness_unknown"
                    if assessment_complete
                    else assessment_reason
                    or "execution_inventory_or_risk_assessment_scope_incomplete"
                )
            elif assessment_complete:
                assessment_state = "empty"
                assessment_reason = "no_recorded_risk_assessments_for_execution_subjects"
            else:
                assessment_state = "degraded"
                assessment_reason = assessment_reason or (
                    "execution_inventory_or_risk_assessment_scope_incomplete"
                )

    signal_complete = (
        read.available
        and read.scope_known
        and not read.truncated
        and execution_inventory_complete
        and not invalid_record_seen
    )
    assessment_complete = assessment_read is None or (
        assessment_read.available
        and assessment_read.scope_known
        and not assessment_read.truncated
        and execution_inventory_complete
        and not invalid_assessment_seen
    )
    combined_complete = signal_complete and assessment_complete
    if signals or assessments:
        state: Literal["partial", "empty", "unknown", "degraded", "unavailable"] = (
            "partial" if combined_complete else "degraded"
        )
        reason = (
            "execution_risk_records_are_snapshots_not_causal_or_complete_risk_history"
            if combined_complete
            else read.reason
            or assessment_reason
            or "execution_inventory_or_risk_signal_scope_incomplete"
        )
    elif combined_complete:
        state = "empty"
        reason = "no_recorded_canonical_risk_signals_or_assessments_for_execution_subjects"
    elif not read.available and (
        assessment_read is None or not assessment_read.available
    ):
        state = "unavailable"
        reason = (
            read.reason
            or assessment_reason
            or "execution_risk_signal_and_assessment_sources_unavailable"
        )
    else:
        state = "degraded"
        reason = (
            read.reason
            or assessment_reason
            or "execution_inventory_or_risk_signal_scope_incomplete"
        )
    return ExecutionRiskEventContext(
        state=state,
        signals=tuple(signals),
        assessments=tuple(assessments),
        reason=reason,
        source_read_state="available" if read.available else "unavailable",
        truncated=read.truncated or assessment_truncated,
        scope_known=read.scope_known and (assessment_scope_known if assessment_read else True),
        assessment_state=assessment_state,
        assessment_source_read_state=assessment_source_read_state,
        assessment_reason=assessment_reason,
        assessment_truncated=assessment_truncated,
        assessment_scope_known=assessment_scope_known,
    )


def _risk_assessment_evidence(assessment: Any, tenant_id: str) -> list[EvidenceRef]:
    """Ground an exact assessment join in its canonical record and inputs."""
    assessed_at = assessment.assessed_at
    observed_at = (
        assessed_at.astimezone(timezone.utc).isoformat()
        if assessed_at is not None and assessed_at.tzinfo is not None
        else None
    )
    record_ref = EvidenceRef(
        id=assessment.assessment_id,
        type="model_output",
        source="risk_assessments",
        observedAt=observed_at,
        uri=f"store://risk_assessments/{quote(f'{tenant_id}:{assessment.assessment_id}', safe='')}",
    )
    refs = [record_ref, *assessment.evidence_refs]
    for component in assessment.vector.components:
        refs.extend(component.evidence_refs)
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for ref in refs:
        unique.setdefault((ref.source, ref.id), ref)
    return list(unique.values())


def _execution_risk_assessment_payload(assessment: Any, tenant_id: str) -> dict[str, Any]:
    """Render only bounded assessment state and its exact record evidence."""
    assessed_at = (
        assessment.assessed_at.astimezone(timezone.utc).isoformat()
        if assessment.assessed_at is not None
        else None
    )
    return {
        "executionId": assessment.subject_id,
        "assessmentId": assessment.assessment_id,
        "policyId": assessment.policy_id,
        "policyVersion": assessment.policy_version,
        "dimensions": list(assessment.dimensions),
        "claimState": assessment.claim_state.value,
        "confidence": assessment.confidence,
        "assessedAt": assessed_at,
        "runId": assessment.run_id,
        "components": [
            {
                "dimension": component.dimension,
                "state": component.state.value,
                "score": component.score,
                "claimState": component.claim_state.value,
                "confidence": component.confidence,
                "evidenceRefs": [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for ref in component.evidence_refs
                ],
            }
            for component in assessment.vector.components
        ],
        "evidenceRefs": [
            ref.model_dump(mode="json", by_alias=True, exclude_none=True)
            for ref in _risk_assessment_evidence(assessment, tenant_id)
        ],
    }


def _execution_approval_context(
    read: ExecutionApprovalRead,
    *,
    tenant_id: str,
    execution_ids: set[str],
    internal: list[dict[str, Any]],
    execution_inventory_complete: bool,
    temporal_unavailable: bool,
) -> ExecutionApprovalContext:
    """Validate commerce approvals and decisions against exact run references."""
    if temporal_unavailable:
        return ExecutionApprovalContext(
            state="unknown",
            reason="historical_execution_approval_chain_not_supported",
            source_read_state="not_read",
        )
    if not execution_ids:
        return ExecutionApprovalContext(
            state="unknown",
            reason="no_admitted_execution_to_join_approval_chain",
            source_read_state="not_read",
            scope_known=execution_inventory_complete,
        )
    if not read.available:
        return ExecutionApprovalContext(
            state="unavailable",
            reason=read.reason or "execution_approval_decision_source_unavailable",
            source_read_state="unavailable",
            truncated=read.truncated,
            scope_known=False,
        )

    approval_refs: dict[str, tuple[str, str, Optional[str], Optional[str]]] = {}
    invalid_reference = False
    for row in internal:
        execution_id = _safe_text(row.get("executionId"))
        approval_id = _safe_text(row.get("approvalId"))
        decision_id = _safe_text(row.get("approvalDecisionId"))
        if execution_id not in execution_ids:
            continue
        if approval_id is None and decision_id is None:
            continue
        if not approval_id or not decision_id or execution_id in approval_refs:
            invalid_reference = True
            continue
        approval_refs[execution_id] = (
            approval_id,
            decision_id,
            _safe_text(row.get("requestedAction")),
            _safe_text(row.get("requestedResource")),
        )

    decisions: list[dict[str, Any]] = []
    evidence_refs: list[EvidenceRef] = []
    seen_ids: set[str] = set()
    invalid_record = False
    referenced_decisions_found: set[str] = set()
    for raw in read.rows:
        if not isinstance(raw, dict):
            invalid_record = True
            continue
        execution_id = _safe_text(raw.get("execution_id"))
        approval_id = _safe_text(raw.get("approval_id"))
        decision_id = _safe_text(raw.get("decision_id"))
        action = _safe_text(raw.get("action"))
        decided_by = _safe_text(raw.get("decided_by"))
        decided_at = _safe_text(raw.get("decided_at"))
        if (
            raw.get("tenant_id") != tenant_id
            or execution_id not in execution_ids
            or not approval_id
            or not decision_id
            or not action
            or not decided_by
            or _parse_aware_instant(decided_at) is None
            or decision_id in seen_ids
        ):
            invalid_record = True
            continue
        expected_ref = approval_refs.get(execution_id)
        if expected_ref is None or expected_ref[0] != approval_id:
            invalid_record = True
            continue
        if decision_id == expected_ref[1]:
            if action != "approve":
                invalid_record = True
                continue
            referenced_decisions_found.add(decision_id)
        evidence_ref = _evidence_ref(
            evidence_id=decision_id,
            source="commerce_approval_decisions",
            observed_at=decided_at,
            store="commerce_approval_decisions",
        )
        if evidence_ref is None:
            invalid_record = True
            continue
        seen_ids.add(decision_id)
        evidence_refs.append(evidence_ref)
        decisions.append(
            {
                "executionId": execution_id,
                "approvalId": approval_id,
                "decisionId": decision_id,
                "action": action,
                "decidedBy": decided_by,
                "decidedAt": decided_at,
                "isOverride": raw.get("is_override") is True,
                "authorizedExecutionDecision": decision_id == expected_ref[1],
                "evidenceRef": evidence_ref.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            }
        )

    approval_requests: list[dict[str, Any]] = []
    seen_approval_ids: set[str] = set()
    matched_approval_ids: set[str] = set()
    conflicted_approval_decision_ids: set[str] = set()
    invalid_approval_request = False
    for raw in read.approval_requests:
        if not isinstance(raw, dict):
            invalid_approval_request = True
            continue
        execution_id = _safe_text(raw.get("execution_id"))
        approval_id = _safe_text(raw.get("approval_id"))
        action = _safe_text(raw.get("execution_action"))
        resource_id = _safe_text(raw.get("resource_id"))
        created_at = _safe_text(raw.get("created_at"))
        expected_ref = approval_refs.get(execution_id or "")
        if (
            raw.get("tenant_id") != tenant_id
            or execution_id not in execution_ids
            or not approval_id
            or not action
            or not resource_id
            or _parse_aware_instant(created_at) is None
            or approval_id in seen_approval_ids
            or expected_ref is None
            or expected_ref[0] != approval_id
        ):
            invalid_approval_request = True
            continue
        expected_action, expected_resource = expected_ref[2], expected_ref[3]
        if (
            (expected_action is not None and expected_action != action)
            or (expected_resource is not None and expected_resource != resource_id)
        ):
            # Exact approval-to-execution linkage is insufficient when the
            # persisted approval request conflicts with fields recorded on the
            # AETHER lifecycle row. Keep both claims out of the joined slot;
            # otherwise the decision could sound like approval of another
            # action or resource.
            invalid_approval_request = True
            if expected_ref is not None and expected_ref[0] == approval_id:
                conflicted_approval_decision_ids.add(expected_ref[1])
            continue
        evidence_ref = _evidence_ref(
            evidence_id=approval_id,
            source="commerce_approvals",
            observed_at=created_at,
            store="commerce_approvals",
        )
        if evidence_ref is None:
            invalid_approval_request = True
            continue
        seen_approval_ids.add(approval_id)
        matched_approval_ids.add(approval_id)
        evidence_refs.append(evidence_ref)
        approval_requests.append(
            {
                "executionId": execution_id,
                "approvalId": approval_id,
                "action": action,
                "resourceId": resource_id,
                "createdAt": created_at,
                "lifecycleRequestMatch": (
                    "matched"
                    if expected_action is not None and expected_resource is not None
                    else "unknown"
                ),
                "evidenceRef": evidence_ref.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            }
        )

    if conflicted_approval_decision_ids:
        decisions = [
            row
            for row in decisions
            if row["decisionId"] not in conflicted_approval_decision_ids
        ]
        evidence_refs = [
            ref
            for ref in evidence_refs
            if not (
                ref.source == "commerce_approval_decisions"
                and ref.id in conflicted_approval_decision_ids
            )
        ]
        referenced_decisions_found.difference_update(conflicted_approval_decision_ids)

    unresolved_refs = {
        decision_id
        for _, decision_id, _, _ in approval_refs.values()
        if decision_id not in referenced_decisions_found
    }
    unresolved_approval_requests = {
        approval_id
        for approval_id, _, _, _ in approval_refs.values()
        if approval_id not in matched_approval_ids
    }
    truncated = read.truncated
    scope_known = (
        read.scope_known
        and not invalid_reference
        and not invalid_record
        and not invalid_approval_request
    )
    complete_read = (
        scope_known
        and not truncated
        and execution_inventory_complete
        and not unresolved_refs
        and not unresolved_approval_requests
    )
    if (
        invalid_reference
        or invalid_record
        or invalid_approval_request
        or unresolved_refs
        or unresolved_approval_requests
        or truncated
        or not read.scope_known
        or not execution_inventory_complete
    ):
        state: Literal["partial", "empty", "unknown", "degraded", "unavailable"] = "degraded"
        reason = (
            read.reason
            or "execution_approval_link_conflict_or_incomplete_evidence"
        )
    elif decisions:
        state = "partial"
        reason = (
            "commerce_approval_requests_and_decisions_only_other_approval_authorities_not_joined"
        )
    else:
        # No commerce decision is linked to these runs. The provider has no
        # complete inventory of non-commerce approval authorities.
        state = "unknown"
        reason = "no_linked_commerce_approval_non_commerce_authority_coverage_unknown"
    decisions.sort(key=lambda row: (row["executionId"], row["decidedAt"], row["decisionId"]))
    return ExecutionApprovalContext(
        state=state,
        decisions=tuple(decisions),
        approval_requests=tuple(approval_requests),
        evidence_refs=tuple(evidence_refs),
        reason=reason,
        source_read_state="available",
        scope_known=complete_read,
        truncated=truncated,
    )


def _latest_approval_observed_at(approval_chain: ExecutionApprovalContext) -> Optional[str]:
    """Return the latest stored approval timestamp without assigning freshness."""
    timestamps = [row.get("decidedAt") for row in approval_chain.decisions] + [
        row.get("createdAt") for row in approval_chain.approval_requests
    ]
    instants = [
        parsed
        for value in timestamps
        if (parsed := _parse_aware_instant(value)) is not None
    ]
    return max(instants).isoformat() if instants else None


def _lifecycle_elapsed_ms(row: dict[str, Any]) -> Optional[float]:
    """Return duration from two valid, timezone-aware server lifecycle times."""
    started_at = _parse_aware_instant(row.get("startedAt"))
    ended_at = _parse_aware_instant(row.get("endedAt"))
    if started_at is None or ended_at is None or ended_at < started_at:
        return None
    return round((ended_at - started_at).total_seconds() * 1000, 3)


def _plan_steps_summary(
    plan_decompositions: list[dict[str, Any]],
    internal: list[dict[str, Any]],
    server: ExecutionRead,
    *,
    temporal_unavailable: bool,
) -> dict[str, Any]:
    """Expose exact execution-linked task structure as partial plan evidence."""
    lifecycle_evidence_by_id = {
        row["executionId"]: ref
        for row in internal
        if row.get("executionId")
        and (ref := _lifecycle_evidence(row)) is not None
    }
    records: list[dict[str, Any]] = []
    for row in plan_decompositions:
        task_evidence = _task_decomposition_evidence(row)
        lifecycle_evidence = lifecycle_evidence_by_id.get(row["executionId"])
        if task_evidence is None or lifecycle_evidence is None:
            continue
        records.append(
            {
                "executionId": row["executionId"],
                "recordId": row["recordId"],
                "rootTaskId": row["rootTaskId"],
                "subtaskIds": row["subtaskIds"],
                "subtaskIdsTruncated": row["subtaskIdsTruncated"],
                "observedAt": row["occurredAt"],
                "recordMeaning": "persisted_task_decomposition_observation",
                "stepOrderKnown": False,
                "completionKnown": False,
                "evidenceRefs": [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for ref in (task_evidence, lifecycle_evidence)
                ],
            }
        )
    if temporal_unavailable:
        state = "unknown"
        reason = "temporal_anchor_not_reconstructable_from_current_sources"
    elif records:
        state = "degraded"
        reason = "task_decomposition_refs_do_not_establish_full_plan_or_step_order"
    else:
        state = "unknown"
        reason = (
            "no_exact_execution_linked_task_decomposition_observed"
            if server.available and server.scope_known and not server.truncated
            else server.reason or "execution_task_decomposition_source_coverage_incomplete"
        )
    return {
        "state": state,
        "readAuthority": _INTERNAL_SOURCE,
        "records": records if not temporal_unavailable else [],
        "observedCount": len(records) if not temporal_unavailable else None,
        "fullPlanKnown": False,
        "reason": reason,
    }


def _inputs_outputs_summary(
    internal: list[dict[str, Any]],
    server: ExecutionRead,
    *,
    temporal_unavailable: bool,
) -> dict[str, Any]:
    """Project request metadata and result references without raw bodies.

    The execution repository stores arbitrary input, output, and error JSON.
    Only its allowlisted request fields and outcome event *reference* may leave
    this provider. A recorded event ID is not proof that an output was emitted
    or that an external action succeeded.
    """
    records: list[dict[str, Any]] = []
    for row in internal:
        evidence = _lifecycle_evidence(row)
        if evidence is None:
            continue
        requested = {
            "action": row.get("requestedAction"),
            "resourceRef": row.get("requestedResource"),
            "triggerEventRef": row.get("triggeredByEventId"),
        }
        if not any(requested.values()) and not row.get("outcomeEventId"):
            continue
        records.append(
            {
                "executionId": row.get("executionId"),
                "request": {
                    "state": "available" if any(requested.values()) else "unknown",
                    **requested,
                    "payloadRead": False,
                },
                "result": {
                    "state": "unknown",
                    "lifecycleStatus": row.get("status"),
                    "outcomeEventRef": row.get("outcomeEventId"),
                    "eventPublicationState": (
                        "published"
                        if row.get("outcomeEventPublished") is True
                        else "not_published"
                        if row.get("outcomeEventPublished") is False
                        else "unknown"
                    ),
                    "outputBodyRead": False,
                    "externalEffect": "not_established",
                },
                "evidenceRefs": [
                    evidence.model_dump(mode="json", by_alias=True, exclude_none=True)
                ],
            }
        )

    if temporal_unavailable:
        state = "unknown"
        reason = "temporal_anchor_not_reconstructable_from_current_sources"
    elif records:
        state = "degraded" if not server.available or not server.scope_known or server.truncated else "available"
        reason = "server_execution_source_coverage_incomplete" if state == "degraded" else None
    elif server.available and server.scope_known and not server.truncated:
        state = "empty"
        reason = None
    else:
        state = "unknown"
        reason = server.reason or "server_execution_subject_binding_incomplete"
    return {
        "state": state,
        "readAuthority": _INTERNAL_SOURCE,
        "records": records if not temporal_unavailable else [],
        "count": len(records) if state in {"available", "empty"} else None,
        "reason": reason,
    }


def _failure_summary(
    internal: list[dict[str, Any]],
    external: list[dict[str, Any]],
    server: ExecutionRead,
    observed: ExecutionRead,
    *,
    temporal_unavailable: bool,
) -> dict[str, Any]:
    """Keep exact lifecycle failures separate from unlinked source telemetry."""
    records: list[dict[str, Any]] = []
    for row in internal:
        if row.get("status") not in _SERVER_FAILURE_STATUSES:
            continue
        evidence = _lifecycle_evidence(row)
        if evidence is None:
            continue
        records.append(
            {
                "source": _INTERNAL_SOURCE,
                "executionId": row.get("executionId"),
                "recordedStatus": row.get("status"),
                "classification": "server_recorded_lifecycle_failure",
                "externalEffect": "unknown",
                "occurredAt": row.get("endedAt") or row.get("startedAt"),
                "evidenceRefs": [
                    evidence.model_dump(mode="json", by_alias=True, exclude_none=True)
                ],
            }
        )
    unlinked_source_reported: list[dict[str, Any]] = []
    for row in external:
        if row.get("reportedStatus") not in _SOURCE_REPORTED_FAILURE_STATUSES:
            continue
        evidence = _fact_evidence(row)
        if evidence is None:
            continue
        unlinked_source_reported.append(
            {
                "source": _SILVER_SOURCE,
                "sourceEventId": row.get("sourceEventId"),
                "reportedStatus": row.get("reportedStatus"),
                "classification": "source_reported_unlinked_failure_telemetry",
                "externalEffect": "unknown",
                "occurredAt": row.get("occurredAt"),
                "evidenceRefs": [
                    evidence.model_dump(mode="json", by_alias=True, exclude_none=True)
                ],
            }
        )

    complete = server.available and server.scope_known and not server.truncated
    source_coverage_complete = observed.available and observed.scope_known and not observed.truncated
    if temporal_unavailable:
        state = "unknown"
        reason = "temporal_anchor_not_reconstructable_from_current_sources"
    elif records:
        state = "available" if complete else "degraded"
        reason = None if complete else "server_execution_failure_coverage_incomplete"
    elif complete:
        state = "empty"
        reason = (
            "source_reported_failure_unlinked_to_execution"
            if unlinked_source_reported
            else None
        )
    else:
        state = "unknown"
        reason = "server_execution_failure_coverage_incomplete"
    return {
        "state": state,
        "readAuthorities": [_INTERNAL_SOURCE],
        "contextAuthority": _SILVER_SOURCE,
        "records": records if not temporal_unavailable else [],
        "unlinkedSourceReportedFailures": (
            unlinked_source_reported if not temporal_unavailable else []
        ),
        "count": len(records) if state in {"available", "empty"} else None,
        "unlinkedSourceReportedCount": (
            len(unlinked_source_reported)
            if source_coverage_complete and not temporal_unavailable
            else None
        ),
        "reason": reason,
    }


def _latency_cost_summary(
    internal: list[dict[str, Any]],
    server: ExecutionRead,
    cost_read: ExecutionCostRead,
    *,
    execution_inventory_complete: bool,
    temporal_unavailable: bool,
) -> dict[str, Any]:
    """Expose lifecycle latency and exact action-linked AI invocation economics."""
    samples: list[dict[str, Any]] = []
    incomplete_count = 0
    for row in internal:
        elapsed_ms = _lifecycle_elapsed_ms(row)
        evidence = _lifecycle_evidence(row)
        if elapsed_ms is None or evidence is None:
            incomplete_count += 1
            continue
        samples.append(
            {
                "executionId": row.get("executionId"),
                "startedAt": row.get("startedAt"),
                "endedAt": row.get("endedAt"),
                "elapsedMs": elapsed_ms,
                "measurement": "server_recorded_lifecycle_elapsed_time",
                "evidenceRefs": [
                    evidence.model_dump(mode="json", by_alias=True, exclude_none=True)
                ],
            }
        )

    if temporal_unavailable:
        latency_state = "unknown"
        reason = "temporal_anchor_not_reconstructable_from_current_sources"
        samples = []
    elif samples:
        latency_state = (
            "degraded"
            if incomplete_count
            or not server.available
            or server.truncated
            or not server.scope_known
            else "available"
        )
        reason = (
            "some_server_lifecycle_records_lack_valid_start_or_end_timestamps"
            if incomplete_count
            else "execution_source_coverage_incomplete"
            if not server.available or server.truncated or not server.scope_known
            else None
        )
    elif not internal and server.available and server.scope_known and not server.truncated:
        latency_state = "unknown"
        reason = "no_server_lifecycle_records_with_measurable_duration"
    elif not internal and server.available and not server.scope_known:
        latency_state = "unknown"
        reason = server.reason or "execution_subject_binding_incomplete"
    elif internal:
        latency_state = "degraded"
        reason = "some_server_lifecycle_records_lack_valid_start_or_end_timestamps"
    else:
        latency_state = "degraded"
        reason = server.reason or "server_lifecycle_duration_read_incomplete"

    durations = [item["elapsedMs"] for item in samples]
    latency: dict[str, Any] = {
        "state": latency_state,
        "measurement": "server_recorded_lifecycle_elapsed_time",
        "sampleCount": len(samples) if samples else None,
        "samples": samples,
        "reason": reason,
    }
    if durations:
        latency.update(
            {
                "minimumMs": min(durations),
                "averageMs": round(sum(durations) / len(durations), 3),
                "maximumMs": max(durations),
            }
        )

    invocation_records: list[dict[str, Any]] = []
    cost_totals: dict[str, Decimal] = {}
    cost_evidence_by_currency: dict[str, list[dict[str, Any]]] = {}
    invocation_latency_samples: list[tuple[float, dict[str, Any]]] = []
    unknown_cost_count = 0
    invalid_fact_count = 0
    for row in cost_read.rows:
        execution_id = _safe_text(row.get("execution_id"))
        invocation_id = _safe_text(row.get("invocation_id"))
        action_id = _safe_text(row.get("action_id"))
        observed_at = _safe_text(row.get("observed_at"))
        if (
            execution_id is None
            or invocation_id is None
            or action_id != execution_id
            or execution_id not in {item.get("executionId") for item in internal}
        ):
            invalid_fact_count += 1
            continue
        tenant_fact_id = _safe_text(row.get("tenant_id")) or ""
        evidence = EvidenceRef(
            id=invocation_id,
            type="event",
            source="ai_execution_facts",
            observedAt=observed_at,
            uri=f"store://ai_execution_facts/{quote(f'{tenant_fact_id}:{invocation_id}', safe='')}",
        )
        selected_raw = row.get("selected_cost")
        selected_cost: Optional[Decimal] = None
        if selected_raw is not None and not isinstance(selected_raw, bool):
            try:
                candidate_cost = Decimal(str(selected_raw))
                if candidate_cost.is_finite() and candidate_cost >= 0:
                    selected_cost = candidate_cost
            except (InvalidOperation, ValueError, TypeError):
                selected_cost = None
        cost_basis = _safe_text(row.get("cost_basis"), limit=32)
        if cost_basis not in {"billed", "provider_reported", "calculated", "estimated", "unknown"}:
            cost_basis = None
            invalid_fact_count += 1
        currency = _safe_text(row.get("currency"), limit=16)
        if currency is not None:
            currency = currency.upper()
        if (
            selected_cost is None
            or cost_basis in {None, "unknown"}
            or currency is None
        ):
            unknown_cost_count += 1
            known_selected_cost = None
        else:
            known_selected_cost = selected_cost
            cost_totals[currency] = cost_totals.get(currency, Decimal("0")) + selected_cost
            cost_evidence_by_currency.setdefault(currency, []).append(
                evidence.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        latency_raw = row.get("latency_ms")
        invocation_latency_ms: Optional[float] = None
        if latency_raw is not None and not isinstance(latency_raw, bool):
            try:
                candidate_latency = Decimal(str(latency_raw))
                if candidate_latency.is_finite() and candidate_latency >= 0:
                    invocation_latency_ms = float(candidate_latency)
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                invocation_latency_ms = None
        if latency_raw is not None and invocation_latency_ms is None:
            invalid_fact_count += 1

        record = {
            "executionId": execution_id,
            "invocationId": invocation_id,
            "observedAt": observed_at,
            "latencyMs": invocation_latency_ms,
            "costBasis": cost_basis,
            "currency": currency,
            "selectedCost": (
                float(known_selected_cost) if known_selected_cost is not None else None
            ),
            "evidenceRefs": [
                evidence.model_dump(mode="json", by_alias=True, exclude_none=True)
            ],
        }
        invocation_records.append(record)
        if invocation_latency_ms is not None:
            invocation_latency_samples.append(
                (invocation_latency_ms, record["evidenceRefs"][0])
            )

    source_complete = (
        cost_read.available
        and cost_read.scope_known
        and not cost_read.truncated
        and execution_inventory_complete
    )
    if temporal_unavailable:
        cost_state = "unknown"
        cost_reason = "temporal_anchor_not_reconstructable_from_current_sources"
        invocation_records = []
        cost_totals = {}
        cost_evidence_by_currency = {}
        invocation_latency_samples = []
    elif not cost_read.available:
        cost_state = "unavailable"
        cost_reason = cost_read.reason or "ai_execution_fact_read_unavailable"
    elif not internal:
        cost_state = "unknown"
        cost_reason = "execution_subject_not_admitted_from_server_lifecycle"
    elif not invocation_records:
        cost_state = "degraded" if not source_complete else "unknown"
        cost_reason = (
            cost_read.reason or "ai_execution_fact_read_or_execution_inventory_incomplete"
            if not source_complete
            else "no_ai_execution_invocation_linked_to_admitted_execution"
        )
    elif not cost_totals:
        cost_state = "degraded" if not source_complete or invalid_fact_count else "unknown"
        cost_reason = (
            cost_read.reason or "linked_ai_execution_cost_coverage_incomplete"
            if not source_complete or invalid_fact_count
            else "linked_ai_execution_facts_have_unknown_or_invalid_cost"
        )
    elif not source_complete or unknown_cost_count or invalid_fact_count:
        cost_state = "degraded"
        cost_reason = (
            cost_read.reason
            or "linked_ai_execution_cost_coverage_incomplete"
            if not source_complete
            else "some_linked_ai_execution_facts_have_unknown_or_invalid_cost"
        )
    else:
        cost_state = "available"
        cost_reason = None

    latest_observed = max(
        (
            instant
            for row in cost_read.rows
            if (instant := _parse_aware_instant(row.get("observed_at"))) is not None
        ),
        default=None,
    )
    cost = {
        "state": cost_state,
        "readAuthority": "ai_execution_facts",
        "linkage": "exact_tenant_execution_action_id_and_agent_id",
        "completeness": "explicit_action_id_invocation_facts_only",
        "invocationCount": len(invocation_records) if invocation_records else None,
        "knownCostInvocationCount": sum(
            len(refs) for refs in cost_evidence_by_currency.values()
        ),
        "unknownCostInvocationCount": (
            unknown_cost_count if invocation_records else None
        ),
        "byCurrency": [
            {
                "currency": currency,
                "total": float(total),
                "factCount": len(cost_evidence_by_currency[currency]),
                "evidenceRefs": cost_evidence_by_currency[currency],
            }
            for currency, total in sorted(cost_totals.items())
        ],
        "invocations": invocation_records,
        "coverage": {
            "state": "complete_for_exact_execution_action_links"
            if source_complete
            else "partial_or_unknown",
            "executionInventoryComplete": execution_inventory_complete,
            "sourceScopeKnown": cost_read.scope_known,
            "truncated": cost_read.truncated,
            "invalidFactCount": invalid_fact_count,
        },
        "freshness": {
            "state": "unknown",
            "latestObservedAt": (
                latest_observed.isoformat() if latest_observed is not None else None
            ),
            "reason": "no_execution_ai_fact_freshness_threshold_is_configured",
        },
        "reason": cost_reason,
    }

    if temporal_unavailable:
        invocation_latency_state = "unknown"
        invocation_latency_reason = "temporal_anchor_not_reconstructable_from_current_sources"
    elif not cost_read.available:
        invocation_latency_state = "unavailable"
        invocation_latency_reason = cost_read.reason or "ai_execution_fact_read_unavailable"
    elif not invocation_latency_samples:
        invocation_latency_state = "unknown"
        invocation_latency_reason = (
            "no_linked_ai_invocation_latency_measurements"
            if source_complete
            else cost_read.reason or "ai_execution_fact_coverage_incomplete"
        )
    elif not source_complete or len(invocation_latency_samples) < len(invocation_records):
        invocation_latency_state = "degraded"
        invocation_latency_reason = cost_read.reason or "ai_execution_fact_coverage_incomplete"
    else:
        invocation_latency_state = "available"
        invocation_latency_reason = None
    invocation_durations = [value for value, _ in invocation_latency_samples]
    latency["aiInvocationTelemetry"] = {
        "state": invocation_latency_state,
        "measurement": "source_reported_ai_invocation_latency",
        "sampleCount": len(invocation_durations) if invocation_durations else None,
        "samples": [
            {
                "latencyMs": value,
                "evidenceRefs": [evidence_ref],
            }
            for value, evidence_ref in invocation_latency_samples
        ],
        "reason": invocation_latency_reason,
        "freshness": cost["freshness"],
    }
    if invocation_durations:
        latency["aiInvocationTelemetry"].update(
            {
                "minimumMs": min(invocation_durations),
                "averageMs": round(sum(invocation_durations) / len(invocation_durations), 3),
                "maximumMs": max(invocation_durations),
            }
        )
    return {
        "latency": latency,
        "cost": cost,
    }


def _content_state(
    server: ExecutionRead,
    observed: ExecutionRead,
    internal: list[dict[str, Any]],
    external: list[dict[str, Any]],
) -> str:
    if not server.available or not observed.available or server.truncated or observed.truncated:
        return "degraded"
    if internal or external:
        if not server.scope_known or not observed.scope_known:
            return "degraded"
        return "available"
    if server.scope_known and observed.scope_known:
        return "empty"
    return "unknown"


def _section_state(
    server: ExecutionRead,
    observed: ExecutionRead,
    internal: list[dict[str, Any]],
    external: list[dict[str, Any]],
    temporal_unavailable: bool,
) -> str:
    if temporal_unavailable:
        return "degraded"
    if not server.available or not observed.available or server.truncated or observed.truncated:
        return "degraded"
    if internal or external:
        if not server.scope_known or not observed.scope_known:
            return "degraded"
        return "available"
    if server.scope_known and observed.scope_known:
        return "empty"
    return "unknown"


def register_provider(registry: ProviderRegistry) -> None:
    """Explicit wiring seam; importing this module never registers globally."""
    registry.register(
        Execution360Provider(),
        source="services/api/actions/agent/execution360_provider",
    )


__all__ = [
    "Execution360Provider",
    "Execution360Source",
    "ExecutionRead",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositoryExecution360Source",
    "register_provider",
]
