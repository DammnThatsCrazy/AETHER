"""Read-only Workflow360 projection over exact workflow-run invocation refs.

The repository has no general workflow definition, trigger, schedule, approval,
or workflow-run state authority yet. The only exact workflow-run join currently
available is ``workflow_run_id`` on tenant-scoped ``ai_execution_facts``. This
provider exposes those records as observed AI invocations associated with the
requested run ID. It does not infer that they are a complete workflow trace,
that a workflow definition exists, or that a business outcome occurred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef
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
_RUN_SUBJECT_KINDS = frozenset({"run", "workflow_run"})
_APPROVAL_DECISION_ACTIONS = frozenset({"approve", "reject", "escalate", "revoke"})
_SOURCE = "ai_execution_facts"
_AGENT_EXECUTION_SOURCE = "agent_executions"


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


class Workflow360Source(Protocol):
    """Tenant-scoped exact-ID read seam for workflow run evidence."""

    async def run_invocations(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowRunInvocationRead: ...

    async def run_agent_executions(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowAgentExecutionRead: ...

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


class RepositoryWorkflow360Source:
    """Adapter over the existing derived AI invocation facts store."""

    def __init__(self, *, principal_identity_repository: Any = None) -> None:
        self._principal_identity_repository = principal_identity_repository

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
                        "decided_by": decision_data["decided_by"],
                        "decided_at": decision_data.get("decided_at"),
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
        claims.extend(actor_claims)
        claims.extend(approval_claims)
        claims.extend(agent_step_claims)

        sections: list[ProjectionSection] = [
            _unknown_section("workflow_summary"),
            _unknown_section("triggers"),
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
            _unknown_section("actions"),
            _failure_section(
                subject,
                tenant_id=tenant_id,
                records=records,
                refs=valid_refs,
                available=read_available,
                complete=read_complete,
                reason=read_reason,
            ),
            _unknown_section("outcomes"),
            _unknown_section("risk"),
            _evidence_trace_section(
                subject,
                tenant_id=tenant_id,
                refs=valid_refs,
                agent_execution_refs=agent_execution_refs,
                available=read_available,
                complete=read_complete,
                agent_execution_available=agent_execution_read.available,
                agent_execution_complete=agent_execution_read_complete,
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
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
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
    """Project execution identifiers and status only, omitting payload and reasoning."""
    return {
        "executionId": _safe_identifier(row.get("execution_id")),
        "agentId": _safe_identifier(row.get("agent_id")),
        "status": _safe_token(
            row.get("status"),
            allowed={"running", "completed", "succeeded", "failed", "cancelled", "timeout"},
        ),
        "startedAt": _safe_timestamp(row.get("started_at")),
        "endedAt": _safe_timestamp(row.get("ended_at")),
        "triggeredByEventId": _safe_identifier(row.get("triggered_by_event_id")),
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
    reason: Optional[str],
) -> ProjectionSection:
    all_refs = _dedupe_evidence_refs(refs + agent_execution_refs)
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
    "WorkflowAgentIdentityRead",
    "WorkflowApprovalRead",
    "WorkflowPrincipalIdentityRead",
    "Workflow360Source",
    "WorkflowRunInvocationRead",
    "register_provider",
]
