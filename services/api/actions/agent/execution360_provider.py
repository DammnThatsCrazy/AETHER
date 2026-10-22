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
SLOT_RISK_EVENTS = "risk_events"

_SERVER_FAILURE_STATUSES = frozenset({"failed", "revoked"})
_SOURCE_REPORTED_FAILURE_STATUSES = frozenset({"failed", "error", "denied", "revoked"})

_MAX_ROWS = 500
_MAX_TOOL_EDGE_SCAN = 10_000
_MAX_EXECUTION_RISK_SIGNAL_SCAN = 1000
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


@dataclass(frozen=True)
class ExecutionRiskEventContext:
    """Validated, evidence-backed execution risk signals and coverage state."""

    state: Literal["partial", "empty", "unknown", "degraded", "unavailable"]
    signals: tuple[Any, ...] = ()
    reason: Optional[str] = None
    source_read_state: Literal["available", "unavailable", "not_read"] = "not_read"
    truncated: bool = False
    scope_known: bool = False


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
    # Lifecycle graph calls are attached only after exact execution, tenant,
    # and canonical actor joins. Their completeness is still source-unknown.
    tool_calls: Optional[ExecutionToolCallRead] = None


@dataclass(frozen=True)
class EpisodeExecutionScope:
    """Tenant-scoped event and actor bindings persisted on one episode."""

    available: bool
    event_ids: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    complete: bool = False
    reason: Optional[str] = None


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

    async def execution_risk_events(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskEventRead:
        """Read canonical RiskSignals for admitted exact execution subjects."""


class RepositoryExecution360Source:
    """Defensive adapter over existing agent repositories and Silver facts."""

    def __init__(self, *, episode_store: Any = None, graph_client: Any = None) -> None:
        self._episode_store = episode_store
        self._graph_client = graph_client

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
        tool_calls = await self._read_execution_tool_calls(tenant_id, scoped)
        return ExecutionRead(
            rows=scoped[:limit],
            available=True,
            scope_known=complete_identity_scope,
            truncated=source_truncated or identity_truncated or len(scoped) > limit,
            reason=("agent_identity_binding_incomplete" if not complete_identity_scope else None),
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
            elif subject.kind == "entity":
                configs = await AgentConfigRepository().list_for_owner(subject.id)
                source_agent_ids = {
                    str(row.get("agent_id"))
                    for row in configs
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
                truncated or len(result) > limit or (scope is not None and not scope.complete)
            ),
            reason=(
                "some_tenant_facts_have_unresolved_actor_binding"
                if unresolved_actor_seen
                else "agent_identity_binding_incomplete"
                if not identity_scope_complete
                else scope.reason
                if scope is not None and not scope.complete
                else None
            ),
            agent_ids=tuple(sorted(allowed_agent_ids)),
            subject_event_ids=scope.event_ids if scope is not None else (),
        )

    async def execution_risk_events(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskEventRead:
        """Read RiskSignals whose subjects match admitted tenant execution IDs."""
        admitted_ids = {
            value for raw in execution_ids if (value := _safe_text(raw)) is not None
        }
        if not admitted_ids:
            return ExecutionRiskEventRead(rows=[], available=True, scope_known=True)
        try:
            from intelligence.risk360.store import RiskSignalRepository

            repository = RiskSignalRepository()
            if len(admitted_ids) == 1:
                rows = await repository.list_by_subject(
                    tenant_id,
                    "execution",
                    next(iter(admitted_ids)),
                    limit=limit + 1,
                )
                scan_limit = limit
            else:
                rows = await repository.find_many(
                    filters={"tenant_id": tenant_id, "subject_kind": "execution"},
                    limit=_MAX_EXECUTION_RISK_SIGNAL_SCAN + 1,
                )
                scan_limit = _MAX_EXECUTION_RISK_SIGNAL_SCAN
        except Exception:  # noqa: BLE001 - optional canonical source failure is isolated
            return ExecutionRiskEventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_risk_signal_source_unavailable",
            )

        if not isinstance(rows, list):
            return ExecutionRiskEventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_risk_signal_read_invalid",
            )
        scan_truncated = len(rows) > scan_limit
        bounded = rows[:scan_limit]
        mismatch = any(
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("subject_kind") != "execution"
            or (len(admitted_ids) == 1 and row.get("subject_id") not in admitted_ids)
            for row in bounded
        )
        exact_rows = [
            {
                key: value
                for key, value in row.items()
                if key not in {"id", "created_at", "updated_at"}
            }
            for row in bounded
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("subject_kind") == "execution"
            and row.get("subject_id") in admitted_ids
        ]
        truncated = scan_truncated or len(exact_rows) > limit
        exact_rows = exact_rows[:limit]
        return ExecutionRiskEventRead(
            rows=exact_rows,
            available=True,
            scope_known=not mismatch,
            truncated=truncated,
            reason=(
                "execution_risk_signal_scope_mismatch"
                if mismatch
                else "execution_risk_signal_read_truncated"
                if truncated
                else None
            ),
        )


def _tenant_agent_config(row: Any, tenant_id: str, agent_id: Any) -> bool:
    return bool(
        isinstance(row, dict)
        and row.get("tenant_id") == tenant_id
        and isinstance(agent_id, str)
        and agent_id
        and row.get("agent_id") == agent_id
    )


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
    policy = row.get("policy_log")
    policy = policy if isinstance(policy, dict) else {}
    decision = policy.get("delegation_check")
    decision = decision if isinstance(decision, dict) else {}
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
        "triggeredByEventId": _safe_text(row.get("triggered_by_event_id")),
        "requestedAction": _safe_text(snapshot.get("action")),
        "requestedResource": _safe_text(snapshot.get("resource")),
        "recordedDelegationDecision": (
            decision.get("allowed") if isinstance(decision.get("allowed"), bool) else None
        ),
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
                    row.get("agentId") in allowed_agent_ids
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
                or row.get("agentId") in allowed_agent_ids
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

        admitted_execution_ids = {
            row["executionId"] for row in internal if row.get("executionId")
        }
        tool_calls = _project_tool_call_read(
            server.tool_calls,
            admitted_execution_ids=admitted_execution_ids,
            time_range=request.timeRange,
            temporal_unavailable=temporal_unavailable,
        )
        execution_inventory_complete = (
            server.available
            and server.scope_known
            and not server.truncated
            and not episode_event_binding_mismatch
            and not temporal_unavailable
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
        if request.subject.kind == "episode" and episode_event_binding_mismatch:
            reasons.append("episode_execution_event_binding_conflict")

        state = _section_state(server, observed, internal, external, temporal_unavailable)
        evidence = self._all_evidence(
            internal, external, plan_decompositions, tool_calls, risk_events
        )
        claims = (
            self._claims(
                request.subject,
                internal,
                external,
                plan_decompositions,
                tool_calls,
                risk_events,
            )
            if request.includeClaims is not False
            else []
        )
        sections = self._sections(
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
            return result
        except Exception:  # noqa: BLE001 - fail-isolate optional canonical source
            return ExecutionRiskEventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason="execution_risk_event_source_unavailable",
            )

    @staticmethod
    def _all_evidence(
        internal: list[dict[str, Any]],
        external: list[dict[str, Any]],
        plan_decompositions: list[dict[str, Any]],
        tool_calls: ExecutionToolCallRead,
        risk_events: ExecutionRiskEventContext,
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
        for signal in risk_events.signals:
            for ref in signal.evidence_refs:
                if (ref.id, ref.source) in seen:
                    continue
                seen.add((ref.id, ref.source))
                refs.append(ref)
        return refs

    @staticmethod
    def _claims(
        subject: ProjectionSubject,
        internal: list[dict[str, Any]],
        external: list[dict[str, Any]],
        plan_decompositions: list[dict[str, Any]],
        tool_calls: ExecutionToolCallRead,
        risk_events: ExecutionRiskEventContext,
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
                            f"AETHER recorded authenticated tenant user {principal_user_id} as the initiating principal for execution {row['executionId']}; this does not make that principal the acting agent or establish a canonical human entity link."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
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
            if isinstance(row.get("recordedDelegationDecision"), bool):
                decision = "allowed" if row["recordedDelegationDecision"] else "denied"
                action = row.get("requestedAction") or "unknown action"
                resource = row.get("requestedResource") or "unknown resource"
                claims.append(
                    ClaimEnvelope(
                        id=f"execution360:delegation:{row['executionId']}",
                        kind="server_recorded_delegation_decision",
                        subject=subject,
                        evidenceRefs=[evidence],
                        claims=[
                            f"AETHER recorded a {decision} delegation-engine decision for {action} on {resource} in execution {row['executionId']}; the decision is action-scoped at request time and does not establish standing authority or prove execution."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[
                            SLOT_AUTHORITY_CHECK,
                            SLOT_AGENT_AUTHORITY_ENVELOPE,
                            SLOT_EVIDENCE,
                        ],
                    )
                )
            grant_evidence = _internal_delegation_evidence(row)
            if grant_evidence is not None and isinstance(row.get("recordedDelegationDecision"), bool):
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
        return claims

    @staticmethod
    def _sections(
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
            "state": "unknown",
            "reason": "execution_approval_id_canonical_join_not_available",
            "sourceReadState": "not_read",
            "joinedExecutionApprovals": [],
            "evidenceRefs": [],
        }
        risk_event_linkage = {
            "state": risk_events.state,
            "reason": risk_events.reason,
            "sourceReadState": risk_events.source_read_state,
            "completeness": "recorded_execution_subject_signals_only",
            "scopeKnown": risk_events.scope_known,
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
                for signal in risk_events.signals
                for ref in signal.evidence_refs
            ],
            "freshness": {
                "state": "unknown",
                "latestObservedAt": max(
                    (
                        signal.observed_at.astimezone(timezone.utc).isoformat()
                        for signal in risk_events.signals
                        if signal.observed_at is not None
                    ),
                    default=None,
                ),
                "reason": "no_execution_risk_signal_freshness_threshold_is_configured",
            },
            "truncated": risk_events.truncated,
        }
        latency_cost = _latency_cost_summary(
            internal,
            server,
            temporal_unavailable=temporal_unavailable,
        )
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
                    "sourceLineage": [
                        _INTERNAL_SOURCE if internal else None,
                        _SILVER_SOURCE if external else None,
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
                        {k: v for k, v in row.items() if k not in {"source"}} for row in internal
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
                    "workerRunLinkage": worker_linkage,
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
    """Validate exact execution-scoped RiskSignals before projection.

    A recorded signal is risk context, not a complete risk assessment or proof
    that the execution caused the signal. Signals without evidence or with
    invalid subject/time scope are omitted and downgrade the coverage state.
    """
    if not read.available:
        return ExecutionRiskEventContext(
            state="unavailable",
            reason=read.reason or "execution_risk_signal_source_unavailable",
            source_read_state="unavailable",
            truncated=read.truncated,
            scope_known=False,
        )

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

    from intelligence.risk360.contracts import RiskSignal

    signals: list[Any] = []
    seen_ids: set[str] = set()
    invalid_record_seen = False
    for raw in read.rows:
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

    complete_read = (
        read.scope_known
        and not read.truncated
        and execution_inventory_complete
        and not invalid_record_seen
    )
    if signals:
        state: Literal["partial", "empty", "unknown", "degraded", "unavailable"] = (
            "partial" if complete_read else "degraded"
        )
        reason = (
            "risk_signals_are_recorded_context_not_a_complete_execution_risk_assessment"
            if complete_read
            else read.reason
            or "execution_inventory_or_risk_signal_scope_incomplete"
        )
    elif complete_read:
        state = "empty"
        reason = "no_recorded_canonical_risk_signals_for_execution_subject"
    else:
        state = "degraded"
        reason = read.reason or "execution_inventory_or_risk_signal_scope_incomplete"
    return ExecutionRiskEventContext(
        state=state,
        signals=tuple(signals),
        reason=reason,
        source_read_state="available",
        truncated=read.truncated,
        scope_known=read.scope_known,
    )


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
    *,
    temporal_unavailable: bool,
) -> dict[str, Any]:
    """Expose measured lifecycle elapsed time and leave unsupported cost unknown."""
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
    return {
        "latency": latency,
        "cost": {
            "state": "unknown",
            "reason": "no_execution_cost_authority_is_joined_by_execution360",
        },
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
