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
:class:`RiskSourceReader``). The default :class:`RepositoryRiskSourceReader`
reads tenant-scoped risk assessments/signals, Gold anomaly-alert materializations,
poisoning evidence, intervention records, and computation-run history. Graph
paths and financial transfers stay on their own canonical read authorities.

Imports stay lazy/defensive: importing this module must never require a
database, a store backend, or any heavy canonical service. All canonical reads
happen inside :meth:`Risk360Provider.project`, each wrapped so an unavailable
backing source degrades its section.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
    RiskInterventionRecord,
    RiskPoisoningEvidence,
    RiskSignal,
)
from intelligence.risk360.dimensions import RISK_DIMENSIONS
from intelligence.risk360.store import (
    RiskAssessmentRepository,
    RiskInterventionRead,
    RiskInterventionRepository,
    RiskInterventionReadIncomplete,
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
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "financial_risk",
    "evidence",
    "findings",
    "health",
)

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
_MAX_RISK_ANOMALY_SCAN = 100
_MAX_SOURCE_PROVENANCE_SCAN = 100
_MAX_POISONING_EVIDENCE_SCAN = 100
_MAX_RISK_INTERVENTION_SCAN = 100
_MAX_ASSESSMENT_HISTORY_SCAN = 100
_MAX_RISK_SOCIAL_CONTAGION_SCAN = 100
_MAX_RISK_SOCIAL_CONTAGION_EVIDENCE_REFS = 512
_MAX_FINANCIAL_PATH_NODES = 21
_MAX_TRANSFERS_PER_PATH_EDGE = 2
_MAX_SOCIAL_PROPAGATION_PATHS = 50
_FINANCIAL_RISK_DIMENSIONS = {"economic", "payment", "transaction"}
_FINANCIAL_RISK_SUBJECT_KINDS = {"agent", "cluster", "entity", "source"}

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


@dataclass(frozen=True)
class RiskAnomalyEventRead:
    """Bounded exact-subject anomaly-alert materializations from Gold."""

    records: list[dict[str, Any]]
    complete: bool
    reason: Optional[str] = None


def _dependency_missing(dep_state: list[Any], projection_id: str) -> bool:
    """True when a sibling projection is missing or not yet available."""
    dep = next((d for d in dep_state if d.projectionId == projection_id), None)
    return dep is None or dep.state != "available"


def _is_current_subject_read(
    request: ProjectionRequest,
    context: ProjectionContext,
) -> bool:
    """Whether current-only Risk360 claims may be routed into Value360."""
    return (
        request.asOf is None
        and context.asOf is None
        and request.timeRange is None
        and request.temporalMode in {None, "window"}
    )


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


def _risk_evidence_slot_ids(
    subject_kind: str,
    *,
    risk_dimension: Optional[str] = None,
    current_subject_read: bool = False,
) -> list[str]:
    """Map atomic risk observations to slots supported for this subject kind."""
    slot_ids = ["risk_evidence_and_limitations", "evidence_trace"]
    if subject_kind == "agent":
        # Agent subjects are accepted by Agent360; the exact summary slot is
        # the governed Risk360 destination. ``risk_signals`` is not a product
        # SSOT slot and must not escape as an invented compatibility binding.
        slot_ids.append("risk_summary")
    elif subject_kind == "support_case":
        slot_ids.insert(0, "risk")
    if (
        current_subject_read
        and subject_kind in _FINANCIAL_RISK_SUBJECT_KINDS
        and risk_dimension in _FINANCIAL_RISK_DIMENSIONS
    ):
        # Value360 requires an assessed financial dimension (risk output), not
        # a generic RiskSignal, and joins it to economic facts by the exact
        # tenant + subject already bound to this projection request.
        slot_ids.append("financial_risk")
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

    async def anomaly_events(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> RiskAnomalyEventRead:
        """Exact tenant/typed-subject Gold anomaly-alert records."""
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

    async def interventions(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: Optional[datetime],
    ) -> RiskInterventionRead:
        """Bounded immutable intervention decision/outcome records."""
        ...

    async def financial_flow_path_subjects(
        self,
        *,
        tenant_id: str,
        path_id: str,
    ) -> Optional[dict[str, Any]]:
        """Discover exact path entity subjects without reading flow details."""
        ...

    async def financial_flow_path_details(
        self,
        *,
        tenant_id: str,
        path_id: str,
        trace_id: str,
        path_nodes: list[str],
        path_discovered_at: datetime,
    ) -> Optional[dict[str, Any]]:
        """Read trace/transfer detail after exact path entities pass consent."""
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
        self._interventions = RiskInterventionRepository()
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
            supersedes_run_id = data.get("supersedes_run_id")
            restatement_link: Optional[dict[str, Any]] = None
            if supersedes_run_id is not None:
                if (
                    not isinstance(supersedes_run_id, str)
                    or not supersedes_run_id.strip()
                    or supersedes_run_id == run_id
                ):
                    raise RiskSourceReadIncomplete(
                        "risk assessment run supersession reference is invalid"
                    )
                prior = await self._runs.get_run(tenant_id, supersedes_run_id)
                prior_data = _decode_mapping(prior.get("data")) if isinstance(prior, dict) else {}
                prior_started = (
                    _aware_datetime(prior.get("started_at")) if isinstance(prior, dict) else None
                )
                if (
                    not isinstance(prior, dict)
                    or str(prior.get("tenant_id", "")) != tenant_id
                    or prior.get("run_id") != supersedes_run_id
                    or prior.get("definition_id") != row.get("definition_id")
                    or prior.get("definition_version") != row.get("definition_version")
                    or not isinstance(row.get("definition_version"), str)
                    or not row["definition_version"].strip()
                    or prior.get("context_hash") != row.get("context_hash")
                    or not isinstance(row.get("context_hash"), str)
                    or not row["context_hash"].strip()
                    or prior.get("status") != "completed"
                    or row.get("status") != "completed"
                    or prior_data.get("assessment_id") != assessment_id
                    or prior_data.get("subject_kind") != subject.kind
                    or prior_data.get("subject_id") != subject.id
                    or prior_started is None
                    or started is None
                    or prior_started > started
                ):
                    raise RiskSourceReadIncomplete(
                        "risk assessment run supersession predecessor scope is incomplete"
                    )
                restatement_link = {
                    "state": "verified_direct_predecessor",
                    "prior_tenant_id": tenant_id,
                    "prior_subject_kind": subject.kind,
                    "prior_subject_id": subject.id,
                    "prior_run_id": supersedes_run_id,
                    "prior_assessment_id": assessment_id,
                    "prior_definition_id": str(prior.get("definition_id", "")),
                    "prior_definition_version": prior["definition_version"],
                    "prior_context_hash": prior["context_hash"],
                    "prior_status": prior.get("status"),
                    "prior_started_at": prior_started.isoformat(),
                }
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
                    "supersedes_run_id": supersedes_run_id,
                    "restatement_link": restatement_link,
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

    async def anomaly_events(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> RiskAnomalyEventRead:
        """Read exact tenant-owned Gold anomaly alerts for one typed subject.

        Gold is the existing alert materialization authority, not an immutable
        event ledger. An optional ``dimensions`` triplet (``risk_signal_id``,
        ``source_event_id``, ``source_event_source``) joins to one canonical
        RiskSignal and its exact event EvidenceRef. Without that explicit link,
        the alert remains metadata only. Consumers receive the alert record's
        storage timestamp rather than an invented source event time.
        """
        if not tenant_id or not subject.kind or not subject.id:
            return RiskAnomalyEventRead([], complete=False, reason="exact_anomaly_subject_required")
        from repositories.lake import gold_identity

        rows = await gold_identity.find_many(
            filters={
                "tenant_id": tenant_id,
                "metric_name": "anomaly_alert",
                "entity_id": subject.id,
                "entity_type": subject.kind,
            },
            limit=_MAX_RISK_ANOMALY_SCAN + 1,
            sort_by="updated_at",
            sort_order="desc",
        )
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RiskSourceReadIncomplete("Gold anomaly alert read contract is invalid")
        exact = [
            row
            for row in rows
            if str(row.get("tenant_id", "")) == tenant_id
            and row.get("metric_name") == "anomaly_alert"
            and row.get("entity_id") == subject.id
            and row.get("entity_type") == subject.kind
        ]
        if len(exact) != len(rows):
            raise RiskSourceReadIncomplete("Gold anomaly alert scope is incomplete")
        truncated = len(exact) > _MAX_RISK_ANOMALY_SCAN
        enriched: list[dict[str, Any]] = []
        for row in exact[:_MAX_RISK_ANOMALY_SCAN]:
            enriched.append(
                {
                    **row,
                    "source_event_join": await self._anomaly_source_event_join(
                        row, tenant_id=tenant_id, subject=subject
                    ),
                }
            )
        return RiskAnomalyEventRead(
            records=enriched,
            complete=not truncated,
            reason="gold_anomaly_alert_scan_truncated" if truncated else None,
        )

    async def _anomaly_source_event_join(
        self,
        alert: dict[str, Any],
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> dict[str, Any]:
        """Resolve only an explicit Gold-to-signal-to-event-evidence binding."""
        dimensions = alert.get("dimensions")
        if not isinstance(dimensions, dict):
            return {"state": "degraded", "reason": "anomaly_alert_dimensions_invalid"}
        keys = ("risk_signal_id", "source_event_id", "source_event_source")
        if not any(key in dimensions for key in keys):
            return {"state": "unknown", "reason": "explicit_anomaly_event_reference_unavailable"}
        values = [dimensions.get(key) for key in keys]
        if any(not isinstance(value, str) or not value.strip() for value in values):
            return {"state": "degraded", "reason": "anomaly_event_reference_incomplete"}
        signal_id, event_id, event_source = values
        try:
            raw_signal = await self._signals.get_scoped(tenant_id, signal_id)
        except Exception:  # noqa: BLE001 - preserve the independently scoped Gold alert
            return {"state": "degraded", "reason": "anomaly_event_risk_signal_read_failed"}
        if not isinstance(raw_signal, dict):
            return {"state": "degraded", "reason": "anomaly_event_risk_signal_unavailable"}
        try:
            signal = RiskSignal.model_validate(raw_signal)
        except ValidationError:
            return {"state": "degraded", "reason": "anomaly_event_risk_signal_invalid"}
        if (
            signal.tenant_id != tenant_id
            or signal.subject_kind != subject.kind
            or signal.subject_id != subject.id
            or signal.signal_id != signal_id
            or not signal.source.strip()
        ):
            return {"state": "degraded", "reason": "anomaly_event_risk_signal_scope_mismatch"}
        matching_refs = [
            ref
            for ref in signal.evidence_refs
            if ref.id == event_id and ref.source == event_source and ref.type == "event"
        ]
        if len(matching_refs) != 1:
            return {"state": "degraded", "reason": "anomaly_event_evidence_reference_unverified"}
        joined = {
            "state": "verified_signal_evidence_reference",
            "risk_signal_id": signal_id,
            "detector_source": signal.source,
            "detector_version": signal.detector_version,
            "signal_claim_state": signal.claim_state.value,
            "evidence_ref": matching_refs[0],
            "source_event_record_read": "not_performed",
        }
        if event_source == "bronze_sdk_events":
            joined.update(
                await self._exact_bronze_anomaly_event(tenant_id=tenant_id, event_id=event_id)
            )
        return joined

    @staticmethod
    async def _exact_bronze_anomaly_event(*, tenant_id: str, event_id: str) -> dict[str, Any]:
        """Corroborate one explicit Bronze pointer without reading event payloads.

        Both typed V2 and legacy V1 SDK rows can carry the event. The two-row
        bound detects duplicate schema versions or mixed V1/V2 records rather
        than choosing one arbitrarily. A tombstoned, quarantined, or malformed
        row never becomes event evidence for an alert.
        """
        from repositories.repos import _IN_MEMORY_STORES, get_pool

        try:
            pool = await get_pool()
            if pool is None:
                candidates = []
                for row in _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {}).values():
                    if not isinstance(row, dict) or row.get("tenant_id") != tenant_id:
                        continue
                    if row.get("event_id") == event_id or (
                        row.get("event_id") is None
                        and row.get("provider_record_id") == event_id
                    ):
                        candidates.append(row)
                        if len(candidates) == 2:
                            break
            else:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT id, tenant_id, event_id, schema_version,
                                  event_timestamp, received_at, source,
                                  data->>'provider_record_id' AS provider_record_id,
                                  data #>> '{payload,event_id}' AS legacy_event_id,
                                  data->>'source' AS legacy_source,
                                  data->>'ingested_at' AS ingested_at,
                                  data->>'quarantine_status' AS quarantine_status,
                                  data->>'tombstoned' AS tombstoned
                           FROM bronze_sdk_events
                           WHERE tenant_id = $1
                             AND (event_id = $2 OR
                                  (event_id IS NULL AND data->>'provider_record_id' = $2))
                           ORDER BY created_at DESC, id ASC
                           LIMIT 2""",
                        tenant_id,
                        event_id,
                    )
                candidates = [dict(row) for row in rows]
        except Exception:  # noqa: BLE001 - a Gold alert remains independently readable
            return {"source_event_record_read": "unavailable"}

        if not candidates:
            return {"source_event_record_read": "unavailable"}
        if len(candidates) != 1:
            return {"source_event_record_read": "ambiguous"}
        row = candidates[0]
        raw_data = _decode_mapping(row.get("data"))
        bronze_id = row.get("id")
        typed_event_id = row.get("event_id")
        legacy_event_id = row.get("legacy_event_id") or _decode_mapping(
            row.get("payload") if typed_event_id is None else raw_data.get("payload")
        ).get("event_id")
        legacy_id = row.get("provider_record_id") or raw_data.get("provider_record_id")
        source = row.get("source") or row.get("legacy_source") or raw_data.get("source")
        tombstoned = row.get("tombstoned") or raw_data.get("tombstoned")
        quarantine_status = row.get("quarantine_status") or raw_data.get(
            "quarantine_status"
        )
        if (
            row.get("tenant_id") != tenant_id
            or not isinstance(bronze_id, str)
            or not bronze_id
            or source != "sdk"
            or tombstoned is True
            or tombstoned == "true"
            or quarantine_status == "quarantined"
            or (
                typed_event_id == event_id
                and (
                    not isinstance(row.get("schema_version"), str)
                    or not row["schema_version"].strip()
                )
            )
            or (
                typed_event_id is None
                and (legacy_id != event_id or legacy_event_id != event_id)
            )
            or (typed_event_id is not None and typed_event_id != event_id)
        ):
            return {"source_event_record_read": "invalid"}

        event_time = _aware_datetime(row.get("event_timestamp"))
        recorded_at = _aware_datetime(
            row.get("received_at") or row.get("ingested_at") or raw_data.get("ingested_at")
        )
        return {
            "source_event_record_read": "verified_exact_bronze_record",
            "source_event_record_evidence_ref": EvidenceRef(
                id=event_id,
                type="event",
                source="bronze_sdk_events",
                observedAt=event_time.isoformat() if event_time is not None else None,
                uri=f"store://bronze_sdk_events/{quote(bronze_id, safe='')}",
            ),
            "source_event_recorded_at": (
                recorded_at.isoformat() if recorded_at is not None else None
            ),
        }

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

    async def interventions(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: Optional[datetime],
    ) -> RiskInterventionRead:
        """Read immutable risk intervention records for an exact subject."""
        if not tenant_id or not subject.kind or not subject.id:
            raise RiskInterventionReadIncomplete(
                "risk intervention read requires exact tenant and subject scope"
            )
        return await self._interventions.list_for_subject(
            tenant_id,
            subject.kind,
            subject.id,
            as_of=as_of,
            limit=_MAX_RISK_INTERVENTION_SCAN,
        )

    async def financial_flow_path_subjects(
        self,
        *,
        tenant_id: str,
        path_id: str,
    ) -> Optional[dict[str, Any]]:
        """Discover path membership before any trace or transfer detail read."""
        if not tenant_id or not path_id:
            return None

        from repositories.repos import FlowTracePathRepository

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
            return {
                "tenant_id": tenant_id,
                "path_id": path_id,
                "trace_id": None,
                "path_nodes": [],
                "hop_count": None,
                "path_discovered_at": path.get("discovered_at"),
                "linkage_reason": "financial_flow_trace_reference_unavailable",
            }

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
                "hop_count": hop_count,
                "path_discovered_at": path.get("discovered_at"),
                "linkage_reason": "financial_flow_path_sequence_not_exact",
            }

        discovered_at = _aware_datetime(path.get("discovered_at"))
        if discovered_at is None:
            return {
                "tenant_id": tenant_id,
                "path_id": path_id,
                "trace_id": trace_id,
                "path_nodes": [],
                "hop_count": hop_count,
                "path_discovered_at": path.get("discovered_at"),
                "linkage_reason": "financial_flow_path_discovery_time_unavailable",
            }

        return {
            "tenant_id": tenant_id,
            "path_id": path_id,
            "trace_id": trace_id,
            "path_nodes": list(raw_nodes),
            "hop_count": hop_count,
            "path_discovered_at": discovered_at.isoformat(),
            "linkage_reason": None,
        }

    async def financial_flow_path_details(
        self,
        *,
        tenant_id: str,
        path_id: str,
        trace_id: str,
        path_nodes: list[str],
        path_discovered_at: datetime,
    ) -> Optional[dict[str, Any]]:
        """Read trace and transfer facts only after consent for path members.

        The flow path is reread and compared with the consent-gated discovery
        result before any transfer query, preventing a changed path from
        substituting unconsented entity subjects between the two reads.
        """
        if (
            not tenant_id
            or not path_id
            or not trace_id
            or not path_nodes
            or path_discovered_at.tzinfo is None
        ):
            raise RiskSourceReadIncomplete("financial flow detail scope is incomplete")

        from repositories.repos import (
            FlowTracePathRepository,
            FlowTraceRepository,
            TransferRepository,
        )

        path = await FlowTracePathRepository().find_by_id(path_id)
        if (
            not isinstance(path, dict)
            or str(path.get("id", "")) != path_id
            or str(path.get("tenant_id", "")) != tenant_id
            or path.get("trace_id") != trace_id
            or path.get("path_nodes") != path_nodes
            or path.get("hop_count") != len(path_nodes) - 1
            or _aware_datetime(path.get("discovered_at")) != path_discovered_at
        ):
            raise RiskSourceReadIncomplete(
                "financial flow path changed after consent-gated discovery"
            )

        trace = await FlowTraceRepository().find_by_id(trace_id)
        if (
            not isinstance(trace, dict)
            or str(trace.get("id", "")) != trace_id
            or str(trace.get("tenant_id", "")) != tenant_id
            or trace.get("status") != "complete"
        ):
            raise RiskSourceReadIncomplete("financial flow trace scope is incomplete")

        transfer_repo = TransferRepository()
        transfer_edges: list[dict[str, Any]] = []
        for from_entity_id, to_entity_id in zip(path_nodes, path_nodes[1:]):
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
                    "path_nodes": list(path_nodes),
                    "hop_count": len(path_nodes) - 1,
                    "path_discovered_at": path_discovered_at.isoformat(),
                    "trace_completed_at": trace.get("completed_at"),
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
            "path_nodes": list(path_nodes),
            "hop_count": len(path_nodes) - 1,
            "path_discovered_at": path_discovered_at.isoformat(),
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
        social_evidence_authority: Optional[Any] = None,
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
        self._social_evidence_authority = social_evidence_authority
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

        if not support_case_scope_verified:
            anomaly_events, anomaly_events_degraded = [], False
            anomaly_events_reason = "support_case_subject_scope_unavailable"
        elif context.tenantId != tenant_id:
            anomaly_events, anomaly_events_degraded = [], True
            anomaly_events_reason = "risk_anomaly_alert_tenant_context_mismatch"
        elif not _is_current_subject_read(request, context):
            anomaly_events, anomaly_events_degraded = [], False
            anomaly_events_reason = "gold_anomaly_alert_bitemporal_history_unavailable"
        else:
            (
                anomaly_events,
                anomaly_events_degraded,
                anomaly_events_reason,
            ) = await self._safe_anomaly_events(tenant_id, request.subject)

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

        interventions_as_of, intervention_anchor_reason = self._interventions_as_of(
            request, context
        )
        if not support_case_scope_verified:
            interventions, interventions_degraded = [], False
            interventions_reason = "support_case_subject_scope_unavailable"
        elif context.tenantId != tenant_id:
            interventions, interventions_degraded = [], True
            interventions_reason = "risk_intervention_tenant_context_mismatch"
        elif intervention_anchor_reason is not None:
            interventions, interventions_degraded = [], False
            interventions_reason = intervention_anchor_reason
        else:
            (
                interventions,
                interventions_degraded,
                interventions_reason,
            ) = await self._safe_interventions(
                tenant_id,
                request.subject,
                as_of=interventions_as_of,
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
            social_contagion, social_contagion_claims = self._unknown_social_contagion(
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
            social_contagion, social_contagion_claims = self._unknown_social_contagion(
                "support_case_contagion_authority_not_connected"
            ), []
        else:
            financial_link, financial_link_degraded, financial_link_reason = (
                await self._safe_financial_contagion_link(request, context)
            )
            social_propagation, social_path_claims = await self._safe_social_propagation_paths(
                request, context
            )
            social_contagion, social_contagion_claims = (
                await self._safe_social_contagion_evidence(request, context)
            )

        evidence = self._collect_evidence(
            assessment,
            signals,
            anomaly_events,
            source_provenance,
            poisoning_evidence,
            agent_policy_flags,
            interventions,
        )
        if support_case_evidence:
            evidence = _dedupe_evidence([*evidence, *support_case_evidence])
        if financial_link is not None:
            evidence = _dedupe_evidence([*evidence, *financial_link["evidence_refs"]])
        evidence = _dedupe_evidence([*evidence, *social_propagation["evidence_refs"]])
        evidence = _dedupe_evidence([*evidence, *social_contagion["evidence_refs"]])
        history_evidence = self._assessment_history_evidence(assessment_history)
        evidence = _dedupe_evidence([*evidence, *history_evidence])

        sections = [
            self._summary_section(request, assessment, assessment_degraded, dep_state),
            self._state_section(request, assessment, assessment_degraded, dep_state),
            self._financial_risk_section(
                request,
                assessment,
                assessment_degraded,
                current_subject_read=_is_current_subject_read(request, context),
            ),
            self._evidence_section(
                evidence,
                source_degraded=(
                    assessment_degraded
                    or signals_degraded
                    or source_provenance_degraded
                    or poisoning_evidence_degraded
                    or interventions_degraded
                    or assessment_history_degraded
                    or anomaly_events_degraded
                    or financial_link_degraded
                    or social_propagation["state"] == "degraded"
                    or social_contagion["state"] == "degraded"
                ),
            ),
            self._findings_section(
                request,
                assessment,
                assessment_degraded,
                signals,
                anomaly_events,
                anomaly_events_degraded,
                anomaly_events_reason,
                evidence,
                source_provenance,
                source_provenance_degraded,
                source_provenance_reason,
                poisoning_evidence,
                poisoning_evidence_degraded,
                poisoning_evidence_reason,
                interventions,
                interventions_degraded,
                interventions_reason,
                financial_link,
                financial_link_degraded,
                financial_link_reason,
                social_propagation,
                social_contagion,
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
                anomaly_events,
                anomaly_events_degraded,
                anomaly_events_reason,
                assessment_degraded,
                signals_degraded,
                source_provenance,
                source_provenance_degraded,
                source_provenance_reason,
                poisoning_evidence,
                poisoning_evidence_degraded,
                poisoning_evidence_reason,
                interventions,
                interventions_degraded,
                interventions_reason,
            ),
        ]
        claims = self._build_claims(
            request,
            assessment,
            signals,
            anomaly_events,
            source_provenance,
            poisoning_evidence,
            interventions,
            financial_link,
            agent_policy_flags,
            current_subject_read=_is_current_subject_read(request, context),
            support_case_evidence=support_case_evidence,
        )
        claims.extend(social_path_claims)
        claims.extend(social_contagion_claims)

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
    def _unknown_social_contagion(reason: str, *, state: str = "unknown") -> dict[str, Any]:
        return {
            "state": state,
            "reason": reason,
            "records": [],
            "evidence_refs": [],
            "coverage": "bounded_exact_tenant_subject_source_reported_evidence",
            "completeness": "unknown",
            "freshness": "unknown",
            "claimState": "unknown",
            "causalStatus": "unverified",
            "policyState": "unknown",
            "causalRiskPropagationEstablished": False,
        }

    @staticmethod
    def _financial_contagion_summary(
        financial_link: Optional[dict[str, Any]],
        *,
        degraded: bool,
        reason: Optional[str],
    ) -> dict[str, Any]:
        """Render a transfer/risk association without implying contagion or loss."""
        if degraded or financial_link is None:
            return {
                "state": "degraded" if degraded else "unknown",
                "reason": reason or (
                    "financial_flow_risk_read_incomplete"
                    if degraded
                    else "exact_financial_flow_path_subject_required"
                ),
                "records": [],
                "completeness": "unknown",
                "freshness": "unknown",
                "claimState": "unknown",
                "causalStatus": "unverified",
                "contagionAttribution": "not_established",
                "exposureAttribution": "not_established",
                "lossAttribution": "not_established",
                "causalRiskPropagationEstablished": False,
                "evidenceRefs": [],
            }
        evidence_refs = [
            ref.model_dump(mode="json")
            for ref in financial_link.get("evidence_refs", [])
            if isinstance(ref, EvidenceRef)
        ]
        return {
            "state": "partial",
            "reason": "financial_value_risk_link_observed_contagion_attribution_unavailable",
            "pathId": financial_link["path_id"],
            "traceId": financial_link["trace_id"],
            "transferCount": financial_link["transfer_count"],
            "riskContexts": financial_link["risk_contexts"],
            "exposureState": financial_link["exposure_state"],
            "completeness": "complete_within_declared_bounds",
            "freshness": "unknown",
            "claimState": EpistemicStatus.CORRELATED.value,
            "causalStatus": "unverified",
            "contagionAttribution": "not_established",
            "exposureAttribution": "not_established",
            "lossAttribution": "not_established",
            "causalRiskPropagationEstablished": False,
            "evidenceRefs": evidence_refs,
        }

    async def _safe_social_contagion_evidence(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[dict[str, Any], list[ClaimEnvelope]]:
        """Read source-reported correlated evidence without claiming causation."""
        if request.subject.kind != "entity" or not request.subject.id:
            return self._unknown_social_contagion("exact_entity_subject_required"), []
        if context.tenantId != request.tenantId:
            return self._unknown_social_contagion(
                "social_contagion_runtime_tenant_context_mismatch", state="degraded"
            ), []

        request_anchor = _aware_datetime(request.asOf) if request.asOf is not None else None
        context_anchor = _aware_datetime(context.asOf) if context.asOf is not None else None
        if request.asOf is not None and request_anchor is None:
            return self._unknown_social_contagion(
                "social_contagion_as_of_anchor_invalid", state="degraded"
            ), []
        if context.asOf is not None and context_anchor is None:
            return self._unknown_social_contagion(
                "social_contagion_context_anchor_invalid", state="degraded"
            ), []
        if (
            request_anchor is not None
            and context_anchor is not None
            and request_anchor != context_anchor
        ):
            return self._unknown_social_contagion(
                "social_contagion_as_of_anchor_mismatch", state="degraded"
            ), []
        anchor = request_anchor or context_anchor or datetime.now(timezone.utc)
        if request.temporalMode == "as_of" and request_anchor is None and context_anchor is None:
            return self._unknown_social_contagion(
                "social_contagion_as_of_anchor_missing", state="degraded"
            ), []

        start = end = None
        if request.timeRange is not None:
            raw_start = getattr(request.timeRange, "from_", None)
            raw_end = getattr(request.timeRange, "to", None)
            start = _aware_datetime(raw_start) if raw_start is not None else None
            end = _aware_datetime(raw_end) if raw_end is not None else None
            if (raw_start is not None and start is None) or (raw_end is not None and end is None):
                return self._unknown_social_contagion(
                    "social_contagion_time_range_invalid", state="degraded"
                ), []
            if start is not None and end is not None and end <= start:
                return self._unknown_social_contagion(
                    "social_contagion_time_range_invalid", state="degraded"
                ), []

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

        # The subject's current consent gates access before the evidence read.
        try:
            subject_allowed, subject_consent_reason = await consent_for(request.subject.id)
        except Exception:  # noqa: BLE001 - consent policy fails closed
            return self._unknown_social_contagion(
                "social_contagion_consent_authority_unavailable", state="degraded"
            ), []
        if not subject_allowed:
            if subject_consent_reason == "consent_authority_unavailable":
                return self._unknown_social_contagion(
                    "social_contagion_consent_authority_unavailable", state="degraded"
                ), []
            return self._unknown_social_contagion(
                "social_contagion_subject_consent_restricted"
            ), []

        try:
            from services.social360.evidence_authority import (
                MAX_SOCIAL_EVIDENCE_READ,
                SocialEvidenceAuthority,
                SocialEvidenceRead,
            )

            authority = self._social_evidence_authority
            if authority is None:
                authority = SocialEvidenceAuthority()
                self._social_evidence_authority = authority
            read = await authority.read_social_contagion_evidence(
                request.tenantId,
                request.subject.id,
                start=start,
                end=end,
                as_of=anchor,
                limit=min(_MAX_RISK_SOCIAL_CONTAGION_SCAN, MAX_SOCIAL_EVIDENCE_READ),
            )
        except Exception:  # noqa: BLE001 - evidence authority fails closed
            return self._unknown_social_contagion(
                "social_contagion_evidence_authority_unavailable", state="degraded"
            ), []
        if not isinstance(read, SocialEvidenceRead) or not isinstance(read.records, tuple):
            return self._unknown_social_contagion(
                "social_contagion_evidence_source_contract_invalid", state="degraded"
            ), []
        if read.tenant_id != request.tenantId or read.subject_entity_id != request.subject.id:
            return self._unknown_social_contagion(
                "social_contagion_evidence_scope_mismatch", state="degraded"
            ), []
        if not read.available:
            reason = read.reason
            if not isinstance(reason, str) or not reason.isidentifier() or len(reason) > 128:
                reason = "social_contagion_evidence_authority_unavailable"
            return self._unknown_social_contagion(
                reason,
                state="degraded",
            ), []
        if read.truncated or len(read.records) > min(
            _MAX_RISK_SOCIAL_CONTAGION_SCAN, MAX_SOCIAL_EVIDENCE_READ
        ):
            reason = read.reason
            if not isinstance(reason, str) or not reason.isidentifier() or len(reason) > 128:
                reason = "social_contagion_evidence_read_truncated"
            return self._unknown_social_contagion(
                reason,
                state="degraded",
            ), []
        if not read.records:
            return self._unknown_social_contagion(
                "social_contagion_evidence_not_observed"
            ), []

        validated_records: list[dict[str, Any]] = []
        all_evidence: list[EvidenceRef] = []
        seen_records: set[str] = set()
        required_graph_nodes: set[str] = set()
        for raw in read.records:
            if not isinstance(raw, dict):
                return self._unknown_social_contagion(
                    "social_contagion_record_invalid", state="degraded"
                ), []
            path = raw.get("path_entity_ids")
            source_entity_id = raw.get("source_entity_id")
            target_entity_id = raw.get("target_entity_id")
            signal_ids = raw.get("risk_signal_ids")
            record_id = raw.get("record_id")
            observed_at = _aware_datetime(raw.get("observed_at"))
            effective_at = _aware_datetime(raw.get("effective_at"))
            recorded_at = _aware_datetime(raw.get("recorded_at"))
            if (
                raw.get("tenant_id") != request.tenantId
                or raw.get("subject_entity_id") != request.subject.id
                or raw.get("assertion_kind") != "social_contagion"
                or raw.get("assertion_state") != "source_reported"
                or raw.get("claim_state") != EpistemicStatus.CORRELATED.value
                or raw.get("causal_status") != "unverified"
                or raw.get("policy_state") != "unknown"
                or not isinstance(record_id, str)
                or not record_id.strip()
                or record_id in seen_records
                or not isinstance(source_entity_id, str)
                or not isinstance(target_entity_id, str)
                or target_entity_id != request.subject.id
                or not isinstance(path, list)
                or not 3 <= len(path) <= 4
                or any(not isinstance(entity_id, str) or not entity_id.strip() for entity_id in path)
                or len(set(path)) != len(path)
                or path[0] != source_entity_id
                or path[-1] != target_entity_id
                or not isinstance(signal_ids, list)
                or not signal_ids
                or len(signal_ids) > MAX_SOCIAL_EVIDENCE_READ
                or any(not isinstance(signal_id, str) or not signal_id.strip() for signal_id in signal_ids)
                or len(set(signal_ids)) != len(signal_ids)
                or observed_at is None
                or effective_at is None
                or recorded_at is None
                or observed_at > anchor
                or effective_at > anchor
                or recorded_at > anchor
                or (start is not None and observed_at < start)
                or (end is not None and observed_at >= end)
                or not isinstance(raw.get("actor_id"), str)
                or not raw["actor_id"].strip()
                or not isinstance(raw.get("actor_type"), str)
                or not raw["actor_type"].strip()
                or not isinstance(raw.get("source_id"), str)
                or not raw["source_id"].strip()
                or not isinstance(raw.get("source_observation_id"), str)
                or not raw["source_observation_id"].strip()
                or not isinstance(raw.get("source_revision_id"), str)
                or not raw["source_revision_id"].strip()
                or not isinstance(raw.get("source_event_id"), str)
                or not raw["source_event_id"].strip()
                or not isinstance(raw.get("source_revision_status"), str)
                or raw["source_revision_status"] not in {
                    "canonical_source_revision_bound",
                    "source_reported_revision_unverified",
                }
                or not isinstance(raw.get("source_trust_classification"), str)
                or not raw["source_trust_classification"].strip()
            ):
                return self._unknown_social_contagion(
                    "social_contagion_record_scope_or_semantics_invalid", state="degraded"
                ), []

            raw_source_refs = raw.get("source_evidence_refs", [])
            raw_path_refs = raw.get("path_evidence_refs", [])
            raw_risk_refs = raw.get("risk_evidence_refs", [])
            if (
                not isinstance(raw_source_refs, list)
                or not isinstance(raw_path_refs, list)
                or not isinstance(raw_risk_refs, list)
                or len(raw_source_refs) != 1
                or len(raw_path_refs) > _MAX_RISK_SOCIAL_CONTAGION_EVIDENCE_REFS
                or len(raw_risk_refs) > _MAX_RISK_SOCIAL_CONTAGION_EVIDENCE_REFS
            ):
                return self._unknown_social_contagion(
                    "social_contagion_evidence_join_invalid", state="degraded"
                ), []
            try:
                source_refs = [EvidenceRef.model_validate(ref) for ref in raw_source_refs]
                path_refs = [EvidenceRef.model_validate(ref) for ref in raw_path_refs]
                risk_refs = [EvidenceRef.model_validate(ref) for ref in raw_risk_refs]
            except Exception:  # noqa: BLE001 - malformed provenance fails closed
                return self._unknown_social_contagion(
                    "social_contagion_evidence_reference_invalid", state="degraded"
                ), []
            path_hop_count = len(path) - 1
            graph_path_refs = [ref for ref in path_refs if ref.source == "entity_graph"]
            relationship_fact_refs = [
                ref for ref in path_refs if ref.source == "relationship_facts"
            ]
            if (
                len(source_refs) != 1
                or any(
                    ref.source != "bronze_sdk_events"
                    or ref.id != raw.get("source_event_id")
                    or ref.type != "event"
                    for ref in source_refs
                )
                or len(path_refs) > _MAX_RISK_SOCIAL_CONTAGION_EVIDENCE_REFS
                or any(
                    (ref.source == "entity_graph" and ref.type != "relationship")
                    or (ref.source == "relationship_facts" and ref.type != "event")
                    or ref.source not in {"entity_graph", "relationship_facts"}
                    for ref in path_refs
                )
                or len(graph_path_refs) < path_hop_count
                or len(relationship_fact_refs) < path_hop_count
                or len({ref.id for ref in graph_path_refs}) != len(graph_path_refs)
                or not risk_refs
                or len(risk_refs) > _MAX_RISK_SOCIAL_CONTAGION_EVIDENCE_REFS
                or not all(
                    any(
                        ref.type == "model_output"
                        and ref.source.startswith("risk_signals:")
                        and ref.id == signal_id
                        for ref in risk_refs
                    )
                    for signal_id in signal_ids
                )
            ):
                return self._unknown_social_contagion(
                    "social_contagion_evidence_join_invalid", state="degraded"
                ), []

            seen_records.add(record_id)
            required_graph_nodes.update(path)
            refs = _dedupe_evidence([*source_refs, *path_refs, *risk_refs])
            validated_records.append(
                {
                    "recordId": record_id,
                    "sourceId": raw["source_id"],
                    "sourceObservationId": raw["source_observation_id"],
                    "sourceRevisionId": raw["source_revision_id"],
                    "sourceRevisionStatus": raw["source_revision_status"],
                    "sourceEventId": raw["source_event_id"],
                    "sourceEntityId": source_entity_id,
                    "targetEntityId": target_entity_id,
                    "pathEntityIds": list(path),
                    "riskSignalIds": list(signal_ids),
                    "sourceTrustClassification": raw["source_trust_classification"],
                    "actorId": raw["actor_id"],
                    "actorType": raw["actor_type"],
                    "observedAt": observed_at.isoformat(),
                    "effectiveAt": effective_at.isoformat(),
                    "recordedAt": recorded_at.isoformat(),
                    "claimState": EpistemicStatus.CORRELATED.value,
                    "causalStatus": "unverified",
                    "policyState": "unknown",
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
                }
            )
            all_evidence.extend(refs)

        # Consent is rechecked for every entity named in the source assertion.
        # The stored policy_state is still unknown; an allowed read is not a
        # retrospective policy decision or causal finding.
        for entity_id in sorted(required_graph_nodes):
            try:
                allowed, reason = await consent_for(entity_id)
            except Exception:  # noqa: BLE001 - consent failure suppresses evidence
                return self._unknown_social_contagion(
                    "social_contagion_consent_authority_unavailable", state="degraded"
                ), []
            if not allowed:
                if reason == "consent_authority_unavailable":
                    return self._unknown_social_contagion(
                        "social_contagion_consent_authority_unavailable", state="degraded"
                    ), []
                return self._unknown_social_contagion(
                    "social_contagion_path_consent_restricted"
                ), []

        claims: list[ClaimEnvelope] = []
        for record in validated_records:
            refs = [EvidenceRef.model_validate(ref) for ref in record["evidenceRefs"]]
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.social-contagion.{record['recordId']}",
                    kind="risk_social_contagion_source_assertion",
                    subject=request.subject,
                    evidenceRefs=refs,
                    claims=[
                        "A source-reported risk assertion is linked to the recorded entity path. "
                        "This is correlated source evidence only; causality and policy outcome remain unverified."
                    ],
                    claimState=EpistemicStatus.CORRELATED,
                    domainSlotIds=["social_contagion", "evidence_trace"],
                )
            )
        return (
            {
                "state": "partial",
                "reason": "source_reported_correlated_evidence_causality_unverified_policy_unknown",
                "records": validated_records,
                "evidence_refs": _dedupe_evidence(all_evidence),
                "coverage": "bounded_exact_tenant_subject_source_reported_evidence",
                "completeness": "unknown",
                "freshness": "unknown",
                "claimState": EpistemicStatus.CORRELATED.value,
                "causalStatus": "unverified",
                "policyState": "unknown",
                "causalRiskPropagationEstablished": False,
            },
            claims,
        )

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

    def _financial_risk_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        assessment_degraded: bool,
        *,
        current_subject_read: bool,
    ) -> ProjectionSection:
        """Expose only assessed, evidence-backed financial risk dimensions.

        This section is the narrow Risk360 source bound into Value360. It avoids
        copying general findings/evidence that can contain poisoning, social,
        policy, or unrelated risk data. Current RiskAssessment reads do not
        provide bitemporal replay, so anchored or ranged requests expose no facts.
        """
        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "dimensions": [],
            "evidenceRefs": [],
        }
        state: str = "available"
        warnings: list[str] = []

        if not current_subject_read:
            state = "unknown"
            warnings.append("financial risk assessment history is not bitemporal")
        elif assessment_degraded:
            state = "degraded"
            warnings.append("risk assessment source unavailable; financial risk is degraded")
        elif assessment is None:
            state = "missing"
            warnings.append("no risk assessment exists for the exact subject")
        else:
            financial_components = [
                component
                for component in assessment.vector.components
                if component.dimension in _FINANCIAL_RISK_DIMENSIONS
                and requires_value(component.state)
                and component.evidence_refs
            ]
            if not financial_components:
                state = "empty"
                warnings.append(
                    "no evidence-backed economic, payment, or transaction dimension is assessed"
                )
            else:
                evidence_refs = _dedupe_evidence(
                    [
                        ref
                        for component in financial_components
                        for ref in component.evidence_refs
                    ]
                )
                content["assessment"] = {
                    "assessmentId": assessment.assessment_id,
                    "policy": (
                        {"id": assessment.policy_id, "version": assessment.policy_version}
                        if assessment.policy_id is not None
                        else None
                    ),
                    "assessedAt": (
                        assessment.assessed_at.isoformat()
                        if assessment.assessed_at is not None
                        else None
                    ),
                    "runId": assessment.run_id,
                    "claimState": assessment.claim_state.value,
                    "confidence": assessment.confidence,
                }
                content["dimensions"] = [
                    {
                        "dimension": component.dimension,
                        "state": component.state.value,
                        "score": component.score,
                        "claimState": component.claim_state.value,
                        "confidence": component.confidence,
                        "evidenceRefs": [
                            ref.model_dump(mode="json") for ref in component.evidence_refs
                        ],
                    }
                    for component in financial_components
                ]
                content["evidenceRefs"] = [
                    ref.model_dump(mode="json") for ref in evidence_refs
                ]

        return ProjectionSection(
            id="financial_risk",
            state=state,  # type: ignore[arg-type]
            title="Financial risk",
            content=content,
            warnings=warnings or None,
            canonicalAuthorityRefs=["risk_outputs"],
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
        anomaly_events: list[dict[str, Any]],
        anomaly_events_degraded: bool,
        anomaly_events_reason: Optional[str],
        evidence: list[EvidenceRef],
        source_provenance: list[dict[str, Any]],
        source_provenance_degraded: bool,
        source_provenance_reason: Optional[str],
        poisoning_evidence: list[RiskPoisoningEvidence],
        poisoning_evidence_degraded: bool,
        poisoning_evidence_reason: Optional[str],
        interventions: list[RiskInterventionRecord],
        interventions_degraded: bool,
        interventions_reason: Optional[str],
        financial_link: Optional[dict[str, Any]],
        financial_link_degraded: bool,
        financial_link_reason: Optional[str],
        social_propagation: dict[str, Any],
        social_contagion: dict[str, Any],
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
                "anomalyEvents": self._anomaly_event_summary(
                    anomaly_events,
                    degraded=anomaly_events_degraded,
                    reason=anomaly_events_reason,
                ),
                "poisoningEvidence": self._poisoning_evidence_summary(
                    poisoning_evidence,
                    degraded=poisoning_evidence_degraded,
                    reason=poisoning_evidence_reason,
                ),
                "interventions": self._intervention_summary(
                    interventions,
                    degraded=interventions_degraded,
                    reason=interventions_reason,
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
                "financialContagion": self._financial_contagion_summary(
                    financial_link,
                    degraded=financial_link_degraded,
                    reason=financial_link_reason,
                ),
                "socialContagion": {
                    key: value
                    for key, value in social_contagion.items()
                    if key != "evidence_refs"
                },
                "auditHistory": self._assessment_history_summary(
                    assessment_history,
                    degraded=assessment_history_degraded,
                    reason=assessment_history_reason,
                    interventions=self._intervention_summary(
                        interventions,
                        degraded=interventions_degraded,
                        reason=interventions_reason,
                    ),
                ),
                "requiredSlotCoverage": self._required_slot_coverage(
                    request,
                    assessment,
                    signals,
                    anomaly_events,
                    anomaly_events_degraded,
                    anomaly_events_reason,
                    evidence,
                    source_provenance,
                    source_provenance_degraded,
                    source_provenance_reason,
                    assessment_degraded,
                    poisoning_evidence,
                    poisoning_evidence_degraded,
                    poisoning_evidence_reason,
                    interventions,
                    interventions_degraded,
                    interventions_reason,
                    financial_link,
                    financial_link_degraded,
                    financial_link_reason,
                    social_propagation,
                    social_contagion,
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
                "gold_identity.anomaly_alert",
                "graph",
                "relationship_facts",
                "risk_assessments",
                "risk_intervention_records",
                "social_relationship_evidence_events",
                "bronze_sdk_events",
                "entity_graph",
                "risk_signals",
                "flow_trace_paths",
                "flow_traces",
                "transfers",
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
    def _anomaly_event_summary(
        events: list[dict[str, Any]],
        *,
        degraded: bool,
        reason: Optional[str],
    ) -> dict[str, Any]:
        """Expose exact Gold alerts and independently bound event evidence refs."""
        state = "degraded" if degraded else "partial" if events else "unknown"
        verified_records = sum(
            event.get("sourceEventJoin", {}).get("sourceEventRecordRead")
            == "verified_exact_bronze_record"
            for event in events
        )
        verified_links = sum(
            event.get("sourceEventJoin", {}).get("state")
            == "verified_signal_evidence_reference"
            for event in events
        )
        if verified_records:
            default_reason = (
                "gold_anomaly_alerts_with_exact_bronze_event_records_"
                "detector_coverage_and_cause_not_attested"
            )
        elif verified_links:
            default_reason = (
                "gold_anomaly_alerts_with_exact_risk_signal_event_evidence_"
                "references_detector_coverage_and_cause_not_attested"
            )
        elif events:
            default_reason = (
                "gold_anomaly_alerts_only_underlying_event_and_detector_coverage_not_attested"
            )
        else:
            default_reason = "canonical_anomaly_detector_coverage_not_attested"
        latest_recorded_at = max(
            (event["recordedAt"] for event in events if event.get("recordedAt")),
            default=None,
        )
        return {
            "state": state,
            "reason": reason or default_reason,
            "records": [
                {
                    key: value
                    for key, value in event.items()
                    if key not in {
                        "evidence_ref",
                        "source_event_ref",
                        "source_event_record_ref",
                    }
                }
                | {
                    "evidenceRef": event["evidence_ref"].model_dump(mode="json")
                }
                for event in events
            ],
            "coverage": {
                "completeAlertRecordScan": not degraded and reason is None,
                "detectorCoverage": "unattested",
                "underlyingEventLineage": (
                    "bounded_exact_bronze_event_record"
                    if verified_records
                    else
                    "bounded_exact_risk_signal_event_evidence_reference"
                    if verified_links
                    else "not_attested"
                ),
                "verifiedSourceEventEvidenceLinkCount": verified_links,
                "verifiedSourceEventRecordCount": verified_records,
                "sourceEventRecordVerification": (
                    "bounded_exact_bronze_record" if verified_records else "not_attested"
                ),
                "negativeFindingInference": "prohibited",
                "rawAlertPayload": "excluded",
            },
            "freshness": {
                "state": "degraded" if degraded else "known" if latest_recorded_at else "unknown",
                "recordCount": len(events),
                "timestampedRecordCount": sum(bool(event.get("recordedAt")) for event in events),
                "latestMaterializedAt": latest_recorded_at,
                "threshold": "unconfigured",
            },
        }

    @staticmethod
    def _intervention_summary(
        records: list[RiskInterventionRecord],
        *,
        degraded: bool,
        reason: Optional[str],
    ) -> dict[str, Any]:
        """Render immutable intervention reports without upgrading their claims."""
        if degraded:
            state = "degraded"
        elif records:
            state = "partial"
        else:
            state = "unknown"
        safe_records = [
            {
                "recordId": record.record_id,
                "interventionId": record.intervention_id,
                "recordKind": record.record_kind,
                "type": record.intervention_type,
                "label": record.label,
                "requiresConfirmation": record.requires_confirmation,
                "reversible": record.reversible,
                "decisionState": record.decision_state,
                "reportedOutcome": record.reported_outcome,
                "decisionRecordId": record.decision_record_id,
                "subject": {"kind": record.subject_kind, "id": record.subject_id},
                "actor": {
                    "kind": record.actor_kind,
                    "id": record.actor_id,
                    "attributionState": "source_reported_unverified",
                    "evidenceRefs": [
                        ref.model_dump(mode="json") for ref in record.actor_evidence_refs
                    ],
                },
                "policyDecisionId": record.policy_decision_id,
                "policyEvaluation": "reference_only_not_replayed",
                "claimState": record.claim_state.value,
                "observedAt": record.observed_at.isoformat(),
                "effectiveAt": record.effective_at.isoformat(),
                "recordedAt": record.recorded_at.isoformat(),
                "sourceSystem": record.source_system,
                "sourceRecordId": record.source_record_id,
                "evidenceRefs": [ref.model_dump(mode="json") for ref in record.evidence_refs],
                "semantics": (
                    "decision_record_only_not_proof_of_actor_authority_or_execution"
                    if record.record_kind == "decision"
                    else "source_reported_outcome_not_independently_verified"
                ),
            }
            for record in records
        ]
        return {
            "state": state,
            "reason": reason
            or (
                "risk_intervention_actor_authority_and_outcome_coverage_not_attested"
                if records
                else "risk_intervention_producer_coverage_not_attested"
            ),
            "records": safe_records,
            "semantics": {
                "decisionProvesExecution": False,
                "reportedOutcomeProvesExternalEffect": False,
                "risk360ExecutesInterventions": False,
                "actorAuthorityEvaluation": "not_performed_by_risk360",
                "producerCoverage": "unattested",
            },
            "coverage": {
                "completeRecordScan": not degraded and reason is None,
                "producerCoverage": "unattested",
                "actorIdentity": "source_reported_unverified",
                "actorAuthority": "not_evaluated",
                "applicationOutcomeVerification": "not_available",
            },
            "freshness": {
                "state": "degraded" if degraded else "known" if records else "unknown",
                "recordCount": len(records),
                "timestampedRecordCount": sum(
                    record.recorded_at is not None for record in records
                ),
                "latestObservedAt": max(
                    (record.observed_at.isoformat() for record in records), default=None
                ),
                "latestEffectiveAt": max(
                    (record.effective_at.isoformat() for record in records), default=None
                ),
                "latestRecordedAt": max(
                    (record.recorded_at.isoformat() for record in records), default=None
                ),
                "threshold": "unconfigured",
            },
        }

    @staticmethod
    def _required_slot_coverage(
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
        anomaly_events: list[dict[str, Any]],
        anomaly_events_degraded: bool,
        anomaly_events_reason: Optional[str],
        evidence: list[EvidenceRef],
        source_provenance: list[dict[str, Any]],
        source_provenance_degraded: bool,
        source_provenance_reason: Optional[str],
        assessment_degraded: bool,
        poisoning_evidence: list[RiskPoisoningEvidence],
        poisoning_evidence_degraded: bool,
        poisoning_evidence_reason: Optional[str],
        interventions: list[RiskInterventionRecord],
        interventions_degraded: bool,
        interventions_reason: Optional[str],
        financial_link: Optional[dict[str, Any]],
        financial_link_degraded: bool,
        financial_link_reason: Optional[str],
        social_propagation: dict[str, Any],
        social_contagion: dict[str, Any],
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

        if anomaly_events_degraded:
            anomaly_coverage = {
                "state": "degraded",
                "reason": anomaly_events_reason or "gold_anomaly_alert_read_incomplete",
            }
        elif anomaly_events:
            anomaly_record_links = any(
                event.get("sourceEventJoin", {}).get("sourceEventRecordRead")
                == "verified_exact_bronze_record"
                for event in anomaly_events
            )
            anomaly_source_links = any(
                event.get("sourceEventJoin", {}).get("state")
                == "verified_signal_evidence_reference"
                for event in anomaly_events
            )
            anomaly_coverage = {
                "state": "partial",
                "reason": (
                    "gold_anomaly_alerts_with_exact_bronze_event_records_"
                    "detector_coverage_and_cause_not_attested"
                    if anomaly_record_links
                    else
                    "gold_anomaly_alerts_with_exact_risk_signal_event_evidence_"
                    "references_detector_coverage_and_cause_not_attested"
                    if anomaly_source_links
                    else "gold_anomaly_alerts_only_underlying_event_and_detector_coverage_not_attested"
                ),
            }
        else:
            anomaly_coverage = {
                "state": "unknown",
                "reason": anomaly_events_reason
                or "canonical_anomaly_detector_coverage_not_attested",
            }

        intervention_coverage = (
            {
                "state": "degraded",
                "reason": interventions_reason or "risk_intervention_read_incomplete",
            }
            if interventions_degraded
            else {
                "state": "partial",
                "reason": "risk_intervention_records_available_actor_authority_and_outcome_verification_not_attested",
            }
            if interventions
            else {
                "state": "unknown",
                "reason": interventions_reason or "risk_intervention_producer_coverage_not_attested",
            }
        )

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
            "anomaly_events": anomaly_coverage,
            "poisoning_evidence": poisoning_coverage,
            "interventions": intervention_coverage,
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
        supported["financial_contagion"] = {
            "state": "unknown",
            "reason": "financial_contagion_attribution_authority_unavailable",
        }
        contagion_state = social_contagion.get("state")
        if contagion_state == "degraded":
            supported["social_contagion"] = {
                "state": "degraded",
                "reason": social_contagion.get("reason")
                or "social_contagion_evidence_read_incomplete",
            }
        elif social_contagion.get("records"):
            supported["social_contagion"] = {
                "state": "partial",
                "reason": "source_reported_correlated_evidence_causality_unverified_policy_unknown",
            }
        else:
            supported["social_contagion"] = {
                "state": "unknown",
                "reason": social_contagion.get("reason")
                or "social_contagion_evidence_not_observed",
            }
        supported["policy_flags"] = policy_flags_coverage
        has_verified_restatement_links = any(
            isinstance(row.get("restatement_link"), dict)
            and row["restatement_link"].get("state") == "verified_direct_predecessor"
            for row in assessment_history
        )
        if assessment_history_degraded or interventions_degraded:
            supported["audit_history"] = {
                "state": "degraded",
                "reason": assessment_history_reason
                or interventions_reason
                or "risk_intervention_audit_read_incomplete",
            }
        elif assessment_history or interventions:
            supported["audit_history"] = {
                "state": "partial",
                "reason": (
                    "assessment_run_history_and_verified_direct_restatement_links_available_full_lineage_actor_authority_and_producer_coverage_unknown"
                    if has_verified_restatement_links
                    else "assessment_run_history_available_restatement_links_not_observed_actor_authority_and_producer_coverage_unknown"
                    if assessment_history
                    else "intervention_records_available_assessment_run_history_unavailable"
                ),
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
        anomaly_events: list[dict[str, Any]],
        anomaly_events_degraded: bool,
        anomaly_events_reason: Optional[str],
        assessment_degraded: bool,
        signals_degraded: bool,
        source_provenance: list[dict[str, Any]],
        source_provenance_degraded: bool,
        source_provenance_reason: Optional[str],
        poisoning_evidence: list[RiskPoisoningEvidence],
        poisoning_evidence_degraded: bool,
        poisoning_evidence_reason: Optional[str],
        interventions: list[RiskInterventionRecord],
        interventions_degraded: bool,
        interventions_reason: Optional[str],
    ) -> ProjectionSection:
        """health — detector/source freshness for the signals feeding the read.

        Backed by the tenant's RiskSignal rows: each contributing source's count,
        detector versions and newest observation. No signals yet -> honest
        ``missing`` (no contributing source to assess); an unreadable signal
        source degrades the section content-free.
        """
        state: str = "available"
        warnings: list[str] = []
        if (
            signals_degraded
            or anomaly_events_degraded
            or poisoning_evidence_degraded
            or interventions_degraded
        ):
            state = "degraded"
            if signals_degraded:
                warnings.append("risk signal source unavailable; health is degraded")
            if anomaly_events_degraded:
                warnings.append("Gold anomaly alert source unavailable or incomplete")
            if poisoning_evidence_degraded:
                warnings.append("poisoning evidence source unavailable or incomplete")
            if interventions_degraded:
                warnings.append("risk intervention source unavailable or incomplete")
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
            "anomalyAlertFreshness": self._anomaly_event_summary(
                anomaly_events,
                degraded=anomaly_events_degraded,
                reason=anomaly_events_reason,
            )["freshness"],
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
            "interventionFreshness": self._intervention_summary(
                interventions,
                degraded=interventions_degraded,
                reason=interventions_reason,
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
                "interventions": self._intervention_summary(
                    interventions,
                    degraded=interventions_degraded,
                    reason=interventions_reason,
                )["freshness"],
                "anomalyAlerts": self._anomaly_event_summary(
                    anomaly_events,
                    degraded=anomaly_events_degraded,
                    reason=anomaly_events_reason,
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
        anomaly_events: list[dict[str, Any]],
        source_provenance: list[dict[str, Any]],
        poisoning_evidence: list[RiskPoisoningEvidence],
        interventions: list[RiskInterventionRecord],
        financial_link: Optional[dict[str, Any]],
        agent_policy_flags: list[dict[str, Any]],
        *,
        current_subject_read: bool,
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
                        domainSlotIds=_risk_evidence_slot_ids(
                            subject.kind,
                            risk_dimension=component.dimension,
                            current_subject_read=current_subject_read,
                        ),
                    )
                )

        for event in anomaly_events:
            evidence_ref = event.get("evidence_ref")
            if not isinstance(evidence_ref, EvidenceRef):
                continue
            source_event_ref = event.get("source_event_ref")
            source_event_record_ref = event.get("source_event_record_ref")
            linked = isinstance(source_event_ref, EvidenceRef)
            record_linked = isinstance(source_event_record_ref, EvidenceRef)
            anomaly_evidence = [evidence_ref]
            if linked:
                anomaly_evidence.append(source_event_ref)
            if record_linked:
                anomaly_evidence.append(source_event_record_ref)
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.anomaly-alert.{event['alertRecordId']}",
                    kind="risk_anomaly_alert_recorded",
                    subject=subject,
                    evidenceRefs=anomaly_evidence,
                    claims=[
                        "The tenant-scoped Gold identity authority contains an anomaly_alert "
                        "materialization for this exact typed subject, with a matching "
                        "RiskSignal event reference and an exact Bronze SDK event record. "
                        "Cause, severity, and detector coverage are not verified here."
                        if record_linked
                        else
                        "The tenant-scoped Gold identity authority contains an anomaly_alert "
                        "materialization for this exact typed subject, with a matching "
                        "RiskSignal event evidence reference. Source event contents, cause, "
                        "severity, and detector coverage are not verified here."
                        if linked
                        else "The tenant-scoped Gold identity authority contains an anomaly_alert "
                        "materialization for this exact typed subject; the underlying event, "
                        "cause, severity, and detector coverage are not attested here."
                    ],
                    confidence=None,
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["anomaly_events", "evidence_trace"],
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

        for record in interventions:
            if record.record_kind == "decision":
                claim = (
                    f"Risk intervention {record.intervention_id!r} has a recorded decision "
                    f"state {record.decision_state!r} for {record.intervention_type!r}; "
                    "the record does not establish actor authority or execution."
                )
                claim_kind = "risk_intervention_decision_recorded"
            else:
                claim = (
                    f"Source {record.source_system!r} reports outcome "
                    f"{record.reported_outcome!r} for intervention "
                    f"{record.intervention_id!r}; the reported outcome is not independently "
                    "verified as an external effect."
                )
                claim_kind = "risk_intervention_outcome_reported"
            claims.append(
                ClaimEnvelope(
                    id=f"risk360.intervention.{record.record_id}",
                    kind=claim_kind,
                    subject=subject,
                    evidenceRefs=_dedupe_evidence(
                        [*record.evidence_refs, *record.actor_evidence_refs]
                    ),
                    claims=[claim],
                    confidence=None,
                    claimState=record.claim_state,
                    domainSlotIds=["interventions", "audit_history", "evidence_trace"],
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
                    claimState=EpistemicStatus.CORRELATED,
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

        subject_reader = getattr(self._sources, "financial_flow_path_subjects", None)
        details_reader = getattr(self._sources, "financial_flow_path_details", None)
        if not callable(subject_reader) or not callable(details_reader):
            return None, False, "financial_flow_path_authority_not_connected"
        try:
            raw_subjects = await subject_reader(
                tenant_id=request.tenantId,
                path_id=request.subject.id,
            )
        except Exception:  # noqa: BLE001 - exact-source failures stay content-free
            return None, True, "financial_flow_path_subject_read_incomplete"
        if raw_subjects is None:
            return None, False, "financial_flow_path_record_unavailable"
        if (
            not isinstance(raw_subjects, dict)
            or raw_subjects.get("tenant_id") != request.tenantId
            or raw_subjects.get("path_id") != request.subject.id
        ):
            return None, True, "financial_flow_path_subject_scope_incomplete"
        linkage_reason = raw_subjects.get("linkage_reason")
        if isinstance(linkage_reason, str) and linkage_reason:
            return None, False, linkage_reason

        path_nodes = raw_subjects.get("path_nodes")
        hop_count = raw_subjects.get("hop_count")
        trace_id = raw_subjects.get("trace_id")
        path_discovered_at = _aware_datetime(raw_subjects.get("path_discovered_at"))
        if (
            not isinstance(path_nodes, list)
            or not 2 <= len(path_nodes) <= _MAX_FINANCIAL_PATH_NODES
            or any(not isinstance(node, str) or not node.strip() for node in path_nodes)
            or isinstance(hop_count, bool)
            or not isinstance(hop_count, int)
            or hop_count != len(path_nodes) - 1
            or len(set(path_nodes)) < 2
            or not isinstance(trace_id, str)
            or not trace_id.strip()
            or path_discovered_at is None
        ):
            return None, True, "financial_flow_path_subject_sequence_incomplete"

        consent_reader = self._consent_reader
        if consent_reader is None:
            try:
                from governance.consent.authority import evaluate_consent
            except Exception:  # noqa: BLE001 - absent consent authority is fail closed
                return None, True, "financial_contagion_consent_authority_unavailable"

            consent_reader = evaluate_consent
            self._consent_reader = consent_reader
        if not callable(consent_reader):
            return None, True, "financial_contagion_consent_authority_unavailable"
        for entity_id in dict.fromkeys(path_nodes):
            try:
                consent = await consent_reader(
                    request.tenantId,
                    entity_id,
                    None,
                    "analytics",
                )
            except Exception:  # noqa: BLE001 - financial consent is fail closed
                return None, True, "financial_contagion_consent_authority_unavailable"
            if (
                isinstance(consent, tuple)
                and len(consent) == 2
                and type(consent[0]) is bool
                and (consent[1] is None or isinstance(consent[1], str))
            ):
                allowed, consent_reason = consent
            elif (
                hasattr(consent, "allowed")
                and hasattr(consent, "reason_code")
                and type(getattr(consent, "allowed")) is bool
                and (
                    getattr(consent, "reason_code") is None
                    or isinstance(getattr(consent, "reason_code"), str)
                )
            ):
                allowed = getattr(consent, "allowed")
                consent_reason = getattr(consent, "reason_code")
            else:
                return None, False, "financial_contagion_consent_result_ambiguous"
            if allowed and consent_reason is not None:
                return None, False, "financial_contagion_consent_result_ambiguous"
            if not allowed:
                if consent_reason == "consent_authority_unavailable":
                    return None, True, "financial_contagion_consent_authority_unavailable"
                if consent_reason in {None, "consent_receipt_missing", "consent_unknown"}:
                    return None, False, "financial_contagion_consent_not_affirmed"
                return None, False, "financial_contagion_consent_restricted"

        # No transfer, trace, or per-entity risk detail is read until every
        # exact path entity has returned an affirmative analytics decision.
        try:
            raw_path = await details_reader(
                tenant_id=request.tenantId,
                path_id=request.subject.id,
                trace_id=trace_id,
                path_nodes=list(path_nodes),
                path_discovered_at=path_discovered_at,
            )
        except Exception:  # noqa: BLE001 - detail authority fails closed
            return None, True, "financial_flow_path_detail_read_incomplete"
        if raw_path is None:
            return None, False, "financial_flow_path_detail_unavailable"
        if (
            not isinstance(raw_path, dict)
            or raw_path.get("tenant_id") != request.tenantId
            or raw_path.get("path_id") != request.subject.id
            or raw_path.get("trace_id") != trace_id
            or raw_path.get("path_nodes") != path_nodes
            or raw_path.get("hop_count") != hop_count
            or _aware_datetime(raw_path.get("path_discovered_at")) != path_discovered_at
        ):
            return None, True, "financial_flow_path_detail_binding_changed"
        linkage_reason = raw_path.get("linkage_reason")
        if isinstance(linkage_reason, str) and linkage_reason:
            return None, False, linkage_reason
        transfer_edges = raw_path.get("transfer_edges")
        trace_completed_at = _aware_datetime(raw_path.get("trace_completed_at"))
        if (
            not isinstance(transfer_edges, list)
            or len(transfer_edges) != hop_count
            or trace_completed_at is None
        ):
            return None, False, "financial_flow_path_detail_sequence_or_freshness_unknown"

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

            exposure_context: Optional[dict[str, Any]] = None
            exposure_refs: list[EvidenceRef] = []
            exposure = assessment.exposure
            if exposure is not None:
                if (
                    exposure.tenant_id != request.tenantId
                    or exposure.subject_kind != "entity"
                    or exposure.subject_id != entity_id
                ):
                    return None, True, "financial_exposure_exact_binding_mismatch"
                exposure_refs = _dedupe_evidence(exposure.evidence_refs)
                if any(not ref.id.strip() or not ref.source.strip() for ref in exposure_refs):
                    return None, True, "financial_exposure_evidence_invalid"
                if any(
                    (observed := _aware_datetime(ref.observedAt)) is not None
                    and observed > assessment_at
                    for ref in exposure_refs
                ):
                    return None, True, "financial_exposure_evidence_temporal_order_invalid"
                # An exposure without evidence is not surfaced as an observed
                # path-node fact. A legitimate unpriced or label-only exposure
                # remains representable when its canonical refs are present.
                if exposure_refs:
                    economic_value = exposure.economic_value
                    exposure_context = {
                        "subject": {"kind": "entity", "id": entity_id},
                        "claimState": exposure.claim_state.value,
                        "exposedAssetCount": len(exposure.exposed_asset_labels),
                        "exposedOutcomeCount": len(exposure.exposed_outcome_labels),
                        "exposedPopulationCount": len(exposure.exposed_population_labels),
                        "economicValue": (
                            {
                                "amount": (
                                    str(economic_value.amount)
                                    if economic_value.amount is not None
                                    else None
                                ),
                                "currency": economic_value.currency,
                                "usdValue": (
                                    str(economic_value.usd_value)
                                    if economic_value.usd_value is not None
                                    else None
                                ),
                                "valuation": (
                                    economic_value.valuation.model_dump(mode="json")
                                    if economic_value.valuation is not None
                                    else None
                                ),
                            }
                            if economic_value is not None
                            else None
                        ),
                        "evidenceRefs": [ref.model_dump(mode="json") for ref in exposure_refs],
                    }

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
            node_refs.extend(exposure_refs)
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
                    "exposure": exposure_context,
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
        exposure_count = sum(row["exposure"] is not None for row in risk_contexts)
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
            f"transfer timestamps are {', '.join(observed_transfer_times)}. Evidence-backed "
            f"subject exposures are present for {exposure_count} path entities; these are not "
            "attributed to transfer edges. This is a correlated financial value/risk linkage "
            "only; it does not establish contagion, causal transmission, loss, or freshness "
            "against an SLA."
        )
        return (
            {
                "path_id": request.subject.id,
                "trace_id": raw_path["trace_id"],
                "risk_contexts": risk_contexts,
                "exposure_state": "partial" if exposure_count else "unknown",
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

    async def _safe_anomaly_events(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[list[dict[str, Any]], bool, Optional[str]]:
        """Project exact Gold alerts and bounded, explicit signal evidence joins.

        A Gold ``anomaly_alert`` materialization proves that an alert record
        was stored for this exact typed subject. A matching canonical RiskSignal
        can identify an event EvidenceRef and detector source; the event record
        itself, detector coverage, cause, and severity remain unverified.
        """
        reader = getattr(self._sources, "anomaly_events", None)
        if not callable(reader):
            return [], False, "canonical_anomaly_event_authority_unavailable"
        try:
            result = await reader(tenant_id=tenant_id, subject=subject)
        except Exception:  # noqa: BLE001 - source diagnostics stay private
            return [], True, "gold_anomaly_alert_read_incomplete"
        raw_records = getattr(result, "records", None)
        complete = getattr(result, "complete", None)
        read_reason = getattr(result, "reason", None)
        if not isinstance(raw_records, list) or not isinstance(complete, bool):
            return [], True, "gold_anomaly_alert_read_contract_invalid"
        if len(raw_records) > _MAX_RISK_ANOMALY_SCAN:
            return [], True, "gold_anomaly_alert_scan_limit_exceeded"

        reason = read_reason.strip() if isinstance(read_reason, str) and read_reason.strip() else None
        degraded = not complete or reason is not None
        if reason is None and not complete:
            reason = "gold_anomaly_alert_scan_truncated"
        events: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        try:
            from repositories.lake import GoldRepository

            expected_id = GoldRepository.compute_record_id(
                tenant_id,
                "anomaly_alert",
                subject.id,
                subject.kind,
            )
        except Exception:  # noqa: BLE001 - missing identity authority stays unavailable
            return [], True, "gold_anomaly_alert_identity_authority_unavailable"

        for raw in raw_records:
            if not isinstance(raw, dict):
                degraded = True
                reason = reason or "gold_anomaly_alert_record_invalid"
                continue
            alert_id = raw.get("id")
            if (
                str(raw.get("tenant_id", "")) != tenant_id
                or raw.get("metric_name") != "anomaly_alert"
                or raw.get("entity_id") != subject.id
                or raw.get("entity_type") != subject.kind
                or not isinstance(alert_id, str)
                or alert_id != expected_id
            ):
                degraded = True
                reason = reason or "gold_anomaly_alert_exact_binding_mismatch"
                continue
            if alert_id in seen_ids:
                degraded = True
                reason = reason or "gold_anomaly_alert_duplicate_record"
                continue
            seen_ids.add(alert_id)
            materialized_at = _aware_datetime(raw.get("materialized_at"))
            raw_join = raw.get("source_event_join")
            source_event_ref: Optional[EvidenceRef] = None
            source_event_record_ref: Optional[EvidenceRef] = None
            event_join: dict[str, Any] = {
                "state": "unknown",
                "reason": "explicit_anomaly_event_reference_unavailable",
            }
            if isinstance(raw_join, dict) and raw_join.get("state") == "degraded":
                degraded = True
                reason = reason or "gold_anomaly_source_event_join_incomplete"
                event_join = {
                    "state": "degraded",
                    "reason": "gold_anomaly_source_event_join_incomplete",
                }
            elif isinstance(raw_join, dict) and raw_join.get("state") == "verified_signal_evidence_reference":
                dimensions = raw.get("dimensions")
                ref = raw_join.get("evidence_ref")
                signal_id = raw_join.get("risk_signal_id")
                detector_source = raw_join.get("detector_source")
                claim_state = raw_join.get("signal_claim_state")
                record_read = raw_join.get("source_event_record_read")
                record_ref = raw_join.get("source_event_record_evidence_ref")
                if (
                    not isinstance(dimensions, dict)
                    or not isinstance(signal_id, str)
                    or not signal_id.strip()
                    or dimensions.get("risk_signal_id") != signal_id
                    or not isinstance(ref, EvidenceRef)
                    or ref.type != "event"
                    or not ref.id.strip()
                    or not ref.source.strip()
                    or dimensions.get("source_event_id") != ref.id
                    or dimensions.get("source_event_source") != ref.source
                    or not isinstance(detector_source, str)
                    or not detector_source.strip()
                    or claim_state not in {state.value for state in EpistemicStatus}
                    or not isinstance(record_read, str)
                    or record_read not in {
                        "not_performed",
                        "unavailable",
                        "ambiguous",
                        "invalid",
                        "verified_exact_bronze_record",
                    }
                    or (
                        record_read == "verified_exact_bronze_record"
                        and (
                            ref.source != "bronze_sdk_events"
                            or not isinstance(record_ref, EvidenceRef)
                            or record_ref.type != "event"
                            or record_ref.source != "bronze_sdk_events"
                            or record_ref.id != ref.id
                            or not isinstance(record_ref.uri, str)
                            or not record_ref.uri.startswith("store://bronze_sdk_events/")
                        )
                    )
                    or (record_read != "verified_exact_bronze_record" and record_ref is not None)
                ):
                    degraded = True
                    reason = reason or "gold_anomaly_source_event_join_incomplete"
                    event_join = {
                        "state": "degraded",
                        "reason": "gold_anomaly_source_event_join_incomplete",
                    }
                else:
                    source_event_ref = ref
                    if record_read == "verified_exact_bronze_record":
                        source_event_record_ref = record_ref
                    event_join = {
                        "state": "verified_signal_evidence_reference",
                        "riskSignalId": signal_id,
                        "detectorSource": detector_source,
                        "detectorVersion": raw_join.get("detector_version")
                        if isinstance(raw_join.get("detector_version"), str)
                        else None,
                        "signalClaimState": claim_state,
                        "sourceEventRecordRead": record_read,
                        "sourceEventEvidenceRef": ref.model_dump(mode="json"),
                    }
                    if source_event_record_ref is not None:
                        event_join["sourceEventRecordEvidenceRef"] = (
                            source_event_record_ref.model_dump(mode="json")
                        )
                        recorded_at = _aware_datetime(
                            raw_join.get("source_event_recorded_at")
                        )
                        event_join["sourceEventRecordRecordedAt"] = (
                            recorded_at.isoformat() if recorded_at is not None else None
                        )
            elif raw_join is not None and (
                not isinstance(raw_join, dict) or raw_join.get("state") != "unknown"
            ):
                degraded = True
                reason = reason or "gold_anomaly_source_event_join_incomplete"
                event_join = {
                    "state": "degraded",
                    "reason": "gold_anomaly_source_event_join_incomplete",
                }
            evidence_ref = EvidenceRef(
                id=alert_id,
                type="model_output",
                source="gold_identity.anomaly_alert",
                observedAt=materialized_at.isoformat() if materialized_at is not None else None,
                uri=f"store://gold_identity/{quote(alert_id, safe='')}",
            )
            events.append(
                {
                    "alertRecordId": alert_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "recordedAt": (
                        materialized_at.isoformat() if materialized_at is not None else None
                    ),
                    "timestampSemantics": "gold_materialization_time_not_source_event_time",
                    "payload": "excluded",
                    "evidence_ref": evidence_ref,
                    "source_event_ref": source_event_ref,
                    "source_event_record_ref": source_event_record_ref,
                    "sourceEventJoin": event_join,
                    "semantics": (
                        "tenant_scoped_gold_alert_with_exact_bronze_event_record_"
                        "cause_and_detector_coverage_unattested"
                        if source_event_record_ref is not None
                        else
                        "tenant_scoped_gold_alert_with_exact_risk_signal_event_evidence_"
                        "reference_cause_and_detector_coverage_unattested"
                        if source_event_ref is not None
                        else "tenant_scoped_gold_anomaly_alert_record_only_underlying_event_"
                        "cause_and_detector_coverage_not_attested"
                    ),
                }
            )
        events.sort(
            key=lambda row: (row["recordedAt"] or "", row["alertRecordId"]),
            reverse=True,
        )
        return events, degraded, reason

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
    def _interventions_as_of(
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> tuple[Optional[datetime], Optional[str]]:
        """Resolve an exact known-then anchor; range reads are not supported."""
        if request.timeRange is not None or request.temporalMode in {
            "window",
            "compare",
            "relative",
        }:
            return None, "risk_intervention_window_history_unavailable"
        request_anchor = _aware_datetime(request.asOf) if request.asOf is not None else None
        context_anchor = _aware_datetime(context.asOf) if context.asOf is not None else None
        if request.asOf is not None and request_anchor is None:
            return None, "risk_intervention_as_of_anchor_invalid"
        if context.asOf is not None and context_anchor is None:
            return None, "risk_intervention_context_anchor_invalid"
        if request_anchor is not None and context_anchor is not None:
            if request_anchor != context_anchor:
                return None, "risk_intervention_as_of_anchor_mismatch"
        anchor = request_anchor or context_anchor
        if request.temporalMode == "as_of" and anchor is None:
            return None, "risk_intervention_as_of_anchor_missing"
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
            supersedes_run_id = raw.get("supersedes_run_id")
            raw_link = raw.get("restatement_link")
            restatement_link: Optional[dict[str, Any]] = None
            if supersedes_run_id is None:
                if raw_link is not None:
                    degraded = True
                    reason = reason or "risk_assessment_history_restatement_link_invalid"
            elif not isinstance(supersedes_run_id, str) or not supersedes_run_id.strip():
                degraded = True
                reason = reason or "risk_assessment_history_restatement_reference_invalid"
            else:
                prior_started_at = (
                    _aware_datetime(raw_link.get("prior_started_at"))
                    if isinstance(raw_link, dict)
                    else None
                )
                if (
                    not isinstance(raw_link, dict)
                    or raw_link.get("state") != "verified_direct_predecessor"
                    or raw_link.get("prior_tenant_id") != tenant_id
                    or raw_link.get("prior_subject_kind") != subject.kind
                    or raw_link.get("prior_subject_id") != subject.id
                    or raw_link.get("prior_run_id") != supersedes_run_id
                    or supersedes_run_id == raw.get("run_id")
                    or raw_link.get("prior_assessment_id") != raw.get("assessment_id")
                    or not isinstance(raw_link.get("prior_definition_id"), str)
                    or not raw_link["prior_definition_id"].startswith("risk360.")
                    or raw_link["prior_definition_id"] != raw.get("definition_id")
                    or raw_link.get("prior_definition_version") != raw.get("definition_version")
                    or not isinstance(raw.get("definition_version"), str)
                    or not raw["definition_version"].strip()
                    or raw_link.get("prior_context_hash") != raw.get("context_hash")
                    or not isinstance(raw.get("context_hash"), str)
                    or not raw["context_hash"].strip()
                    or raw_link.get("prior_status") != "completed"
                    or prior_started_at is None
                    or prior_started_at > started_at
                ):
                    degraded = True
                    reason = reason or "risk_assessment_history_restatement_link_unverified"
                else:
                    restatement_link = {
                        "state": "verified_direct_predecessor",
                        "prior_run_id": supersedes_run_id,
                        "prior_tenant_id": tenant_id,
                        "prior_subject_kind": subject.kind,
                        "prior_subject_id": subject.id,
                        "prior_assessment_id": raw_link["prior_assessment_id"],
                        "prior_definition_id": raw_link["prior_definition_id"],
                        "prior_definition_version": raw_link["prior_definition_version"],
                        "prior_context_hash": raw_link["prior_context_hash"],
                        "prior_status": raw_link["prior_status"],
                        "prior_started_at": prior_started_at.isoformat(),
                    }
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
                    "restatement_link": restatement_link,
                }
            )
        rows.sort(
            key=lambda row: (row["started_at"], row["run_id"]),
            reverse=True,
        )
        return rows, degraded, reason

    @staticmethod
    def _assessment_history_evidence(rows: list[dict[str, Any]]) -> list[EvidenceRef]:
        """Make run rows and verified predecessor links traceable to the substrate."""
        evidence: list[EvidenceRef] = []
        for row in rows:
            run_id = row.get("run_id")
            started_at = row.get("started_at")
            if isinstance(run_id, str) and isinstance(started_at, str):
                evidence.append(
                    EvidenceRef(
                        id=run_id,
                        type="model_output",
                        source="computation_runs",
                        observedAt=started_at,
                        uri=f"store://computation_runs/{run_id}",
                    )
                )
            link = row.get("restatement_link")
            if not isinstance(link, dict) or link.get("state") != "verified_direct_predecessor":
                continue
            prior_run_id = link.get("prior_run_id")
            prior_started_at = link.get("prior_started_at")
            if isinstance(prior_run_id, str) and isinstance(prior_started_at, str):
                evidence.append(
                    EvidenceRef(
                        id=prior_run_id,
                        type="model_output",
                        source="computation_runs",
                        observedAt=prior_started_at,
                        uri=f"store://computation_runs/{prior_run_id}",
                    )
                )
        return _dedupe_evidence(evidence)

    @staticmethod
    def _assessment_history_summary(
        rows: list[dict[str, Any]],
        *,
        degraded: bool,
        reason: Optional[str],
        interventions: dict[str, Any],
    ) -> dict[str, Any]:
        """Render assessment-run history while preserving uncovered audit areas."""
        intervention_degraded = interventions.get("state") == "degraded"
        has_interventions = bool(interventions.get("records"))
        restatement_links = [
            {
                "priorRunId": row["restatement_link"]["prior_run_id"],
                "newRunId": row["run_id"],
                "assessmentId": row["assessment_id"],
                "definitionId": row["definition_id"],
                "definitionVersion": row["definition_version"],
                "contextHash": row["context_hash"],
                "priorStartedAt": row["restatement_link"]["prior_started_at"],
                "newStartedAt": row["started_at"],
                "relation": "computation_run_supersedes_run",
                "evidenceRefs": [
                    ref.model_dump(mode="json")
                    for ref in Risk360Provider._assessment_history_evidence([row])
                ],
            }
            for row in rows
            if isinstance(row.get("restatement_link"), dict)
            and row["restatement_link"].get("state") == "verified_direct_predecessor"
        ]
        state = (
            "degraded"
            if degraded or intervention_degraded
            else "partial"
            if rows or has_interventions
            else "unknown"
        )
        if degraded:
            resolved_reason = reason or "risk_assessment_run_history_read_incomplete"
        elif intervention_degraded:
            resolved_reason = interventions.get("reason") or "risk_intervention_read_incomplete"
        elif rows:
            resolved_reason = (
                "assessment_run_history_and_verified_direct_restatement_links_available_full_lineage_actor_authority_and_producer_coverage_unknown"
                if restatement_links
                else "assessment_run_history_available_restatement_links_not_observed_actor_authority_and_producer_coverage_unknown"
            )
        elif has_interventions:
            resolved_reason = "intervention_records_available_assessment_run_history_unavailable"
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
                "supersedesRunId": (
                    row["restatement_link"]["prior_run_id"]
                    if isinstance(row.get("restatement_link"), dict)
                    and row["restatement_link"].get("state") == "verified_direct_predecessor"
                    else None
                ),
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
            "restatementLinks": restatement_links,
            "interventions": interventions,
            "coverage": {
                "completeRunScan": not degraded and reason is None,
                "assessmentVersionLineage": (
                    "bounded_verified_direct_predecessor_links"
                    if restatement_links
                    else "no_verified_direct_predecessor_links_observed"
                ),
                "verifiedDirectRestatementLinkCount": len(restatement_links),
                "fullRestatementLineage": "unknown_beyond_direct_bounded_links",
                "interventionAuditLineage": interventions.get("state", "unknown"),
                "actorAuthorityEvaluation": "not_performed_by_risk360",
                "externalOutcomeVerification": "unavailable",
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

    async def _safe_interventions(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        as_of: Optional[datetime],
    ) -> tuple[list[RiskInterventionRecord], bool, Optional[str]]:
        """Read typed intervention events and revalidate their exact scope."""
        reader = getattr(self._sources, "interventions", None)
        if not callable(reader):
            return [], False, "risk_intervention_authority_unavailable"
        try:
            result = await reader(tenant_id=tenant_id, subject=subject, as_of=as_of)
        except Exception:  # noqa: BLE001 - provider boundary returns safe absence
            return [], True, "risk_intervention_read_incomplete"

        raw_records = getattr(result, "records", None)
        complete = getattr(result, "complete", None)
        read_reason = getattr(result, "reason", None)
        if not isinstance(raw_records, list) or not isinstance(complete, bool):
            return [], True, "risk_intervention_read_contract_invalid"
        if len(raw_records) > _MAX_RISK_INTERVENTION_SCAN:
            return [], True, "risk_intervention_scan_limit_exceeded"

        records: list[RiskInterventionRecord] = []
        seen_ids: set[str] = set()
        reason = read_reason.strip() if isinstance(read_reason, str) and read_reason.strip() else None
        degraded = not complete or reason is not None
        if reason is None and not complete:
            reason = "risk_intervention_scan_truncated"
        for raw in raw_records:
            try:
                record = (
                    raw
                    if isinstance(raw, RiskInterventionRecord)
                    else RiskInterventionRecord.model_validate(raw)
                )
            except Exception:  # noqa: BLE001 - malformed rows cannot back a claim
                degraded = True
                reason = reason or "risk_intervention_contract_invalid"
                continue
            if (
                record.tenant_id != tenant_id
                or record.subject_kind != subject.kind
                or record.subject_id != subject.id
            ):
                degraded = True
                reason = reason or "risk_intervention_exact_binding_mismatch"
                continue
            if record.record_id in seen_ids:
                degraded = True
                reason = reason or "risk_intervention_duplicate_record"
                continue
            seen_ids.add(record.record_id)
            if as_of is not None and (
                record.recorded_at > as_of or record.observed_at > as_of
            ):
                degraded = True
                reason = reason or "risk_intervention_as_of_read_inconsistent"
                continue
            records.append(record)

        records.sort(
            key=lambda record: (record.recorded_at, record.record_id),
            reverse=True,
        )
        by_id = {record.record_id: record for record in records}
        for record in records:
            if record.record_kind != "outcome":
                continue
            decision = by_id.get(record.decision_record_id or "")
            if decision is None:
                degraded = True
                reason = reason or "risk_intervention_decision_link_not_in_bounded_read"
                continue
            if (
                decision.record_kind != "decision"
                or decision.tenant_id != record.tenant_id
                or decision.intervention_id != record.intervention_id
                or decision.subject_kind != record.subject_kind
                or decision.subject_id != record.subject_id
                or decision.intervention_type != record.intervention_type
            ):
                degraded = True
                reason = reason or "risk_intervention_decision_link_mismatch"
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
        anomaly_events: list[dict[str, Any]],
        source_provenance: list[dict[str, Any]],
        poisoning_evidence: list[RiskPoisoningEvidence],
        agent_policy_flags: list[dict[str, Any]],
        interventions: list[RiskInterventionRecord],
    ) -> list[EvidenceRef]:
        """Every canonical EvidenceRef grounding this projection, deduped."""
        refs: list[EvidenceRef] = []
        if assessment is not None:
            refs.extend(Risk360Provider._assessment_evidence(assessment))
        for signal in signals:
            refs.extend(signal.evidence_refs)
        for event in anomaly_events:
            ref = event.get("evidence_ref")
            if isinstance(ref, EvidenceRef):
                refs.append(ref)
            source_ref = event.get("source_event_ref")
            if isinstance(source_ref, EvidenceRef):
                refs.append(source_ref)
        for row in source_provenance:
            ref = row.get("evidence_ref")
            if isinstance(ref, EvidenceRef):
                refs.append(ref)
        for record in poisoning_evidence:
            refs.extend(record.evidence_refs)
            for event in record.lifecycle_events:
                refs.extend(event.evidence_refs)
        for record in interventions:
            refs.extend(record.actor_evidence_refs)
            refs.extend(record.evidence_refs)
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
    "RiskAnomalyEventRead",
    "Risk360Provider",
    "RiskSourceReader",
    "SECTION_DEPENDENCIES",
    "build_projection_request",
    "register_provider",
]
