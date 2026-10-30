"""Read-only Workflow360 projection over registered definitions and exact run evidence.

Workflow definitions are read only from explicitly registered, tenant-owned
definition revisions. Exact run-linked evidence comes from
tenant-scoped ``ai_execution_facts`` and AgentExecution rows validated against
their explicit invocation ``action_id`` links. These records can reference
canonical Agent identities, trigger events, x402 approvals, and outcome IDs.
Those references do not establish complete workflow coverage, event causality,
external action receipts, or workflow-attributed business outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef
from intelligence.workflow.definitions import (
    WorkflowDefinitionRead,
    WorkflowDefinitionRepository,
    WorkflowDefinitionRevision,
    workflow_definition_evidence,
)
from shared.backend_interpretation.primitives import CLAIM_TYPES, OUTCOME_STATES, VALUE_STATES
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry


PROJECTION_ID = "workflow360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "workflow_summary",
    "triggers",
    "runs",
    "actors",
    "approvals",
    "agent_steps",
    "actions",
    "failures",
    "outcomes",
    "risk",
    "evidence_trace",
)

_MAX_INVOCATION_FACTS = 200
_MAX_AGENT_EXECUTIONS = 200
_MAX_WORKFLOW_ACTIONS = 500
_MAX_WORKFLOW_ACTION_EDGE_SCAN = 10_000
_MAX_TRIGGER_EVENTS = 200
_MAX_WORKFLOW_OUTCOMES = 200
_MAX_WORKFLOW_RISK_ASSESSMENTS = 200
_RUN_SUBJECT_KINDS = frozenset({"run", "workflow_run"})
_APPROVAL_DECISION_ACTIONS = frozenset({"approve", "reject", "escalate", "revoke"})
_OUTCOME_STATES = frozenset(OUTCOME_STATES)
_OUTCOME_VALUE_STATES = frozenset(VALUE_STATES)
_SOURCE = "ai_execution_facts"
_AGENT_EXECUTION_SOURCE = "agent_executions"
_EVENT_SOURCE = "services/api/repositories/repos.py:events"
_OUTCOME_SOURCE = "outcome_truth"


@dataclass(frozen=True)
class WorkflowRunInvocationRead:
    """Bounded read of AI invocation facts explicitly linked to one run ID."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowAgentIdentityRead:
    """Tenant-owned Agent identity resolutions for source-reported agent refs."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowAgentExecutionRead:
    """Bounded read of canonical Agent executions explicitly linked to a run."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowTriggerRead:
    """Bounded canonical event reads for explicit execution trigger references."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None
    source_read_state: Literal["available", "unavailable", "not_read"] = "not_read"


@dataclass(frozen=True)
class WorkflowActionRead:
    """Bounded execution-linked tool-call edges for one exact workflow run."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowPrincipalIdentityRead:
    """Tenant USER_ID alias resolutions for execution principals/approvers."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowApprovalRead:
    """Exact x402 approvals and decisions linked to admitted AgentExecutions."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowOutcomeRead:
    """Exact tenant outcome rows referenced by this run's invocation facts."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class WorkflowRiskAssessmentRead:
    """Bounded exact execution-subject risk assessment reads for one run."""

    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool
    scope_mismatch: bool = False
    reason: Optional[str] = None


class Workflow360Source(Protocol):
    """Tenant-scoped exact-ID read seam for workflow run evidence."""

    async def workflow_definition(
        self, *, tenant_id: str, workflow_id: str
    ) -> WorkflowDefinitionRead: ...

    async def workflow_definition_as_of(
        self, *, tenant_id: str, workflow_id: str, as_of: datetime
    ) -> WorkflowDefinitionRead: ...

    async def run_invocations(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowRunInvocationRead: ...

    async def run_agent_executions(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowAgentExecutionRead: ...

    async def run_trigger_events(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowTriggerRead: ...

    async def run_execution_actions(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowActionRead: ...

    async def actor_identities(
        self, *, tenant_id: str, agent_ids: set[str], limit: int
    ) -> WorkflowAgentIdentityRead: ...

    async def principal_identities(
        self, *, tenant_id: str, principal_user_ids: set[str], limit: int
    ) -> WorkflowPrincipalIdentityRead: ...

    async def run_execution_approvals(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowApprovalRead: ...

    async def run_linked_outcomes(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        invocation_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowOutcomeRead: ...

    async def run_execution_risk_assessments(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowRiskAssessmentRead: ...


class RepositoryWorkflow360Source:
    """Adapter over the existing derived AI invocation facts store."""

    def __init__(
        self,
        *,
        principal_identity_repository: Any = None,
        outcome_truth_store: Any = None,
        workflow_definition_repository: Any = None,
    ) -> None:
        self._principal_identity_repository = principal_identity_repository
        self._outcome_truth_store = outcome_truth_store
        self._workflow_definition_repository = workflow_definition_repository

    async def workflow_definition(
        self, *, tenant_id: str, workflow_id: str
    ) -> WorkflowDefinitionRead:
        if not tenant_id or not workflow_id:
            return WorkflowDefinitionRead(reason="exact_tenant_workflow_id_required")
        try:
            repository = self._workflow_definition_repository or WorkflowDefinitionRepository()
            return await repository.read_latest(tenant_id, workflow_id)
        except Exception:  # noqa: BLE001 - definition authority remains unknown
            return WorkflowDefinitionRead(reason="workflow_definition_read_unavailable")

    async def workflow_definition_as_of(
        self, *, tenant_id: str, workflow_id: str, as_of: datetime
    ) -> WorkflowDefinitionRead:
        if not tenant_id or not workflow_id:
            return WorkflowDefinitionRead(reason="exact_tenant_workflow_as_of_required")
        try:
            repository = self._workflow_definition_repository or WorkflowDefinitionRepository()
            return await repository.read_as_of(tenant_id, workflow_id, as_of)
        except Exception:  # noqa: BLE001 - history authority remains unknown
            return WorkflowDefinitionRead(reason="workflow_definition_history_read_unavailable")

    async def run_invocations(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowRunInvocationRead:
        if not tenant_id or not workflow_run_id:
            return WorkflowRunInvocationRead(
                (), False, False, "exact_tenant_workflow_run_scope_required"
            )
        try:
            from config.settings import settings

            if not settings.ai_economics.execution_facts_enabled:
                return WorkflowRunInvocationRead(
                    (), False, False, "ai_execution_facts_disabled"
                )

            from value.economic.ai_aggregation import list_facts

            bounded_limit = min(max(int(limit), 1), _MAX_INVOCATION_FACTS)
            rows = await list_facts(
                tenant_id,
                workflow_run_id=workflow_run_id,
                limit=bounded_limit + 1,
            )
        except Exception:  # noqa: BLE001 - source details must not escape the provider
            return WorkflowRunInvocationRead(
                (), False, False, "ai_execution_fact_repository_unavailable"
            )

        bounded_limit = min(max(int(limit), 1), _MAX_INVOCATION_FACTS)
        complete = len(rows) <= bounded_limit
        if not complete:
            rows = rows[:bounded_limit]
        return WorkflowRunInvocationRead(
            tuple(row for row in rows if isinstance(row, dict)),
            True,
            complete,
            None if complete else "ai_execution_fact_read_truncated",
        )

    async def run_agent_executions(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowAgentExecutionRead:
        """Read canonical executions carrying this exact tenant/run link.

        The consumer still verifies each persisted invocation reference against
        this run's canonical AI facts before exposing an execution.
        """
        if not tenant_id or not workflow_run_id:
            return WorkflowAgentExecutionRead(
                (), False, False, reason="exact_tenant_workflow_run_scope_required"
            )
        try:
            from repositories.repos import AgentExecutionRepository

            bounded_limit = min(max(int(limit), 1), _MAX_AGENT_EXECUTIONS)
            rows = await AgentExecutionRepository().find_many(
                filters={"tenant_id": tenant_id, "workflow_run_id": workflow_run_id},
                limit=bounded_limit + 1,
            )
        except Exception:  # noqa: BLE001 - source details must not escape the provider
            return WorkflowAgentExecutionRead(
                (), False, False, reason="canonical_agent_execution_repository_unavailable"
            )

        bounded_limit = min(max(int(limit), 1), _MAX_AGENT_EXECUTIONS)
        complete = len(rows) <= bounded_limit
        if not complete:
            rows = rows[:bounded_limit]
        return WorkflowAgentExecutionRead(
            tuple(row for row in rows if isinstance(row, dict)),
            True,
            complete,
            reason=None if complete else "canonical_agent_execution_read_truncated",
        )

    async def run_execution_actions(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowActionRead:
        """Resolve only graph tool-call edges tied to admitted run executions.

        These edges establish an observed tool-call lifecycle reference. They
        do not establish a workflow definition, action authorization, tool
        completion, an external effect, or complete action coverage.
        """
        if not tenant_id or not workflow_run_id:
            return WorkflowActionRead(
                (), False, False, reason="exact_tenant_workflow_run_scope_required"
            )

        execution_agents: dict[str, str] = {}
        scope_mismatch = False
        for row in execution_rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("workflow_run_id") != workflow_run_id
            ):
                scope_mismatch = True
                continue
            execution_id = _safe_identifier(row.get("execution_id"))
            agent_id = _safe_identifier(row.get("agent_id"))
            if execution_id is None or agent_id is None:
                scope_mismatch = True
                continue
            existing_agent = execution_agents.get(execution_id)
            if existing_agent is not None:
                scope_mismatch = scope_mismatch or existing_agent != agent_id
                continue
            execution_agents[execution_id] = agent_id

        if not execution_agents:
            return WorkflowActionRead(
                (), True, False, scope_mismatch=scope_mismatch,
                reason=(
                    "unscoped_or_invalid_workflow_execution_rows_dropped"
                    if scope_mismatch
                    else "no_admitted_run_linked_execution_for_action_join"
                ),
            )

        try:
            from shared.graph.graph import EdgeType, GraphClient

            graph = GraphClient()
            edges, truncated = await graph.get_edges_for_tenant(
                tenant_id,
                limit=_MAX_WORKFLOW_ACTION_EDGE_SCAN,
                edge_types=[EdgeType.CALLED_TOOL],
            )
        except Exception:  # noqa: BLE001 - graph source diagnostics stay private
            return WorkflowActionRead(
                (), False, False, scope_mismatch=scope_mismatch,
                reason="canonical_workflow_action_graph_source_unavailable",
            )
        if not isinstance(edges, list):
            return WorkflowActionRead(
                (), False, False, scope_mismatch=scope_mismatch,
                reason="canonical_workflow_action_graph_read_invalid",
            )

        rows: list[dict[str, Any]] = []
        for edge in edges:
            properties = getattr(edge, "properties", None)
            if (
                getattr(edge, "edge_type", None) != EdgeType.CALLED_TOOL
                or not isinstance(properties, dict)
            ):
                scope_mismatch = True
                continue
            edge_tenant_id = _exact_identifier(
                properties.get("tenant_id") or properties.get("tenantId")
            )
            raw_execution_id = properties.get("execution_id")
            execution_id = _exact_identifier(raw_execution_id)
            if edge_tenant_id != tenant_id:
                scope_mismatch = True
                continue
            if execution_id is None:
                # A malformed value that normalizes to an admitted execution
                # is an ambiguous attempted join, so it must affect coverage.
                if _safe_identifier(raw_execution_id) in execution_agents:
                    scope_mismatch = True
                continue
            if execution_id not in execution_agents:
                continue

            expected_agent_id = execution_agents[execution_id]
            expected_agent_vertex = f"{tenant_id}:agent:{expected_agent_id}"
            target_vertex_id = _exact_identifier(getattr(edge, "to_vertex_id", None))
            tool_prefix = f"{tenant_id}:tool:"
            if (
                getattr(edge, "from_vertex_id", None) != expected_agent_vertex
                or target_vertex_id is None
                or not target_vertex_id.startswith(tool_prefix)
            ):
                scope_mismatch = True
                continue

            tool_id = _exact_identifier(target_vertex_id[len(tool_prefix):])
            called_at = _safe_timestamp(properties.get("called_at"))
            event_ref = _exact_identifier(
                properties.get("source_event_id") or properties.get("idempotency_key")
            )
            if tool_id is None or called_at is None or event_ref is None:
                scope_mismatch = True
                continue
            try:
                tool_vertex = await graph.get_vertex_for_tenant(tenant_id, target_vertex_id)
            except Exception:  # noqa: BLE001 - unresolved tool identity is omitted
                scope_mismatch = True
                continue
            tool_properties = getattr(tool_vertex, "properties", None)
            if (
                tool_vertex is None
                or getattr(tool_vertex, "vertex_type", None) != "Tool"
                or not isinstance(tool_properties, dict)
                or _exact_identifier(
                    tool_properties.get("tenant_id") or tool_properties.get("tenantId")
                ) != tenant_id
                or _exact_identifier(tool_properties.get("tool_id")) != tool_id
            ):
                scope_mismatch = True
                continue

            evidence = EvidenceRef(
                id=event_ref,
                type="event",
                source="graph_edges",
                observedAt=called_at,
                uri=f"store://graph_edges/{quote(event_ref, safe='')}",
            )
            tool_evidence = EvidenceRef(
                id=target_vertex_id,
                type="entity",
                source="graph_vertices",
                uri=f"store://graph_vertices/{quote(target_vertex_id, safe='')}",
            )
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "workflow_run_id": workflow_run_id,
                    "execution_id": execution_id,
                    "agent_id": expected_agent_id,
                    "tool_id": tool_id,
                    "called_at": called_at,
                    "evidence_ref": evidence.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    "tool_evidence_ref": tool_evidence.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                }
            )

        bounded_limit = min(max(int(limit), 1), _MAX_WORKFLOW_ACTIONS)
        truncated = bool(truncated or len(rows) > bounded_limit)
        rows = rows[:bounded_limit]
        return WorkflowActionRead(
            tuple(rows),
            True,
            not truncated and not scope_mismatch,
            scope_mismatch=scope_mismatch,
            reason=(
                "canonical_workflow_action_graph_scope_mismatch"
                if scope_mismatch
                else "canonical_workflow_action_graph_read_truncated"
                if truncated
                else None
            ),
        )

    async def run_trigger_events(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowTriggerRead:
        """Resolve only explicit trigger event IDs from exact run-linked executions.

        The persisted ``triggered_by_event_id`` field is caller-reported input.
        Resolving it to a tenant analytics event proves that the execution row
        references an event, not that the event caused or initiated the workflow.
        """
        if not tenant_id or not workflow_run_id:
            return WorkflowTriggerRead(
                (),
                False,
                False,
                reason="exact_tenant_workflow_run_scope_required",
                source_read_state="not_read",
            )

        execution_ids_by_event: dict[str, set[str]] = {}
        complete = True
        scope_mismatch = False
        for row in execution_rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("workflow_run_id") != workflow_run_id
            ):
                scope_mismatch = True
                complete = False
                continue
            execution_id = _safe_identifier(row.get("execution_id"))
            raw_event_id = row.get("triggered_by_event_id")
            event_id = _safe_identifier(raw_event_id)
            if execution_id is None:
                complete = False
                continue
            if raw_event_id is None or raw_event_id == "":
                complete = False
                continue
            if event_id is None:
                complete = False
                continue
            execution_ids_by_event.setdefault(event_id, set()).add(execution_id)

        bounded_limit = min(max(int(limit), 1), _MAX_TRIGGER_EVENTS)
        event_ids = sorted(execution_ids_by_event)
        queried_event_ids = event_ids[:bounded_limit]
        if len(queried_event_ids) < len(event_ids):
            complete = False
        if not queried_event_ids:
            return WorkflowTriggerRead(
                (),
                True,
                False,
                scope_mismatch=scope_mismatch,
                reason=(
                    "workflow_execution_trigger_reference_scope_mismatch"
                    if scope_mismatch
                    else "workflow_execution_trigger_reference_not_recorded"
                ),
                source_read_state="available",
            )

        try:
            from dependencies.providers import get_cache
            from repositories.repos import AnalyticsRepository

            analytics = AnalyticsRepository(get_cache())
            resolved: list[dict[str, Any]] = []
            for event_id in queried_event_ids:
                matches = await analytics.query_events(
                    tenant_id,
                    {"event_id": event_id},
                    limit=2,
                )
                if not isinstance(matches, list):
                    return WorkflowTriggerRead(
                        (),
                        False,
                        False,
                        reason="workflow_trigger_event_read_invalid",
                        source_read_state="unavailable",
                    )
                exact = [
                    row
                    for row in matches
                    if isinstance(row, dict)
                    and row.get("tenant_id") == tenant_id
                    and row.get("event_id") == event_id
                ]
                if len(exact) != len(matches):
                    scope_mismatch = True
                    complete = False
                if len(exact) != 1:
                    complete = False
                    continue
                row = exact[0]
                resolved.append(
                    {
                        "tenant_id": tenant_id,
                        "workflow_run_id": workflow_run_id,
                        "event_id": event_id,
                        "event_type": row.get("event_type"),
                        "occurred_at": row.get("occurred_at"),
                        "execution_ids": sorted(execution_ids_by_event[event_id]),
                    }
                )
        except Exception:  # noqa: BLE001 - analytics source details stay private
            return WorkflowTriggerRead(
                (),
                False,
                False,
                reason="workflow_trigger_event_source_unavailable",
                source_read_state="unavailable",
            )

        return WorkflowTriggerRead(
            tuple(resolved),
            True,
            complete and not scope_mismatch,
            scope_mismatch=scope_mismatch,
            reason=(
                "workflow_trigger_event_scope_mismatch"
                if scope_mismatch
                else None
                if complete
                else "workflow_trigger_event_reference_coverage_incomplete"
            ),
            source_read_state="available",
        )

    async def actor_identities(
        self, *, tenant_id: str, agent_ids: set[str], limit: int
    ) -> WorkflowAgentIdentityRead:
        """Resolve invocation agent refs through canonical tenant identity authorities."""
        bounded_ids = {
            value for value in agent_ids if _safe_identifier(value) is not None
        }
        if not tenant_id or not bounded_ids:
            return WorkflowAgentIdentityRead((), True, True)
        try:
            from actions.agent.deployments import get_deployment_repository
            from actions.agent.identity_resolution import resolve_agent_identities
            from actions.agent_marketplace.identity_binding import (
                AgentDeploymentIdentityBindingRepository,
            )
            from repositories.repos import EntityRepository

            result = await resolve_agent_identities(
                tenant_id,
                bounded_ids,
                deployments=get_deployment_repository(),
                identity_bindings=AgentDeploymentIdentityBindingRepository(),
                entities=EntityRepository(),
                limit=min(max(int(limit), 1), _MAX_INVOCATION_FACTS),
            )
        except Exception:  # noqa: BLE001 - source internals must not escape
            return WorkflowAgentIdentityRead(
                (), False, False, reason="canonical_agent_identity_source_unavailable"
            )

        rows = tuple(row for row in result.rows if isinstance(row, dict))
        return WorkflowAgentIdentityRead(
            rows,
            True,
            not result.scope_mismatch and not result.truncated,
            scope_mismatch=result.scope_mismatch,
            reason=(
                "canonical_agent_identity_scope_incomplete"
                if result.scope_mismatch or result.truncated
                else None
            ),
        )

    async def principal_identities(
        self, *, tenant_id: str, principal_user_ids: set[str], limit: int
    ) -> WorkflowPrincipalIdentityRead:
        """Resolve user refs only through active tenant USER_ID identity links."""
        requested = sorted(
            {
                value
                for raw in principal_user_ids
                if (value := _safe_identifier(raw)) is not None
            }
        )
        if not tenant_id or not requested:
            return WorkflowPrincipalIdentityRead((), bool(tenant_id), bool(tenant_id))
        if len(requested) > min(max(int(limit), 1), _MAX_AGENT_EXECUTIONS):
            return WorkflowPrincipalIdentityRead(
                (), True, False, reason="principal_identity_read_truncated"
            )
        try:
            from identity.identity.hashing import hash_value
            from identity.identity.models import IdentitySignalType
            from identity.identity.repository import IdentityResolutionRepository

            repository = (
                self._principal_identity_repository
                or IdentityResolutionRepository()
            )
            rows: list[dict[str, Any]] = []
            complete = True
            for principal_user_id in requested:
                alias_hash = hash_value(principal_user_id, scope=f"user:{tenant_id}")
                aliases = await repository.find_aliases_by_signal(
                    tenant_id,
                    IdentitySignalType.USER_ID,
                    alias_hash,
                    limit=101,
                )
                if not isinstance(aliases, list) or len(aliases) > 100:
                    complete = False
                    continue
                surviving_ids: set[str] = set()
                for alias in aliases:
                    if (
                        not isinstance(alias, dict)
                        or alias.get("tenant_id") != tenant_id
                        or alias.get("alias_type") != IdentitySignalType.USER_ID.value
                        or alias.get("alias_value_hash") != alias_hash
                        or alias.get("revoked_at")
                        or alias.get("confidence_tier") != "deterministic"
                        or not isinstance(alias.get("canonical_entity_id"), str)
                    ):
                        complete = False
                        continue
                    canonical_id = await repository.resolve_surviving_canonical_entity_id(
                        tenant_id, alias["canonical_entity_id"]
                    )
                    subject = await repository.get_subject_by_canonical_entity_id(
                        tenant_id, canonical_id
                    )
                    if (
                        not isinstance(subject, dict)
                        or subject.get("tenant_id") != tenant_id
                        or subject.get("canonical_entity_id") != canonical_id
                        or subject.get("entity_type") != "human"
                        or subject.get("status") != "active"
                    ):
                        complete = False
                        continue
                    alias_id = _safe_identifier(alias.get("id"))
                    subject_id = _safe_identifier(subject.get("id"))
                    if alias_id is None or subject_id is None:
                        complete = False
                        continue
                    surviving_ids.add(canonical_id)
                    rows.append(
                        {
                            "tenant_id": tenant_id,
                            "principal_user_id": principal_user_id,
                            "canonical_human_entity_id": canonical_id,
                            "identity_evidence_refs": [
                                EvidenceRef(
                                    id=alias_id,
                                    type="entity",
                                    source="identity_aliases",
                                    observedAt=_safe_timestamp(
                                        alias.get("last_seen_at") or alias.get("updated_at")
                                    ),
                                ).model_dump(
                                    mode="json", by_alias=True, exclude_none=True
                                ),
                                EvidenceRef(
                                    id=subject_id,
                                    type="entity",
                                    source="identity_subjects",
                                    observedAt=_safe_timestamp(
                                        subject.get("last_seen_at") or subject.get("updated_at")
                                    ),
                                ).model_dump(
                                    mode="json", by_alias=True, exclude_none=True
                                ),
                            ],
                        }
                    )
                if len(surviving_ids) > 1:
                    complete = False
            return WorkflowPrincipalIdentityRead(
                tuple(rows),
                True,
                complete,
                reason=None if complete else "principal_identity_scope_or_subject_mismatch",
            )
        except Exception:  # noqa: BLE001 - identity outage remains unknown
            return WorkflowPrincipalIdentityRead(
                (), False, False, reason="canonical_human_identity_source_unavailable"
            )

    async def run_execution_approvals(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowApprovalRead:
        """Read only approval records exactly referenced by run-linked executions."""
        admitted = {
            execution_id
            for row in execution_rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("workflow_run_id") == workflow_run_id
            and (execution_id := _safe_identifier(row.get("execution_id"))) is not None
        }
        if not admitted:
            return WorkflowApprovalRead((), True, True)
        try:
            from value.x402.commerce_store import get_commerce_store

            store = get_commerce_store()
            result: list[dict[str, Any]] = []
            complete = True
            for row in execution_rows:
                if not isinstance(row, dict):
                    complete = False
                    continue
                execution_id = _safe_identifier(row.get("execution_id"))
                approval_id = _safe_identifier(row.get("approval_id"))
                decision_id = _safe_identifier(row.get("approval_decision_id"))
                if not approval_id and not decision_id:
                    continue
                if (
                    execution_id not in admitted
                    or approval_id is None
                    or decision_id is None
                ):
                    complete = False
                    continue
                approval = await store.get_approval(tenant_id, approval_id)
                decision = await store.get_approval_decision(tenant_id, decision_id)
                approval_data = _model_or_dict(approval)
                decision_data = _model_or_dict(decision)
                if (
                    approval_data is None
                    or decision_data is None
                    or approval_data.get("tenant_id") != tenant_id
                    or approval_data.get("approval_id") != approval_id
                    or approval_data.get("execution_id") != execution_id
                    or decision_data.get("tenant_id") != tenant_id
                    or decision_data.get("decision_id") != decision_id
                    or decision_data.get("approval_id") != approval_id
                    or decision_data.get("execution_id") != execution_id
                    or decision_data.get("action") not in _APPROVAL_DECISION_ACTIONS
                    or not _safe_identifier(decision_data.get("decided_by"))
                ):
                    complete = False
                    continue
                result.append(
                    {
                        "tenant_id": tenant_id,
                        "workflow_run_id": workflow_run_id,
                        "execution_id": execution_id,
                        "approval_id": approval_id,
                        "decision_id": decision_id,
                        "action": decision_data["action"],
                        "requester_id": approval_data.get("requester_id"),
                        "requester_type": approval_data.get("requester_type"),
                        "execution_action": approval_data.get("execution_action"),
                        "resource_id": approval_data.get("resource_id"),
                        "approved_amount_usd": approval_data.get("amount_usd"),
                        "decided_by": decision_data["decided_by"],
                        "decided_at": decision_data.get("decided_at"),
                        **(
                            {"permission_receipt": decision_data["permission_receipt"]}
                            if decision_data.get("permission_receipt") is not None else {}
                        ),
                    }
                )
            return WorkflowApprovalRead(
                tuple(result),
                True,
                complete,
                reason=None if complete else "canonical_execution_approval_link_incomplete",
            )
        except Exception:  # noqa: BLE001 - approval outage remains unknown
            return WorkflowApprovalRead(
                (), False, False, reason="canonical_execution_approval_source_unavailable"
            )

    async def run_execution_risk_assessments(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowRiskAssessmentRead:
        """Read Risk360 snapshots only for exact tenant/run-linked executions.

        AgentExecution rows are independently admitted by the provider after
        verifying their stored invocation IDs and action IDs against this
        tenant's invocation facts. This adapter keeps the next join exact at
        both boundaries: workflow_run_id -> execution_id -> RiskAssessment's
        execution subject. The assessment is association evidence, not proof
        that the workflow caused the recorded risk.
        """
        if not tenant_id or not workflow_run_id:
            return WorkflowRiskAssessmentRead(
                (),
                False,
                False,
                reason="exact_tenant_workflow_run_scope_required",
            )

        execution_ids: list[str] = []
        scope_mismatch = False
        for row in execution_rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("workflow_run_id") != workflow_run_id
            ):
                scope_mismatch = True
                continue
            execution_id = _safe_identifier(row.get("execution_id"))
            if execution_id is None or execution_id in execution_ids:
                scope_mismatch = True
                continue
            execution_ids.append(execution_id)

        if not execution_ids:
            return WorkflowRiskAssessmentRead(
                (),
                True,
                not scope_mismatch,
                scope_mismatch=scope_mismatch,
                reason=(
                    "unscoped_or_duplicate_workflow_execution_rows_dropped"
                    if scope_mismatch
                    else None
                ),
            )

        bounded_limit = min(max(int(limit), 1), _MAX_WORKFLOW_RISK_ASSESSMENTS)
        query_ids = execution_ids[:_MAX_WORKFLOW_RISK_ASSESSMENTS]
        truncated = len(query_ids) < len(execution_ids)
        per_subject_limit = max(1, bounded_limit // len(query_ids))
        exact_rows: list[dict[str, Any]] = []
        try:
            from intelligence.risk360.store import RiskAssessmentRepository

            repository = RiskAssessmentRepository()
            for execution_id in query_ids:
                rows = await repository.list_by_subject(
                    tenant_id,
                    "execution",
                    execution_id,
                    limit=per_subject_limit + 1,
                )
                if not isinstance(rows, list):
                    return WorkflowRiskAssessmentRead(
                        (),
                        False,
                        False,
                        scope_mismatch=scope_mismatch,
                        reason="canonical_execution_risk_assessment_read_invalid",
                    )
                if len(rows) > per_subject_limit:
                    truncated = True
                for row in rows[:per_subject_limit]:
                    if (
                        not isinstance(row, dict)
                        or row.get("tenant_id") != tenant_id
                        or row.get("subject_kind") != "execution"
                        or row.get("subject_id") != execution_id
                    ):
                        scope_mismatch = True
                        continue
                    exact_rows.append(
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"id", "created_at", "updated_at"}
                        }
                    )
        except Exception:  # noqa: BLE001 - canonical source failure remains explicit
            return WorkflowRiskAssessmentRead(
                (),
                False,
                False,
                scope_mismatch=scope_mismatch,
                reason="canonical_execution_risk_assessment_source_unavailable",
            )

        if len(exact_rows) > bounded_limit:
            exact_rows = exact_rows[:bounded_limit]
            truncated = True
        return WorkflowRiskAssessmentRead(
            tuple(exact_rows),
            True,
            not truncated and not scope_mismatch,
            scope_mismatch=scope_mismatch,
            reason=(
                "canonical_execution_risk_assessment_scope_mismatch"
                if scope_mismatch
                else "canonical_execution_risk_assessment_read_truncated"
                if truncated
                else None
            ),
        )

    async def run_linked_outcomes(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        invocation_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowOutcomeRead:
        """Resolve only exact outcome IDs referenced by this tenant/run's AI facts.

        The invocation-to-outcome reference establishes association only. The
        canonical outcome record supplies the outcome state and its independent
        evidence lineage; this reader never infers workflow causation.
        """
        if not tenant_id or not workflow_run_id:
            return WorkflowOutcomeRead(
                (), False, False, reason="exact_tenant_workflow_run_scope_required"
            )

        invocation_ids_by_outcome: dict[str, set[str]] = {}
        complete = True
        scope_mismatch = False
        for row in invocation_rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("workflow_run_id") != workflow_run_id
            ):
                complete = False
                scope_mismatch = True
                continue
            invocation_id = _safe_identifier(row.get("invocation_id"))
            raw_outcome_id = row.get("outcome_id")
            if invocation_id is None:
                complete = False
                continue
            if raw_outcome_id is None or raw_outcome_id == "":
                continue
            outcome_id = _safe_identifier(raw_outcome_id)
            if outcome_id is None:
                complete = False
                continue
            invocation_ids_by_outcome.setdefault(outcome_id, set()).add(invocation_id)

        bounded_limit = min(max(int(limit), 1), _MAX_WORKFLOW_OUTCOMES)
        outcome_ids = sorted(invocation_ids_by_outcome)
        queried_ids = outcome_ids[:bounded_limit]
        truncated = len(queried_ids) < len(outcome_ids)
        if not queried_ids:
            return WorkflowOutcomeRead(
                (), True, complete, scope_mismatch=scope_mismatch,
                reason=None if complete else "canonical_outcome_reference_read_incomplete",
            )
        try:
            from shared.backend_interpretation.flags import outcome_truth_store_enabled

            if not outcome_truth_store_enabled():
                return WorkflowOutcomeRead(
                    (), False, False, reason="canonical_outcome_truth_store_disabled"
                )
            store = self._outcome_truth_store
            if store is None:
                from shared.backend_interpretation.stores import OutcomeTruthStore

                store = OutcomeTruthStore()
            rows: list[dict[str, Any]] = []
            for outcome_id in queried_ids:
                record = await store.get(tenant_id, outcome_id)
                if record is None:
                    complete = False
                    continue
                data = _model_or_dict(record)
                if (
                    not isinstance(data, dict)
                    or data.get("tenant_id") != tenant_id
                    or data.get("outcome_id") != outcome_id
                ):
                    complete = False
                    scope_mismatch = True
                    continue
                rows.append(
                    {
                        "tenant_id": tenant_id,
                        "workflow_run_id": workflow_run_id,
                        "outcome_id": outcome_id,
                        "invocation_ids": sorted(invocation_ids_by_outcome[outcome_id]),
                        "outcome_record": data,
                    }
                )
        except Exception:  # noqa: BLE001 - optional canonical source failure stays unknown
            return WorkflowOutcomeRead(
                (), False, False, reason="canonical_outcome_truth_source_unavailable"
            )

        return WorkflowOutcomeRead(
            tuple(rows),
            True,
            complete and not truncated and not scope_mismatch,
            scope_mismatch=scope_mismatch,
            reason=(
                "canonical_outcome_truth_scope_mismatch"
                if scope_mismatch
                else "canonical_outcome_reference_read_incomplete"
                if not complete or truncated
                else None
            ),
        )


def _definition_as_of_anchor(
    request: ProjectionRequest, context: ProjectionContext
) -> tuple[Optional[datetime], Optional[str]]:
    """Accept only one unambiguous point-in-time definition request."""
    historical = bool(
        request.asOf is not None
        or context.asOf is not None
        or request.timeRange is not None
        or request.temporalMode in {"as_of", "compare", "relative"}
    )
    if not historical:
        return None, None
    if request.timeRange is not None or request.temporalMode in {"compare", "relative"}:
        return None, "workflow_definition_window_or_comparison_replay_not_supported"
    raw_anchors = [value for value in (request.asOf, context.asOf) if value is not None]
    if not raw_anchors:
        return None, "workflow_definition_as_of_anchor_required"
    parsed: list[datetime] = []
    for value in raw_anchors:
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return None, "workflow_definition_as_of_anchor_invalid"
        if instant.tzinfo is None or instant.utcoffset() is None:
            return None, "workflow_definition_as_of_anchor_invalid"
        parsed.append(instant.astimezone(timezone.utc))
    if any(value != parsed[0] for value in parsed[1:]):
        return None, "workflow_definition_as_of_anchor_mismatch"
    return parsed[0], None


class Workflow360Provider:
    """Tenant-safe projection for the current Workflow360 evidence contract."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, *, source: Optional[Workflow360Source] = None) -> None:
        self._source = source or RepositoryWorkflow360Source()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        tenant_id = request.tenantId
        if context.tenantId != tenant_id or context.projectionId != self.projection_id:
            raise ValueError("Workflow360 request and projection context scope must match")

        subject = request.subject
        summary_requested = (
            request.includeSections is None or "workflow_summary" in request.includeSections
        )
        definition_read = WorkflowDefinitionRead(reason="workflow_summary_slot_not_requested")
        definition_historical = bool(
            request.asOf is not None
            or context.asOf is not None
            or request.timeRange is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        )
        definition_anchor, definition_anchor_reason = _definition_as_of_anchor(
            request, context
        )
        if summary_requested and subject.kind in {
            "workflow",
            "automation",
            "automation_id",
        }:
            if definition_historical and definition_anchor_reason:
                definition_read = WorkflowDefinitionRead(
                    reason=definition_anchor_reason
                )
            else:
                reader_name = (
                    "workflow_definition_as_of"
                    if definition_historical
                    else "workflow_definition"
                )
                definition_reader = getattr(self._source, reader_name, None)
                if definition_reader is None:
                    definition_read = WorkflowDefinitionRead(
                        reason="workflow_definition_source_unavailable"
                    )
                else:
                    try:
                        reader_args: dict[str, Any] = {
                            "tenant_id": tenant_id,
                            "workflow_id": subject.id,
                        }
                        if definition_historical:
                            reader_args["as_of"] = definition_anchor
                        definition_read = await definition_reader(**reader_args)
                    except Exception:  # noqa: BLE001 - definition source remains unknown
                        definition_read = WorkflowDefinitionRead(
                            reason="workflow_definition_source_unavailable"
                        )
        elif summary_requested and subject.kind in _RUN_SUBJECT_KINDS:
            definition_read = WorkflowDefinitionRead(
                reason="workflow_run_has_no_exact_workflow_definition_id_link"
            )
        elif summary_requested:
            definition_read = WorkflowDefinitionRead(
                reason="workflow_definition_subject_kind_not_supported"
            )

        read: Optional[WorkflowRunInvocationRead] = None
        if subject.kind in _RUN_SUBJECT_KINDS:
            try:
                read = await self._source.run_invocations(
                    tenant_id=tenant_id,
                    workflow_run_id=subject.id,
                    limit=_MAX_INVOCATION_FACTS,
                )
            except Exception:  # noqa: BLE001 - source diagnostics stay private
                read = WorkflowRunInvocationRead(
                    (), False, False, "ai_execution_fact_repository_unavailable"
                )

        rows, scope_mismatch = _scoped_rows(
            read.rows if read is not None else (),
            tenant_id=tenant_id,
            workflow_run_id=subject.id if subject.kind in _RUN_SUBJECT_KINDS else None,
        )
        read_available = bool(read is not None and read.available)
        read_complete = bool(
            read is not None and read.available and read.complete and not scope_mismatch
        )
        read_reason = (
            "unscoped_or_invalid_ai_execution_facts_dropped"
            if scope_mismatch
            else _safe_reason(read.reason)
            if read is not None
            else "subject_kind_not_supported_by_workflow_run_evidence"
        )
        refs = [_invocation_evidence(row) for row in rows]
        valid_refs = [ref for ref in refs if ref is not None]
        records = [_public_invocation(row) for row in rows]

        reported_agent_ids = {
            agent_id
            for row in rows
            if (agent_id := _safe_identifier(row.get("agent_id"))) is not None
        }
        if reported_agent_ids:
            try:
                actor_identity_read = await self._source.actor_identities(
                    tenant_id=tenant_id,
                    agent_ids=reported_agent_ids,
                    limit=_MAX_INVOCATION_FACTS,
                )
            except Exception:  # noqa: BLE001 - source diagnostics stay private
                actor_identity_read = WorkflowAgentIdentityRead(
                    (), False, False, reason="canonical_agent_identity_source_unavailable"
                )
        else:
            actor_identity_read = WorkflowAgentIdentityRead((), True, True)
        if subject.kind in _RUN_SUBJECT_KINDS:
            try:
                agent_execution_read = await self._source.run_agent_executions(
                    tenant_id=tenant_id,
                    workflow_run_id=subject.id,
                    limit=_MAX_AGENT_EXECUTIONS,
                )
            except Exception:  # noqa: BLE001 - source diagnostics stay private
                agent_execution_read = WorkflowAgentExecutionRead(
                    (),
                    False,
                    False,
                    reason="canonical_agent_execution_repository_unavailable",
                )
        else:
            agent_execution_read = WorkflowAgentExecutionRead(
                (),
                False,
                False,
                reason="subject_kind_not_supported_by_workflow_run_evidence",
            )
        agent_execution_rows, agent_execution_scope_mismatch = (
            _scoped_agent_execution_rows(
                agent_execution_read.rows,
                tenant_id=tenant_id,
                workflow_run_id=(
                    subject.id if subject.kind in _RUN_SUBJECT_KINDS else None
                ),
                invocation_by_id={
                    invocation_id: row
                    for row in rows
                    if (invocation_id := _safe_identifier(row.get("invocation_id")))
                    is not None
                },
            )
        )
        agent_execution_read_complete = bool(
            agent_execution_read.available
            and agent_execution_read.complete
            and not agent_execution_read.scope_mismatch
            and not agent_execution_scope_mismatch
        )
        agent_execution_refs = [
            ref
            for row in agent_execution_rows
            if (ref := _agent_execution_evidence(row)) is not None
        ]
        actions_requested = (
            request.includeSections is None or "actions" in request.includeSections
        )
        historical_action_scope = bool(
            request.asOf is not None
            or context.asOf is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        )
        if not actions_requested:
            action_read = WorkflowActionRead(
                (), False, False, reason="workflow_action_slot_not_requested"
            )
        elif historical_action_scope:
            action_read = WorkflowActionRead(
                (), False, False, reason="workflow_action_historical_state_unavailable"
            )
        elif subject.kind not in _RUN_SUBJECT_KINDS:
            action_read = WorkflowActionRead(
                (), False, False, reason="subject_kind_not_supported_by_workflow_run_evidence"
            )
        elif not agent_execution_rows:
            action_read = WorkflowActionRead(
                (), False, False,
                reason=(
                    _safe_reason(agent_execution_read.reason)
                    or "no_admitted_run_linked_execution_for_action_join"
                ),
            )
        else:
            action_reader = getattr(self._source, "run_execution_actions", None)
            if action_reader is None:
                action_read = WorkflowActionRead(
                    (), False, False, reason="canonical_workflow_action_source_unavailable"
                )
            else:
                try:
                    action_read = await action_reader(
                        tenant_id=tenant_id,
                        workflow_run_id=subject.id,
                        execution_rows=tuple(agent_execution_rows),
                        limit=_MAX_WORKFLOW_ACTIONS,
                    )
                except Exception:  # noqa: BLE001 - graph source details stay private
                    action_read = WorkflowActionRead(
                        (), False, False,
                        reason="canonical_workflow_action_source_unavailable",
                    )
        historical_trigger_scope = bool(
            request.asOf is not None
            or context.asOf is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        )
        if historical_trigger_scope:
            trigger_read = WorkflowTriggerRead(
                (),
                False,
                False,
                reason="workflow_trigger_historical_state_unavailable",
                source_read_state="not_read",
            )
        elif subject.kind in _RUN_SUBJECT_KINDS:
            try:
                trigger_read = await self._source.run_trigger_events(
                    tenant_id=tenant_id,
                    workflow_run_id=subject.id,
                    execution_rows=tuple(agent_execution_rows),
                    limit=_MAX_TRIGGER_EVENTS,
                )
            except Exception:  # noqa: BLE001 - event source details stay private
                trigger_read = WorkflowTriggerRead(
                    (),
                    False,
                    False,
                    reason="workflow_trigger_event_source_unavailable",
                    source_read_state="unavailable",
                )
        else:
            trigger_read = WorkflowTriggerRead(
                (),
                False,
                False,
                reason="subject_kind_not_supported_by_workflow_run_evidence",
                source_read_state="not_read",
            )
        outcome_requested = (
            request.includeSections is None or "outcomes" in request.includeSections
        )
        historical_outcome_scope = bool(
            request.asOf is not None
            or context.asOf is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        )
        if not outcome_requested:
            outcome_read = WorkflowOutcomeRead(
                (), False, False, reason="workflow_outcome_slot_not_requested"
            )
        elif historical_outcome_scope:
            outcome_read = WorkflowOutcomeRead(
                (), False, False, reason="workflow_outcome_historical_state_unavailable"
            )
        elif subject.kind in _RUN_SUBJECT_KINDS and rows:
            try:
                outcome_read = await self._source.run_linked_outcomes(
                    tenant_id=tenant_id,
                    workflow_run_id=subject.id,
                    invocation_rows=tuple(rows),
                    limit=_MAX_WORKFLOW_OUTCOMES,
                )
            except Exception:  # noqa: BLE001 - optional canonical source stays unknown
                outcome_read = WorkflowOutcomeRead(
                    (), False, False, reason="canonical_outcome_truth_source_unavailable"
                )
        elif subject.kind in _RUN_SUBJECT_KINDS:
            outcome_read = WorkflowOutcomeRead(
                (), read_available, read_complete,
                reason=("workflow_run_invocation_outcome_references_not_recorded"
                        if read_complete else read_reason),
            )
        else:
            outcome_read = WorkflowOutcomeRead(
                (), False, False,
                reason="subject_kind_not_supported_by_workflow_run_evidence",
            )
        outcome_rows, outcome_scope_mismatch, outcome_join_incomplete = _scoped_linked_outcome_rows(
            outcome_read.rows,
            tenant_id=tenant_id,
            workflow_run_id=subject.id if subject.kind in _RUN_SUBJECT_KINDS else None,
            invocation_rows=rows,
        )
        outcome_read_complete = bool(
            outcome_read.available
            and outcome_read.complete
            and not outcome_read.scope_mismatch
            and not outcome_scope_mismatch
            and not outcome_join_incomplete
            and read_complete
        )
        if subject.kind in _RUN_SUBJECT_KINDS:
            try:
                approval_read = await self._source.run_execution_approvals(
                    tenant_id=tenant_id,
                    workflow_run_id=subject.id,
                    execution_rows=tuple(agent_execution_rows),
                    limit=_MAX_AGENT_EXECUTIONS,
                )
            except Exception:  # noqa: BLE001 - source diagnostics stay private
                approval_read = WorkflowApprovalRead(
                    (), False, False, reason="canonical_execution_approval_source_unavailable"
                )
        else:
            approval_read = WorkflowApprovalRead(
                (), False, False, reason="subject_kind_not_supported_by_workflow_run_evidence"
            )
        approval_rows, approval_scope_mismatch = _scoped_approval_rows(
            approval_read.rows,
            tenant_id=tenant_id,
            workflow_run_id=subject.id if subject.kind in _RUN_SUBJECT_KINDS else None,
            execution_rows=agent_execution_rows,
        )
        approval_read_complete = bool(
            approval_read.available
            and approval_read.complete
            and not approval_read.scope_mismatch
            and not approval_scope_mismatch
        )
        from actions.agent.action_associations import action_association_read_authorized
        from intelligence.workflow.approval_agent_access import read_approval_agent_access

        approval_agent_access_rows: list[dict[str, Any]] = []
        action_agent_access_rows: list[dict[str, Any]] = []
        approval_access_allowed = action_association_read_authorized(
            request, context, surface="workflow360", slot="approvals", consumer="workflow360"
        )
        action_access_allowed = action_association_read_authorized(
            request, context, surface="workflow360", slot="actions", consumer="workflow360"
        )
        if (approval_rows and subject.kind in _RUN_SUBJECT_KINDS
                and request.asOf is None and context.asOf is None
                and request.temporalMode not in {"as_of", "compare", "relative"}
                and ((approval_access_allowed and (request.includeSections is None or "approvals" in request.includeSections))
                     or (action_access_allowed and (request.includeSections is None or "actions" in request.includeSections)))):
            try:
                access_read = await read_approval_agent_access(
                    tenant_id=tenant_id, workflow_run_id=subject.id,
                    executions=agent_execution_rows, approvals=approval_rows,
                )
                if access_read.available:
                    if approval_access_allowed:
                        approval_agent_access_rows = list(access_read.rows)
                    if action_access_allowed:
                        action_agent_access_rows = list(access_read.rows)
            except Exception:  # noqa: BLE001 - access evidence fails closed independently
                pass
        risk_requested = (
            request.includeSections is None or "risk" in request.includeSections
        )
        historical_risk_scope = bool(
            request.asOf is not None
            or context.asOf is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        )
        if not risk_requested:
            risk_read = WorkflowRiskAssessmentRead(
                (), False, False, reason="workflow_risk_slot_not_requested"
            )
        elif historical_risk_scope:
            risk_read = WorkflowRiskAssessmentRead(
                (), False, False, reason="workflow_risk_historical_state_unavailable"
            )
        elif subject.kind in _RUN_SUBJECT_KINDS and agent_execution_rows:
            risk_reader = getattr(self._source, "run_execution_risk_assessments", None)
            if risk_reader is None:
                risk_read = WorkflowRiskAssessmentRead(
                    (),
                    False,
                    False,
                    reason="canonical_execution_risk_assessment_source_unavailable",
                )
            else:
                try:
                    risk_read = await risk_reader(
                        tenant_id=tenant_id,
                        workflow_run_id=subject.id,
                        execution_rows=tuple(agent_execution_rows),
                        limit=_MAX_WORKFLOW_RISK_ASSESSMENTS,
                    )
                except Exception:  # noqa: BLE001 - optional canonical source stays unknown
                    risk_read = WorkflowRiskAssessmentRead(
                        (),
                        False,
                        False,
                        reason="canonical_execution_risk_assessment_source_unavailable",
                    )
        elif subject.kind in _RUN_SUBJECT_KINDS:
            risk_read = WorkflowRiskAssessmentRead(
                (),
                False,
                False,
                reason=(
                    "no_admitted_run_linked_agent_execution_for_risk_join"
                    if agent_execution_read.available
                    else _safe_reason(agent_execution_read.reason)
                    or "canonical_agent_execution_repository_unavailable"
                ),
            )
        else:
            risk_read = WorkflowRiskAssessmentRead(
                (), False, False, reason="subject_kind_not_supported_by_workflow_run_evidence"
            )
        principal_user_ids = {
            principal_id
            for row in agent_execution_rows
            if (principal_id := _safe_identifier(row.get("initiating_principal_user_id")))
            is not None
        }
        principal_user_ids.update(
            principal_id
            for row in approval_rows
            if (principal_id := _safe_identifier(row.get("decided_by"))) is not None
        )
        if principal_user_ids:
            try:
                principal_identity_read = await self._source.principal_identities(
                    tenant_id=tenant_id,
                    principal_user_ids=principal_user_ids,
                    limit=_MAX_AGENT_EXECUTIONS,
                )
            except Exception:  # noqa: BLE001 - source diagnostics stay private
                principal_identity_read = WorkflowPrincipalIdentityRead(
                    (), False, False, reason="canonical_human_identity_source_unavailable"
                )
        else:
            principal_identity_read = WorkflowPrincipalIdentityRead((), True, True)
        actor_section, actor_claims = _actors_section(
            subject,
            tenant_id=tenant_id,
            invocation_rows=rows,
            invocation_refs=valid_refs,
            requested_agent_ids=reported_agent_ids,
            identity_read=actor_identity_read,
            execution_rows=agent_execution_rows,
            execution_refs=agent_execution_refs,
            approval_rows=approval_rows,
            principal_identity_read=principal_identity_read,
        )
        approvals_section, approval_claims = _approvals_section(
            subject,
            tenant_id=tenant_id,
            approval_rows=approval_rows,
            execution_refs=agent_execution_refs,
            available=approval_read.available,
            complete=approval_read_complete,
            reason=(
                "unscoped_or_invalid_execution_approval_rows_dropped"
                if approval_scope_mismatch or approval_read.scope_mismatch
                else _safe_reason(approval_read.reason)
            ),
            principal_identity_read=principal_identity_read,
            agent_access_rows=approval_agent_access_rows,
        )
        agent_steps_section, agent_step_claims = _agent_steps_section(
            subject,
            tenant_id=tenant_id,
            rows=agent_execution_rows,
            refs=agent_execution_refs,
            invocation_refs=valid_refs,
            available=agent_execution_read.available,
            complete=agent_execution_read_complete,
            reason=(
                "unscoped_or_invalid_agent_execution_rows_dropped"
                if agent_execution_scope_mismatch or agent_execution_read.scope_mismatch
                else _safe_reason(agent_execution_read.reason)
            ),
        )
        triggers_section, trigger_claims, trigger_evidence_refs = _triggers_section(
            subject,
            tenant_id=tenant_id,
            execution_rows=agent_execution_rows,
            execution_refs=agent_execution_refs,
            read=trigger_read,
            time_range=request.timeRange,
        )
        outcomes_section, outcome_claims = _linked_outcomes_section(
            subject,
            tenant_id=tenant_id,
            invocation_rows=rows,
            invocation_refs=valid_refs,
            outcome_rows=outcome_rows,
            available=outcome_read.available,
            complete=outcome_read_complete,
            reason=(
                _safe_reason(outcome_read.reason)
                if not outcome_read.available
                else "unscoped_or_invalid_canonical_outcome_rows_dropped"
                if outcome_scope_mismatch or outcome_read.scope_mismatch
                else "canonical_outcome_reference_join_incomplete"
                if outcome_join_incomplete
                else _safe_reason(outcome_read.reason)
            ),
            time_range=request.timeRange,
        )
        risk_section, risk_claims = _workflow_risk_section(
            subject,
            tenant_id=tenant_id,
            read=risk_read,
            execution_rows=agent_execution_rows,
            execution_refs=agent_execution_refs,
            execution_inventory_complete=agent_execution_read_complete,
            time_range=request.timeRange,
            requested=risk_requested,
            historical=historical_risk_scope,
            subject_supported=subject.kind in _RUN_SUBJECT_KINDS,
        )
        from intelligence.workflow.action_authorities import approved_resources

        commerce_authorized = (action_access_allowed and context.tenantId == tenant_id
            and context.projectionId == "workflow360" and any(
                auth.tenantId == tenant_id and auth.sourceSurfaceId == "workflow360"
                and auth.sourceSubject == subject and auth.sourceSlotId == "actions"
                and auth.consumerProjectionId == "workflow360" and auth.targetProjectionId == "commerce360"
                and auth.capabilityKey == "commerce360.read" and auth.policyState == "allowed"
                and bool(auth.policyIds) and bool(auth.policyEvaluatedAt)
                for auth in context.experience360ReadAuthorizations))
        resource_rows: list[dict[str, str]] = []
        if commerce_authorized and not historical_action_scope and actions_requested and action_agent_access_rows:
            try:
                resource_rows = await approved_resources(tenant_id=tenant_id, workflow_run_id=subject.id,
                                                         access_rows=action_agent_access_rows)
            except Exception:  # noqa: BLE001 - resource authority remains unknown
                pass
        actions_section, action_claims = _workflow_actions_section(
            subject,
            tenant_id=tenant_id,
            read=action_read,
            execution_rows=agent_execution_rows,
            execution_refs=agent_execution_refs,
            execution_inventory_complete=agent_execution_read_complete,
            time_range=request.timeRange,
            requested=actions_requested,
            historical=historical_action_scope,
            execution_results_authorized=action_access_allowed,
            resource_rows=resource_rows,
        )
        registrar_identity_read = WorkflowPrincipalIdentityRead(
            (), False, False, reason="definition_registrar_identity_not_read"
        )
        if (
            summary_requested
            and subject.kind in {"workflow", "automation", "automation_id"}
            and not definition_historical
            and definition_read.available
            and definition_read.complete
            and not definition_read.reason
            and len(definition_read.rows) == 1
            and isinstance(definition_read.rows[0], dict)
        ):
            actor_ref = _safe_identifier(definition_read.rows[0].get("actor_ref"))
            if actor_ref is not None:
                reader = getattr(self._source, "principal_identities", None)
                if reader is not None:
                    try:
                        registrar_identity_read = await reader(
                            tenant_id=tenant_id,
                            principal_user_ids={actor_ref},
                            limit=1,
                        )
                    except Exception:  # noqa: BLE001 - identity outage stays unknown
                        registrar_identity_read = WorkflowPrincipalIdentityRead(
                            (), False, False, reason="definition_registrar_identity_unavailable"
                        )
        if subject.kind in _RUN_SUBJECT_KINDS:
            workflow_summary_section, workflow_summary_claims = (
                await _workflow_run_definition_summary(
                    source=self._source,
                    subject=subject,
                    tenant_id=tenant_id,
                    execution_rows=agent_execution_rows,
                    invocation_rows=rows,
                    invocation_read_complete=read_complete,
                    execution_read_complete=agent_execution_read_complete,
                    requested=summary_requested,
                    historical=definition_historical,
                )
            )
        else:
            workflow_summary_section, workflow_summary_claims = _workflow_summary_section(
                subject,
                tenant_id=tenant_id,
                read=definition_read,
                requested=summary_requested,
                historical_anchor=definition_anchor if definition_historical else None,
                registrar_identity_read=registrar_identity_read,
            )

        if records and read_complete:
            run_state = "available"
            run_warnings = None
        elif records:
            run_state = "degraded"
            run_warnings = [read_reason or "workflow run evidence is incomplete"]
        else:
            # No invocation facts are not proof that a workflow run is absent;
            # the AI telemetry feed is only one optional evidence source.
            run_state = "unknown"
            run_warnings = [read_reason or "workflow run authority is not connected"]

        run_content: dict[str, Any] = {
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "source": _SOURCE,
            "evidenceScope": "AI invocation facts with an exact workflow_run_id match",
            "workflowRunState": "unknown",
            "aiInvocationRecords": records,
            "scopeState": "complete_for_ai_invocation_feed" if read_complete else "partial_or_unknown",
            "workflowRunAuthorityState": "unknown",
            "freshness": {
                "state": "unknown",
                "latestReturnedObservedAt": _latest_returned_observed_at(records),
                "evidenceReadComplete": read_complete,
                "thresholdSeconds": None,
                "freshnessAuthorityState": "unknown",
                "reasonCode": "workflow_run_freshness_threshold_not_configured",
                "evidenceScope": "exactly linked AI invocation facts returned by this bounded read",
            },
        }
        if read_available:
            run_content["returnedAiInvocationCount"] = len(records)
        if read_complete and records:
            run_content["aiInvocationCount"] = len(records)
        else:
            run_content["reasonCode"] = read_reason or "workflow_run_authority_not_available"

        claims = [
            ClaimEnvelope(
                id=f"workflow360.ai_invocation.{record['invocationId']}",
                kind="ai_invocation_record_linked_to_workflow_run",
                subject=subject,
                evidenceRefs=[evidence],
                claims=[
                    "A tenant-scoped AI invocation fact explicitly records the requested workflow_run_id; this does not establish a complete workflow trace or business outcome."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["runs", "evidence_trace"],
            )
            for record, evidence in zip(records, valid_refs)
        ]
        claims.extend(trigger_claims)
        claims.extend(actor_claims)
        claims.extend(approval_claims)
        claims.extend(agent_step_claims)
        claims.extend(action_claims)
        claims.extend(outcome_claims)
        claims.extend(risk_claims)
        claims.extend(workflow_summary_claims)

        sections: list[ProjectionSection] = [
            workflow_summary_section,
            triggers_section,
            ProjectionSection(
                id="runs",
                state=run_state,
                title="Workflow run evidence",
                content=run_content,
                warnings=run_warnings,
                canonicalAuthorityRefs=[_SOURCE],
            ),
            actor_section,
            approvals_section,
            agent_steps_section,
            actions_section,
            _failure_section(
                subject,
                tenant_id=tenant_id,
                records=records,
                refs=valid_refs,
                available=read_available,
                complete=read_complete,
                reason=read_reason,
            ),
            outcomes_section,
            risk_section,
            _evidence_trace_section(
                subject,
                tenant_id=tenant_id,
                refs=valid_refs,
                agent_execution_refs=agent_execution_refs,
                available=read_available,
                complete=read_complete,
                agent_execution_available=agent_execution_read.available,
                agent_execution_complete=agent_execution_read_complete,
                trigger_refs=trigger_evidence_refs,
                trigger_available=trigger_read.source_read_state == "available",
                reason=read_reason,
            ),
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=(
                request.asOf or context.asOf
                if definition_historical
                and definition_anchor is not None
                and subject.kind in {"workflow", "automation", "automation_id"}
                and definition_read.available
                and definition_read.complete
                and not definition_read.reason
                else None
            ),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
        )


async def _workflow_run_definition_summary(
    *,
    source: Workflow360Source,
    subject: Any,
    tenant_id: str,
    execution_rows: list[dict[str, Any]],
    invocation_rows: list[dict[str, Any]],
    invocation_read_complete: bool,
    execution_read_complete: bool,
    requested: bool,
    historical: bool,
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Validate only a caller-reported run association against exact authorities."""

    def unknown(reason: str) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        return _unknown_section_with_reason("workflow_summary", reason), []

    if not requested:
        return unknown("workflow_summary_slot_not_requested")
    if historical:
        return unknown("workflow_run_definition_historical_replay_unavailable")
    if not invocation_read_complete or not execution_read_complete:
        return unknown("workflow_run_definition_execution_inventory_incomplete")
    if not execution_rows:
        return unknown("workflow_run_has_no_exact_workflow_definition_id_link")
    if len(execution_rows) > 32:
        return unknown("workflow_run_definition_join_bound_exceeded")
    reader = getattr(source, "workflow_definition_as_of", None)
    if reader is None:
        return unknown("workflow_definition_history_source_unavailable")

    invocation_by_id = {
        row.get("invocation_id"): row
        for row in invocation_rows
        if isinstance(row, dict) and _safe_identifier(row.get("invocation_id")) is not None
    }
    signatures: set[tuple[str, int, str, str]] = set()
    execution_ids: list[str] = []
    refs: list[EvidenceRef] = []
    definition: Optional[WorkflowDefinitionRevision] = None
    definition_ref: Optional[EvidenceRef] = None
    read_cache: dict[tuple[str, datetime], WorkflowDefinitionRead] = {}
    for execution in execution_rows:
        link = execution.get("workflow_definition_link")
        execution_id = _safe_identifier(execution.get("execution_id"))
        workflow_id = _safe_identifier(link.get("workflow_id")) if isinstance(link, dict) else None
        record_id = _safe_identifier(link.get("definition_record_id")) if isinstance(link, dict) else None
        digest = _safe_identifier(link.get("definition_digest")) if isinstance(link, dict) else None
        revision = link.get("revision") if isinstance(link, dict) else None
        checked_at = _parse_timestamp(link.get("reference_checked_at")) if isinstance(link, dict) else None
        started_at = _parse_timestamp(execution.get("started_at"))
        execution_ref = _agent_execution_evidence(execution)
        linked_invocation_ids = execution.get("workflow_run_invocation_ids")
        if (
            not isinstance(link, dict)
            or link.get("association_kind") != "caller_reported_exact_definition_reference"
            or link.get("workflow_run_id") != subject.id
            or execution.get("tenant_id") != tenant_id
            or execution.get("workflow_run_id") != subject.id
            or workflow_id is None
            or record_id is None
            or digest is None
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or checked_at is None
            or started_at is None
            or checked_at > started_at
            or execution_id is None
            or execution_ref is None
            or not isinstance(linked_invocation_ids, list)
            or not linked_invocation_ids
        ):
            return unknown("workflow_run_definition_link_invalid_or_missing")
        invocation_refs: list[EvidenceRef] = []
        for invocation_id in linked_invocation_ids:
            invocation = invocation_by_id.get(invocation_id)
            invocation_ref = _invocation_evidence(invocation) if isinstance(invocation, dict) else None
            if invocation_ref is None:
                return unknown("workflow_run_definition_invocation_evidence_missing")
            invocation_refs.append(invocation_ref)
        cache_key = (workflow_id, checked_at)
        if cache_key not in read_cache:
            try:
                read_cache[cache_key] = await reader(
                    tenant_id=tenant_id, workflow_id=workflow_id, as_of=checked_at
                )
            except Exception:  # noqa: BLE001 - definition source stays unknown
                return unknown("workflow_definition_history_source_unavailable")
        read = read_cache[cache_key]
        if (
            not isinstance(read, WorkflowDefinitionRead)
            or not read.available
            or not read.complete
            or read.reason
            or len(read.rows) != 1
            or not isinstance(read.rows[0], dict)
        ):
            return unknown("workflow_run_definition_history_incomplete")
        raw = read.rows[0]
        try:
            current = WorkflowDefinitionRevision.model_validate(
                {key: raw[key] for key in WorkflowDefinitionRevision.model_fields if key in raw}
            )
            stored_ref = EvidenceRef.model_validate(link.get("definition_evidence_ref"))
        except Exception:  # noqa: BLE001 - malformed evidence fails closed
            return unknown("workflow_run_definition_evidence_invalid")
        current_ref = workflow_definition_evidence(current)
        if (
            current.tenant_id != tenant_id
            or current.workflow_id != workflow_id
            or current.revision != revision
            or current.record_id != record_id
            or current.definition_digest != digest
            or current.status != "active"
            or current.created_at > checked_at
            or (current.effective_at is not None and current.effective_at > checked_at)
            or raw.get("tenant_id") != tenant_id
            or raw.get("subject_ref") != workflow_id
            or raw.get("record_id") != record_id
            or raw.get("definition_digest") != digest
            or current_ref is None
            or stored_ref.id != current_ref.id
            or stored_ref.type != current_ref.type
            or stored_ref.source != current_ref.source
            or stored_ref.uri != current_ref.uri
            or _parse_timestamp(stored_ref.observedAt)
            != _parse_timestamp(current_ref.observedAt)
            or not any(
                step.kind == "agent" and step.agent_ref == execution.get("agent_id")
                for step in current.steps
            )
        ):
            return unknown("workflow_run_definition_reference_mismatch")
        signatures.add((workflow_id, revision, record_id, digest))
        execution_ids.append(execution_id)
        refs.extend([execution_ref, *invocation_refs])
        definition = current
        definition_ref = current_ref
    if len(signatures) != 1 or definition is None or definition_ref is None:
        return unknown("workflow_run_definition_association_conflicted")

    evidence_refs = _dedupe_evidence_refs([definition_ref, *refs])
    content = {
        "state": "degraded",
        "coverage": "partial",
        "reason": "caller_reported_exact_definition_reference_validated",
        "associationKind": "caller_reported_exact_definition_reference",
        "workflowId": definition.workflow_id,
        "revision": definition.revision,
        "definitionRecordId": definition.record_id,
        "definitionDigest": definition.definition_digest,
        "associatedExecutionIds": sorted(execution_ids),
        "declaredTriggers": [trigger.model_dump(mode="json") for trigger in definition.triggers],
        "declaredSteps": [step.model_dump(mode="json") for step in definition.steps],
        "triggerExecutionState": "unknown",
        "stepExecutionState": "unknown",
        "externalEffectState": "unknown",
        "freshness": {
            "state": "unknown",
            "thresholdSeconds": None,
            "reasonCode": "workflow_definition_freshness_threshold_not_configured",
        },
        "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
    }
    section = ProjectionSection(
        id="workflow_summary",
        state="degraded",
        title="Reported workflow definition association",
        content=content,
        canonicalAuthorityRefs=[
            "workflow_definition_revisions", "agent_executions", "ai_execution_facts"
        ],
        warnings=[
            "The caller-reported association references a registered definition; trigger and step execution remain unknown."
        ],
    )
    claim = ClaimEnvelope(
        id=f"workflow360:reported_definition:{subject.id}:{definition.record_id}",
        kind="workflow_run_reported_definition_association",
        subject=subject,
        evidenceRefs=evidence_refs,
        claims=[
            "A caller-reported workflow definition reference on exact tenant AgentExecution records matches a registered revision and AI invocation run link; this does not prove that its triggers or steps executed or caused an external effect."
        ],
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["workflow_summary", "evidence_trace"],
    )
    return section, [claim]


def _workflow_summary_section(
    subject: Any,
    *,
    tenant_id: str,
    read: WorkflowDefinitionRead,
    requested: bool,
    historical_anchor: Optional[datetime],
    registrar_identity_read: WorkflowPrincipalIdentityRead,
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    if not requested:
        return _unknown_section("workflow_summary"), []
    if subject.kind not in {"workflow", "automation", "automation_id"}:
        reason = (
            "workflow_run_has_no_exact_workflow_definition_id_link"
            if subject.kind in _RUN_SUBJECT_KINDS
            else "workflow_definition_subject_kind_not_supported"
        )
        return _unknown_section_with_reason("workflow_summary", reason), []
    if not read.available:
        return _unknown_section_with_reason(
            "workflow_summary", read.reason or "workflow_definition_read_unavailable"
        ), []
    if read.reason:
        return _unknown_section_with_reason("workflow_summary", read.reason), []
    if not read.rows:
        if read.complete:
            return (
                ProjectionSection(
                    id="workflow_summary",
                    state="empty",
                    title="Registered workflow definition",
                    content={
                        "state": "empty",
                        "coverage": (
                            "complete_for_exact_workflow_id_as_of_lookup"
                            if historical_anchor is not None
                            else "complete_for_exact_workflow_id_lookup"
                        ),
                        "reason": (
                            "no_registered_workflow_definition_at_as_of"
                            if historical_anchor is not None
                            else "no_registered_workflow_definition_for_exact_id"
                        ),
                        "workflowId": subject.id,
                        "asOf": (
                            historical_anchor.isoformat()
                            if historical_anchor is not None
                            else None
                        ),
                        "executionState": "unknown",
                    },
                    canonicalAuthorityRefs=["workflow_definition_revisions"],
                ),
                [],
            )
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_read_incomplete"
        ), []
    if len(read.rows) != 1 or not read.complete:
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_latest_revision_not_proven"
        ), []

    raw = read.rows[0]
    if (
        not isinstance(raw, dict)
        or raw.get("tenant_id") != tenant_id
        or raw.get("workflow_id") != subject.id
    ):
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_scope_mismatch"
        ), []
    allowed_fields = set(WorkflowDefinitionRevision.model_fields)
    payload = {key: value for key, value in raw.items() if key in allowed_fields}
    try:
        definition = WorkflowDefinitionRevision.model_validate(payload)
    except Exception:  # noqa: BLE001 - malformed authority payload remains unknown
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_contract_invalid"
        ), []
    if definition.tenant_id != tenant_id or definition.workflow_id != subject.id:
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_scope_mismatch"
        ), []
    if (
        raw.get("definition_digest") != definition.definition_digest
        or raw.get("record_id") != definition.record_id
    ):
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_digest_or_record_id_mismatch"
        ), []
    evidence = workflow_definition_evidence(definition)
    if evidence is None:
        return _unknown_section_with_reason(
            "workflow_summary", "workflow_definition_timestamp_invalid"
        ), []

    triggers = [item.model_dump(mode="json") for item in definition.triggers]
    steps = [item.model_dump(mode="json") for item in definition.steps]
    registrar_identity_state = "unknown"
    registrar_identity_reason = "historical_identity_replay_unavailable" if historical_anchor else (
        registrar_identity_read.reason or "definition_registrar_identity_unresolved"
    )
    registrar_canonical_human_id: Optional[str] = None
    registrar_identity_refs: list[EvidenceRef] = []
    if historical_anchor is None:
        if not isinstance(registrar_identity_read, WorkflowPrincipalIdentityRead):
            registrar_identity_read = WorkflowPrincipalIdentityRead(
                (), False, False, reason="definition_registrar_identity_contract_invalid"
            )
        bindings, identity_complete = _principal_identity_bindings(
            registrar_identity_read,
            tenant_id=tenant_id,
            principal_user_ids={definition.actor_ref},
        )
        binding = bindings.get(definition.actor_ref)
        if binding and binding.get("state") == "resolved" and identity_complete:
            registrar_identity_state = "resolved"
            registrar_identity_reason = "active_tenant_user_id_alias"
            registrar_canonical_human_id = binding["canonical_human_entity_id"]
            registrar_identity_refs = binding["evidence_refs"]
        elif (
            registrar_identity_read.available
            and registrar_identity_read.complete
            and binding is not None
        ):
            registrar_identity_state = (
                "ambiguous"
                if binding and binding.get("state") == "ambiguous"
                else "unresolved"
            )
            registrar_identity_reason = (
                "definition_registrar_identity_ambiguous"
                if registrar_identity_state == "ambiguous"
                else "definition_registrar_identity_unresolved"
            )
        else:
            registrar_identity_reason = (
                registrar_identity_read.reason
                or "definition_registrar_identity_scope_or_proof_incomplete"
            )
    content = {
        "state": "available",
        "coverage": (
            "complete_for_exact_workflow_id_as_of_lookup"
            if historical_anchor is not None
            else "complete_for_latest_registered_revision"
        ),
        "reason": "explicit_tenant_registered_workflow_definition_revision",
        "workflowId": definition.workflow_id,
        "revision": definition.revision,
        "name": definition.name,
        "description": definition.description,
        "status": definition.status,
        "definitionDigest": raw.get("definition_digest"),
        "registeredByActorRef": definition.actor_ref,
        "registeredByCanonicalHumanEntityId": registrar_canonical_human_id,
        "registrarIdentityState": registrar_identity_state,
        "registrarIdentityReason": registrar_identity_reason,
        "registrarIdentityEvidenceRefs": [
            ref.model_dump(mode="json") for ref in registrar_identity_refs
        ],
        "registeredAt": _safe_timestamp(definition.created_at),
        "effectiveAt": _safe_timestamp(definition.effective_at),
        "declaredTriggers": triggers,
        "declaredSteps": steps,
        "definitionHistoryCoverage": (
            "bounded_as_of_revision_selection"
            if historical_anchor is not None
            else "latest_revision_only"
        ),
        "asOf": historical_anchor.isoformat() if historical_anchor is not None else None,
        "runLinkState": "unknown",
        "triggerExecutionState": "unknown",
        "stepExecutionState": "unknown",
        "externalEffectState": "unknown",
        "evidenceRefs": [
            ref.model_dump(mode="json") for ref in [evidence, *registrar_identity_refs]
        ],
    }
    section = ProjectionSection(
        id="workflow_summary",
        state="available",
        title="Registered workflow definition",
        content=content,
        canonicalAuthorityRefs=[
            "workflow_definition_revisions",
            *(["identity"] if registrar_canonical_human_id and registrar_identity_refs else []),
        ],
    )
    claim = ClaimEnvelope(
        id=f"workflow360:definition:{definition.record_id}",
        kind="registered_workflow_definition_revision",
        subject=subject,
        evidenceRefs=[evidence],
        claims=[
            "A tenant-scoped workflow definition revision is explicitly registered; the record does not establish that its triggers or steps executed."
        ],
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=["workflow_summary", "evidence_trace"],
    )
    claims = [claim]
    if registrar_canonical_human_id is not None:
        claims.append(
            ClaimEnvelope(
                id=f"workflow360:definition_registrar:{definition.record_id}",
                kind="registered_workflow_definition_registrar_identity",
                subject=subject,
                evidenceRefs=[evidence, *registrar_identity_refs],
                claims=[
                    "The authenticated registrar reference on this workflow definition resolves through one active tenant USER_ID alias to a canonical Human entity at the current read time; this does not identify a workflow run initiator or approver."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["workflow_summary", "evidence_trace"],
            )
        )
    return section, claims


def _unknown_section_with_reason(slot_id: str, reason: str) -> ProjectionSection:
    return ProjectionSection(
        id=slot_id,
        state="unknown",
        title=slot_id.replace("_", " ").title(),
        content={"state": "unknown", "reasonCode": _safe_reason(reason) or "authority_read_unknown"},
        warnings=[_safe_reason(reason) or "authority_read_unknown"],
    )


def _unknown_section(slot_id: str) -> ProjectionSection:
    reasons = {
        "workflow_summary": "canonical_workflow_definition_authority_not_available",
        "triggers": "canonical_workflow_trigger_authority_not_available",
        "actors": "canonical_workflow_actor_attribution_not_joined",
        "approvals": "canonical_workflow_approval_authority_not_available",
        "agent_steps": "canonical_workflow_step_authority_not_joined",
        "actions": "canonical_workflow_action_authority_not_joined",
        "outcomes": "canonical_workflow_business_outcome_join_not_available",
        "risk": "canonical_workflow_risk_policy_join_not_available",
    }
    reason = reasons[slot_id]
    return ProjectionSection(
        id=slot_id,
        state="unknown",
        title=slot_id.replace("_", " ").title(),
        content={"state": "unknown", "reasonCode": reason},
        warnings=[reason],
    )


def _workflow_actions_section(
    subject: Any,
    *,
    tenant_id: str,
    read: WorkflowActionRead,
    execution_rows: list[dict[str, Any]],
    execution_refs: list[EvidenceRef],
    execution_inventory_complete: bool,
    time_range: Any,
    requested: bool,
    historical: bool,
    execution_results_authorized: bool,
    resource_rows: list[dict[str, str]],
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Project exact observed tool-call edges without upgrading them to effects."""
    reason = (
        "workflow_action_slot_not_requested"
        if not requested
        else "workflow_action_historical_state_unavailable"
        if historical
        else _safe_reason(read.reason)
    )
    if subject.kind not in _RUN_SUBJECT_KINDS:
        reason = "subject_kind_not_supported_by_workflow_run_evidence"
    if not requested or historical or subject.kind not in _RUN_SUBJECT_KINDS or not read.available:
        reason = reason or "canonical_workflow_action_source_unavailable"
        return (
            ProjectionSection(
                id="actions",
                state="unknown",
                title="Observed workflow actions",
                content={
                    "state": "unknown",
                    "coverage": "unknown",
                    "reasonCode": reason,
                    "workflowDefinitionState": "unknown",
                    "actionProducerCoverage": "unknown",
                    "freshness": {
                        "state": "unknown",
                        "thresholdSeconds": None,
                        "reasonCode": "workflow_action_freshness_threshold_not_configured",
                    },
                },
                warnings=[reason],
            ),
            [],
        )

    execution_by_id: dict[str, dict[str, Any]] = {}
    for row in execution_rows:
        execution_id = _safe_identifier(row.get("execution_id"))
        if (
            row.get("tenant_id") != tenant_id
            or row.get("workflow_run_id") != subject.id
            or execution_id is None
            or execution_id in execution_by_id
        ):
            reason = "workflow_action_execution_join_incomplete"
            continue
        execution_by_id[execution_id] = row
    execution_ref_by_id = {
        ref.id: ref
        for ref in execution_refs
        if ref.source == _AGENT_EXECUTION_SOURCE and ref.id in execution_by_id
    }

    lower_raw = getattr(time_range, "from_", None) if time_range else None
    upper_raw = getattr(time_range, "to", None) if time_range else None
    lower = _parse_timestamp(lower_raw) if lower_raw is not None else None
    upper = _parse_timestamp(upper_raw) if upper_raw is not None else None
    invalid_window = bool(
        time_range is not None
        and (
            (lower_raw is not None and lower is None)
            or (upper_raw is not None and upper is None)
            or (lower is not None and upper is not None and upper < lower)
        )
    )
    if invalid_window:
        reason = "workflow_action_time_range_invalid"
        return (
            ProjectionSection(
                id="actions",
                state="unknown",
                title="Observed workflow actions",
                content={
                    "state": "unknown",
                    "coverage": "unknown",
                    "reasonCode": reason,
                    "workflowDefinitionState": "unknown",
                    "actionProducerCoverage": "unknown",
                    "freshness": {
                        "state": "unknown",
                        "thresholdSeconds": None,
                        "reasonCode": "workflow_action_freshness_threshold_not_configured",
                    },
                },
                warnings=[reason],
            ),
            [],
        )

    actions: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    invalid_rows = False
    filtered_by_time_range = False
    raw_rows = read.rows if isinstance(read.rows, (tuple, list)) else ()
    if not isinstance(read.rows, (tuple, list)):
        invalid_rows = True
    for raw in raw_rows:
        execution_id = _safe_identifier(raw.get("execution_id")) if isinstance(raw, dict) else None
        tool_id = _safe_identifier(raw.get("tool_id")) if isinstance(raw, dict) else None
        called_at = _safe_timestamp(raw.get("called_at")) if isinstance(raw, dict) else None
        raw_evidence = raw.get("evidence_ref") if isinstance(raw, dict) else None
        if (
            not isinstance(raw, dict)
            or raw.get("tenant_id") != tenant_id
            or raw.get("workflow_run_id") != subject.id
            or execution_id is None
            or execution_id not in execution_by_id
            or tool_id is None
            or called_at is None
        ):
            invalid_rows = True
            continue
        execution_evidence = execution_ref_by_id.get(execution_id)
        try:
            action_evidence = EvidenceRef.model_validate(raw_evidence)
        except Exception:  # noqa: BLE001 - malformed source evidence is omitted
            action_evidence = None
        try:
            tool_evidence = EvidenceRef.model_validate(raw.get("tool_evidence_ref"))
        except Exception:  # noqa: BLE001 - legacy rows have no Tool vertex evidence
            tool_evidence = None
        if tool_evidence is not None and (
            tool_evidence.source != "graph_vertices"
            or tool_evidence.type != "entity"
            or tool_evidence.id != f"{tenant_id}:tool:{tool_id}"
        ):
            tool_evidence = None
            invalid_rows = True
        if (
            execution_evidence is None
            or action_evidence is None
            or action_evidence.source != "graph_edges"
            or _safe_identifier(action_evidence.id) is None
            or _safe_timestamp(action_evidence.observedAt) != called_at
        ):
            invalid_rows = True
            continue

        called_at_instant = _parse_timestamp(called_at)
        if (
            lower is not None
            and called_at_instant is not None
            and called_at_instant < lower
        ) or (
            upper is not None
            and called_at_instant is not None
            and called_at_instant > upper
        ):
            filtered_by_time_range = True
            continue

        evidence_refs = [
            action_evidence,
            execution_evidence,
            *([tool_evidence] if tool_evidence is not None else []),
        ]
        from intelligence.workflow.action_authorities import execution_result

        outcome = (execution_result(tenant_id=tenant_id, workflow_run_id=subject.id,
                                    execution=execution_by_id[execution_id], called_at=called_at)
                   if execution_results_authorized else None)
        resource = next((row for row in resource_rows if row.get("execution_id") == execution_id), None)
        resource_view: dict[str, Any] = {"state": "unknown"}
        if (resource is not None and all(_safe_identifier(resource.get(key)) for key in
                ("resource_id", "approval_id", "decision_id", "delegation_id"))):
            resource_ref = EvidenceRef(id=resource["resource_id"], type="entity", source="commerce_resources",
                                       observedAt=resource.get("registered_at"))
            authority_refs = [resource_ref, EvidenceRef(id=resource["approval_id"], type="event", source="commerce_approvals"),
                              EvidenceRef(id=resource["decision_id"], type="event", source="commerce_approval_decisions"),
                              EvidenceRef(id=resource["delegation_id"], type="relationship", source="delegations")]
            evidence_refs = _dedupe_evidence_refs([*evidence_refs, *authority_refs])
            resource_view = {"state": "resolved_current_approved_resource", "resourceId": resource["resource_id"],
                             "evidenceRef": resource_ref.model_dump(mode="json", by_alias=True, exclude_none=True),
                             "resourceOperation": "unknown"}
        actions.append(
            {
                "executionId": execution_id,
                "toolId": tool_id,
                "toolIdentityState": "resolved" if tool_evidence is not None else "unknown",
                "calledAt": called_at,
                "observationKind": "tenant_scoped_execution_linked_tool_call_edge",
                "operationState": "call_observed_external_effect_unknown",
                "authorityDecision": "not_established_by_tool_call_edge",
                "executionResult": outcome or {"state": "unknown"},
                "approvedResource": resource_view,
                "evidenceRefs": [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for ref in evidence_refs
                ],
            }
        )
        claims.append(
            ClaimEnvelope(
                id=f"workflow360.tool_call.{action_evidence.id}",
                kind="workflow_run_tool_invocation_observed",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    "A tenant-scoped CALLED_TOOL graph edge references an admitted execution linked to this workflow run; an exact Tool vertex is evidenced only when separately resolved. The edge does not establish action authorization, tool completion, or an external effect."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["actions", "evidence_trace"],
            )
        )
        if outcome is not None:
            claims.append(ClaimEnvelope(
                id=f"workflow360.execution_result.{quote(execution_id, safe='')}:{quote(action_evidence.id, safe='')}",
                kind="workflow_linked_executor_result", subject=subject,
                evidenceRefs=[execution_evidence, action_evidence],
                claims=["The linked AgentExecution records a published executor completion or failure; this does not establish the result of the observed tool call or an external effect."],
                claimState=EpistemicStatus.OBSERVED, domainSlotIds=["actions", "evidence_trace"],
            ))
        if resource_view["state"] == "resolved_current_approved_resource":
            claims.append(ClaimEnvelope(
                id=f"workflow360.approved_resource.{quote(execution_id, safe='')}:{quote(action_evidence.id, safe='')}",
                kind="workflow_linked_approved_resource", subject=subject, evidenceRefs=evidence_refs,
                claims=["The linked execution's approved request names this current tenant resource; the tool edge does not establish that the resource was acted upon."],
                claimState=EpistemicStatus.OBSERVED, domainSlotIds=["actions", "evidence_trace"],
            ))

    source_incomplete = bool(
        not read.complete or read.scope_mismatch or invalid_rows or not execution_inventory_complete
    )
    state = "degraded" if source_incomplete and actions else "available" if actions else "unknown"
    reason = (
        "workflow_action_source_or_execution_inventory_incomplete"
        if source_incomplete
        else "no_tool_call_edge_in_requested_time_range"
        if filtered_by_time_range
        else "no_exact_execution_linked_tool_call_edges_observed"
        if not actions
        else reason
    )
    latest_observed_at = max((item["calledAt"] for item in actions), default=None)
    content = {
        "state": state,
        "coverage": "partial" if actions else "unknown",
        "reasonCode": reason,
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "source": "graph_edges",
        "evidenceScope": "CALLED_TOOL edges joined to exact admitted tenant and workflow-run execution IDs",
        "actions": actions,
        "observedCount": len(actions),
        "executionInventoryReadComplete": execution_inventory_complete,
        "actionEdgeReadComplete": read.complete and not read.scope_mismatch and not invalid_rows,
        "workflowDefinitionState": "unknown",
        "actionProducerCoverage": "unknown",
        "authorizationState": "not_established_by_tool_call_edge",
        "externalEffectState": "unknown",
        "freshness": {
            "state": "unknown",
            "latestReturnedObservedAt": latest_observed_at,
            "thresholdSeconds": None,
            "reasonCode": "workflow_action_freshness_threshold_not_configured",
        },
    }
    return (
        ProjectionSection(
            id="actions",
            state=state,
            title="Observed workflow actions",
            content=content,
            warnings=[reason] if reason else None,
            canonicalAuthorityRefs=(
                ["agent_executions", "graph_edges", *(
                    ["tools"] if any(row["toolIdentityState"] == "resolved" for row in actions) else []
                ), *(["actions"] if any(row["executionResult"]["state"] != "unknown" for row in actions) else []),
                 *(["resources"] if any(row["approvedResource"]["state"] != "unknown" for row in actions) else [])]
                if actions else None
            ),
        ),
        claims,
    )


def _actors_section(
    subject: Any,
    *,
    tenant_id: str,
    invocation_rows: list[dict[str, Any]],
    invocation_refs: list[EvidenceRef],
    requested_agent_ids: set[str],
    identity_read: WorkflowAgentIdentityRead,
    execution_rows: list[dict[str, Any]],
    execution_refs: list[EvidenceRef],
    approval_rows: list[dict[str, Any]],
    principal_identity_read: WorkflowPrincipalIdentityRead,
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Expose only AI invocation agent refs resolved to tenant canonical Agents.

    The slot remains partial even when every observed ref resolves: AI invocation
    telemetry cannot establish the complete set of workflow actors, human
    approvers, initiators, or authority holders.
    """
    invocation_evidence = {ref.id: ref for ref in invocation_refs}
    invocation_ids_by_agent: dict[str, set[str]] = {}
    invalid_invocation_actor_ref = False
    for row in invocation_rows:
        agent_id = _safe_identifier(row.get("agent_id"))
        invocation_id = _safe_identifier(row.get("invocation_id"))
        if agent_id is None:
            continue
        if (
            agent_id not in requested_agent_ids
            or invocation_id is None
            or invocation_id not in invocation_evidence
        ):
            invalid_invocation_actor_ref = True
            continue
        invocation_ids_by_agent.setdefault(agent_id, set()).add(invocation_id)

    identity_rows_by_agent: dict[str, list[tuple[str, EvidenceRef]]] = {}
    invalid_identity = False
    allowed_authorities = {
        ("entities", "canonical_agent_entity"),
        ("agent_deployment_identity_bindings", "tenant_admin_explicit"),
    }
    for row in identity_read.rows:
        if not isinstance(row, dict):
            invalid_identity = True
            continue
        agent_id = _safe_identifier(row.get("agent_id"))
        canonical_id = _safe_identifier(row.get("canonical_agent_entity_id"))
        evidence_source = _safe_token(row.get("identity_evidence_source"))
        evidence_id = _safe_identifier(row.get("identity_evidence_id"))
        authority = _safe_token(row.get("identity_binding_authority"))
        if (
            row.get("tenant_id") != tenant_id
            or agent_id not in requested_agent_ids
            or canonical_id is None
            or evidence_source is None
            or evidence_id is None
            or authority is None
            or (evidence_source, authority) not in allowed_authorities
        ):
            invalid_identity = True
            continue
        identity_ref = EvidenceRef(
            id=evidence_id,
            type="entity",
            source=evidence_source,
            observedAt=_safe_timestamp(row.get("identity_bound_at")),
            uri=f"store://{evidence_source}/{quote(evidence_id, safe='')}",
        )
        identity_rows_by_agent.setdefault(agent_id, []).append((canonical_id, identity_ref))

    canonical_by_agent: dict[str, str] = {}
    identity_refs_by_agent: dict[str, list[EvidenceRef]] = {}
    for agent_id, identities in identity_rows_by_agent.items():
        canonical_ids = {canonical_id for canonical_id, _ in identities}
        if len(canonical_ids) != 1:
            invalid_identity = True
            continue
        canonical_by_agent[agent_id] = next(iter(canonical_ids))
        identity_refs_by_agent[agent_id] = [ref for _, ref in identities]

    actor_by_canonical: dict[str, dict[str, Any]] = {}
    for agent_id, canonical_id in canonical_by_agent.items():
        linked_invocations = invocation_ids_by_agent.get(agent_id, set())
        if not linked_invocations:
            continue
        actor = actor_by_canonical.setdefault(
            canonical_id,
            {"agentRefs": set(), "invocationIds": set(), "identityRefs": []},
        )
        actor["agentRefs"].add(agent_id)
        actor["invocationIds"].update(linked_invocations)
        actor["identityRefs"].extend(identity_refs_by_agent.get(agent_id, []))

    actor_items: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    all_evidence: list[EvidenceRef] = []
    for canonical_id, actor in sorted(actor_by_canonical.items()):
        observed_invocation_ids = sorted(actor["invocationIds"])
        actor_invocation_refs = [
            invocation_evidence[invocation_id]
            for invocation_id in observed_invocation_ids
            if invocation_id in invocation_evidence
        ]
        actor_identity_refs = _dedupe_evidence_refs(actor["identityRefs"])
        evidence_refs = _dedupe_evidence_refs(actor_invocation_refs + actor_identity_refs)
        all_evidence.extend(evidence_refs)
        actor_items.append(
            {
                "canonicalAgentEntityId": canonical_id,
                "observedAiInvocationIds": observed_invocation_ids,
                "identityResolution": "tenant_canonical_agent_identity",
                "identityEvidenceRefs": [
                    ref.model_dump(mode="json") for ref in actor_identity_refs
                ],
                "invocationEvidenceRefs": [
                    ref.model_dump(mode="json") for ref in actor_invocation_refs
                ],
                "lastObservedAt": max(
                    (
                        ref.observedAt
                        for ref in actor_invocation_refs
                        if ref.observedAt is not None
                    ),
                    default=None,
                ),
            }
        )
        claims.append(
            ClaimEnvelope(
                id=f"workflow360.actor.{quote(canonical_id, safe='')}",
                kind="canonical_agent_identity_linked_to_workflow_invocation",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    "At least one tenant-scoped AI invocation fact linked to the requested run records an agent reference that resolves through tenant canonical Agent identity evidence; this does not identify human actors or establish workflow initiation, approval, or authority."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["actors"],
            )
        )

    principal_user_ids = {
        principal_id
        for row in execution_rows
        if (principal_id := _safe_identifier(row.get("initiating_principal_user_id")))
        is not None
    }
    principal_user_ids.update(
        principal_id
        for row in approval_rows
        if (principal_id := _safe_identifier(row.get("decided_by"))) is not None
    )
    principal_bindings, principal_identity_complete = _principal_identity_bindings(
        principal_identity_read,
        tenant_id=tenant_id,
        principal_user_ids=principal_user_ids,
    )
    execution_evidence_by_id = {ref.id: ref for ref in execution_refs}
    human_actors: dict[str, dict[str, Any]] = {}
    human_claims: list[ClaimEnvelope] = []
    unresolved_principal_link = False

    def add_human_actor(
        *,
        principal_user_id: str,
        role: str,
        execution_id: str,
        approval: Optional[dict[str, Any]] = None,
    ) -> None:
        nonlocal unresolved_principal_link
        binding = principal_bindings.get(principal_user_id)
        if not isinstance(binding, dict) or binding.get("state") != "resolved":
            unresolved_principal_link = True
            return
        canonical_id = _safe_identifier(binding.get("canonical_human_entity_id"))
        execution_ref = execution_evidence_by_id.get(execution_id)
        if canonical_id is None or execution_ref is None:
            unresolved_principal_link = True
            return
        actor = human_actors.setdefault(
            canonical_id,
            {
                "roles": set(),
                "executionIds": set(),
                "approvalIds": set(),
                "identityEvidenceRefs": [],
                "executionEvidenceRefs": [],
                "approvalEvidenceRefs": [],
            },
        )
        actor["roles"].add(role)
        actor["executionIds"].add(execution_id)
        actor["identityEvidenceRefs"].extend(binding.get("evidence_refs") or [])
        actor["executionEvidenceRefs"].append(execution_ref)
        if approval is not None:
            approval_id = _safe_identifier(approval.get("approval_id"))
            if approval_id is not None:
                actor["approvalIds"].add(approval_id)
            actor["approvalEvidenceRefs"].extend(_approval_evidence_refs(approval))

    for row in execution_rows:
        principal_user_id = _safe_identifier(row.get("initiating_principal_user_id"))
        execution_id = _safe_identifier(row.get("execution_id"))
        if principal_user_id is not None and execution_id is not None:
            add_human_actor(
                principal_user_id=principal_user_id,
                role="initiating_principal",
                execution_id=execution_id,
            )
    for row in approval_rows:
        principal_user_id = _safe_identifier(row.get("decided_by"))
        execution_id = _safe_identifier(row.get("execution_id"))
        if principal_user_id is not None and execution_id is not None:
            add_human_actor(
                principal_user_id=principal_user_id,
                role="approver",
                execution_id=execution_id,
                approval=row,
            )

    for canonical_id, actor in sorted(human_actors.items()):
        identity_refs = _dedupe_evidence_refs(actor["identityEvidenceRefs"])
        execution_actor_refs = _dedupe_evidence_refs(actor["executionEvidenceRefs"])
        approval_actor_refs = _dedupe_evidence_refs(actor["approvalEvidenceRefs"])
        evidence_refs = _dedupe_evidence_refs(
            execution_actor_refs + approval_actor_refs + identity_refs
        )
        all_evidence.extend(evidence_refs)
        actor_items.append(
            {
                "canonicalHumanEntityId": canonical_id,
                "actorKind": "human",
                "roles": sorted(actor["roles"]),
                "executionIds": sorted(actor["executionIds"]),
                "approvalIds": sorted(actor["approvalIds"]),
                "identityResolution": "tenant_canonical_human_identity",
                "identityEvidenceRefs": [
                    ref.model_dump(mode="json") for ref in identity_refs
                ],
                "executionEvidenceRefs": [
                    ref.model_dump(mode="json") for ref in execution_actor_refs
                ],
                "approvalEvidenceRefs": [
                    ref.model_dump(mode="json") for ref in approval_actor_refs
                ],
            }
        )
        role_text = " and ".join(sorted(actor["roles"]))
        human_claims.append(
            ClaimEnvelope(
                id=f"workflow360.human_actor.{quote(canonical_id, safe='')}",
                kind="tenant_canonical_human_linked_to_workflow_execution",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    f"A tenant-scoped canonical AgentExecution and active USER_ID identity evidence link Human {canonical_id} to the workflow as {role_text}; this attribution does not establish complete actor coverage or authorization beyond separately recorded decision evidence."
                ],
                claimState=EpistemicStatus.RESOLVED,
                domainSlotIds=["actors", "evidence_trace"],
            )
        )

    identity_complete = (
        identity_read.available
        and identity_read.complete
        and not identity_read.scope_mismatch
        and not invalid_identity
        and not invalid_invocation_actor_ref
        and set(canonical_by_agent) == requested_agent_ids
    )
    if actor_items:
        reason_code = (
            "workflow_agent_actor_attribution_partial_ai_invocation_only"
            if identity_complete
            else "workflow_agent_identity_resolution_incomplete"
        )
        state = "degraded"
        warning = (
            "Only canonical Agent identities reported on linked AI invocation facts are shown; workflow actor coverage remains incomplete."
        )
    elif requested_agent_ids:
        reason_code = (
            "workflow_agent_identity_scope_mismatch"
            if invalid_identity or invalid_invocation_actor_ref or identity_read.scope_mismatch
            else _safe_reason(identity_read.reason)
            or "workflow_agent_identity_unresolved"
        )
        state = "unknown"
        warning = "No source-reported AI invocation agent reference resolved to a tenant canonical Agent identity."
    elif invocation_rows:
        reason_code = "workflow_agent_actor_reference_not_present"
        state = "unknown"
        warning = "The linked AI invocation facts do not report an agent identity reference."
    else:
        reason_code = "workflow_agent_actor_observations_not_available"
        state = "unknown"
        warning = "No exact workflow-run AI invocation actor evidence is available."

    if invalid_identity or invalid_invocation_actor_ref or identity_read.scope_mismatch:
        if actor_items:
            reason_code = "workflow_agent_identity_resolution_incomplete"
    if unresolved_principal_link or not principal_identity_complete:
        if actor_items:
            reason_code = "workflow_human_identity_resolution_incomplete"
        elif principal_user_ids:
            reason_code = (
                principal_identity_read.reason
                or "workflow_human_identity_unresolved_or_ambiguous"
            )

    if human_actors and not actor_by_canonical:
        state = "degraded"
        warning = "Only canonical human principals explicitly linked through workflow execution and identity evidence are shown; workflow actor coverage remains incomplete."

    content = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "actorCoverageState": (
            "partial_agent_and_human_execution_actor_evidence"
            if human_actors and actor_by_canonical
            else "partial_human_execution_actor_evidence"
            if human_actors
            else "partial_ai_invocation_actor_refs_only"
            if actor_by_canonical
            else "unknown"
        ),
        "workflowActorAuthorityState": "unknown",
        "identityResolutionCompleteForReportedRefs": identity_complete,
        "principalIdentityResolutionCompleteForReportedRefs": principal_identity_complete,
        "actors": actor_items,
        "evidenceRefs": [
            ref.model_dump(mode="json") for ref in _dedupe_evidence_refs(all_evidence)
        ],
        "reasonCode": reason_code,
    }
    if requested_agent_ids:
        content["reportedAgentReferenceCount"] = len(requested_agent_ids)
    if actor_by_canonical:
        content["resolvedCanonicalAgentCount"] = len(actor_by_canonical)
    if human_actors:
        content["resolvedCanonicalHumanCount"] = len(human_actors)
        content["reportedPrincipalReferenceCount"] = len(principal_user_ids)
    section = ProjectionSection(
        id="actors",
        state=state,
        title="Workflow actor evidence",
        content=content,
        warnings=[warning],
        canonicalAuthorityRefs=(
            [
                authority
                for authority, present in (
                    ("ai_execution_facts", bool(actor_by_canonical)),
                    ("agent_entities", bool(actor_by_canonical)),
                    ("agent_executions", bool(human_actors)),
                    ("commerce", bool(approval_rows)),
                    ("identity", bool(actor_by_canonical or human_actors)),
                )
                if present
            ]
            if actor_items
            else None
        ),
    )
    return section, claims + human_claims


def _principal_identity_bindings(
    read: WorkflowPrincipalIdentityRead,
    *,
    tenant_id: str,
    principal_user_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Admit only complete alias + active Human subject evidence in exact scope."""
    if not principal_user_ids:
        return {}, bool(read.available and read.complete and not read.scope_mismatch)
    if not read.available or not read.complete or read.scope_mismatch:
        return {}, False
    grouped: dict[str, dict[str, Any]] = {}
    mismatch = False
    for row in read.rows:
        if not isinstance(row, dict):
            mismatch = True
            continue
        principal_id = _safe_identifier(row.get("principal_user_id"))
        if principal_id not in principal_user_ids and row.get("tenant_id") == tenant_id:
            # The actor section may share one identity read across initiators
            # and approvers; a slot-specific caller can safely ignore other
            # exact-tenant principals from that same read.
            continue
        canonical_id = _safe_identifier(row.get("canonical_human_entity_id"))
        raw_refs = row.get("identity_evidence_refs")
        refs: list[EvidenceRef] = []
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
                refs.append(ref)
        if (
            row.get("tenant_id") != tenant_id
            or principal_id not in principal_user_ids
            or canonical_id is None
            or {ref.source for ref in refs}
            != {"identity_aliases", "identity_subjects"}
            or len(refs) != len(raw_refs or [])
        ):
            mismatch = True
            continue
        entry = grouped.setdefault(
            principal_id,
            {"canonical_ids": set(), "evidence_refs": []},
        )
        entry["canonical_ids"].add(canonical_id)
        entry["evidence_refs"].extend(refs)
    if mismatch:
        return {}, False

    bindings: dict[str, dict[str, Any]] = {}
    all_resolved = True
    for principal_id in principal_user_ids:
        entry = grouped.get(principal_id)
        canonical_ids = entry["canonical_ids"] if entry else set()
        refs = entry["evidence_refs"] if entry else []
        if len(canonical_ids) == 1:
            canonical_id = next(iter(canonical_ids))
            bindings[principal_id] = {
                "state": "resolved",
                "canonical_human_entity_id": canonical_id,
                "evidence_refs": list(
                    {
                        (ref.source, ref.id): ref for ref in refs
                    }.values()
                ),
            }
        elif len(canonical_ids) > 1:
            all_resolved = False
            bindings[principal_id] = {"state": "ambiguous"}
        else:
            all_resolved = False
            bindings[principal_id] = {"state": "unresolved"}
    return bindings, all_resolved


def _approval_evidence_refs(row: dict[str, Any]) -> list[EvidenceRef]:
    approval_id = _safe_identifier(row.get("approval_id"))
    decision_id = _safe_identifier(row.get("decision_id"))
    refs: list[EvidenceRef] = []
    if approval_id is not None:
        refs.append(
            EvidenceRef(
                id=approval_id,
                type="event",
                source="commerce_approvals",
                observedAt=_safe_timestamp(row.get("decided_at")),
                uri=f"store://commerce_approvals/{quote(approval_id, safe='')}",
            )
        )
    if decision_id is not None:
        refs.append(
            EvidenceRef(
                id=decision_id,
                type="event",
                source="commerce_approval_decisions",
                observedAt=_safe_timestamp(row.get("decided_at")),
                uri=(
                    "store://commerce_approval_decisions/"
                    f"{quote(decision_id, safe='')}"
                ),
            )
        )
    return refs


def _approvals_section(
    subject: Any,
    *,
    tenant_id: str,
    approval_rows: list[dict[str, Any]],
    execution_refs: list[EvidenceRef],
    available: bool,
    complete: bool,
    reason: Optional[str],
    principal_identity_read: WorkflowPrincipalIdentityRead,
    agent_access_rows: list[dict[str, Any]],
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    execution_evidence = {ref.id: ref for ref in execution_refs}
    principal_ids = {
        principal_id
        for row in approval_rows
        if (principal_id := _safe_identifier(row.get("decided_by"))) is not None
    }
    bindings, identity_complete = _principal_identity_bindings(
        principal_identity_read,
        tenant_id=tenant_id,
        principal_user_ids=principal_ids,
    )
    records: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    all_refs: list[EvidenceRef] = []
    invalid = False
    for row in approval_rows:
        approval_id = _safe_identifier(row.get("approval_id"))
        decision_id = _safe_identifier(row.get("decision_id"))
        execution_id = _safe_identifier(row.get("execution_id"))
        action = _safe_token(row.get("action"), allowed=_APPROVAL_DECISION_ACTIONS)
        execution_ref = execution_evidence.get(execution_id or "")
        refs = _approval_evidence_refs(row)
        if (
            row.get("tenant_id") != tenant_id
            or row.get("workflow_run_id") != subject.id
            or approval_id is None
            or decision_id is None
            or execution_id is None
            or execution_ref is None
            or action is None
            or len(refs) != 2
        ):
            invalid = True
            continue
        identity = bindings.get(_safe_identifier(row.get("decided_by")) or "", {})
        canonical_decider = (
            _safe_identifier(identity.get("canonical_human_entity_id"))
            if identity.get("state") == "resolved"
            else None
        )
        evidence_refs = _dedupe_evidence_refs([execution_ref, *refs])
        record = {
            "executionId": execution_id,
            "approvalId": approval_id,
            "decisionId": decision_id,
            "action": action,
            "decidedAt": _safe_timestamp(row.get("decided_at")),
            "decisionActorIdentityState": identity.get("state", "unresolved"),
            "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
        }
        receipt = row.get("permission_receipt")
        checked_at = _safe_timestamp(receipt.get("checked_at")) if isinstance(receipt, dict) else None
        decided_at = _safe_timestamp(row.get("decided_at"))
        checked_time = _parse_timestamp(checked_at) if checked_at else None
        decided_time = _parse_timestamp(decided_at) if decided_at else None
        receipt_valid = bool(
            isinstance(receipt, dict)
            and _safe_identifier(receipt.get("receipt_id"))
            and receipt.get("tenant_id") == tenant_id
            and receipt.get("approval_id") == approval_id
            and receipt.get("execution_id") == execution_id
            and receipt.get("principal_id") == row.get("decided_by")
            and receipt.get("permission") == "commerce:approve"
            and checked_time is not None and decided_time is not None
            and checked_time <= decided_time
        )
        record["approverPermissionCheck"] = (
            {
                "state": "recorded",
                "permission": "commerce:approve",
                "checkedAt": checked_at,
                "receiptId": receipt["receipt_id"],
                "evidenceRef": refs[1].model_dump(mode="json"),
            }
            if receipt_valid else {"state": "unknown"}
        )
        agent_access = next((item for item in agent_access_rows
                             if item.get("tenant_id") == tenant_id
                             and item.get("workflow_run_id") == subject.id
                             and item.get("execution_id") == execution_id
                             and item.get("approval_id") == approval_id
                             and item.get("decision_id") == decision_id
                             and _safe_identifier(item.get("delegation_id"))
                             and _safe_timestamp(item.get("evaluated_at"))), None)
        record["agentAccess"] = {"state": "unknown"}
        if agent_access is not None:
            grant_ref = EvidenceRef(id=agent_access["delegation_id"], type="relationship",
                                    source="delegations", observedAt=agent_access["evaluated_at"])
            evidence_refs = _dedupe_evidence_refs([*evidence_refs, grant_ref])
            record["agentAccess"] = {
                "state": "recorded_request_time_allow", "delegationId": agent_access["delegation_id"],
                "evaluatedAt": agent_access["evaluated_at"],
                "evidenceRef": grant_ref.model_dump(mode="json"),
                "currentAuthorization": "unknown", "externalEffect": "unknown",
            }
        if canonical_decider is not None:
            record["decidedByCanonicalHumanEntityId"] = canonical_decider
        records.append(record)
        all_refs.extend(evidence_refs)
        claims.append(
            ClaimEnvelope(
                id=f"workflow360.approval.{quote(decision_id, safe='')}",
                kind="canonical_execution_approval_decision_linked_to_workflow_run",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    f"Canonical approval decision {decision_id} is explicitly linked to exact AgentExecution {execution_id}, which is linked to this tenant workflow run; this records the decision without asserting general workflow approval authority."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["approvals", "evidence_trace"],
            )
        )
    records.sort(key=lambda row: (row.get("decidedAt") or "", row["decisionId"]))
    exact_complete = complete and not invalid
    if records:
        state = "degraded"
        reason_code = reason or (
            "canonical_execution_approval_records_linked_but_workflow_approval_coverage_partial"
        )
        warning = "Only exact x402 approval decisions referenced by run-linked AgentExecutions are shown; workflow approval coverage and authorization policy remain unknown."
    else:
        state = "unknown"
        reason_code = reason or "canonical_workflow_approval_authority_not_available"
        warning = "No exact canonical approval decision is available for a run-linked AgentExecution."
    content = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "approvals": records,
        "approvalCoverageState": (
            "partial_exact_execution_approval_links_only" if records else "unknown"
        ),
        "workflowApprovalAuthorityState": "unknown",
        "sourceReadCompleteForExactLinks": exact_complete,
        "decisionActorIdentityResolutionCompleteForReportedRefs": identity_complete,
        "evidenceRefs": [
            ref.model_dump(mode="json") for ref in _dedupe_evidence_refs(all_refs)
        ],
        "reasonCode": reason_code,
    }
    if available:
        content["returnedApprovalDecisionCount"] = len(records)
    if records:
        content["canonicalApprovalDecisionCount"] = len(records)
    refs = ["agent_executions", "commerce"]
    if any(record["agentAccess"]["state"] == "recorded_request_time_allow" for record in records):
        refs.append("agent_access")
    return (
        ProjectionSection(
            id="approvals",
            state=state,
            title="Workflow approval evidence",
            content=content,
            warnings=[warning],
            canonicalAuthorityRefs=refs if records else None,
        ),
        claims,
    )


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _scoped_agent_execution_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    tenant_id: str,
    workflow_run_id: Optional[str],
    invocation_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Require explicit AI action_id links to exact tenant/run invocation facts."""
    scoped: list[dict[str, Any]] = []
    seen_execution_ids: set[str] = set()
    scope_mismatch = False
    for row in rows:
        execution_id = (
            _safe_identifier(row.get("execution_id"))
            if isinstance(row, dict)
            else None
        )
        raw_invocation_ids = (
            row.get("workflow_run_invocation_ids") if isinstance(row, dict) else None
        )
        linked_invocation_ids = (
            {
                value
                for raw in raw_invocation_ids
                if (value := _safe_identifier(raw)) is not None
            }
            if isinstance(raw_invocation_ids, list)
            else set()
        )
        agent_id = _safe_identifier(row.get("agent_id")) if isinstance(row, dict) else None
        linked_invocations = [
            invocation_by_id.get(invocation_id) for invocation_id in linked_invocation_ids
        ]
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or workflow_run_id is None
            or row.get("workflow_run_id") != workflow_run_id
            or not linked_invocation_ids
            or len(linked_invocations) != len(linked_invocation_ids)
            or any(
                not isinstance(invocation, dict)
                or invocation.get("tenant_id") != tenant_id
                or invocation.get("workflow_run_id") != workflow_run_id
                or invocation.get("action_id") != execution_id
                or invocation.get("agent_id") != agent_id
                for invocation in linked_invocations
            )
            or len(linked_invocation_ids) != len(raw_invocation_ids or [])
            or execution_id is None
            or agent_id is None
            or execution_id in seen_execution_ids
        ):
            scope_mismatch = True
            continue
        seen_execution_ids.add(execution_id)
        scoped.append(row)
    return scoped[:_MAX_AGENT_EXECUTIONS], scope_mismatch


def _scoped_approval_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    tenant_id: str,
    workflow_run_id: Optional[str],
    execution_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    expected = {
        (
            execution_id,
            _safe_identifier(row.get("approval_id")),
            _safe_identifier(row.get("approval_decision_id")),
        )
        for row in execution_rows
        if (execution_id := _safe_identifier(row.get("execution_id"))) is not None
        and _safe_identifier(row.get("approval_id")) is not None
        and _safe_identifier(row.get("approval_decision_id")) is not None
    }
    scoped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    mismatch = False
    for row in rows:
        execution_id = (
            _safe_identifier(row.get("execution_id")) if isinstance(row, dict) else None
        )
        approval_id = (
            _safe_identifier(row.get("approval_id")) if isinstance(row, dict) else None
        )
        decision_id = (
            _safe_identifier(row.get("decision_id")) if isinstance(row, dict) else None
        )
        key = (execution_id or "", approval_id or "", decision_id or "")
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or workflow_run_id is None
            or row.get("workflow_run_id") != workflow_run_id
            or key not in expected
            or key in seen
        ):
            mismatch = True
            continue
        seen.add(key)
        scoped.append(row)
    if len(seen) != len(expected):
        # A missing canonical record is incomplete authority evidence.
        mismatch = True
    return scoped[:_MAX_AGENT_EXECUTIONS], mismatch


def _scoped_linked_outcome_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    tenant_id: str,
    workflow_run_id: Optional[str],
    invocation_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Validate canonical outcomes against exact tenant/run invocation refs."""
    expected: dict[str, set[str]] = {}
    scope_mismatch = False
    for invocation in invocation_rows:
        if (
            not isinstance(invocation, dict)
            or invocation.get("tenant_id") != tenant_id
            or workflow_run_id is None
            or invocation.get("workflow_run_id") != workflow_run_id
        ):
            scope_mismatch = True
            continue
        raw_outcome_id = invocation.get("outcome_id")
        if raw_outcome_id is None or raw_outcome_id == "":
            continue
        outcome_id = _safe_identifier(raw_outcome_id)
        invocation_id = _safe_identifier(invocation.get("invocation_id"))
        if outcome_id is None or invocation_id is None:
            scope_mismatch = True
            continue
        expected.setdefault(outcome_id, set()).add(invocation_id)

    scoped: list[dict[str, Any]] = []
    seen_outcome_ids: set[str] = set()
    for row in rows:
        outcome_id = _safe_identifier(row.get("outcome_id")) if isinstance(row, dict) else None
        invocation_ids_raw = row.get("invocation_ids") if isinstance(row, dict) else None
        invocation_ids = (
            {
                value
                for raw in invocation_ids_raw
                if (value := _safe_identifier(raw)) is not None
            }
            if isinstance(invocation_ids_raw, list)
            else set()
        )
        outcome_record = (
            _model_or_dict(row.get("outcome_record")) if isinstance(row, dict) else None
        )
        expected_invocation_ids = expected.get(outcome_id or "")
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or workflow_run_id is None
            or row.get("workflow_run_id") != workflow_run_id
            or outcome_id is None
            or outcome_id not in expected
            or outcome_id in seen_outcome_ids
            or not isinstance(invocation_ids_raw, list)
            or len(invocation_ids) != len(invocation_ids_raw)
            or invocation_ids != expected_invocation_ids
            or not isinstance(outcome_record, dict)
            or outcome_record.get("tenant_id") != tenant_id
            or outcome_record.get("outcome_id") != outcome_id
        ):
            scope_mismatch = True
            continue
        seen_outcome_ids.add(outcome_id)
        scoped.append(
            {
                "tenant_id": tenant_id,
                "workflow_run_id": workflow_run_id,
                "outcome_id": outcome_id,
                "invocation_ids": sorted(invocation_ids),
                "outcome_record": outcome_record,
            }
        )

    join_incomplete = seen_outcome_ids != set(expected)
    return scoped[:_MAX_WORKFLOW_OUTCOMES], scope_mismatch, join_incomplete


def _linked_outcomes_section(
    subject: Any,
    *,
    tenant_id: str,
    invocation_rows: list[dict[str, Any]],
    invocation_refs: list[EvidenceRef],
    outcome_rows: list[dict[str, Any]],
    available: bool,
    complete: bool,
    reason: Optional[str],
    time_range: Any,
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Project exact outcome-ID links without asserting workflow causation."""
    invocation_evidence = {
        invocation_id: ref
        for row in invocation_rows
        if (invocation_id := _safe_identifier(row.get("invocation_id"))) is not None
        and (ref := next((item for item in invocation_refs if item.id == invocation_id), None))
        is not None
    }
    lower = _parse_timestamp(getattr(time_range, "from_", None)) if time_range else None
    upper = _parse_timestamp(getattr(time_range, "to", None)) if time_range else None
    lower_raw = getattr(time_range, "from_", None) if time_range else None
    upper_raw = getattr(time_range, "to", None) if time_range else None
    invalid_window = bool(
        time_range is not None
        and (
            (lower_raw is not None and lower is None)
            or (upper_raw is not None and upper is None)
            or (lower is not None and upper is not None and upper < lower)
        )
    )
    invalid_rows = False
    filtered_outside_time_range = False
    records: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    all_refs: list[EvidenceRef] = []
    returned_observed_at: list[str] = []
    for link in outcome_rows:
        outcome = link.get("outcome_record")
        outcome_id = _safe_identifier(link.get("outcome_id"))
        definition_ref = _safe_token(outcome.get("definition_ref")) if isinstance(outcome, dict) else None
        outcome_state = (
            _safe_token(outcome.get("state"), allowed=set(_OUTCOME_STATES))
            if isinstance(outcome, dict)
            else None
        )
        value_state = (
            _safe_token(outcome.get("value_state"), allowed=set(_OUTCOME_VALUE_STATES))
            if isinstance(outcome, dict)
            else None
        )
        invocation_ids = link.get("invocation_ids")
        if (
            not isinstance(outcome, dict)
            or link.get("tenant_id") != tenant_id
            or link.get("workflow_run_id") != subject.id
            or outcome.get("tenant_id") != tenant_id
            or outcome.get("outcome_id") != outcome_id
            or outcome_id is None
            or definition_ref is None
            or outcome_state is None
            or value_state is None
            or not isinstance(invocation_ids, list)
            or not invocation_ids
        ):
            invalid_rows = True
            continue

        outcome_evidence_raw = outcome.get("evidence_refs")
        outcome_evidence: list[EvidenceRef] = []
        if isinstance(outcome_evidence_raw, list):
            for raw_ref in outcome_evidence_raw:
                try:
                    outcome_evidence.append(EvidenceRef.model_validate(raw_ref))
                except Exception:  # noqa: BLE001 - invalid canonical provenance is omitted
                    invalid_rows = True
        if not outcome_evidence:
            invalid_rows = True
            continue
        invocation_refs_for_outcome = [
            invocation_evidence[invocation_id]
            for raw_id in invocation_ids
            if (invocation_id := _safe_identifier(raw_id)) is not None
            and invocation_id in invocation_evidence
        ]
        if len(invocation_refs_for_outcome) != len(invocation_ids):
            invalid_rows = True
            continue

        outcome_observed_at = (
            _safe_timestamp(outcome.get("achieved_at"))
            or _safe_timestamp(outcome.get("observed_at"))
            or _safe_timestamp(outcome.get("updated_at"))
        )
        outcome_instant = _parse_timestamp(outcome_observed_at)
        if time_range is not None:
            if outcome_instant is None:
                invalid_rows = True
                continue
            if (lower is not None and outcome_instant < lower) or (
                upper is not None and outcome_instant > upper
            ):
                filtered_outside_time_range = True
                continue

        value_amount: Optional[str] = None
        value_currency = _safe_token(outcome.get("value_currency"))
        if value_state in {"present", "zero"}:
            raw_amount = outcome.get("value_amount")
            if raw_amount is None and value_state == "zero":
                value_amount = "0"
            elif raw_amount is None:
                invalid_rows = True
                continue
            else:
                try:
                    amount = Decimal(str(raw_amount))
                except (InvalidOperation, ValueError, TypeError):
                    invalid_rows = True
                    continue
                if not amount.is_finite() or (value_state == "zero" and amount != 0):
                    invalid_rows = True
                    continue
                value_amount = str(raw_amount)

        canonical_refs = _dedupe_evidence_refs(outcome_evidence)
        invocation_refs_for_outcome = _dedupe_evidence_refs(invocation_refs_for_outcome)
        evidence_refs = _dedupe_evidence_refs(invocation_refs_for_outcome + canonical_refs)
        if not evidence_refs:
            invalid_rows = True
            continue
        record = {
            "outcomeId": outcome_id,
            "definitionRef": definition_ref,
            "outcomeState": outcome_state,
            "claimType": _safe_token(
                outcome.get("claim_type"), allowed=set(CLAIM_TYPES)
            ),
            "achievedAt": _safe_timestamp(outcome.get("achieved_at")),
            "valueState": value_state,
            "linkedInvocationIds": sorted(
                value for raw in invocation_ids if (value := _safe_identifier(raw)) is not None
            ),
            "outcomeEvidenceRefs": [
                ref.model_dump(mode="json") for ref in canonical_refs
            ],
            "invocationEvidenceRefs": [
                ref.model_dump(mode="json") for ref in invocation_refs_for_outcome
            ],
            "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
        }
        if value_amount is not None:
            record["valueAmount"] = value_amount
            if value_currency is not None:
                record["valueCurrency"] = value_currency
        records.append(record)
        if outcome_observed_at is not None:
            returned_observed_at.append(outcome_observed_at)
        all_refs.extend(evidence_refs)
        claims.append(
            ClaimEnvelope(
                id=f"workflow360.outcome.{quote(outcome_id, safe='')}",
                kind="canonical_outcome_explicitly_referenced_by_workflow_run_invocation",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    f"A tenant-scoped AI invocation linked to workflow run {subject.id} explicitly references canonical outcome {outcome_id}, and the tenant outcome authority contains that record; this establishes association, not workflow causation or complete outcome coverage."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["outcomes", "evidence_trace"],
            )
        )

    records.sort(key=lambda row: (row.get("achievedAt") or "", row["outcomeId"]))
    if invalid_window:
        state = "unknown"
        reason_code = "workflow_outcome_time_window_invalid"
    elif records:
        state = "degraded"
        reason_code = reason or (
            "canonical_outcomes_linked_by_invocation_reference_only"
            if complete and not invalid_rows
            else "workflow_outcome_reference_coverage_incomplete"
        )
    else:
        state = "unknown"
        reason_code = (
            reason
            or "canonical_workflow_outcome_records_not_available"
        )
        if not invocation_rows:
            reason_code = reason or "workflow_run_invocation_outcome_references_not_recorded"
        elif not any(_safe_identifier(row.get("outcome_id")) for row in invocation_rows):
            reason_code = "workflow_run_invocation_outcome_references_not_recorded"
        elif filtered_outside_time_range:
            reason_code = "no_canonical_workflow_outcome_in_requested_time_range"
    latest_observed_at = max(returned_observed_at, default=None)
    content = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "outcomes": records,
        "outcomeCoverageState": (
            "partial_explicit_invocation_outcome_refs_only" if records else "unknown"
        ),
        "workflowOutcomeCausalityState": "not_established",
        "sourceReadCompleteForReportedOutcomeRefs": complete and not invalid_rows,
        "freshness": {
            "state": "unknown",
            "latestReturnedObservedAt": latest_observed_at,
            "evidenceReadCompleteForReportedRefs": complete,
            "thresholdSeconds": None,
            "freshnessAuthorityState": "unknown",
            "reasonCode": "workflow_outcome_freshness_threshold_not_configured",
        },
        "evidenceRefs": [
            ref.model_dump(mode="json") for ref in _dedupe_evidence_refs(all_refs)
        ],
        "reasonCode": reason_code,
    }
    if available:
        content["returnedCanonicalOutcomeCount"] = len(records)
    if records:
        content["canonicalOutcomeCount"] = len(records)
    if invalid_rows:
        content["invalidOutcomeEvidenceDropped"] = True
    if filtered_outside_time_range:
        content["outcomesFilteredByRequestedTimeRange"] = True
    return (
        ProjectionSection(
            id="outcomes",
            state=state,
            title="Canonical workflow-linked outcome evidence",
            content=content,
            warnings=[
                "Only canonical outcomes explicitly referenced by linked AI invocations are shown; this join does not establish workflow causation or complete business outcome coverage."
                if records
                else reason_code
            ],
            canonicalAuthorityRefs=(
                [_SOURCE, _OUTCOME_SOURCE] if available and records else None
            ),
        ),
        claims,
    )


def _workflow_risk_section(
    subject: Any,
    *,
    tenant_id: str,
    read: WorkflowRiskAssessmentRead,
    execution_rows: list[dict[str, Any]],
    execution_refs: list[EvidenceRef],
    execution_inventory_complete: bool,
    time_range: Any,
    requested: bool,
    historical: bool,
    subject_supported: bool,
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Project risk snapshots only through admitted exact run-linked executions."""
    if not requested:
        return _unknown_section("risk"), []
    if historical:
        return (
            ProjectionSection(
                id="risk",
                state="unknown",
                title="Workflow risk evidence",
                content={
                    "state": "unknown",
                    "reasonCode": "workflow_risk_historical_state_unavailable",
                    "assessments": [],
                    "evidenceRefs": [],
                    "historicalRiskState": "unknown",
                },
                warnings=["workflow_risk_historical_state_unavailable"],
                canonicalAuthorityRefs=["risk_assessments", _AGENT_EXECUTION_SOURCE],
            ),
            [],
        )

    reason = (
        "subject_kind_not_supported_by_workflow_run_evidence"
        if not subject_supported
        else read.reason or "no_admitted_run_linked_agent_execution_for_risk_join"
        if not execution_rows
        else read.reason or "canonical_execution_risk_assessment_source_unavailable"
        if not read.available
        else _safe_reason(read.reason)
    )
    execution_evidence_by_id = {
        execution_id: ref
        for row in execution_rows
        if (execution_id := _safe_identifier(row.get("execution_id"))) is not None
        and (ref := next((item for item in execution_refs if item.id == execution_id), None))
        is not None
    }
    from intelligence.risk360.contracts import RiskAssessment

    records: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    all_refs: list[EvidenceRef] = []
    invalid_seen = read.scope_mismatch
    filtered_outside_time_range = False
    lower_raw = getattr(time_range, "from_", None) if time_range else None
    upper_raw = getattr(time_range, "to", None) if time_range else None
    lower = _parse_timestamp(lower_raw) if lower_raw else None
    upper = _parse_timestamp(upper_raw) if upper_raw else None
    invalid_window = bool(
        time_range is not None
        and (
            (lower_raw is not None and lower is None)
            or (upper_raw is not None and upper is None)
            or (lower is not None and upper is not None and upper < lower)
        )
    )
    seen_assessment_ids: set[str] = set()
    for raw in read.rows if read.available else ():
        if not isinstance(raw, dict) or raw.get("tenant_id") != tenant_id:
            invalid_seen = True
            continue
        execution_id = _safe_identifier(raw.get("subject_id"))
        if (
            raw.get("subject_kind") != "execution"
            or execution_id is None
            or execution_id not in execution_evidence_by_id
        ):
            invalid_seen = True
            continue
        try:
            assessment = RiskAssessment.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed canonical rows are not evidence
            invalid_seen = True
            continue
        if (
            not assessment.assessment_id.strip()
            or assessment.assessment_id in seen_assessment_ids
            or assessment.subject_kind != "execution"
            or assessment.subject_id != execution_id
            or assessment.tenant_id != tenant_id
        ):
            invalid_seen = True
            continue
        assessed_at = assessment.assessed_at
        if assessed_at is not None:
            if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
                invalid_seen = True
                continue
            assessed_at = assessed_at.astimezone(timezone.utc)
        if time_range is not None:
            if assessed_at is None:
                invalid_seen = True
                continue
            if (lower is not None and assessed_at < lower) or (
                upper is not None and assessed_at > upper
            ):
                filtered_outside_time_range = True
                continue

        observed_at = assessed_at.isoformat() if assessed_at is not None else None
        assessment_ref = EvidenceRef(
            id=assessment.assessment_id,
            type="model_output",
            source="risk_assessments",
            observedAt=observed_at,
            uri=(
                "store://risk_assessments/"
                f"{quote(f'{tenant_id}:{assessment.assessment_id}', safe='')}"
            ),
        )
        assessment_refs = [assessment_ref, *assessment.evidence_refs]
        for component in assessment.vector.components:
            assessment_refs.extend(component.evidence_refs)
        assessment_refs = _dedupe_evidence_refs(assessment_refs)
        if not assessment_refs or any(
            not ref.id.strip() or not ref.source.strip() for ref in assessment_refs
        ):
            invalid_seen = True
            continue
        evidence_refs = _dedupe_evidence_refs(
            [execution_evidence_by_id[execution_id], *assessment_refs]
        )
        records.append(
            {
                "executionId": execution_id,
                "assessmentId": assessment.assessment_id,
                "policyId": assessment.policy_id,
                "policyVersion": assessment.policy_version,
                "dimensions": list(assessment.dimensions),
                "claimState": assessment.claim_state.value,
                "confidence": assessment.confidence,
                "assessedAt": observed_at,
                "runId": assessment.run_id,
                "components": [
                    {
                        "dimension": component.dimension,
                        "state": component.state.value,
                        "score": component.score,
                        "claimState": component.claim_state.value,
                        "confidence": component.confidence,
                        "evidenceRefs": [
                            ref.model_dump(
                                mode="json", by_alias=True, exclude_none=True
                            )
                            for ref in component.evidence_refs
                        ],
                    }
                    for component in assessment.vector.components
                ],
                "evidenceRefs": [
                    ref.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for ref in evidence_refs
                ],
                "associationBoundary": "recorded_execution_subject_not_workflow_causation",
            }
        )
        seen_assessment_ids.add(assessment.assessment_id)
        all_refs.extend(evidence_refs)
        claims.append(
            ClaimEnvelope(
                id=f"workflow360.risk_assessment.{quote(assessment.assessment_id, safe='')}",
                kind="risk_assessment_recorded_for_run_linked_execution",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    "A tenant-scoped canonical RiskAssessment names an exact AgentExecution linked to this workflow run; this records subject association only and does not establish workflow causation, complete risk coverage, or current policy authority."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["risk", "evidence_trace"],
            )
        )

    complete = bool(
        read.available
        and read.complete
        and not read.scope_mismatch
        and not invalid_seen
        and execution_inventory_complete
    )
    if invalid_window:
        state = "unknown"
        reason = "workflow_risk_time_window_invalid"
        records = []
        claims = []
        all_refs = []
    elif not subject_supported or not execution_rows:
        state = "unknown"
    elif not read.available:
        state = "unknown"
    elif not execution_inventory_complete or invalid_seen or not read.complete:
        state = "degraded"
        reason = read.reason or "run_execution_or_risk_assessment_scope_incomplete"
    elif records:
        state = "available"
        reason = "exact_execution_risk_assessment_snapshots_history_and_freshness_unknown"
    else:
        state = "empty"
        reason = (
            "no_execution_risk_assessments_in_requested_time_range"
            if filtered_outside_time_range
            else "no_recorded_execution_risk_assessments_for_admitted_workflow_executions"
        )

    latest_assessed_at = max(
        (item["assessedAt"] for item in records if item["assessedAt"] is not None),
        default=None,
    )
    content = {
        "state": state,
        "reasonCode": reason,
        "scope": "current canonical assessments for exact run-linked AgentExecution subjects",
        "assessmentCount": len(records) if read.available else None,
        "assessments": records,
        "sourceReadState": "available" if read.available else "unavailable",
        "sourceReadCompleteForExactExecutionSubjects": complete,
        "workflowExecutionCoverage": {
            "state": "partial" if execution_rows else "unknown",
            "reason": "complete_workflow_definition_and_execution_coverage_not_available",
        },
        "riskHistoryCoverage": {
            "state": "unknown",
            "reason": "risk_assessment_history_not_reconstructed",
        },
        "freshness": {
            "state": "unknown",
            "latestAssessedAt": latest_assessed_at,
            "reason": "no_workflow_execution_risk_freshness_threshold_is_configured",
        },
        "policyAuthority": {
            "state": "unknown",
            "reason": "recorded_policy_id_and_version_do_not_prove_current_or_replayed_authority",
        },
        "causalAttribution": {
            "state": "unknown",
            "reason": "execution_subject_association_does_not_establish_workflow_causation",
        },
        "truncated": not complete,
        "evidenceRefs": [
            ref.model_dump(mode="json", by_alias=True, exclude_none=True)
            for ref in _dedupe_evidence_refs(all_refs)
        ],
    }
    return (
        ProjectionSection(
            id="risk",
            state=state,
            title="Workflow risk evidence",
            content=content,
            warnings=[
                "workflow_execution_coverage_and_risk_history_remain_unknown",
                "execution_risk_assessment_subject_links_do_not_prove_workflow_causation_or_current_policy_authority",
                "workflow_execution_risk_freshness_threshold_not_configured",
            ],
            canonicalAuthorityRefs=["risk_assessments", _AGENT_EXECUTION_SOURCE],
        ),
        claims,
    )


def _model_or_dict(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            data = dump(mode="json")
        except TypeError:
            data = dump()
        return data if isinstance(data, dict) else None
    return None


def _public_agent_execution(row: dict[str, Any]) -> dict[str, Any]:
    """Project execution identifiers and status, omitting claims and private payloads."""
    return {
        "executionId": _safe_identifier(row.get("execution_id")),
        "agentId": _safe_identifier(row.get("agent_id")),
        "status": _safe_token(
            row.get("status"),
            allowed={"running", "completed", "succeeded", "failed", "cancelled", "timeout"},
        ),
        "startedAt": _safe_timestamp(row.get("started_at")),
        "endedAt": _safe_timestamp(row.get("ended_at")),
        "delegationId": _safe_identifier(row.get("delegation_id")),
        "sourceRecordKind": "canonical_agent_execution",
    }


def _agent_execution_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    execution_id = _safe_identifier(row.get("execution_id"))
    tenant_id = _safe_identifier(row.get("tenant_id"))
    if execution_id is None or tenant_id is None:
        return None
    observed_at = _safe_timestamp(row.get("ended_at")) or _safe_timestamp(
        row.get("started_at")
    )
    store_key = quote(f"{tenant_id}:{execution_id}", safe="")
    return EvidenceRef(
        id=execution_id,
        type="event",
        source=_AGENT_EXECUTION_SOURCE,
        observedAt=observed_at,
        uri=f"store://{_AGENT_EXECUTION_SOURCE}/{store_key}",
    )


def _agent_steps_section(
    subject: Any,
    *,
    tenant_id: str,
    rows: list[dict[str, Any]],
    refs: list[EvidenceRef],
    invocation_refs: list[EvidenceRef],
    available: bool,
    complete: bool,
    reason: Optional[str],
) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
    """Expose exact run-linked canonical Agent executions as partial step evidence."""
    evidence_by_execution = {ref.id: ref for ref in refs}
    invocation_evidence = {ref.id: ref for ref in invocation_refs}
    records = [
        _public_agent_execution(row)
        for row in rows
        if _safe_identifier(row.get("execution_id")) in evidence_by_execution
    ]
    records.sort(key=lambda row: (row.get("startedAt") or "", row["executionId"]))
    ordered_refs = [evidence_by_execution[row["executionId"]] for row in records]
    latest_observed_at = max(
        (ref.observedAt for ref in ordered_refs if ref.observedAt is not None),
        default=None,
    )
    claims = [
        ClaimEnvelope(
            id=f"workflow360.agent_step.{quote(record['executionId'], safe='')}",
            kind="canonical_agent_execution_explicitly_linked_to_workflow_run",
            subject=subject,
            evidenceRefs=[
                evidence_by_execution[record["executionId"]],
                *[
                    invocation_evidence[invocation_id]
                    for invocation_id in (
                        _safe_identifier(value)
                        for value in next(
                            row.get("workflow_run_invocation_ids") or []
                            for row in rows
                            if _safe_identifier(row.get("execution_id"))
                            == record["executionId"]
                        )
                    )
                    if invocation_id in invocation_evidence
                ],
            ],
            claims=[
                "A tenant-scoped canonical Agent execution explicitly records the requested workflow_run_id; this does not establish that all workflow steps are represented or that the workflow run completed."
            ],
            claimState=EpistemicStatus.OBSERVED,
            domainSlotIds=["agent_steps", "evidence_trace"],
        )
        for record in records
    ]
    has_records = bool(records)
    source_reason = reason or (
        "canonical_agent_execution_read_truncated" if not complete else None
    )
    if has_records:
        reason_code = source_reason or (
            "canonical_agent_execution_records_linked_but_step_coverage_partial"
        )
    else:
        reason_code = source_reason or "agent_execution_workflow_run_link_not_available"
    content = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "steps": records,
        "stepCoverageState": (
            "partial_exactly_linked_agent_execution_records_only"
            if has_records
            else "unknown"
        ),
        "workflowStepAuthorityState": "unknown",
        "sourceReadCompleteForExactLinks": complete,
        "policyState": "unknown",
        "policyReasonCode": "workflow_agent_step_policy_context_not_joined",
        "freshness": {
            "state": "unknown",
            "latestReturnedObservedAt": latest_observed_at,
            "evidenceReadCompleteForExactLinks": complete,
            "thresholdSeconds": None,
            "freshnessAuthorityState": "unknown",
            "reasonCode": "workflow_agent_step_freshness_threshold_not_configured",
        },
        "evidenceRefs": [ref.model_dump(mode="json") for ref in ordered_refs],
        "reasonCode": reason_code,
    }
    if available:
        content["returnedCanonicalAgentExecutionCount"] = len(records)
    if has_records:
        content["canonicalAgentExecutionCount"] = len(records)
    # The exact linked records are available; the product slot is degraded by
    # the registry's explicit full-step-coverage limitation.
    state = "available" if has_records else "unknown"
    warning = (
        "Only canonical Agent execution records with an exact workflow_run_id are shown; the repository does not establish complete step coverage, policy state, or freshness."
        if has_records
        else "No canonical Agent execution record with this exact workflow_run_id is available; no step list is inferred from AI invocation telemetry."
    )
    return (
        ProjectionSection(
            id="agent_steps",
            state=state,
            title="Workflow agent step evidence",
            content=content,
            warnings=[warning],
            canonicalAuthorityRefs=[_AGENT_EXECUTION_SOURCE] if available else None,
        ),
        claims,
    )


def _triggers_section(
    subject: Any,
    *,
    tenant_id: str,
    execution_rows: list[dict[str, Any]],
    execution_refs: list[EvidenceRef],
    read: WorkflowTriggerRead,
    time_range: Any,
) -> tuple[ProjectionSection, list[ClaimEnvelope], list[EvidenceRef]]:
    """Project only tenant events referenced by exact run-linked executions.

    ``triggered_by_event_id`` is caller-reported execution metadata. Exact event
    resolution establishes a stored reference; it does not establish causal
    workflow triggering or complete workflow trigger coverage.
    """
    execution_evidence = {ref.id: ref for ref in execution_refs}
    expected_by_event: dict[str, set[str]] = {}
    missing_execution_reference = False
    invalid_execution_reference = False
    for row in execution_rows:
        execution_id = (
            _safe_identifier(row.get("execution_id"))
            if isinstance(row, dict) and row.get("tenant_id") == tenant_id
            and row.get("workflow_run_id") == subject.id
            else None
        )
        raw_event_id = row.get("triggered_by_event_id") if isinstance(row, dict) else None
        if execution_id is None or execution_id not in execution_evidence:
            invalid_execution_reference = True
            continue
        if raw_event_id is None or raw_event_id == "":
            missing_execution_reference = True
            continue
        event_id = _safe_identifier(raw_event_id)
        if event_id is None:
            invalid_execution_reference = True
            continue
        expected_by_event.setdefault(event_id, set()).add(execution_id)

    lower = _parse_timestamp(getattr(time_range, "from_", None)) if time_range else None
    upper = _parse_timestamp(getattr(time_range, "to", None)) if time_range else None
    lower_raw = getattr(time_range, "from_", None) if time_range else None
    upper_raw = getattr(time_range, "to", None) if time_range else None
    invalid_window = bool(
        time_range is not None
        and (
            (lower_raw is not None and lower is None)
            or (upper_raw is not None and upper is None)
            or (lower is not None and upper is not None and upper < lower)
        )
    )

    source_readable = bool(
        read.available and read.source_read_state == "available"
    )
    invalid_read = not isinstance(read.rows, (tuple, list))
    invalid_record = invalid_execution_reference or invalid_read
    seen_event_ids: set[str] = set()
    filtered_outside_time_range = False
    records: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    all_refs: list[EvidenceRef] = []
    # Fail closed if the adapter reports that the event authority was not read
    # or is unavailable. A stale/inconsistent adapter result must not turn
    # payload rows into canonical event evidence.
    rows = (
        read.rows
        if source_readable and isinstance(read.rows, (tuple, list))
        else ()
    )
    for raw in rows:
        event_id = _safe_identifier(raw.get("event_id")) if isinstance(raw, dict) else None
        execution_ids_raw = raw.get("execution_ids") if isinstance(raw, dict) else None
        event_type = (
            _safe_token(raw.get("event_type")) if isinstance(raw, dict) else None
        )
        event_at = _parse_timestamp(raw.get("occurred_at")) if isinstance(raw, dict) else None
        if (
            not isinstance(raw, dict)
            or raw.get("tenant_id") != tenant_id
            or raw.get("workflow_run_id") != subject.id
            or event_id is None
            or event_id not in expected_by_event
            or event_id in seen_event_ids
            or event_type is None
            or not isinstance(execution_ids_raw, list)
            or any(_safe_identifier(value) is None for value in execution_ids_raw)
            or set(execution_ids_raw) != expected_by_event.get(event_id, set())
        ):
            invalid_record = True
            continue
        seen_event_ids.add(event_id)
        if time_range is not None:
            if event_at is None:
                invalid_record = True
                continue
            if (lower is not None and event_at < lower) or (
                upper is not None and event_at > upper
            ):
                filtered_outside_time_range = True
                continue

        event_ref = EvidenceRef(
            id=event_id,
            type="event",
            source=_EVENT_SOURCE,
            observedAt=event_at.isoformat() if event_at is not None else None,
            uri=f"store://events/{quote(event_id, safe='')}",
        )
        linked_execution_ids = sorted(expected_by_event[event_id])
        linked_execution_refs = [
            execution_evidence[execution_id]
            for execution_id in linked_execution_ids
            if execution_id in execution_evidence
        ]
        if len(linked_execution_refs) != len(linked_execution_ids):
            invalid_record = True
            continue
        evidence_refs = _dedupe_evidence_refs([event_ref, *linked_execution_refs])
        record = {
            "eventId": event_id,
            "eventType": event_type,
            "occurredAt": event_at.isoformat() if event_at is not None else None,
            "linkedExecutionIds": linked_execution_ids,
            "referenceKind": "agent_execution_triggered_by_event_id",
            "causalityState": "not_established",
            "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
        }
        records.append(record)
        all_refs.extend(evidence_refs)
        claims.append(
            ClaimEnvelope(
                id=f"workflow360.trigger_reference.{quote(event_id, safe='')}",
                kind="tenant_event_referenced_by_workflow_run_execution",
                subject=subject,
                evidenceRefs=evidence_refs,
                claims=[
                    "A tenant-scoped canonical AgentExecution linked to this workflow run records a triggered_by_event_id that resolves to this tenant event; this proves the stored reference, not event causation or complete workflow trigger coverage."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["triggers", "evidence_trace"],
            )
        )

    exact_source_complete = (
        source_readable
        and read.complete
        and not read.scope_mismatch
        and not invalid_record
        and not missing_execution_reference
        and seen_event_ids == set(expected_by_event)
    )
    if invalid_window:
        state = "unknown"
        reason_code = "workflow_trigger_time_window_invalid"
    elif records:
        state = "degraded"
        reason_code = (
            _safe_reason(read.reason)
            or "execution_event_references_do_not_establish_workflow_causation_or_complete_trigger_coverage"
            if exact_source_complete
            else _safe_reason(read.reason)
            or "workflow_trigger_event_reference_coverage_incomplete"
        )
    elif read.source_read_state == "not_read":
        state = "unknown"
        reason_code = _safe_reason(read.reason) or "workflow_trigger_event_source_not_read"
    elif not source_readable:
        state = "degraded"
        reason_code = _safe_reason(read.reason) or "workflow_trigger_event_source_unavailable"
    elif filtered_outside_time_range:
        state = "unknown"
        reason_code = "workflow_trigger_events_outside_requested_time_range"
    elif invalid_record or read.scope_mismatch:
        state = "degraded"
        reason_code = _safe_reason(read.reason) or "workflow_trigger_event_scope_incomplete"
    else:
        state = "unknown"
        reason_code = _safe_reason(read.reason) or (
            "workflow_trigger_event_reference_not_available"
        )

    records.sort(key=lambda item: (item.get("occurredAt") or "", item["eventId"]))
    all_refs = _dedupe_evidence_refs(all_refs)
    content = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "triggers": records,
        "triggerCoverageState": (
            "partial_exact_execution_event_references_only" if records else "unknown"
        ),
        "workflowTriggerAuthorityState": "unknown",
        "causalityState": "reference_only",
        "sourceReadState": read.source_read_state,
        "sourceReadCompleteForExactEventReferences": exact_source_complete,
        "freshness": {
            "state": "unknown",
            "latestReturnedObservedAt": max(
                (record["occurredAt"] for record in records if record["occurredAt"]),
                default=None,
            ),
            "thresholdSeconds": None,
            "reasonCode": "workflow_trigger_freshness_threshold_not_configured",
        },
        "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
        "reasonCode": reason_code,
    }
    return (
        ProjectionSection(
            id="triggers",
            state=state,
            title="Workflow trigger event references",
            content=content,
            warnings=[
                "Only exact tenant events referenced by run-linked AgentExecution records are shown; the stored reference does not prove causal triggering or complete workflow trigger coverage."
                if records
                else reason_code
            ],
            canonicalAuthorityRefs=(
                [_AGENT_EXECUTION_SOURCE, "events"]
                if source_readable
                else None
            ),
        ),
        claims,
        all_refs,
    )


def _failure_section(
    subject: Any,
    *,
    tenant_id: str,
    records: list[dict[str, Any]],
    refs: list[EvidenceRef],
    available: bool,
    complete: bool,
    reason: Optional[str],
) -> ProjectionSection:
    failed_records = [record for record in records if record.get("status") == "failed"]
    failed_ids = {record["invocationId"] for record in failed_records}
    failed_refs = [ref for ref in refs if ref.id in failed_ids]
    has_evidence = bool(records)
    failure_scope_state = "partial" if has_evidence else "unknown"
    reason_code = (
        "workflow_failure_authority_not_available"
        if not has_evidence
        else "ai_invocation_failures_only_workflow_failures_not_joined"
    )
    return ProjectionSection(
        id="failures",
        state="degraded" if has_evidence else "unknown",
        title="Observed AI invocation failures",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "failureScope": "ai_invocation_status_only",
            "workflowFailureAuthorityState": "unknown",
            "scopeState": failure_scope_state,
            "observedAiInvocationFailures": failed_records,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in failed_refs],
            "sourceReadComplete": complete,
            "reasonCode": reason_code if has_evidence else reason or reason_code,
        },
        warnings=[
            "invocation status does not establish workflow failure or the absence of other workflow failures"
            if has_evidence
            else reason or reason_code
        ],
        canonicalAuthorityRefs=[_SOURCE] if available else None,
    )


def _evidence_trace_section(
    subject: Any,
    *,
    tenant_id: str,
    refs: list[EvidenceRef],
    agent_execution_refs: list[EvidenceRef],
    available: bool,
    complete: bool,
    agent_execution_available: bool,
    agent_execution_complete: bool,
    trigger_refs: list[EvidenceRef],
    trigger_available: bool,
    reason: Optional[str],
) -> ProjectionSection:
    all_refs = _dedupe_evidence_refs(refs + agent_execution_refs + trigger_refs)
    state = "degraded" if all_refs else "unknown"
    reason_code = "workflow_ai_invocation_and_agent_execution_lineage_partial"
    if not all_refs:
        reason_code = reason or "workflow_evidence_trace_not_available"
    elif not agent_execution_refs:
        reason_code = "only_ai_invocation_fact_lineage_is_connected"
    elif not refs:
        reason_code = "only_exact_agent_execution_lineage_is_connected"
    return ProjectionSection(
        id="evidence_trace",
        state=state,
        title="Workflow evidence trace",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "aiInvocationFactRefs": [ref.model_dump(mode="json") for ref in refs],
            "agentExecutionRefs": [
                ref.model_dump(mode="json") for ref in agent_execution_refs
            ],
            "triggerEventRefs": [
                ref.model_dump(mode="json") for ref in trigger_refs
            ],
            "workflowEventLineageState": "unknown",
            "readCompleteForAiInvocationFeed": complete,
            "readCompleteForExactAgentExecutionLinks": agent_execution_complete,
            "reasonCode": reason_code,
        },
        warnings=(
            ["AI invocation facts and/or canonical Agent executions are linked by exact workflow_run_id; workflow definition, full step coverage, and event lineage remain unknown"]
            if all_refs
            else [reason or "workflow evidence lineage is unknown"]
        ),
        canonicalAuthorityRefs=(
            ([_SOURCE] if available else [])
            + ([_AGENT_EXECUTION_SOURCE] if agent_execution_available else [])
            + (["events"] if trigger_available else [])
            or None
        ),
    )


def _scoped_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    tenant_id: str,
    workflow_run_id: Optional[str],
) -> tuple[list[dict[str, Any]], bool]:
    scoped: list[dict[str, Any]] = []
    scope_mismatch = False
    seen_invocation_ids: set[str] = set()
    for row in rows:
        invocation_id = (
            _safe_identifier(row.get("invocation_id")) if isinstance(row, dict) else None
        )
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or (workflow_run_id is not None and row.get("workflow_run_id") != workflow_run_id)
            or invocation_id is None
            or invocation_id in seen_invocation_ids
        ):
            scope_mismatch = True
            continue
        seen_invocation_ids.add(invocation_id)
        scoped.append(row)
    return scoped[:_MAX_INVOCATION_FACTS], scope_mismatch


def _public_invocation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "invocationId": _safe_identifier(row.get("invocation_id")),
        "status": _safe_token(row.get("status"), allowed={"succeeded", "failed", "cancelled", "timeout"}),
        "taskType": _safe_token(row.get("task_type")),
        "provider": _safe_token(row.get("provider")),
        "model": _safe_token(row.get("model")),
        "observedAt": _safe_timestamp(row.get("observed_at")),
        "sourceRecordKind": "derived_ai_invocation_fact",
    }


def _latest_returned_observed_at(records: list[dict[str, Any]]) -> Optional[str]:
    """Return the newest timestamp among returned invocation rows.

    AI invocation facts expose event observation time, but Workflow360 has no
    canonical run watermark or configured freshness SLA. A bounded incomplete
    read also cannot establish that this is the newest timestamp in the source.
    This value is lineage metadata only; it must not imply a fresh run.
    """
    timestamps = [
        parsed
        for record in records
        if (normalized := _safe_timestamp(record.get("observedAt"))) is not None
        and (parsed := _parse_timestamp(normalized)) is not None
    ]
    return max(timestamps).isoformat() if timestamps else None


def _invocation_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    invocation_id = _safe_identifier(row.get("invocation_id"))
    tenant_id = _safe_identifier(row.get("tenant_id"))
    if invocation_id is None or tenant_id is None:
        return None
    store_key = quote(f"{tenant_id}:{invocation_id}", safe="")
    return EvidenceRef(
        id=invocation_id,
        type="event",
        source=_SOURCE,
        observedAt=_safe_timestamp(row.get("observed_at")),
        uri=f"store://{_SOURCE}/{store_key}",
    )


def _safe_identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None
    return text


def _exact_identifier(value: Any) -> Optional[str]:
    """Accept a persisted join key only in its canonical, unpadded form."""
    if not isinstance(value, str) or value != value.strip():
        return None
    return _safe_identifier(value)


def _safe_token(value: Any, *, allowed: Optional[set[str]] = None) -> Optional[str]:
    token = _safe_identifier(value)
    if token is None or len(token) > 128:
        return None
    if any(not (char.isalnum() or char in "._:-") for char in token):
        return None
    return token if allowed is None or token in allowed else None


def _safe_reason(value: Any) -> Optional[str]:
    return _safe_token(value)


def _safe_timestamp(value: Any) -> Optional[str]:
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed is not None else None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_provider(registry: ProviderRegistry) -> None:
    """Register Workflow360 after its generated projection ID is available."""
    registry.register(
        Workflow360Provider(),
        source="services/api/intelligence/workflow/workflow360_provider",
    )


__all__ = [
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositoryWorkflow360Source",
    "Workflow360Provider",
    "WorkflowDefinitionRead",
    "WorkflowAgentIdentityRead",
    "WorkflowApprovalRead",
    "WorkflowPrincipalIdentityRead",
    "Workflow360Source",
    "WorkflowActionRead",
    "WorkflowOutcomeRead",
    "WorkflowRunInvocationRead",
    "register_provider",
]
