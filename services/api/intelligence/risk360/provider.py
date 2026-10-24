"""Risk360 intelligence-projection provider (Phase 4, Risk360/Fraud360 program).

Risk360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). This provider projects the *risk* domain
for a subject (``agent`` / ``entity`` / ``relationship`` / ``cluster`` /
``population`` / ``source``)
from the tenant's canonical risk records: the Phase-3
:class:`~intelligence.risk360.contracts.RiskAssessment` (the aggregation of risk
signals under a policy) and the :class:`~intelligence.risk360.contracts.RiskSignal`
atomic observations feeding it.

The provider is a read-only, fail-isolated, tenant-scoped projection:

* It never writes: ``graphMutationPolicy == "read_only"`` and there is no write
  path anywhere in this module. Detectors and the aggregation pipeline (Phase 5)
  write canonical ``RiskSignal`` / ``RiskAssessment`` rows through their own
  stores; this provider only reads them.
* It raises NO :class:`ProjectionError` in normal operation: a missing /
  empty backing store, an unavailable dependency, or a backing-source exception
  degrades its sections (typed ``degraded`` / ``missing`` / ``empty`` states)
  instead of crashing or fabricating.
* It is honest about absence: no assessment for the subject renders
  ``summary``/``state``/``findings`` as ``missing``; an assessment that records
  zero dimensions renders ``summary`` as ``empty`` (a real zero is legal when
  data supports it). A dimension with no observation is typed
  ``missing_inputs`` / ``not_applicable`` — NEVER a fabricated ``0``.
* Every claim and every per-dimension state row carries the canonical
  ``claim_state`` / confidence and reused :class:`EvidenceRef`s carried by the
  Phase-3 contracts.
* ``profile360`` / ``cluster360`` are still ``in_flight`` siblings: the
  registry's ``build_context`` records them in ``dependencyState`` and this
  provider degrades the sections their context would enrich (``summary`` ←
  ``profile360``, ``state`` ← ``cluster360`` population/context) honestly
  instead of raising.

The ``sources`` constructor seam is the read-only canonical seam (a
:class:`RiskSourceReader``) — abstract enough that Phase 5 wires real detector
output through it; the default :class:`RepositoryRiskSourceReader` reads the
Phase-3 ``risk_assessments`` / ``risk_signals`` stores tenant-scoped.

Imports stay lazy/defensive: importing this module must never require a
database, a store backend, or any heavy canonical service. All canonical reads
happen inside :meth:`Risk360Provider.project`, each wrapped so an unavailable
backing source degrades its section.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol
from urllib.parse import quote

from pydantic import ValidationError

# Lightweight plane imports — always importable.
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry

# Reused canonical primitives (never redefined here).
from graph.operational_intelligence.models import EvidenceRef

# Canonical measurement-plane value-state authority (honest absence, never 0).
from shared.measurement.value_states import requires_value

# Risk360 Phase-3 domain contracts + dimension registry + repositories.
from intelligence.risk360.contracts import (
    EpistemicStatus,
    RiskAssessment,
    RiskPoisoningEvidence,
    RiskSignal,
)
from intelligence.risk360.dimensions import RISK_DIMENSIONS
from intelligence.risk360.store import (
    RiskAssessmentRepository,
    RiskPoisoningEvidenceRead,
    RiskPoisoningEvidenceRepository,
    RiskPoisoningEvidenceReadIncomplete,
    RiskSignalRepository,
)
from journeys.support360.cases import SupportCaseAuthorityRead, SupportCaseRepository

PROJECTION_ID = "risk360"

# The projection's registry-declared capability keys (surface join). The route
# layer gates on ``risk360.read``; ``explore`` is the read-only exploration
# counterpart.
READ_CAPABILITY = "risk360.read"
EXPLORE_CAPABILITY = "risk360.explore"

# Sections this provider emits, exactly the OUTPUT_SECTIONS the orchestrator's
# registry row declares for risk360 (order is the projection's render order).
OUTPUT_SECTIONS: tuple[str, ...] = ("summary", "state", "evidence", "findings", "health")

# Sibling-projection dependencies we degrade honestly for while they are still
# in_flight. ``profile360`` enriches the subject's risk *summary*; ``cluster360``
# supplies the cluster/population-membership context behind the per-dimension
# risk *state* (the ``population`` dimension). economic360 is implemented and its
# exposure facts are already carried canonically on the RiskAssessment — no gate.
SECTION_DEPENDENCIES: dict[str, str] = {
    "summary": "profile360",
    "state": "cluster360",
}

_MAX_ASSESSMENT_SCAN = 50
_MAX_SIGNAL_SCAN = 100
_MAX_AGENT_POLICY_FLAG_SCAN = 100
_MAX_SOURCE_PROVENANCE_SCAN = 100
_MAX_POISONING_EVIDENCE_SCAN = 100
_MAX_ASSESSMENT_HISTORY_SCAN = 100
_MAX_FINANCIAL_PATH_NODES = 21
_MAX_TRANSFERS_PER_PATH_EDGE = 2
_MAX_SOCIAL_PROPAGATION_PATHS = 50

_BLUEPRINT_REQUIRED_SLOT_IDS = (
    "risk_summary",
    "anomaly_events",
    "policy_flags",
    "poisoning_evidence",
    "source_trust",
    "propagation_paths",
    "financial_contagion",
    "social_contagion",
    "agent_amplification",
    "interventions",
    "audit_history",
    "evidence_trace",
)


class RiskSourceReadIncomplete(RuntimeError):
    """A canonical risk read could not establish complete exact-subject scope."""


def _dependency_missing(dep_state: list[Any], projection_id: str) -> bool:
    """True when a sibling projection is missing or not yet available."""
    dep = next((d for d in dep_state if d.projectionId == projection_id), None)
    return dep is None or dep.state != "available"


def _risk_assessment_slot_ids(subject_kind: str) -> list[str]:
    """Map an assessed risk fact only to slots that render assessment state."""
    slots = [
        "risk_assessment_state",
        "risk_evidence_and_limitations",
        "risk_summary",
        "evidence_trace",
    ]
    if subject_kind == "support_case":
        # Support360 has an explicit required risk slot. Keep this binding
        # subject-specific until the surface registry maps Risk360 to it.
        slots.insert(0, "risk")
    return slots


def _risk_evidence_slot_ids(subject_kind: str) -> list[str]:
    """Map atomic risk observations to slots supported for this subject kind."""
    slot_ids = ["risk_evidence_and_limitations", "evidence_trace"]
    if subject_kind == "agent":
        # Agent subjects are accepted by Agent360; the exact summary slot is
        # the governed Risk360 destination. ``risk_signals`` is not a product
        # SSOT slot and must not escape as an invented compatibility binding.
        slot_ids.append("risk_summary")
    elif subject_kind == "support_case":
        slot_ids.insert(0, "risk")
    return slot_ids


def _is_agent_amplification_signal(signal: RiskSignal, subject_kind: str) -> bool:
    """Whether a canonical signal is the explicit delegation-abuse observation."""
    return (
        subject_kind == "agent"
        and signal.subject_kind == "agent"
        and signal.risk_dimension == "agentic"
        and signal.source == "aether.fraud.detector.delegation"
        and any(
            ref.type == "relationship" and ref.source == "aether.fraud.detector.delegation"
            for ref in signal.evidence_refs
        )
    )


def _decode_mapping(value: Any) -> dict[str, Any]:
    """Decode a stored JSON mapping without exposing or trusting malformed data."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _aware_datetime(value: Any) -> Optional[datetime]:
    """Parse a timezone-aware timestamp without inventing a timezone."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else None


def _positive_decimal(value: Any) -> bool:
    """Whether a source-recorded amount is a finite positive decimal."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return amount.is_finite() and amount > 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _only_projection_id_literal_errors(exc: ValidationError) -> bool:
    """True when every error is the projectionId Literal rejection only."""
    errors = exc.errors()
    if not errors:
        return False
    for err in errors:
        if err.get("type") != "literal_error" or err.get("loc") != ("projectionId",):
            return False
    return True


def build_projection_request(
    *,
    projection_id: str,
    tenant_id: str,
    subject: ProjectionSubject,
) -> ProjectionRequest:
    """Build a strict :class:`ProjectionRequest`, tolerating a not-yet-registered id."""
    try:
        return ProjectionRequest(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=subject,
        )
    except ValidationError as exc:
        if not _only_projection_id_literal_errors(exc):
            raise
        return ProjectionRequest.model_construct(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=subject,
        )


class RiskSourceReader(Protocol):
    """Canonical risk read seam for the provider.

    Implementations MUST be tenant-scoped: the provider trusts nothing and
    re-filters every returned record by the requesting tenant. A reader that
    cannot establish an available, complete, exact-subject read may raise; the
    provider boundary sanitizes that failure and degrades the affected section.

    The risk reads are the tenant's latest :class:`RiskAssessment` for the
    subject (the aggregation) and the atomic :class:`RiskSignal` records feeding
    it. Section mapping: ``summary`` /
    ``state`` / ``findings`` render from the assessment (+ its vector
    components), ``evidence`` from the EvidenceRefs both carry, and ``health``
    from the signal sources. Observed social graph paths use a separate,
    optional canonical graph reader; they are never risk detector output.
    Phase 5 wires real detector output here by writing typed RiskSignal /
    RiskAssessment rows these reads consume.
    """

    async def latest_assessment(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> Optional[dict[str, Any]]:
        """The tenant's latest RiskAssessment record for ``subject``, or None."""
        ...

    async def assessment_history(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: Optional[datetime],
    ) -> tuple[list[dict[str, Any]], bool]:
        """Bounded computation-run lineage for exact-subject risk assessments."""
        ...

    async def signals(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped RiskSignal records for ``subject`` (empty when none)."""
        ...

    async def agent_policy_flag_observations(
        self,
        *,
        tenant_id: str,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        """Exact tenant/agent observed policy-flag records, when available.

        These are observation-plane reports, not model-governance evaluation
        records. A consumer must preserve that limitation in slot coverage.
        """
        ...

    async def source_provenance_observations(
        self,
        *,
        tenant_id: str,
        source_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Bounded exact-source ingress classifications and evidence references.

        The boolean reports that the bounded scan exceeded its supported
        coverage, so partial rows must not be mistaken for a complete source
        history. This exposes ingress classification only; it is not a source
        reliability or poisoning assessment.
        """
        ...

    async def poisoning_evidence(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: Optional[datetime],
    ) -> RiskPoisoningEvidenceRead:
        """Bounded poisoning evidence for the exact tenant/subject binding."""
        ...

    async def financial_flow_path(
        self,
        *,
        tenant_id: str,
        path_id: str,
    ) -> Optional[dict[str, Any]]:
        """Read one exact tenant-owned flow path and its transfer evidence."""
        ...


class RepositoryRiskSourceReader:
    """Default canonical reader over the Phase-3 risk repositories.

    Reads the tenant-scoped ``RiskAssessmentRepository`` + ``RiskSignalRepository``
    defensively. Backing-source failures propagate to the projection's safe-read
    boundary, which marks the result degraded without exposing diagnostics.
    """

    def __init__(self) -> None:
        self._assessments = RiskAssessmentRepository()
        self._signals = RiskSignalRepository()
        self._poisoning_evidence = RiskPoisoningEvidenceRepository()
        from intelligence.computation.repositories import get_computation_repository

        self._runs = get_computation_repository()

    async def latest_assessment(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> Optional[dict[str, Any]]:
        """The tenant's latest RiskAssessment for the subject (or None).

        The repository order is not an ``assessed_at`` order, so this reads one
        row beyond the supported bound and declines to choose when more than the
        bound exists. It also rechecks exact tenant and subject scope.
        """
        rows = await self._assessments.list_by_subject(
            tenant_id,
            subject.kind,
            subject.id,
            limit=_MAX_ASSESSMENT_SCAN + 1,
        )
        scoped = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("tenant_id", "")) == tenant_id
            and str(row.get("subject_kind", "")) == subject.kind
            and str(row.get("subject_id", "")) == subject.id
        ]
        if len(scoped) != len(rows) or len(rows) > _MAX_ASSESSMENT_SCAN:
            raise RiskSourceReadIncomplete("risk assessment scope is incomplete")
        rows = scoped
        if not rows:
            return None
        rows.sort(key=lambda r: str(r.get("assessed_at") or ""), reverse=True)
        return rows[0]

    async def assessment_history(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: Optional[datetime],
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read exact-subject risk assessment run lineage from the substrate."""
        rows = await self._runs.list_runs_for_subject(
            tenant_id,
            subject.kind,
            subject.id,
            definition_prefix="risk360.",
            limit=_MAX_ASSESSMENT_HISTORY_SCAN + 1,
            as_of=as_of,
        )
        if not isinstance(rows, list):
            raise RiskSourceReadIncomplete("risk assessment history contract is invalid")
        complete = len(rows) <= _MAX_ASSESSMENT_HISTORY_SCAN
        history: list[dict[str, Any]] = []
        for row in rows[:_MAX_ASSESSMENT_HISTORY_SCAN]:
            if not isinstance(row, dict):
                raise RiskSourceReadIncomplete("risk assessment history row is invalid")
            data = _decode_mapping(row.get("data"))
            run_id = row.get("run_id")
            assessment_id = data.get("assessment_id")
            started_at = row.get("started_at")
            if (
                str(row.get("tenant_id", "")) != tenant_id
                or not str(row.get("definition_id", "")).startswith("risk360.")
                or data.get("subject_kind") != subject.kind
                or data.get("subject_id") != subject.id
                or not isinstance(run_id, str)
                or not run_id.strip()
                or not isinstance(assessment_id, str)
                or not assessment_id.strip()
            ):
                raise RiskSourceReadIncomplete("risk assessment history exact binding is invalid")
            if not isinstance(started_at, (str, datetime)) or _aware_datetime(started_at) is None:
                complete = False
                continue
            started = _aware_datetime(started_at)
            if as_of is not None and started is not None and started > as_of:
                raise RiskSourceReadIncomplete("risk assessment history exceeds as_of anchor")
            history.append(
                {
                    "tenant_id": tenant_id,
                    "subject_kind": subject.kind,
                    "subject_id": subject.id,
                    "run_id": run_id,
                    "assessment_id": assessment_id,
                    "definition_id": str(row.get("definition_id", "")),
                    "definition_version": row.get("definition_version"),
                    "context_hash": row.get("context_hash"),
                    "status": row.get("status"),
                    "started_at": started.isoformat() if started is not None else None,
                    "completed_at": (
                        _aware_datetime(row.get("completed_at")).isoformat()
                        if _aware_datetime(row.get("completed_at")) is not None
                        else None
                    ),
                    "supersedes_run_id": data.get("supersedes_run_id"),
                    "claim_state": data.get("claim_state"),
                    "dimensions": data.get("dimensions")
                    if isinstance(data.get("dimensions"), list)
                    else [],
                }
            )
        history.sort(key=lambda row: (row["started_at"] or "", row["run_id"]), reverse=True)
        return history, complete

    async def signals(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped RiskSignal rows for the subject (empty when none)."""
        rows = await self._signals.list_by_subject(
            tenant_id,
            subject.kind,
            subject.id,
            limit=_MAX_SIGNAL_SCAN + 1,
        )
        scoped = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("tenant_id", "")) == tenant_id
            and str(row.get("subject_kind", "")) == subject.kind
            and str(row.get("subject_id", "")) == subject.id
        ]
        if len(scoped) != len(rows) or len(rows) > _MAX_SIGNAL_SCAN:
            raise RiskSourceReadIncomplete("risk signal scope is incomplete")
        return scoped

    async def agent_policy_flag_observations(
        self,
        *,
        tenant_id: str,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        """Read exact reported agent flags; never consult another tenant or alias."""
        from repositories.agentic_observability_repos import AgentRiskSignalRepository

        rows = await AgentRiskSignalRepository().find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id},
            limit=_MAX_AGENT_POLICY_FLAG_SCAN + 1,
        )
        scoped = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("tenant_id", "")) == tenant_id
            and str(row.get("agent_id", "")) == agent_id
        ]
        if len(scoped) != len(rows) or len(rows) > _MAX_AGENT_POLICY_FLAG_SCAN:
            raise RiskSourceReadIncomplete("agent policy flag scope is incomplete")
        return scoped

    async def source_provenance_observations(
        self,
        *,
        tenant_id: str,
        source_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read exact-source ingress classifications from tenant Bronze rows.

        The join is the gateway-stamped observation envelope's explicit
        ``rights.source_id``. The result is deliberately limited to source
        provenance fields and a Bronze EvidenceRef; event payloads are never
        returned to Risk360. PostgreSQL applies tenant/source predicates and a
        hard result bound in the query. The in-memory adapter stops once it has
        enough matching rows to determine that the result is partial.
        """
        if not tenant_id or not source_id:
            return [], False

        from repositories.repos import _IN_MEMORY_STORES, get_pool

        limit = _MAX_SOURCE_PROVENANCE_SCAN + 1
        pool = await get_pool()
        if pool is None:
            candidates: list[dict[str, Any]] = []
            store = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
            for row in store.values():
                if not isinstance(row, dict) or str(row.get("tenant_id", "")) != tenant_id:
                    continue
                payload = _decode_mapping(row.get("payload"))
                envelope = _decode_mapping(payload.get("observation_envelope"))
                rights = _decode_mapping(envelope.get("rights"))
                if rights.get("source_id") != source_id:
                    continue
                candidates.append(row)
                if len(candidates) >= limit:
                    break
        else:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, tenant_id, event_id, event_timestamp, payload
                       FROM bronze_sdk_events
                       WHERE tenant_id = $1
                         AND payload #>> '{observation_envelope,rights,source_id}' = $2
                       ORDER BY received_at DESC, event_id ASC
                       LIMIT $3""",
                    tenant_id,
                    source_id,
                    limit,
                )
            candidates = [dict(row) for row in rows]

        truncated = len(candidates) > _MAX_SOURCE_PROVENANCE_SCAN
        observations: list[dict[str, Any]] = []
        for row in candidates[:_MAX_SOURCE_PROVENANCE_SCAN]:
            if str(row.get("tenant_id", "")) != tenant_id:
                raise RiskSourceReadIncomplete("source provenance tenant scope is incomplete")
            payload = _decode_mapping(row.get("payload"))
            envelope = _decode_mapping(payload.get("observation_envelope"))
            tenancy = _decode_mapping(envelope.get("tenancy"))
            rights = _decode_mapping(envelope.get("rights"))
            if rights.get("source_id") != source_id:
                # The SQL predicate/local filter and the decoded envelope must
                # agree. A malformed row makes source coverage incomplete.
                raise RiskSourceReadIncomplete("source provenance join is inconsistent")
            if tenancy.get("tenant_id") != tenant_id:
                raise RiskSourceReadIncomplete("source provenance envelope tenant mismatch")

            observation = _decode_mapping(envelope.get("observation"))
            provenance = _decode_mapping(envelope.get("provenance"))
            event_id = row.get("event_id") or observation.get("observation_id")
            bronze_id = row.get("id") or event_id
            if (
                not isinstance(event_id, str)
                or not event_id
                or not isinstance(bronze_id, str)
                or not bronze_id
            ):
                raise RiskSourceReadIncomplete("source provenance evidence reference is incomplete")

            observed_at = observation.get("occurred_at") or row.get("event_timestamp")
            if isinstance(observed_at, datetime):
                observed_at = observed_at.isoformat()
            if not isinstance(observed_at, str):
                observed_at = None

            evidence_ref = EvidenceRef(
                id=event_id,
                type="event",
                source="bronze_sdk_events",
                observedAt=observed_at,
                uri=f"store://bronze_sdk_events/{bronze_id}",
            )
            observations.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "observation_id": observation.get("observation_id") or event_id,
                    "source_trust": provenance.get("source_trust")
                    if isinstance(provenance.get("source_trust"), str)
                    else None,
                    "credential_class": provenance.get("credential_class")
                    if isinstance(provenance.get("credential_class"), str)
                    else None,
                    "signature_status": provenance.get("signature_status")
                    if isinstance(provenance.get("signature_status"), str)
                    else None,
                    "adapter": provenance.get("adapter")
                    if isinstance(provenance.get("adapter"), str)
                    else None,
                    "adapter_version": provenance.get("adapter_version")
                    if isinstance(provenance.get("adapter_version"), str)
                    else None,
                    "observed_at": observed_at,
                    "evidence_ref": evidence_ref.model_dump(mode="json"),
                }
            )
        return observations, truncated

    async def poisoning_evidence(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: Optional[datetime],
    ) -> RiskPoisoningEvidenceRead:
        """Read only explicitly bound, tenant-owned detector evidence."""
        if not tenant_id or not subject.kind or not subject.id:
            raise RiskPoisoningEvidenceReadIncomplete(
                "poisoning evidence requires exact tenant and subject scope"
            )
        return await self._poisoning_evidence.list_for_subject(
            tenant_id,
            subject.kind,
            subject.id,
            source_id=subject.id if subject.kind == "source" else None,
            as_of=as_of,
            limit=_MAX_POISONING_EVIDENCE_SCAN,
        )

    async def financial_flow_path(
        self,
        *,
        tenant_id: str,
        path_id: str,
    ) -> Optional[dict[str, Any]]:
        """Read a complete flow path and rejoin each edge to one transfer row.

        ``flow_trace_paths`` currently stores ordered entity IDs but does not
        retain transfer IDs. The reader therefore accepts only path rows whose
        hop count matches the ordered node list and whose adjacent entity pair
        has exactly one positive tenant-scoped transfer record. Missing or
        ambiguous pair joins remain explicit unknowns; unrelated transfers are
        never selected by recency or aggregated into a synthetic edge.
        """
        if not tenant_id or not path_id:
            return None

        from repositories.repos import (
            FlowTracePathRepository,
            FlowTraceRepository,
            TransferRepository,
        )

        path = await FlowTracePathRepository().find_by_id(path_id)
        if path is None:
            return None
        if (
            not isinstance(path, dict)
            or str(path.get("id", "")) != path_id
            or str(path.get("tenant_id", "")) != tenant_id
        ):
            raise RiskSourceReadIncomplete("financial flow path scope is incomplete")
        trace_id = path.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise RiskSourceReadIncomplete("financial flow trace reference is incomplete")
        trace = await FlowTraceRepository().find_by_id(trace_id)
        if (
            not isinstance(trace, dict)
            or str(trace.get("id", "")) != trace_id
            or str(trace.get("tenant_id", "")) != tenant_id
            or trace.get("status") != "complete"
        ):
            raise RiskSourceReadIncomplete("financial flow trace scope is incomplete")

        raw_nodes = path.get("path_nodes")
        hop_count = path.get("hop_count")
        if (
            not isinstance(raw_nodes, list)
            or not 2 <= len(raw_nodes) <= _MAX_FINANCIAL_PATH_NODES
            or any(not isinstance(node, str) or not node.strip() for node in raw_nodes)
            or isinstance(hop_count, bool)
            or not isinstance(hop_count, int)
            or hop_count != len(raw_nodes) - 1
            or len(set(raw_nodes)) < 2
        ):
            return {
                "tenant_id": tenant_id,
                "path_id": path_id,
                "trace_id": trace_id,
                "path_nodes": [],
                "transfer_edges": [],
                "linkage_reason": "financial_flow_path_sequence_not_exact",
            }

        transfer_repo = TransferRepository()
        transfer_edges: list[dict[str, Any]] = []
        for from_entity_id, to_entity_id in zip(raw_nodes, raw_nodes[1:]):
            rows = await transfer_repo.find_many(
                filters={
                    "tenant_id": tenant_id,
                    "from_entity_id": from_entity_id,
                    "to_entity_id": to_entity_id,
                },
                limit=_MAX_TRANSFERS_PER_PATH_EDGE,
            )
            if not isinstance(rows, list) or len(rows) != 1:
                return {
                    "tenant_id": tenant_id,
                    "path_id": path_id,
                    "trace_id": trace_id,
                    "path_nodes": list(raw_nodes),
                    "transfer_edges": [],
                    "linkage_reason": (
                        "financial_transfer_edge_missing"
                        if not rows
                        else "financial_transfer_edge_ambiguous"
                    ),
                }
            row = rows[0]
            if not isinstance(row, dict):
                raise RiskSourceReadIncomplete("financial transfer row is malformed")
            transfer_id = row.get("transfer_id")
            occurred_at = _aware_datetime(row.get("occurred_at"))
            asset_id = row.get("asset_id")
            if (
                str(row.get("tenant_id", "")) != tenant_id
                or row.get("from_entity_id") != from_entity_id
                or row.get("to_entity_id") != to_entity_id
                or not isinstance(transfer_id, str)
                or not transfer_id.strip()
                or not isinstance(asset_id, str)
                or not asset_id.strip()
                or not _positive_decimal(row.get("amount"))
                or occurred_at is None
            ):
                raise RiskSourceReadIncomplete("financial transfer evidence is incomplete")
            evidence_ref = EvidenceRef(
                id=transfer_id,
                type="transaction",
                source="transfers",
                observedAt=occurred_at.isoformat(),
                uri=f"store://transfers/{transfer_id}",
            )
            transfer_edges.append(
                {
                    "from_entity_id": from_entity_id,
                    "to_entity_id": to_entity_id,
                    "transfer_id": transfer_id,
                    "asset_id": asset_id,
                    "amount": str(row.get("amount")),
                    "occurred_at": occurred_at.isoformat(),
                    "evidence_ref": evidence_ref.model_dump(mode="json"),
                }
            )

        return {
            "tenant_id": tenant_id,
            "path_id": path_id,
            "trace_id": trace_id,
            "path_nodes": list(raw_nodes),
            "hop_count": hop_count,
            "path_discovered_at": path.get("discovered_at"),
            "trace_completed_at": trace.get("completed_at"),
            "transfer_edges": transfer_edges,
            "linkage_reason": None,
        }


class Risk360Provider:
    """Read-only intelligence-projection provider for ``risk360``."""

    projection_id: str = PROJECTION_ID
    contract_version: str = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy: str = "read_only"

    def __init__(
        self,
        sources: Optional[RiskSourceReader] = None,
        *,
        support_case_repository: Optional[SupportCaseRepository] = None,
        social_graph_path_reader: Optional[Any] = None,
        consent_reader: Optional[Any] = None,
    ) -> None:
        # Injected canonical reader (test seam); default reads the Phase-3
        # repositories. Read-only — the provider holds no write path.
        self._sources = sources if sources is not None else RepositoryRiskSourceReader()
        # Support-case risk is readable only after the canonical case authority
        # proves the exact tenant/case binding. The repository is read-only here.
        self._support_case_repository = (
            support_case_repository
            if support_case_repository is not None
            else SupportCaseRepository()
        )
        # Keep the social graph seam lazy. Its default adapter reads canonical
        # graph + relationship-fact authorities and does not become a second
        # risk or contagion store.
        self._social_graph_path_reader = social_graph_path_reader
        self._consent_reader = consent_reader

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Risk360 projection over the tenant's risk records."""
        tenant_id = request.tenantId
        dep_state = context.dependencyState

        support_case_scope: Optional[dict[str, Any]] = None
        support_case_evidence: list[EvidenceRef] = []
        support_case_scope_verified = True
        if request.subject.kind == "support_case":
            if context.tenantId != tenant_id:
                support_case_scope = self._unknown_support_case_scope(
                    tenant_id,
                    request.subject.id,
                    "support_case_tenant_context_mismatch",
                )
            else:
                support_case_scope, support_case_evidence = await self._safe_support_case_scope(
                    tenant_id,
                    request.subject,
                )
            support_case_scope_verified = support_case_scope["state"] == "available"

        # The runtime context is the authenticated tenant boundary. Fail closed
        # when a direct caller supplies a request for a different tenant; never
        # let the request alone choose which canonical rows this provider reads.
        source_provenance_reason: Optional[str] = None
        if not support_case_scope_verified:
            # A risk row keyed by a caller-supplied case ID is not enough. Do
            # not query any risk authority until the canonical support_cases
            # read proves that the exact tenant-owned case exists.
            assessment, assessment_degraded = None, False
            signals, signals_degraded = [], False
            source_provenance, source_provenance_degraded = [], False
        elif context.tenantId != tenant_id:
            assessment, assessment_degraded = None, True
            signals, signals_degraded = [], True
            source_provenance, source_provenance_degraded = (
                [],
                request.subject.kind == "source",
            )
            if request.subject.kind == "source":
                source_provenance_reason = "source_provenance_tenant_context_mismatch"
        elif request.subject.kind == "contagion_path" and (
            request.asOf is not None
            or context.asOf is not None
            or request.timeRange is not None
            or request.temporalMode in {"window", "as_of", "compare", "relative"}
        ):
            # The stored flow paths and latest entity risk outputs do not share
            # a bitemporal snapshot. Suppress both direct and joined current
            # facts for a historical/windowed contagion-path request.
            assessment, assessment_degraded = None, False
            signals, signals_degraded = [], False
            source_provenance, source_provenance_degraded = [], False
        elif request.subject.kind == "source" and (
            request.asOf is not None
            or context.asOf is not None
            or request.timeRange is not None
            or request.temporalMode in {"as_of", "compare", "relative"}
        ):
            # Bronze provenance has no bitemporal reader. Suppress current
            # observations for historical/windowed requests instead of
            # returning present-day source facts under an older anchor.
            assessment, assessment_degraded = await self._safe_assessment(
                tenant_id, request.subject
            )
            signals, signals_degraded = await self._safe_signals(tenant_id, request.subject)
            source_provenance, source_provenance_degraded = [], False
            source_provenance_reason = "source_provenance_bitemporal_history_unavailable"
        else:
            assessment, assessment_degraded = await self._safe_assessment(
                tenant_id, request.subject
            )
            signals, signals_degraded = await self._safe_signals(tenant_id, request.subject)
            source_provenance, source_provenance_degraded = await self._safe_source_provenance(
                tenant_id, request.subject
            )

        if support_case_scope_verified:
            agent_policy_flags, agent_policy_flags_degraded, agent_policy_flags_reason = (
                await self._safe_agent_policy_flag_observations(
                    tenant_id=tenant_id,
                    request=request,
                    context=context,
                )
            )
        else:
            agent_policy_flags, agent_policy_flags_degraded = [], False
            agent_policy_flags_reason = "support_case_subject_scope_unavailable"

        poisoning_as_of, poisoning_anchor_reason = self._poisoning_as_of(request, context)
        if not support_case_scope_verified:
            poisoning_evidence, poisoning_evidence_degraded = [], False
            poisoning_evidence_reason = "support_case_subject_scope_unavailable"
        elif context.tenantId != tenant_id:
            poisoning_evidence, poisoning_evidence_degraded = [], True
            poisoning_evidence_reason = "poisoning_evidence_tenant_context_mismatch"
        elif poisoning_anchor_reason is not None:
            poisoning_evidence, poisoning_evidence_degraded = [], False
            poisoning_evidence_reason = poisoning_anchor_reason
        else:
            (
                poisoning_evidence,
                poisoning_evidence_degraded,
                poisoning_evidence_reason,
            ) = await self._safe_poisoning_evidence(
                tenant_id,
                request.subject,
                as_of=poisoning_as_of,
            )

        assessment_history_as_of, history_anchor_reason = self._assessment_history_as_of(
            request, context
        )
        if not support_case_scope_verified:
            assessment_history, assessment_history_degraded = [], False
            assessment_history_reason = "support_case_subject_scope_unavailable"
        elif context.tenantId != tenant_id:
            assessment_history, assessment_history_degraded = [], True
            assessment_history_reason = "risk_assessment_history_tenant_context_mismatch"
        elif history_anchor_reason is not None:
            assessment_history, assessment_history_degraded = [], False
            assessment_history_reason = history_anchor_reason
        else:
            (
                assessment_history,
                assessment_history_degraded,
                assessment_history_reason,
            ) = await self._safe_assessment_history(
                tenant_id,
                request.subject,
                as_of=assessment_history_as_of,
            )

        if not support_case_scope_verified:
            financial_link, financial_link_degraded = None, False
            financial_link_reason = "support_case_subject_scope_unavailable"
            social_propagation, social_path_claims = self._unknown_social_propagation(
                "support_case_subject_scope_unavailable"
            ), []
        elif request.subject.kind == "support_case":
            # A canonical support-case identity joins case-keyed assessments
            # and signals. It does not establish graph or financial-flow
            # semantics for that case, so do not issue contagion reads.
            financial_link, financial_link_degraded = None, False
            financial_link_reason = "support_case_contagion_authority_not_connected"
            social_propagation, social_path_claims = self._unknown_social_propagation(
                "support_case_contagion_authority_not_connected"
            ), []
        else:
            financial_link, financial_link_degraded, financial_link_reason = (
                await self._safe_financial_contagion_link(request, context)
            )
            social_propagation, social_path_claims = await self._safe_social_propagation_paths(
                request, context
            )

        evidence = self._collect_evidence(
            assessment,
            signals,
            source_provenance,
            poisoning_evidence,
            agent_policy_flags,
        )
        if support_case_evidence:
            evidence = _dedupe_evidence([*evidence, *support_case_evidence])
        if financial_link is not None:
            evidence = _dedupe_evidence([*evidence, *financial_link["evidence_refs"]])
        evidence = _dedupe_evidence([*evidence, *social_propagation["evidence_refs"]])
        history_evidence = self._assessment_history_evidence(assessment_history)
        evidence = _dedupe_evidence([*evidence, *history_evidence])

        sections = [
            self._summary_section(request, assessment, assessment_degraded, dep_state),
            self._state_section(request, assessment, assessment_degraded, dep_state),
            self._evidence_section(
                evidence,
                source_degraded=(
                    assessment_degraded
                    or signals_degraded
                    or source_provenance_degraded
                    or poisoning_evidence_degraded
                    or assessment_history_degraded
                    or social_propagation["state"] == "degraded"
                ),
            ),
            self._findings_section(
                request,
                assessment,
                assessment_degraded,
                signals,
                evidence,
                source_provenance,
                source_provenance_degraded,
                source_provenance_reason,
                poisoning_evidence,
                poisoning_evidence_degraded,
                poisoning_evidence_reason,
                financial_link,
                financial_link_degraded,
                financial_link_reason,
                social_propagation,
                agent_policy_flags,
                agent_policy_flags_degraded,
                agent_policy_flags_reason,
                assessment_history,
                assessment_history_degraded,
                assessment_history_reason,
            ),
            self._health_section(
                request,
                assessment,
                signals,
                assessment_degraded,
                signals_degraded,
                source_provenance,
                source_provenance_degraded,
                source_provenance_reason,
                poisoning_evidence,
                poisoning_evidence_degraded,
                poisoning_evidence_reason,
            ),
        ]
        claims = self._build_claims(
            request,
            assessment,
            signals,
            source_provenance,
            poisoning_evidence,
            financial_link,
            agent_policy_flags,
            support_case_evidence=support_case_evidence,
        )
        claims.extend(social_path_claims)

        if support_case_scope is not None:
            if support_case_scope_verified:
                risk_read = {
                    "state": "available",
                    "subjectKind": "support_case",
                    "subjectId": request.subject.id,
                    "tenantId": tenant_id,
                    "binding": "exact_tenant_subject_kind_and_subject_id",
                    "assessmentRead": "complete" if not assessment_degraded else "degraded",
                    "assessmentPresent": assessment is not None,
                    "signalRead": "complete" if not signals_degraded else "degraded",
                    "signalCount": len(signals),
                    "signalCoverage": "unknown",
                    "freshnessSla": "unavailable",
                }
            else:
                risk_read = {
                    "state": "unknown",
                    "reason": support_case_scope.get(
                        "reason", "support_case_subject_scope_unavailable"
                    ),
                    "binding": "not_attempted",
                    "assessmentRead": "not_read",
                    "signalRead": "not_read",
                    "signalCoverage": "unknown",
                    "freshnessSla": "unavailable",
                }
            support_case_scope = {**support_case_scope, "riskRead": risk_read}

        if support_case_scope is not None:
            sections = self._attach_support_case_scope(
                sections,
                support_case_scope,
                verified=support_case_scope_verified,
            )
            if not support_case_scope_verified:
                claims = []

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(dep_state),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
        )

    async def _safe_support_case_scope(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[dict[str, Any], list[EvidenceRef]]:
        """Prove an exact canonical case before allowing a case-keyed risk read."""
        try:
            read = await self._support_case_repository.get_case(tenant_id, subject.id)
        except Exception:  # noqa: BLE001 - unavailable scope authority remains unknown
            return (
                self._unknown_support_case_scope(
                    tenant_id,
                    subject.id,
                    "support_case_authority_unavailable",
                ),
                [],
            )
        if not isinstance(read, SupportCaseAuthorityRead) or not read.available:
            return (
                self._unknown_support_case_scope(
                    tenant_id,
                    subject.id,
                    "support_case_authority_unavailable",
                ),
                [],
            )
        if read.expired:
            return (
                self._unknown_support_case_scope(
                    tenant_id,
                    subject.id,
                    "support_case_retention_expired",
                ),
                [],
            )
        record = read.record
        if not isinstance(record, dict):
            return (
                self._unknown_support_case_scope(
                    tenant_id,
                    subject.id,
                    "support_case_not_found_for_tenant",
                ),
                [],
            )
        if record.get("tenant_id") != tenant_id or record.get("case_id") != subject.id:
            return (
                self._unknown_support_case_scope(
                    tenant_id,
                    subject.id,
                    "support_case_tenant_scope_mismatch",
                ),
                [],
            )

        observed_at = _aware_datetime(record.get("last_observed_at"))
        events = read.events if isinstance(read.events, list) else []
        reference = EvidenceRef(
            id=subject.id,
            type="entity",
            source="support_cases",
            observedAt=observed_at.isoformat() if observed_at is not None else None,
            uri=f"store://support_cases/{quote(subject.id, safe='')}",
        )
        return (
            {
                "state": "available",
                "tenantId": tenant_id,
                "supportCaseId": subject.id,
                "subjectBinding": "exact_tenant_canonical_support_case_id",
                "caseRecordRead": "available",
                "caseRecordEvidenceRefs": [reference.model_dump(mode="json")],
                "lifecycleEventScan": (
                    "complete"
                    if read.complete is True
                    else "truncated"
                    if read.complete is False
                    else "unknown"
                ),
                "lifecycleEventCount": len(events),
                "sourceHistoryCompleteness": "unknown",
                "freshnessSla": "unavailable",
            },
            [reference],
        )

    @staticmethod
    def _unknown_support_case_scope(
        tenant_id: str,
        support_case_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Safe scope result when canonical case identity cannot be established."""
        return {
            "state": "unknown",
            "reason": reason,
            "tenantId": tenant_id,
            "supportCaseId": support_case_id,
            "subjectBinding": "exact_tenant_canonical_support_case_id_required",
            "riskRead": "suppressed_until_case_identity_is_proven",
            "evidenceRefs": [],
            "sourceHistoryCompleteness": "unknown",
            "freshnessSla": "unavailable",
        }

    @staticmethod
    def _unknown_social_propagation(reason: str) -> dict[str, Any]:
        return {
            "state": "unknown",
            "reason": reason,
            "paths": [],
            "evidence_refs": [],
            "coverage": "bounded_current_observed_follows_paths",
            "completeness": "unknown",
            "freshness": "unknown",
            "causalRiskPropagationEstablished": False,
        }

    @staticmethod
    def _attach_support_case_scope(
        sections: list[ProjectionSection],
        scope: dict[str, Any],
        *,
        verified: bool,
    ) -> list[ProjectionSection]:
        """Expose the case join and its limits beside every Risk360 section."""
        bound: list[ProjectionSection] = []
        for section in sections:
            warnings = list(section.warnings or [])
            if isinstance(section.content, dict):
                content = dict(section.content)
            else:
                # ProjectionSection content is expected to be an object. If a
                # malformed upstream value reaches this boundary, omit it and
                # retain a bounded warning instead of crashing the read.
                content = {}
                warnings.append("risk_section_content_invalid_for_support_case")
            content["supportCaseScope"] = scope
            state = section.state
            if not verified:
                if section.id in {"summary", "state", "evidence", "findings", "health"}:
                    state = "unknown"
                reason = str(scope.get("reason", "support_case_subject_scope_unavailable"))
                warning = f"support case identity could not be established; risk read suppressed ({reason})"
                warnings = [warning]
                if section.id == "findings":
                    coverage = content.get("requiredSlotCoverage")
                    if isinstance(coverage, dict):
                        coverage = dict(coverage)
                        for slot_id in ("risk_summary", "evidence_trace", "poisoning_evidence", "audit_history"):
                            coverage[slot_id] = {"state": "unknown", "reason": reason}
                        content["requiredSlotCoverage"] = coverage
            bound.append(
                section.model_copy(
                    update={
                        "state": state,
                        "content": content,
                        "warnings": warnings or None,
                    }
                )
            )
        return bound

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        assessment_degraded: bool,
        dep_state: list[Any],
    ) -> ProjectionSection:
        """summary — what the risk read says about the subject, typed honestly.

        No assessment -> ``missing``; an assessment recording zero dimensions ->
        ``empty`` (a real zero, never a coerced figure). ``profile360`` context is
        still in_flight so the summary degrades rather than inventing profile
        enrichment — the assessment facts it CAN render stay rendered.
        """
        state: str = "available"
        warnings: list[str] = []
        if assessment_degraded:
            state = "degraded"
            warnings.append("risk assessment source unavailable; summary is degraded")
        elif assessment is None:
            state = "missing"
            warnings.append("no risk assessment exists for the subject; no summary is rendered")
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["summary"]):
            state = "degraded"
            warnings.append("profile360 dependency not available; summary is degraded")
        elif not assessment.vector.components:
            state = "empty"
            warnings.append("risk assessment records no risk dimensions; summary is empty")

        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Risk summary",
            content=self._summary_content(request, assessment),
            warnings=warnings or None,
        )

    def _summary_content(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
    ) -> dict[str, Any]:
        """summary content — canonical facts only, never a fabricated total."""
        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
        }
        if assessment is None:
            return content

        # Dimensions with a real observed/estimated score (data-supported facts).
        scored = [
            component.dimension
            for component in assessment.vector.components
            if requires_value(component.state)
        ]
        assessment_summary: dict[str, Any] = {
            "assessmentId": assessment.assessment_id,
            "policy": (
                {
                    "id": assessment.policy_id,
                    "version": assessment.policy_version,
                }
                if assessment.policy_id is not None
                else None
            ),
            "snapshot": (
                {"graphSnapshotId": assessment.snapshot.graph_snapshot_id}
                if assessment.snapshot is not None
                else None
            ),
            "runId": assessment.run_id,
            "assessedAt": (
                assessment.assessed_at.isoformat() if assessment.assessed_at is not None else None
            ),
            # Sparse by design: the dimensions this assessment evaluated.
            "dimensionsEvaluated": list(assessment.dimensions),
            "componentsRecorded": len(assessment.vector.components),
            "scoredDimensions": scored,
            "claimState": assessment.claim_state.value,
            "confidence": assessment.confidence,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in assessment.evidence_refs],
        }
        content["assessment"] = assessment_summary

        if assessment.exposure is not None:
            exposure = assessment.exposure
            amount = exposure.economic_value
            content["exposure"] = {
                "exposedAssetLabels": list(exposure.exposed_asset_labels),
                "exposedOutcomeLabels": list(exposure.exposed_outcome_labels),
                "exposedPopulationLabels": list(exposure.exposed_population_labels),
                "economicValue": (
                    None
                    if amount is None
                    else {
                        "amount": None if amount.amount is None else str(amount.amount),
                        "currency": amount.currency,
                        "usdValue": (None if amount.usd_value is None else str(amount.usd_value)),
                    }
                ),
                "claimState": exposure.claim_state.value,
                "confidence": exposure.confidence,
            }
        return content

    def _state_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        assessment_degraded: bool,
        dep_state: list[Any],
    ) -> ProjectionSection:
        """state — typed per-dimension risk state over the canonical registry.

        No assessment -> ``missing``. Every seeded risk dimension gets a typed row
        (``ValueState`` vocabulary): recorded components render their canonical
        state/score, absent dimensions render as an honest non-value-bearing state
        (``missing_inputs`` / ``not_applicable``) with ``score=None`` — never a
        fabricated ``0`` and never an invented traffic-light badge. ``cluster360``
        membership context is still in_flight so the section degrades honestly.
        """
        state: str = "available"
        warnings: list[str] = []
        if assessment_degraded:
            state = "degraded"
            warnings.append("risk assessment source unavailable; per-dimension state is degraded")
        elif assessment is None:
            state = "missing"
            warnings.append(
                "no risk assessment exists for the subject; no dimension state is rendered"
            )
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["state"]):
            state = "degraded"
            warnings.append("cluster360 dependency not available; risk state is degraded")
        elif not assessment.vector.components:
            state = "empty"
            warnings.append("risk assessment records no risk dimensions; state is empty")

        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
        }
        if assessment is not None:
            rows: list[dict[str, Any]] = []
            for dim in RISK_DIMENSIONS:
                component = assessment.vector.component_for(dim.key)
                rows.append(
                    {
                        "dimension": dim.key,
                        "label": dim.label,
                        "state": component.state.value,
                        "score": component.score,  # None when not value-bearing
                        "claimState": component.claim_state.value,
                        "confidence": component.confidence,
                        "evidenceRefs": [
                            ref.model_dump(mode="json") for ref in component.evidence_refs
                        ],
                    }
                )
            content["dimensionStates"] = rows
            content["recordedDimensionCount"] = len(assessment.vector.components)
        return ProjectionSection(
            id="state",
            state=state,  # type: ignore[arg-type]
            title="Risk state",
            content=content,
            warnings=warnings or None,
        )

    def _evidence_section(
        self,
        evidence: list[EvidenceRef],
        *,
        source_degraded: bool,
    ) -> ProjectionSection:
        """evidence — canonical refs, with incomplete reads kept explicit."""
        warnings = (
            ["one or more canonical risk sources were unavailable; evidence may be incomplete"]
            if source_degraded
            else None
        )
        return ProjectionSection(
            id="evidence",
            state=("degraded" if source_degraded else "available" if evidence else "empty"),
            title="Evidence",
            content={
                "count": len(evidence),
                "evidence": [e.model_dump(mode="json") for e in evidence],
            },
            warnings=warnings,
        )

    def _findings_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        assessment_degraded: bool,
        signals: list[RiskSignal],
        evidence: list[EvidenceRef],
        source_provenance: list[dict[str, Any]],
        source_provenance_degraded: bool,
        source_provenance_reason: Optional[str],
        poisoning_evidence: list[RiskPoisoningEvidence],
        poisoning_evidence_degraded: bool,
        poisoning_evidence_reason: Optional[str],
        financial_link: Optional[dict[str, Any]],
        financial_link_degraded: bool,
        financial_link_reason: Optional[str],
        social_propagation: dict[str, Any],
        agent_policy_flags: list[dict[str, Any]],
        agent_policy_flags_degraded: bool,
        agent_policy_flags_reason: Optional[str],
        assessment_history: list[dict[str, Any]],
        assessment_history_degraded: bool,
        assessment_history_reason: Optional[str],
    ) -> ProjectionSection:
        """findings — NO risk findings are asserted before materiality exists.

        The SoT (§7) is explicit: materiality precedes finding creation and risk
        does not auto-create findings. The materiality / finding-candidate path is
        a later program phase, so an assessment's scored components are rendered
        as typed dimension state (the ``state`` section), never promoted here.
        Honest states: ``missing`` when there is no assessment to derive from,
        ``empty`` when one exists but no material finding candidate has been
        produced, ``degraded`` when the assessment source could not be read.
        """
        state: str = "missing"
        warnings: list[str] = []
        if assessment_degraded:
            state = "degraded"
            warnings.append("risk assessment source unavailable; findings cannot be derived")
        elif assessment is None:
            state = "missing"
            warnings.append("no risk assessment exists for the subject; no findings are asserted")
        else:
            state = "empty"
            warnings.append(
                "no material risk findings are asserted: materiality / "
                "finding-candidate derivation is not yet live"
            )
        return ProjectionSection(
            id="findings",
            state=state,  # type: ignore[arg-type]
            title="Risk findings",
            content={
                "tenantId": request.tenantId,
                "subject": {"kind": request.subject.kind, "id": request.subject.id},
                "assessmentId": (assessment.assessment_id if assessment is not None else None),
                "findings": [],
                "poisoningEvidence": self._poisoning_evidence_summary(
                    poisoning_evidence,
                    degraded=poisoning_evidence_degraded,
                    reason=poisoning_evidence_reason,
                ),
                "policyFlags": {
                    "state": (
                        "degraded"
                        if agent_policy_flags_degraded
                        else "partial"
                        if agent_policy_flags
                        else "unknown"
                    ),
                    "reason": agent_policy_flags_reason
                    or (
                        "agent_observed_flags_lack_model_governance_policy_version"
                        if agent_policy_flags
                        else "evaluated_policy_flag_authority_unavailable"
                    ),
                    "semantics": "exact_agent_risk_signal_reports_only",
                    "policyEvaluation": "not_attested",
                    "policyVersion": None,
                    "observations": [
                        {
                            "signalId": row["signal_id"],
                            "agentId": row["agent_id"],
                            "policyFlags": list(row["policy_flags"]),
                            "detectedAt": row["detected_at"],
                            "evidenceRefs": [row["evidence_ref"].model_dump(mode="json")],
                        }
                        for row in agent_policy_flags
                    ],
                },
                "propagationPaths": {
                    key: value
                    for key, value in social_propagation.items()
                    if key != "evidence_refs"
                },
                "auditHistory": self._assessment_history_summary(
                    assessment_history,
                    degraded=assessment_history_degraded,
                    reason=assessment_history_reason,
                ),
                "requiredSlotCoverage": self._required_slot_coverage(
                    request,
                    assessment,
                    signals,
                    evidence,
                    source_provenance,
                    source_provenance_degraded,
                    source_provenance_reason,
                    assessment_degraded,
                    poisoning_evidence,
                    poisoning_evidence_degraded,
                    poisoning_evidence_reason,
                    financial_link,
                    financial_link_degraded,
                    financial_link_reason,
                    social_propagation,
                    agent_policy_flags,
                    agent_policy_flags_degraded,
                    agent_policy_flags_reason,
                    assessment_history,
                    assessment_history_degraded,
                    assessment_history_reason,
                ),
            },
            warnings=warnings or None,
            canonicalAuthorityRefs=[
                "computation_runs",
                "graph",
                "relationship_facts",
                "risk_assessments",
            ],
        )

    @staticmethod
    def _poisoning_evidence_summary(
        records: list[RiskPoisoningEvidence],
        *,
        degraded: bool,
        reason: Optional[str],
    ) -> dict[str, Any]:
        """Render safe detector metadata without payloads or negative inference."""
        if degraded:
            state = "degraded"
        elif records:
            state = "partial"
        else:
            # A successful empty query says nothing about detector coverage.
            state = "unknown"
        safe_records = [
            {
                "evidenceId": record.evidence_id,
                "tenantId": record.tenant_id,
                "sourceId": record.source_id,
                "subject": {
                    "kind": record.subject_kind,
                    "id": record.subject_id,
                },
                "poisoningType": record.poisoning_type,
                "signalStrength": record.signal_strength,
                "confidence": record.confidence,
                "claimState": record.claim_state.value,
                "detectorId": record.detector_id,
                "detectorVersion": record.detector_version,
                "sourceRecordId": record.source_record_id,
                "evidenceRefs": [
                    ref.model_dump(mode="json") for ref in record.evidence_refs
                ],
                "firstSeenAt": record.first_seen_at.isoformat(),
                "lastSeenAt": record.last_seen_at.isoformat(),
                "recordedAt": record.recorded_at.isoformat(),
                "status": record.status,
                "version": record.version,
                "supersedesEvidenceId": record.supersedes_evidence_id,
                "supersededByEvidenceId": record.superseded_by_evidence_id,
                "restatementReason": record.restatement_reason,
                "lifecycle": [
                    {
                        "eventId": event.event_id,
                        "fromStatus": event.from_status,
                        "toStatus": event.to_status,
                        "occurredAt": event.occurred_at.isoformat(),
                        "actorId": event.actor_id,
                        "reason": event.reason,
                        "evidenceRefs": [
                            ref.model_dump(mode="json") for ref in event.evidence_refs
                        ],
                    }
                    for event in record.lifecycle_events
                ],
            }
            for record in records
        ]
        latest_recorded_at = max(
            (record.recorded_at.isoformat() for record in records),
            default=None,
        )
        return {
            "state": state,
            "reason": reason
            or ("poisoning_detector_coverage_not_attested" if not records else None),
            "records": safe_records,
            "coverage": {
                "completeEvidenceScan": not degraded and reason is None,
                "detectorCoverage": "unattested",
                "negativeFindingInference": "prohibited",
            },
            "freshness": {
                "state": "degraded" if degraded else "known" if records else "unknown",
                "timestampedRecordCount": len(records),
                "latestRecordedAt": latest_recorded_at,
                "threshold": "unconfigured",
            },
            "policy": {
                "scope": "tenant_read_gated",
                "projection": "metadata_only",
                "rawPayload": "excluded",
            },
        }

    @staticmethod
    def _required_slot_coverage(
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
        evidence: list[EvidenceRef],
        source_provenance: list[dict[str, Any]],
        source_provenance_degraded: bool,
        source_provenance_reason: Optional[str],
        assessment_degraded: bool,
        poisoning_evidence: list[RiskPoisoningEvidence],
        poisoning_evidence_degraded: bool,
        poisoning_evidence_reason: Optional[str],
        financial_link: Optional[dict[str, Any]],
        financial_link_degraded: bool,
        financial_link_reason: Optional[str],
        social_propagation: dict[str, Any],
        agent_policy_flags: list[dict[str, Any]],
        agent_policy_flags_degraded: bool,
        agent_policy_flags_reason: Optional[str],
        assessment_history: list[dict[str, Any]],
        assessment_history_degraded: bool,
        assessment_history_reason: Optional[str],
    ) -> dict[str, dict[str, str]]:
        """Expose exact 360 slot coverage without converting absence into a claim."""
        agent_amplification = any(
            _is_agent_amplification_signal(signal, request.subject.kind) for signal in signals
        )
        source_classification = any(
            isinstance(row.get("source_trust"), str) and row["source_trust"].strip()
            for row in source_provenance
        )
        if source_provenance_degraded:
            source_trust_coverage = {
                "state": "degraded",
                "reason": source_provenance_reason or "source_provenance_read_incomplete",
            }
        elif source_provenance_reason is not None:
            source_trust_coverage = {
                "state": "unknown",
                "reason": source_provenance_reason,
            }
        elif source_classification:
            source_trust_coverage = {
                "state": "partial",
                "reason": "ingress_classification_available_source_reliability_evaluation_unavailable",
            }
        elif request.subject.kind != "source":
            source_trust_coverage = {
                "state": "unknown",
                "reason": "exact_source_subject_required",
            }
        else:
            source_trust_coverage = {
                "state": "unknown",
                "reason": "source_trust_classification_not_recorded",
            }

        if agent_policy_flags_degraded:
            policy_flags_coverage = {
                "state": "degraded",
                "reason": agent_policy_flags_reason or "agent_policy_flag_read_incomplete",
            }
        elif agent_policy_flags:
            policy_flags_coverage = {
                "state": "partial",
                "reason": "agent_observed_flags_lack_model_governance_policy_version",
            }
        else:
            policy_flags_coverage = {
                "state": "unknown",
                "reason": agent_policy_flags_reason or "evaluated_policy_flag_authority_unavailable",
            }

        open_poisoning = any(
            record.status in {"open", "acknowledged"} for record in poisoning_evidence
        )
        if open_poisoning:
            source_trust_coverage = {
                "state": "degraded",
                "reason": "open_poisoning_evidence_requires_source_review",
            }

        if poisoning_evidence_degraded:
            poisoning_coverage = {
                "state": "degraded",
                "reason": poisoning_evidence_reason or "poisoning_evidence_read_incomplete",
            }
        elif poisoning_evidence:
            poisoning_coverage = {
                "state": "partial",
                "reason": "poisoning_detector_coverage_not_attested",
            }
        else:
            poisoning_coverage = {
                "state": "unknown",
                "reason": poisoning_evidence_reason or "poisoning_detector_coverage_not_attested",
            }

        supported: dict[str, dict[str, str]] = {
            "risk_summary": (
                {"state": "available"}
                if assessment is not None
                else {
                    "state": "degraded" if assessment_degraded else "unknown",
                    "reason": "canonical_risk_assessment_read_failed"
                    if assessment_degraded
                    else "canonical_risk_assessment_unavailable",
                }
            ),
            "source_trust": source_trust_coverage,
            "poisoning_evidence": poisoning_coverage,
            "agent_amplification": (
                {"state": "available"}
                if agent_amplification
                else {"state": "unknown", "reason": "agentic_delegation_evidence_unavailable"}
            ),
            "evidence_trace": (
                {"state": "available"}
                if evidence
                else {"state": "unknown", "reason": "canonical_evidence_references_unavailable"}
            ),
        }
        unsupported_reasons = {
            "anomaly_events": "canonical_anomaly_event_authority_unavailable",
            "financial_contagion": "financial_contagion_attribution_authority_unavailable",
            "social_contagion": "social_contagion_causal_evidence_authority_unavailable",
            "interventions": "risk_intervention_authority_unavailable",
        }
        for slot_id, reason in unsupported_reasons.items():
            supported[slot_id] = {"state": "unknown", "reason": reason}
        supported["policy_flags"] = policy_flags_coverage
        if assessment_history_degraded:
            supported["audit_history"] = {
                "state": "degraded",
                "reason": assessment_history_reason
                or "risk_assessment_run_history_read_incomplete",
            }
        elif assessment_history:
            supported["audit_history"] = {
                "state": "partial",
                "reason": "assessment_run_history_available_intervention_audit_and_full_restatement_lineage_unavailable",
            }
        else:
            supported["audit_history"] = {
                "state": "unknown",
                "reason": assessment_history_reason
                or "risk_assessment_run_history_unavailable",
            }
        propagation_state = social_propagation.get("state")
        propagation_reason = social_propagation.get("reason")
        if propagation_state in {"partial", "degraded", "unknown"}:
            supported["propagation_paths"] = {
                "state": propagation_state,
                "reason": propagation_reason or "canonical_social_path_evidence_unavailable",
            }
        if financial_link_degraded:
            supported["financial_contagion"] = {
                "state": "degraded",
                "reason": financial_link_reason or "financial_flow_risk_read_incomplete",
            }
        elif financial_link is not None:
            supported["financial_contagion"] = {
                "state": "partial",
                "reason": "financial_value_risk_link_observed_contagion_attribution_unavailable",
            }
        elif financial_link_reason is not None:
            supported["financial_contagion"] = {
                "state": "unknown",
                "reason": financial_link_reason,
            }
        return {slot_id: supported[slot_id] for slot_id in _BLUEPRINT_REQUIRED_SLOT_IDS}

    def _health_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
        assessment_degraded: bool,
        signals_degraded: bool,
        source_provenance: list[dict[str, Any]],
        source_provenance_degraded: bool,
        source_provenance_reason: Optional[str],
        poisoning_evidence: list[RiskPoisoningEvidence],
        poisoning_evidence_degraded: bool,
        poisoning_evidence_reason: Optional[str],
    ) -> ProjectionSection:
        """health — detector/source freshness for the signals feeding the read.

        Backed by the tenant's RiskSignal rows: each contributing source's count,
        detector versions and newest observation. No signals yet -> honest
        ``missing`` (no contributing source to assess); an unreadable signal
        source degrades the section content-free.
        """
        state: str = "available"
        warnings: list[str] = []
        if signals_degraded or poisoning_evidence_degraded:
            state = "degraded"
            if signals_degraded:
                warnings.append("risk signal source unavailable; health is degraded")
            if poisoning_evidence_degraded:
                warnings.append("poisoning evidence source unavailable or incomplete")
        elif not signals:
            state = "missing"
            warnings.append(
                "no risk signal sources have emitted for this subject; "
                "detector health is not assessable"
            )

        by_source: dict[str, dict[str, Any]] = {}
        for signal in signals:
            source_state = by_source.setdefault(
                signal.source,
                {
                    "signalCount": 0,
                    "detectorVersions": [],
                    "latestObservedAt": None,
                },
            )
            source_state["signalCount"] += 1
            if (
                signal.detector_version
                and signal.detector_version not in source_state["detectorVersions"]
            ):
                source_state["detectorVersions"].append(signal.detector_version)
            observed_at = signal.observed_at.isoformat() if signal.observed_at is not None else None
            if observed_at is not None and (
                source_state["latestObservedAt"] is None
                or observed_at > source_state["latestObservedAt"]
            ):
                source_state["latestObservedAt"] = observed_at

        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "signalSources": by_source,
            # Preserve each canonical signal-to-evidence association for
            # consumers that need the assessed context behind an Agent risk
            # dimension. The detector's epistemic state is carried verbatim;
            # recording a signal does not make its underlying risk inference
            # observed, and an absent score remains absent.
            "signalContext": [
                {
                    "signalId": signal.signal_id,
                    "dimension": signal.risk_dimension,
                    "source": signal.source,
                    "claimState": signal.claim_state.value,
                    "confidence": signal.confidence,
                    "observedAt": (
                        signal.observed_at.isoformat() if signal.observed_at is not None else None
                    ),
                    "score": signal.score,
                    "value": signal.value,
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in signal.evidence_refs],
                }
                for signal in signals
            ],
            "sourceProvenance": self._source_provenance_summary(
                source_provenance,
                source_provenance_degraded=source_provenance_degraded,
                source_subject=request.subject.kind == "source",
                source_provenance_reason=source_provenance_reason,
            ),
            "poisoningEvidenceFreshness": self._poisoning_evidence_summary(
                poisoning_evidence,
                degraded=poisoning_evidence_degraded,
                reason=poisoning_evidence_reason,
            )["freshness"],
            "assessmentFreshness": (
                None
                if assessment is None or assessment.assessed_at is None
                else {
                    "assessmentId": assessment.assessment_id,
                    "assessedAt": assessment.assessed_at.isoformat(),
                }
            ),
            # These states report timestamp coverage only. Risk360 has no
            # canonical freshness threshold, so a known timestamp is never
            # upgraded into a "fresh" / "stale" judgment here.
            "freshness": {
                "assessment": {
                    "state": (
                        "degraded"
                        if assessment_degraded
                        else "known"
                        if assessment is not None and assessment.assessed_at is not None
                        else "unknown"
                    ),
                    "assessmentId": (assessment.assessment_id if assessment is not None else None),
                    "assessedAt": (
                        assessment.assessed_at.isoformat()
                        if assessment is not None and assessment.assessed_at is not None
                        else None
                    ),
                },
                "signals": {
                    "state": (
                        "degraded"
                        if signals_degraded
                        else "known"
                        if signals and all(signal.observed_at is not None for signal in signals)
                        else "unknown"
                    ),
                    "signalCount": len(signals),
                    "timestampedSignalCount": sum(
                        signal.observed_at is not None for signal in signals
                    ),
                    "untimestampedSignalCount": sum(
                        signal.observed_at is None for signal in signals
                    ),
                    "latestObservedAt": max(
                        (
                            signal.observed_at.isoformat()
                            for signal in signals
                            if signal.observed_at is not None
                        ),
                        default=None,
                    ),
                },
                "sourceProvenance": {
                    "state": (
                        "degraded"
                        if source_provenance_degraded
                        else "known"
                        if any(row.get("observed_at") for row in source_provenance)
                        else "unknown"
                    ),
                    "observationCount": len(source_provenance),
                    "timestampedObservationCount": sum(
                        bool(row.get("observed_at")) for row in source_provenance
                    ),
                },
                "poisoningEvidence": self._poisoning_evidence_summary(
                    poisoning_evidence,
                    degraded=poisoning_evidence_degraded,
                    reason=poisoning_evidence_reason,
                )["freshness"],
            },
        }
        return ProjectionSection(
            id="health",
            state=state,  # type: ignore[arg-type]
            title="Risk health",
            content=content,
            warnings=warnings or None,
        )

    @staticmethod
    def _source_provenance_summary(
        source_provenance: list[dict[str, Any]],
        *,
        source_provenance_degraded: bool,
        source_subject: bool,
        source_provenance_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Render only stamped provenance fields, never source payload content."""
        classifications = [
            {
                "observationId": row["observation_id"],
                "sourceTrustClassification": row.get("source_trust"),
                "credentialClass": row.get("credential_class"),
                "signatureStatus": row.get("signature_status"),
                "adapter": row.get("adapter"),
                "adapterVersion": row.get("adapter_version"),
                "observedAt": row.get("observed_at"),
                "evidenceRef": row["evidence_ref"].model_dump(mode="json"),
            }
            for row in source_provenance
        ]
        has_classification = any(
            isinstance(row.get("source_trust"), str) and row["source_trust"].strip()
            for row in source_provenance
        )
        if source_provenance_degraded:
            state = "degraded"
            reason = source_provenance_reason or "source_provenance_read_incomplete"
        elif source_provenance_reason is not None:
            state = "unknown"
            reason = source_provenance_reason
        elif has_classification:
            state = "partial"
            reason = "ingress_classification_is_not_source_reliability_evaluation"
        elif source_provenance:
            state = "unknown"
            reason = "source_trust_classification_not_recorded"
        elif source_subject:
            state = "unknown"
            reason = "no_source_provenance_observations"
        else:
            state = "unknown"
            reason = "exact_source_subject_required"
        return {
            "state": state,
            "reason": reason,
            "semantics": "gateway_stamped_ingress_classification_only",
            "reliabilityEvaluation": "unknown",
            "observations": classifications,
        }

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
        source_provenance: list[dict[str, Any]],
        poisoning_evidence: list[RiskPoisoningEvidence],
        financial_link: Optional[dict[str, Any]],
        agent_policy_flags: list[dict[str, Any]],
        *,
        support_case_evidence: Optional[list[EvidenceRef]] = None,
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: never an empty envelope)."""
        claims: list[ClaimEnvelope] = []
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)
        case_scope_evidence = (
            list(support_case_evidence or []) if subject.kind == "support_case" else []
        )

        if assessment is not None:
            assessment_refs = _dedupe_evidence(
                [*self._assessment_evidence(assessment), *case_scope_evidence]
            )
            if assessment_refs:
                policy = (
                    f" under policy {assessment.policy_id} v{assessment.policy_version}"
                    if assessment.policy_id is not None
                    else ""
                )
                claims.append(
                    ClaimEnvelope(
                        id=f"risk360.assessment.{assessment.assessment_id}",
                        kind="risk_assessment",
                        subject=subject,
                        evidenceRefs=assessment_refs,
                        claims=[
                            f"Risk assessment {assessment.assessment_id}{policy} "
                            f"records {len(assessment.vector.components)} risk "
                            f"dimension(s) with claim_state "
                            f"{assessment.claim_state.value}."
                        ],
                        confidence=assessment.confidence,
                        claimState=assessment.claim_state,
                        domainSlotIds=_risk_assessment_slot_ids(subject.kind),
                    )
                )
            # One claim per scored (value-bearing) dimension, grounded in the
            # dimension's own EvidenceRefs when it carries any.
            for component in assessment.vector.components:
                if not requires_value(component.state):
                    continue
                if not component.evidence_refs:
                    continue
                claims.append(
                    ClaimEnvelope(
                        id=f"risk360.dimension.{component.dimension}",
                        kind="risk_dimension_state",
                        subject=subject,
                        evidenceRefs=_dedupe_evidence(
                            [*component.evidence_refs, *case_scope_evidence]
                        ),
                        claims=[
                            f"Risk dimension {component.dimension!r} is "
                            f"{component.state.value} (score "
                            f"{component.score}); claim_state "
                            f"{component.claim_state.value}."
                        ],
                        confidence=component.confidence,
                        claimState=component.claim_state,
                        domainSlotIds=_risk_evidence_slot_ids(subject.kind),
                    )
                )

        # Carry each evidence-backed signal as its own epistemically classified
        # assessment-context claim. In particular, an inferred Agentic
        # detector result remains inferred even though the canonical record
        # and its observation timestamp are directly available here.
        for signal in signals:
            if not signal.evidence_refs:
                continue
            observed = (
                f" observed at {signal.observed_at.isoformat()}"
                if signal.observed_at is not None
                else ""
            )
            score_context = (
                " no numeric score is recorded."
                if signal.score is None
                else f" recorded score {signal.score}."
            )
            domain_slot_ids = _risk_evidence_slot_ids(subject.kind)
            if _is_agent_amplification_signal(signal, subject.kind):
                domain_slot_ids.append("agent_amplification")
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.signal.{signal.signal_id}",
                    kind="risk_signal_context",
                    subject=subject,
                    evidenceRefs=_dedupe_evidence(
                        [*signal.evidence_refs, *case_scope_evidence]
                    ),
                    claims=[
                        f"Risk signal {signal.signal_id!r} records "
                        f"{signal.risk_dimension!r} context from "
                        f"{signal.source!r}{observed} with claim_state "
                        f"{signal.claim_state.value};{score_context}"
                    ],
                    confidence=signal.confidence,
                    claimState=signal.claim_state,
                    domainSlotIds=domain_slot_ids,
                )
            )

        for row in agent_policy_flags:
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.agent-policy-flags.{row['signal_id']}",
                    kind="agent_policy_flags_reported",
                    subject=subject,
                    evidenceRefs=[row["evidence_ref"]],
                    claims=[
                        f"Exact agent risk signal {row['signal_id']!r} reports policy flags "
                        f"{', '.join(row['policy_flags'])!r}; policy evaluation and model-"
                        "governance version are not attested by this record."
                    ],
                    confidence=None,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["policy_flags", "evidence_trace"],
                )
            )

        # The gateway-stamped value is an ingress credential classification,
        # not a source reputation score. Claim only that exact recorded fact;
        # source reliability and trustworthiness remain unresolved by it.
        for row in source_provenance:
            source_trust = row.get("source_trust")
            evidence_ref = row.get("evidence_ref")
            if (
                request.subject.kind != "source"
                or not isinstance(source_trust, str)
                or not source_trust.strip()
                or not isinstance(evidence_ref, EvidenceRef)
            ):
                continue
            observation_id = row["observation_id"]
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.source-trust.{observation_id}",
                    kind="source_ingress_trust_classification",
                    subject=subject,
                    evidenceRefs=[evidence_ref],
                    claims=[
                        f"Observation {observation_id!r} records ingress source-trust "
                        f"classification {source_trust!r} for source {request.subject.id!r}; "
                        "this is not a source reliability evaluation."
                    ],
                    confidence=None,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["source_trust", "evidence_trace"],
                )
            )

        for record in poisoning_evidence:
            slots = ["poisoning_evidence", "evidence_trace"]
            if request.subject.kind == "source":
                slots.append("source_trust")
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.poisoning.{record.evidence_id}.v{record.version}",
                    kind="source_poisoning_detector_evidence",
                    subject=subject,
                    evidenceRefs=list(record.evidence_refs),
                    claims=[
                        f"Detector {record.detector_id!r} v{record.detector_version} "
                        f"recorded {record.status} {record.poisoning_type!r} evidence "
                        f"for source {record.source_id!r} and exact subject "
                        f"{record.subject_kind}:{record.subject_id}; this detector record "
                        "does not by itself verify that the source was poisoned."
                    ],
                    confidence=None,
                    claimState=record.claim_state,
                    domainSlotIds=slots,
                )
            )

        if signals:
            # One claim per contributing signal source (detector health truth).
            refs_by_source: dict[str, list[EvidenceRef]] = {}
            for signal in signals:
                refs_by_source.setdefault(signal.source, []).extend(signal.evidence_refs)
            for source, refs in refs_by_source.items():
                if not refs:
                    continue
                count = sum(1 for s in signals if s.source == source)
                claims.append(
                    ClaimEnvelope(
                        id=f"risk360.health.{source}",
                        kind="risk_signal_source",
                        subject=subject,
                        evidenceRefs=refs,
                        claims=[
                            f"Risk signal source {source!r} has emitted {count} "
                            f"signal(s) for this subject."
                        ],
                        confidence=None,
                        # This claim is about the canonical source record
                        # existing, not whether its inferred risk condition is
                        # true.
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=_risk_assessment_slot_ids(subject.kind),
                    )
                )
        if financial_link is not None:
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.financial-link.{financial_link['path_id']}",
                    kind="financial_flow_risk_link",
                    subject=subject,
                    evidenceRefs=list(financial_link["evidence_refs"]),
                    claims=[financial_link["claim"]],
                    confidence=None,
                    claimState=EpistemicStatus.DERIVED,
                    domainSlotIds=["financial_contagion", "evidence_trace"],
                )
            )
        return claims

    # ── Canonical read helpers (defensive) ─────────────────────────────────

    async def _safe_social_propagation_paths(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[dict[str, Any], list[ClaimEnvelope]]:
        """Project exact observed FOLLOWS paths without asserting risk contagion.

        Social Silver observations and the canonical graph establish recorded
        relationships. They do not establish that risk, behavior, or losses
        propagated. This read is therefore useful evidence for the
        ``propagation_paths`` basis only; the causal ``social_contagion`` slot
        remains unknown until its own detector/evidence writer is connected.
        """
        empty: dict[str, Any] = {
            "state": "unknown",
            "reason": "exact_entity_subject_required_for_social_graph_path_read",
            "paths": [],
            "evidence_refs": [],
            "coverage": "bounded_current_observed_follows_paths",
            "completeness": "unknown",
            "freshness": "unknown",
            "causalRiskPropagationEstablished": False,
        }
        if request.subject.kind != "entity":
            return empty, []
        if context.tenantId != request.tenantId:
            empty.update(
                state="degraded",
                reason="social_path_runtime_tenant_context_mismatch",
            )
            return empty, []

        time_range = request.timeRange
        bounded_time_range = time_range is not None and any(
            getattr(time_range, field, None) is not None for field in ("from_", "to")
        )
        if (
            request.asOf is not None
            or context.asOf is not None
            or bounded_time_range
            or request.temporalMode in {"as_of", "compare", "relative"}
        ):
            empty["reason"] = "social_graph_path_bitemporal_history_unavailable"
            return empty, []

        async def consent_for(entity_id: str) -> tuple[bool, Optional[str]]:
            reader = self._consent_reader
            if reader is None:
                from governance.consent.authority import evaluate_consent

                reader = evaluate_consent
                self._consent_reader = reader
            result = await reader(request.tenantId, entity_id, None, "analytics")
            if isinstance(result, tuple) and result:
                reason = result[1] if len(result) > 1 and isinstance(result[1], str) else None
                return result[0] is True, reason
            allowed = getattr(result, "allowed", False) is True
            reason = getattr(result, "reason_code", None)
            return allowed, reason if isinstance(reason, str) else None

        try:
            subject_allowed, consent_reason = await consent_for(request.subject.id)
        except Exception:  # noqa: BLE001 - consent failure suppresses graph-derived content
            empty.update(
                state="degraded",
                reason="social_path_consent_authority_unavailable",
            )
            return empty, []
        if not subject_allowed:
            empty["reason"] = (
                "social_path_consent_authority_unavailable"
                if consent_reason == "consent_authority_unavailable"
                else "social_path_subject_consent_restricted"
            )
            if consent_reason == "consent_authority_unavailable":
                empty["state"] = "degraded"
            return empty, []

        try:
            from services.social360.provider import (
                RepositorySocialGraphPathReader,
                SocialGraphPathRead,
                _valid_social_propagation_path,
            )

            reader = self._social_graph_path_reader
            if reader is None:
                reader = RepositorySocialGraphPathReader()
                self._social_graph_path_reader = reader
            result = await reader.read_paths(request.tenantId, request.subject.id)
        except Exception:  # noqa: BLE001 - canonical graph authority fails closed
            empty.update(
                state="degraded",
                reason="canonical_social_graph_authority_unavailable",
            )
            return empty, []

        if not isinstance(result, SocialGraphPathRead):
            empty.update(
                state="degraded",
                reason="invalid_social_graph_path_source_contract",
            )
            return empty, []
        if result.tenant_id != request.tenantId or result.start_entity_id != request.subject.id:
            empty.update(
                state="degraded",
                reason="canonical_social_path_scope_mismatch",
            )
            return empty, []
        if not result.available:
            empty.update(
                state="degraded",
                reason="canonical_social_graph_authority_unavailable",
            )
            return empty, []

        as_of = datetime.now(timezone.utc)
        as_of_iso = as_of.isoformat()
        reasons = set(result.reason_codes)
        path_items: list[dict[str, Any]] = []
        path_refs: list[EvidenceRef] = []
        claims: list[ClaimEnvelope] = []
        invalid_path = False
        consent_filtered = False
        consent_unavailable = False
        candidate_paths = list(result.paths)
        candidate_truncated = len(candidate_paths) > _MAX_SOCIAL_PROPAGATION_PATHS
        if candidate_truncated:
            candidate_paths = candidate_paths[:_MAX_SOCIAL_PROPAGATION_PATHS]
            reasons.add("canonical_social_path_result_capped")

        for path in candidate_paths:
            try:
                valid = _valid_social_propagation_path(
                    path,
                    request.tenantId,
                    request.subject.id,
                    as_of=as_of_iso,
                )
            except Exception:  # noqa: BLE001 - malformed authority result fails closed
                valid = False
            if not valid:
                invalid_path = True
                continue

            # Recheck the graph edge fields and exact evidence source sets at
            # this projection boundary. A social reader result is input, not
            # permission to widen tenant, predicate, or evidence scope.
            edge_refs: list[list[EvidenceRef]] = []
            times: list[Optional[str]] = []
            parsed_times: list[Optional[datetime]] = []
            malformed_time = False
            future_time = False
            for index, edge in enumerate(path.graph_edges):
                properties = (
                    edge.get("properties") or {}
                    if isinstance(edge, dict)
                    else getattr(edge, "properties", None) or {}
                )
                if not isinstance(properties, dict):
                    malformed_time = True
                    break
                observed_value = properties.get("observed_at")
                observed_at = _aware_datetime(observed_value)
                if observed_value is not None and observed_at is None:
                    malformed_time = True
                    break
                if observed_at is not None and observed_at > as_of:
                    future_time = True
                    break

                refs = list(path.edge_evidence_refs[index])
                idempotency_key = properties.get("idempotency_key")
                evidence_ids = properties.get("evidence_refs")
                expected_fact_ids = {
                    str(value).strip()
                    for value in evidence_ids
                    if isinstance(value, str) and value.strip()
                } if isinstance(evidence_ids, (list, tuple)) else set()
                graph_refs = [ref for ref in refs if ref.source == "entity_graph"]
                fact_refs = [ref for ref in refs if ref.source == "relationship_facts"]
                graph_ids = {ref.id for ref in graph_refs}
                fact_ids = {ref.id for ref in fact_refs}
                if (
                    not isinstance(idempotency_key, str)
                    or graph_ids != {idempotency_key}
                    or fact_ids != expected_fact_ids
                    or len(refs) != len(graph_ids) + len(fact_ids)
                    or any(ref.type != "relationship" for ref in graph_refs)
                    or any(ref.type != "event" for ref in fact_refs)
                ):
                    malformed_time = True
                    break
                edge_refs.append(_dedupe_evidence(refs))
                times.append(path.edge_observed_at[index])
                parsed_times.append(observed_at)

            if malformed_time or future_time:
                invalid_path = True
                continue

            endpoint_allowed = True
            for entity_id in path.entity_ids[1:]:
                try:
                    allowed, reason = await consent_for(entity_id)
                except Exception:  # noqa: BLE001 - failed consent read suppresses the path
                    allowed, reason = False, "consent_authority_unavailable"
                if not allowed:
                    endpoint_allowed = False
                    consent_unavailable = consent_unavailable or (
                        reason == "consent_authority_unavailable"
                    )
            if not endpoint_allowed:
                consent_filtered = True
                continue

            if any(value is None for value in parsed_times):
                time_order_state = "unknown"
                reasons.add("social_path_source_observation_time_missing")
            elif parsed_times == sorted(parsed_times):
                time_order_state = "ordered"
            else:
                time_order_state = "conflicted"
                reasons.add("social_path_source_observation_order_conflicted")

            refs = _dedupe_evidence([ref for edge in edge_refs for ref in edge])
            if not refs:
                invalid_path = True
                continue
            path_refs.extend(refs)
            path_items.append(
                {
                    "entityPath": list(path.entity_ids),
                    "edgePredicate": "FOLLOWS",
                    "edgeEvidenceRefs": [
                        [ref.model_dump(mode="json") for ref in edge] for edge in edge_refs
                    ],
                    "sourceObservedAtByEdge": times,
                    "timeOrderState": time_order_state,
                    "semantics": {
                        "observedDirectedGraphEdges": True,
                        "riskPropagationEstablished": False,
                        "socialContagionEstablished": False,
                        "causalityEstablished": False,
                    },
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
                }
            )
            path_digest = hashlib.sha256(
                "\x1f".join([*path.entity_ids, *(ref.id for ref in refs)]).encode("utf-8")
            ).hexdigest()[:24]
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.social-path.{path_digest}",
                    kind="risk_social_graph_path_observation",
                    subject=ProjectionSubject(kind=request.subject.kind, id=request.subject.id),
                    evidenceRefs=refs,
                    claims=[
                        "The tenant-scoped canonical graph and relationship facts record this "
                        "directed sequence of FOLLOWS edges. It is observed path context only; "
                        "the evidence does not establish chronological risk propagation, social "
                        "contagion, causation, or attributable loss."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["propagation_paths", "evidence_trace"],
                )
            )

        if invalid_path:
            reasons.add("canonical_social_path_validation_failed")
        if consent_filtered:
            reasons.add("social_path_endpoint_consent_restricted")
        if consent_unavailable:
            reasons.add("social_path_consent_authority_unavailable")
        if result.truncated:
            reasons.add("canonical_social_path_read_bounded")

        authority_incomplete = bool(
            set(result.reason_codes)
            - {"no_bounded_observed_follows_paths", "canonical_graph_subject_unresolved"}
        )
        if path_items:
            state = (
                "degraded"
                if result.truncated
                or candidate_truncated
                or invalid_path
                or consent_unavailable
                or authority_incomplete
                else "partial"
            )
            reason = (
                "canonical_social_path_evidence_incomplete"
                if state == "degraded"
                else "observed_social_graph_paths_do_not_establish_causal_risk_propagation"
            )
        elif (
            result.truncated
            or candidate_truncated
            or invalid_path
            or consent_unavailable
            or authority_incomplete
        ):
            state = "degraded"
            reason = "canonical_social_path_evidence_incomplete"
        else:
            state = "unknown"
            reason = next(iter(sorted(reasons)), "no_bounded_observed_follows_paths")

        return {
            "state": state,
            "reason": reason,
            "paths": path_items,
            "evidence_refs": _dedupe_evidence(path_refs),
            "coverage": "bounded_current_observed_follows_paths",
            "completeness": (
                "unknown"
                if result.truncated or candidate_truncated or authority_incomplete
                else "complete_within_declared_bounds"
            ),
            "freshness": "unknown",
            "causalRiskPropagationEstablished": False,
            "reasonCodes": sorted(reasons),
        }, claims

    async def _safe_financial_contagion_link(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[Optional[dict[str, Any]], bool, Optional[str]]:
        """Join exact flow-path transfers to policy-bound financial risk outputs.

        The output is a partial financial-contagion basis only. It reports a
        tenant-scoped value/risk linkage, never causal or contagion attribution.
        Historical/windowed reads remain unknown because the path, transfer,
        and latest-risk repositories do not provide a coordinated bitemporal
        snapshot or a freshness SLA.
        """
        if request.subject.kind != "contagion_path":
            return None, False, None
        if context.tenantId != request.tenantId:
            return None, True, "financial_flow_risk_tenant_context_mismatch"
        if (
            request.asOf is not None
            or context.asOf is not None
            or request.timeRange is not None
            or request.temporalMode in {"window", "as_of", "compare", "relative"}
        ):
            return None, False, "financial_flow_risk_bitemporal_history_unavailable"

        reader = getattr(self._sources, "financial_flow_path", None)
        if not callable(reader):
            return None, False, "financial_flow_path_authority_not_connected"
        try:
            raw_path = await reader(tenant_id=request.tenantId, path_id=request.subject.id)
        except Exception:  # noqa: BLE001 - exact-source failures stay content-free
            return None, True, "financial_flow_path_read_incomplete"
        if raw_path is None:
            return None, False, "financial_flow_path_record_unavailable"
        if (
            not isinstance(raw_path, dict)
            or raw_path.get("tenant_id") != request.tenantId
            or raw_path.get("path_id") != request.subject.id
            or not isinstance(raw_path.get("trace_id"), str)
            or not raw_path.get("trace_id")
        ):
            return None, True, "financial_flow_path_scope_incomplete"
        linkage_reason = raw_path.get("linkage_reason")
        if isinstance(linkage_reason, str) and linkage_reason:
            return None, False, linkage_reason

        path_nodes = raw_path.get("path_nodes")
        transfer_edges = raw_path.get("transfer_edges")
        hop_count = raw_path.get("hop_count")
        path_discovered_at = _aware_datetime(raw_path.get("path_discovered_at"))
        trace_completed_at = _aware_datetime(raw_path.get("trace_completed_at"))
        if (
            not isinstance(path_nodes, list)
            or not 2 <= len(path_nodes) <= _MAX_FINANCIAL_PATH_NODES
            or any(not isinstance(node, str) or not node.strip() for node in path_nodes)
            or isinstance(hop_count, bool)
            or not isinstance(hop_count, int)
            or hop_count != len(path_nodes) - 1
            or len(set(path_nodes)) < 2
            or not isinstance(transfer_edges, list)
            or len(transfer_edges) != hop_count
            or path_discovered_at is None
            or trace_completed_at is None
        ):
            return None, False, "financial_flow_path_sequence_or_freshness_unknown"

        transfer_refs: list[EvidenceRef] = []
        transfer_times: list[datetime] = []
        for index, edge in enumerate(transfer_edges):
            if not isinstance(edge, dict):
                return None, True, "financial_transfer_evidence_malformed"
            from_id, to_id = path_nodes[index], path_nodes[index + 1]
            transfer_id = edge.get("transfer_id")
            evidence_ref_raw = edge.get("evidence_ref")
            occurred_at = _aware_datetime(edge.get("occurred_at"))
            try:
                evidence_ref = EvidenceRef.model_validate(evidence_ref_raw)
            except Exception:  # noqa: BLE001 - evidence schema must fail closed
                return None, True, "financial_transfer_evidence_malformed"
            evidence_observed_at = _aware_datetime(evidence_ref.observedAt)
            if (
                edge.get("from_entity_id") != from_id
                or edge.get("to_entity_id") != to_id
                or not isinstance(transfer_id, str)
                or not transfer_id.strip()
                or not isinstance(edge.get("asset_id"), str)
                or not edge["asset_id"].strip()
                or not _positive_decimal(edge.get("amount"))
                or occurred_at is None
                or evidence_observed_at != occurred_at
                or evidence_ref.id != transfer_id
                or evidence_ref.type != "transaction"
                or evidence_ref.source != "transfers"
                or evidence_ref.observedAt is None
            ):
                return None, True, "financial_transfer_evidence_scope_incomplete"
            transfer_refs.append(evidence_ref)
            transfer_times.append(occurred_at)

        # A path's ordered nodes must also be supported by ordered canonical
        # transfer times. Without this check, an edge sequence assembled from
        # exact entity pairs could still run backward in time or include a
        # transfer that occurred after the source trace completed. Preserve
        # that contradiction as degraded coverage instead of calling it a
        # propagation or contagion path.
        if (
            any(transfer_at > trace_completed_at for transfer_at in transfer_times)
            or any(
                earlier > later
                for earlier, later in zip(transfer_times, transfer_times[1:])
            )
        ):
            return None, True, "financial_transfer_temporal_order_inconsistent"

        allowed_states = {
            EpistemicStatus.OBSERVED,
            EpistemicStatus.DERIVED,
            EpistemicStatus.INFERRED,
        }
        financial_dimensions = {"economic", "transaction", "payment"}
        risk_contexts: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = list(transfer_refs)
        for entity_id in dict.fromkeys(path_nodes):
            entity_subject = ProjectionSubject(kind="entity", id=entity_id)
            assessment, assessment_degraded = await self._safe_assessment(
                request.tenantId, entity_subject
            )
            entity_signals, signals_degraded = await self._safe_signals(
                request.tenantId, entity_subject
            )
            if assessment_degraded or signals_degraded:
                return None, True, "financial_path_risk_read_incomplete"
            if assessment is None:
                return None, False, "financial_risk_assessment_missing_for_path_entity"
            assessment_at = _aware_datetime(assessment.assessed_at)
            if (
                not isinstance(assessment.policy_id, str)
                or not assessment.policy_id.strip()
                or not isinstance(assessment.policy_version, str)
                or not assessment.policy_version.strip()
                or assessment_at is None
                or assessment.claim_state not in allowed_states
            ):
                return None, False, "financial_risk_policy_or_freshness_unknown"

            eligible_components = {
                component.dimension: component
                for component in assessment.vector.components
                if component.dimension in financial_dimensions
                and requires_value(component.state)
                and component.claim_state in allowed_states
                and component.evidence_refs
            }
            matched_signals: list[RiskSignal] = []
            matched_components: dict[str, Any] = {}
            for signal in entity_signals:
                component = eligible_components.get(signal.risk_dimension)
                signal_observed_at = _aware_datetime(signal.observed_at)
                if (
                    component is None
                    or signal.claim_state not in allowed_states
                    or not signal.evidence_refs
                    or signal_observed_at is None
                    or signal_observed_at > assessment_at
                ):
                    continue
                component_refs = {
                    (ref.id, ref.type, ref.source, ref.uri)
                    for ref in component.evidence_refs
                }
                if not any(
                    (ref.id, ref.type, ref.source, ref.uri) in component_refs
                    for ref in signal.evidence_refs
                ):
                    continue
                matched_signals.append(signal)
                matched_components[signal.risk_dimension] = component

            if not matched_signals:
                return None, False, "financial_risk_signal_not_linked_to_policy_assessment"

            node_refs: list[EvidenceRef] = []
            for signal in matched_signals:
                node_refs.extend(signal.evidence_refs)
                node_refs.extend(matched_components[signal.risk_dimension].evidence_refs)
            node_refs = _dedupe_evidence(node_refs)
            if not node_refs:
                return None, False, "financial_risk_evidence_unavailable_for_path_entity"
            evidence_refs.extend(node_refs)
            risk_contexts.append(
                {
                    "entity_id": entity_id,
                    "assessment_id": assessment.assessment_id,
                    "policy_id": assessment.policy_id,
                    "policy_version": assessment.policy_version,
                    "assessed_at": assessment_at.isoformat(),
                    "dimensions": sorted(matched_components),
                    "signal_ids": sorted({signal.signal_id for signal in matched_signals}),
                }
            )

        if len(risk_contexts) < 2:
            return None, False, "financial_risk_link_requires_two_path_entities"
        evidence_refs = _dedupe_evidence(evidence_refs)
        if not evidence_refs:
            return None, False, "financial_contagion_evidence_unavailable"

        policies = sorted(
            {
                f"{row['policy_id']} v{row['policy_version']}"
                for row in risk_contexts
            }
        )
        assessment_times = sorted({row["assessed_at"] for row in risk_contexts})
        observed_transfer_times = sorted(
            {
                ref.observedAt
                for ref in transfer_refs
                if ref.observedAt is not None
            }
        )
        claim = (
            f"Flow trace path {request.subject.id!r} joins {len(transfer_refs)} exact positive "
            f"tenant-scoped transfer record(s) to evidence-backed economic, transaction, or "
            f"payment risk contexts for {len(risk_contexts)} path entities. The risk contexts "
            f"were assessed under {', '.join(policies)} at {', '.join(assessment_times)}; "
            f"transfer timestamps are {', '.join(observed_transfer_times)}. This is a partial "
            "financial value/risk linkage only; it does not establish contagion, causal "
            "transmission, attributed exposure, loss, or freshness against an SLA."
        )
        return (
            {
                "path_id": request.subject.id,
                "trace_id": raw_path["trace_id"],
                "risk_contexts": risk_contexts,
                "transfer_count": len(transfer_refs),
                "evidence_refs": evidence_refs,
                "claim": claim,
            },
            False,
            None,
        )

    async def _safe_source_provenance(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read source provenance only for exact ``source`` subjects."""
        if subject.kind != "source":
            return [], False
        reader = getattr(self._sources, "source_provenance_observations", None)
        if not callable(reader):
            return [], True
        try:
            raw_rows, truncated = await reader(tenant_id=tenant_id, source_id=subject.id)
        except Exception:  # noqa: BLE001 - unavailable source authority -> explicit degrade
            return [], True
        if not isinstance(raw_rows, list) or len(raw_rows) > _MAX_SOURCE_PROVENANCE_SCAN:
            return [], True

        observations: list[dict[str, Any]] = []
        degraded = bool(truncated)
        for raw in raw_rows:
            if not isinstance(raw, dict):
                degraded = True
                continue
            if raw.get("tenant_id") != tenant_id or raw.get("source_id") != subject.id:
                degraded = True
                continue
            observation_id = raw.get("observation_id")
            if not isinstance(observation_id, str) or not observation_id.strip():
                degraded = True
                continue
            try:
                evidence_ref = EvidenceRef.model_validate(raw.get("evidence_ref"))
            except Exception:  # noqa: BLE001 - malformed evidence cannot back a claim
                degraded = True
                continue
            if not evidence_ref.id.strip() or not evidence_ref.source.strip():
                degraded = True
                continue
            observed_at = raw.get("observed_at")
            if observed_at is not None and not isinstance(observed_at, str):
                degraded = True
                observed_at = None
            observations.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": subject.id,
                    "observation_id": observation_id,
                    "source_trust": raw.get("source_trust")
                    if isinstance(raw.get("source_trust"), str)
                    else None,
                    "credential_class": raw.get("credential_class")
                    if isinstance(raw.get("credential_class"), str)
                    else None,
                    "signature_status": raw.get("signature_status")
                    if isinstance(raw.get("signature_status"), str)
                    else None,
                    "adapter": raw.get("adapter") if isinstance(raw.get("adapter"), str) else None,
                    "adapter_version": raw.get("adapter_version")
                    if isinstance(raw.get("adapter_version"), str)
                    else None,
                    "observed_at": observed_at,
                    "evidence_ref": evidence_ref,
                }
            )
        return observations, degraded

    async def _safe_agent_policy_flag_observations(
        self,
        *,
        tenant_id: str,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[list[dict[str, Any]], bool, Optional[str]]:
        """Read exact reported agent flags without upgrading them to policy evaluation.

        The observation repository has tenant and agent ids plus a signal id,
        but no model-governance policy/version reference. It can therefore back
        a partial ``policy_flags`` slot for an exact agent subject only.
        Historical reads are suppressed because the legacy observation table
        has no bitemporal completeness contract.
        """
        subject = request.subject
        if context.tenantId != tenant_id:
            return [], True, "agent_policy_flag_tenant_context_mismatch"
        if subject.kind != "agent":
            return [], False, "exact_agent_subject_required"
        if (
            request.asOf is not None
            or context.asOf is not None
            or request.timeRange is not None
            or request.temporalMode in {"window", "as_of", "compare", "relative"}
        ):
            return [], False, "agent_policy_flag_bitemporal_history_unavailable"

        reader = getattr(self._sources, "agent_policy_flag_observations", None)
        if not callable(reader):
            return [], False, "agent_policy_flag_authority_unavailable"
        try:
            raw_rows = await reader(tenant_id=tenant_id, agent_id=subject.id)
        except Exception:  # noqa: BLE001 - provider boundary degrades safely
            return [], True, "agent_policy_flag_read_incomplete"
        if not isinstance(raw_rows, list) or len(raw_rows) > _MAX_AGENT_POLICY_FLAG_SCAN:
            return [], True, "agent_policy_flag_scan_limit_exceeded"

        observations: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        degraded = False
        for raw in raw_rows:
            if not isinstance(raw, dict):
                degraded = True
                continue
            if (
                str(raw.get("tenant_id", "")) != tenant_id
                or str(raw.get("agent_id", "")) != subject.id
            ):
                degraded = True
                continue

            signal_id = raw.get("signal_id")
            flags = raw.get("policy_flags")
            if not isinstance(signal_id, str) or not signal_id.strip() or signal_id in seen_ids:
                degraded = True
                continue
            seen_ids.add(signal_id)
            if not isinstance(flags, list):
                degraded = True
                continue
            safe_flags: list[str] = []
            for flag in flags[:20]:
                if not isinstance(flag, str) or not flag.strip() or len(flag) > 128:
                    degraded = True
                    continue
                if flag not in safe_flags:
                    safe_flags.append(flag)
            if len(flags) > 20:
                degraded = True
            if not safe_flags:
                continue

            detected_at = raw.get("detected_at")
            if detected_at is not None and (
                not isinstance(detected_at, str) or _aware_datetime(detected_at) is None
            ):
                detected_at = None
                degraded = True
            evidence_ref = EvidenceRef(
                id=signal_id,
                type="event",
                source="obs_agent_risk_signals",
                observedAt=detected_at,
                uri=f"store://obs_agent_risk_signals/{signal_id}",
            )
            observations.append(
                {
                    "tenant_id": tenant_id,
                    "agent_id": subject.id,
                    "signal_id": signal_id,
                    "policy_flags": safe_flags,
                    "detected_at": detected_at,
                    "evidence_ref": evidence_ref,
                }
            )
        observations.sort(key=lambda row: (row["detected_at"] or "", row["signal_id"]))
        return observations, degraded, (
            "agent_policy_flag_record_invalid_or_scope_incomplete" if degraded else None
        )

    @staticmethod
    def _poisoning_as_of(
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[Optional[datetime], Optional[str]]:
        """Resolve a point-in-time anchor or explain unsupported temporal reads."""
        if request.timeRange is not None or request.temporalMode in {
            "window",
            "compare",
            "relative",
        }:
            return None, "poisoning_evidence_window_history_unavailable"

        request_anchor = _aware_datetime(request.asOf) if request.asOf is not None else None
        context_anchor = _aware_datetime(context.asOf) if context.asOf is not None else None
        if request.asOf is not None and request_anchor is None:
            return None, "poisoning_evidence_as_of_anchor_invalid"
        if context.asOf is not None and context_anchor is None:
            return None, "poisoning_evidence_context_anchor_invalid"
        if request_anchor is not None and context_anchor is not None:
            if request_anchor != context_anchor:
                return None, "poisoning_evidence_as_of_anchor_mismatch"
        anchor = request_anchor or context_anchor
        if request.temporalMode == "as_of" and anchor is None:
            return None, "poisoning_evidence_as_of_anchor_missing"
        return anchor, None

    @staticmethod
    def _assessment_history_as_of(
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[Optional[datetime], Optional[str]]:
        """Resolve a system-time history anchor without guessing for ranges."""
        if request.timeRange is not None or request.temporalMode in {"compare", "relative"}:
            return None, "risk_assessment_history_window_anchor_unavailable"
        request_anchor = _aware_datetime(request.asOf) if request.asOf is not None else None
        context_anchor = _aware_datetime(context.asOf) if context.asOf is not None else None
        if request.asOf is not None and request_anchor is None:
            return None, "risk_assessment_history_as_of_anchor_invalid"
        if context.asOf is not None and context_anchor is None:
            return None, "risk_assessment_history_context_anchor_invalid"
        if request_anchor is not None and context_anchor is not None:
            if request_anchor != context_anchor:
                return None, "risk_assessment_history_as_of_anchor_mismatch"
        anchor = request_anchor or context_anchor
        if request.temporalMode == "as_of" and anchor is None:
            return None, "risk_assessment_history_as_of_anchor_missing"
        return anchor, None

    async def _safe_assessment_history(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[datetime],
    ) -> tuple[list[dict[str, Any]], bool, Optional[str]]:
        """Read and revalidate bounded exact-subject computation run history."""
        reader = getattr(self._sources, "assessment_history", None)
        if not callable(reader):
            return [], False, "risk_assessment_history_authority_unavailable"
        try:
            result = await reader(tenant_id=tenant_id, subject=subject, as_of=as_of)
        except Exception:  # noqa: BLE001 - provider boundary degrades safely
            return [], True, "risk_assessment_run_history_read_incomplete"
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], list)
            or not isinstance(result[1], bool)
        ):
            return [], True, "risk_assessment_history_read_contract_invalid"

        raw_rows, complete = result
        if len(raw_rows) > _MAX_ASSESSMENT_HISTORY_SCAN:
            return [], True, "risk_assessment_run_history_scan_limit_exceeded"
        rows: list[dict[str, Any]] = []
        degraded = not complete
        reason = None if complete else "risk_assessment_run_history_scan_truncated"
        for raw in raw_rows:
            if not isinstance(raw, dict):
                degraded = True
                reason = reason or "risk_assessment_history_row_invalid"
                continue
            started_at = _aware_datetime(raw.get("started_at"))
            if (
                str(raw.get("tenant_id", "")) != tenant_id
                or raw.get("subject_kind") != subject.kind
                or raw.get("subject_id") != subject.id
                or not isinstance(raw.get("run_id"), str)
                or not raw["run_id"].strip()
                or not isinstance(raw.get("assessment_id"), str)
                or not raw["assessment_id"].strip()
                or not isinstance(raw.get("definition_id"), str)
                or not raw["definition_id"].startswith("risk360.")
            ):
                degraded = True
                reason = reason or "risk_assessment_history_exact_binding_mismatch"
                continue
            if started_at is None:
                degraded = True
                reason = reason or "risk_assessment_history_timestamp_invalid"
                continue
            if as_of is not None and started_at > as_of:
                degraded = True
                reason = reason or "risk_assessment_history_as_of_read_inconsistent"
                continue
            dimensions = raw.get("dimensions")
            if not isinstance(dimensions, list) or any(
                not isinstance(dimension, str) for dimension in dimensions
            ):
                degraded = True
                reason = reason or "risk_assessment_history_dimensions_invalid"
                dimensions = []
            rows.append(
                {
                    **raw,
                    "started_at": started_at.isoformat(),
                    "completed_at": (
                        _aware_datetime(raw.get("completed_at")).isoformat()
                        if _aware_datetime(raw.get("completed_at")) is not None
                        else None
                    ),
                    "dimensions": dimensions,
                }
            )
        rows.sort(
            key=lambda row: (row["started_at"], row["run_id"]),
            reverse=True,
        )
        return rows, degraded, reason

    @staticmethod
    def _assessment_history_evidence(rows: list[dict[str, Any]]) -> list[EvidenceRef]:
        """Make each exact run-history record traceable to its substrate row."""
        evidence: list[EvidenceRef] = []
        for row in rows:
            run_id = row.get("run_id")
            started_at = row.get("started_at")
            if not isinstance(run_id, str) or not isinstance(started_at, str):
                continue
            evidence.append(
                EvidenceRef(
                    id=run_id,
                    type="model_output",
                    source="computation_runs",
                    observedAt=started_at,
                    uri=f"store://computation_runs/{run_id}",
                )
            )
        return evidence

    @staticmethod
    def _assessment_history_summary(
        rows: list[dict[str, Any]],
        *,
        degraded: bool,
        reason: Optional[str],
    ) -> dict[str, Any]:
        """Render assessment-run history while preserving uncovered audit areas."""
        state = "degraded" if degraded else "partial" if rows else "unknown"
        if degraded:
            resolved_reason = reason or "risk_assessment_run_history_read_incomplete"
        elif rows:
            resolved_reason = (
                "assessment_run_history_available_intervention_audit_and_full_restatement_lineage_unavailable"
            )
        else:
            resolved_reason = reason or "risk_assessment_run_history_unavailable"
        records = [
            {
                "runId": row["run_id"],
                "assessmentId": row["assessment_id"],
                "definitionId": row["definition_id"],
                "definitionVersion": row.get("definition_version"),
                "contextHash": row.get("context_hash"),
                "status": row.get("status"),
                "startedAt": row["started_at"],
                "completedAt": row.get("completed_at"),
                "supersedesRunId": row.get("supersedes_run_id"),
                "claimState": row.get("claim_state"),
                "dimensions": list(row.get("dimensions") or []),
                "evidenceRef": Risk360Provider._assessment_history_evidence([row])[0].model_dump(
                    mode="json"
                ),
            }
            for row in rows
        ]
        return {
            "state": state,
            "reason": resolved_reason,
            "assessmentRuns": records,
            "interventions": {
                "state": "unknown",
                "reason": "risk_intervention_authority_unavailable",
            },
            "coverage": {
                "completeRunScan": not degraded and reason is None,
                "assessmentVersionLineage": "partial",
                "interventionAuditLineage": "unavailable",
                "rawRunPayload": "excluded",
            },
        }

    async def _safe_poisoning_evidence(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[datetime],
    ) -> tuple[list[RiskPoisoningEvidence], bool, Optional[str]]:
        """Read bounded evidence and revalidate exact source/subject bindings."""
        reader = getattr(self._sources, "poisoning_evidence", None)
        if not callable(reader):
            return [], False, "data_poisoning_evidence_authority_unavailable"
        try:
            result = await reader(tenant_id=tenant_id, subject=subject, as_of=as_of)
        except Exception:  # noqa: BLE001 - provider boundary returns safe typed absence
            return [], True, "poisoning_evidence_read_incomplete"

        raw_records = getattr(result, "records", None)
        complete = getattr(result, "complete", None)
        read_reason = getattr(result, "reason", None)
        if not isinstance(raw_records, list) or not isinstance(complete, bool):
            return [], True, "poisoning_evidence_read_contract_invalid"
        if len(raw_records) > _MAX_POISONING_EVIDENCE_SCAN:
            return [], True, "poisoning_evidence_scan_limit_exceeded"

        records: list[RiskPoisoningEvidence] = []
        seen_ids: set[str] = set()
        reason = read_reason.strip() if isinstance(read_reason, str) and read_reason.strip() else None
        degraded = not complete or reason is not None
        if reason is None and not complete:
            reason = "poisoning_evidence_scan_truncated"
        for raw in raw_records:
            try:
                record = (
                    raw
                    if isinstance(raw, RiskPoisoningEvidence)
                    else RiskPoisoningEvidence.model_validate(raw)
                )
            except Exception:  # noqa: BLE001 - malformed records cannot back a claim
                degraded = True
                reason = reason or "poisoning_evidence_contract_invalid"
                continue
            if (
                record.tenant_id != tenant_id
                or record.subject_kind != subject.kind
                or record.subject_id != subject.id
                or not record.source_id.strip()
                or (subject.kind == "source" and record.source_id != subject.id)
            ):
                degraded = True
                reason = reason or "poisoning_evidence_exact_binding_mismatch"
                continue
            if record.evidence_id in seen_ids:
                degraded = True
                reason = reason or "poisoning_evidence_duplicate_record"
                continue
            seen_ids.add(record.evidence_id)
            if as_of is not None:
                if record.recorded_at > as_of:
                    degraded = True
                    reason = reason or "poisoning_evidence_as_of_read_inconsistent"
                    continue
                events = [
                    event
                    for event in record.lifecycle_events
                    if event.occurred_at <= as_of
                ]
                status = "open"
                superseded_by = None
                for event in events:
                    status = event.to_status
                    if status == "superseded":
                        superseded_by = record.superseded_by_evidence_id
                record = record.model_copy(
                    update={
                        "status": status,
                        "superseded_by_evidence_id": superseded_by,
                        "lifecycle_events": events,
                    }
                )
            records.append(record)

        records.sort(
            key=lambda record: (record.recorded_at, record.evidence_id),
            reverse=True,
        )
        return records, degraded, reason

    async def _safe_assessment(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[Optional[RiskAssessment], bool]:
        """Latest tenant RiskAssessment, or (None, degraded) — never raises."""
        degraded = False
        raw: Optional[dict[str, Any]] = None
        try:
            raw = await self._sources.latest_assessment(tenant_id=tenant_id, subject=subject)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return None, True
        if raw is None:
            return None, False
        # Tenant scope is server-authoritative: never project another tenant's
        # assessment/sections/evidence.
        if (
            str(raw.get("tenant_id", "")) != tenant_id
            or str(raw.get("subject_kind", "")) != subject.kind
            or str(raw.get("subject_id", "")) != subject.id
        ):
            return None, True
        try:
            return RiskAssessment(**raw), degraded
        except Exception:  # noqa: BLE001 - unrenderable record -> degrade
            return None, True

    async def _safe_signals(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[list[RiskSignal], bool]:
        """Tenant RiskSignal rows parsed to contracts — never raises."""
        degraded = False
        raw_rows: list[dict[str, Any]] = []
        try:
            raw_rows = await self._sources.signals(tenant_id=tenant_id, subject=subject)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return [], True
        signals: list[RiskSignal] = []
        if len(raw_rows) > _MAX_SIGNAL_SCAN:
            return [], True
        for raw in raw_rows:
            # Server-authoritative tenant filter; a leaky row is dropped, not
            # surfaced (and never mistaken for a degraded read of this tenant).
            if (
                str(raw.get("tenant_id", "")) != tenant_id
                or str(raw.get("subject_kind", "")) != subject.kind
                or str(raw.get("subject_id", "")) != subject.id
            ):
                degraded = True
                continue
            try:
                signals.append(RiskSignal(**raw))
            except Exception:  # noqa: BLE001 - skip an unrenderable signal row
                degraded = True
                continue
        return signals, degraded

    @staticmethod
    def _assessment_evidence(assessment: RiskAssessment) -> list[EvidenceRef]:
        """EvidenceRefs the assessment itself carries (level + component rows)."""
        refs = list(assessment.evidence_refs)
        for component in assessment.vector.components:
            refs.extend(component.evidence_refs)
        return _dedupe_evidence(refs)

    @staticmethod
    def _collect_evidence(
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
        source_provenance: list[dict[str, Any]],
        poisoning_evidence: list[RiskPoisoningEvidence],
        agent_policy_flags: list[dict[str, Any]],
    ) -> list[EvidenceRef]:
        """Every canonical EvidenceRef grounding this projection, deduped."""
        refs: list[EvidenceRef] = []
        if assessment is not None:
            refs.extend(Risk360Provider._assessment_evidence(assessment))
        for signal in signals:
            refs.extend(signal.evidence_refs)
        for row in source_provenance:
            ref = row.get("evidence_ref")
            if isinstance(ref, EvidenceRef):
                refs.append(ref)
        for record in poisoning_evidence:
            refs.extend(record.evidence_refs)
            for event in record.lifecycle_events:
                refs.extend(event.evidence_refs)
        for row in agent_policy_flags:
            evidence_ref = row.get("evidence_ref")
            if isinstance(evidence_ref, EvidenceRef):
                refs.append(evidence_ref)
        return _dedupe_evidence(refs)


def _dedupe_evidence(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Dedupe reused EvidenceRefs by their canonical wire identity."""
    seen: set[tuple[Any, ...]] = set()
    deduped: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.id, ref.type, ref.source, ref.uri)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Risk360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Risk360Provider(), source="services/api/intelligence/risk360")


__all__ = [
    "EXPLORE_CAPABILITY",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "READ_CAPABILITY",
    "RepositoryRiskSourceReader",
    "Risk360Provider",
    "RiskSourceReader",
    "SECTION_DEPENDENCIES",
    "build_projection_request",
    "register_provider",
]
