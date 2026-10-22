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
_RUN_SUBJECT_KINDS = frozenset({"run", "workflow_run"})
_SOURCE = "ai_execution_facts"


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


class Workflow360Source(Protocol):
    """Tenant-scoped exact-ID read seam for workflow run evidence."""

    async def run_invocations(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowRunInvocationRead: ...

    async def actor_identities(
        self, *, tenant_id: str, agent_ids: set[str], limit: int
    ) -> WorkflowAgentIdentityRead: ...


class RepositoryWorkflow360Source:
    """Adapter over the existing derived AI invocation facts store."""

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
        actor_section, actor_claims = _actors_section(
            subject,
            tenant_id=tenant_id,
            invocation_rows=rows,
            invocation_refs=valid_refs,
            requested_agent_ids=reported_agent_ids,
            identity_read=actor_identity_read,
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
            _unknown_section("approvals"),
            _unknown_section("agent_steps"),
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
                available=read_available,
                complete=read_complete,
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

    content = {
        "tenantId": tenant_id,
        "subject": {"kind": subject.kind, "id": subject.id},
        "actorCoverageState": "partial_ai_invocation_actor_refs_only" if actor_items else "unknown",
        "workflowActorAuthorityState": "unknown",
        "identityResolutionCompleteForReportedRefs": identity_complete,
        "actors": actor_items,
        "evidenceRefs": [
            ref.model_dump(mode="json") for ref in _dedupe_evidence_refs(all_evidence)
        ],
        "reasonCode": reason_code,
    }
    if requested_agent_ids:
        content["reportedAgentReferenceCount"] = len(requested_agent_ids)
    if actor_items:
        content["resolvedCanonicalAgentCount"] = len(actor_items)
    section = ProjectionSection(
        id="actors",
        state=state,
        title="Workflow actor evidence",
        content=content,
        warnings=[warning],
        canonicalAuthorityRefs=(
            ["ai_execution_facts", "agent_entities", "identity"] if actor_items else None
        ),
    )
    return section, claims


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


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
    available: bool,
    complete: bool,
    reason: Optional[str],
) -> ProjectionSection:
    state = "degraded" if refs else "unknown"
    reason_code = (
        "only_ai_invocation_fact_lineage_is_connected"
        if refs
        else reason or "workflow_evidence_trace_not_available"
    )
    return ProjectionSection(
        id="evidence_trace",
        state=state,
        title="Workflow evidence trace",
        content={
            "tenantId": tenant_id,
            "subject": {"kind": subject.kind, "id": subject.id},
            "aiInvocationFactRefs": [ref.model_dump(mode="json") for ref in refs],
            "workflowEventLineageState": "unknown",
            "readCompleteForAiInvocationFeed": complete,
            "reasonCode": reason_code,
        },
        warnings=(
            ["AI invocation facts are linked by exact workflow_run_id; workflow definition and event lineage remain unknown"]
            if refs
            else [reason or "workflow evidence lineage is unknown"]
        ),
        canonicalAuthorityRefs=[_SOURCE] if available else None,
    )


def _scoped_rows(
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    tenant_id: str,
    workflow_run_id: Optional[str],
) -> tuple[list[dict[str, Any]], bool]:
    scoped: list[dict[str, Any]] = []
    scope_mismatch = False
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or (workflow_run_id is not None and row.get("workflow_run_id") != workflow_run_id)
            or not _safe_identifier(row.get("invocation_id"))
        ):
            scope_mismatch = True
            continue
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
    "Workflow360Source",
    "WorkflowRunInvocationRead",
    "register_provider",
]
