"""Risk360 intelligence-projection provider (Phase 4, Risk360/Fraud360 program).

Risk360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). This provider projects the *risk* domain
for a subject (``entity`` / ``relationship`` / ``cluster`` / ``population``)
from the tenant's canonical risk records: the Phase-3
:class:`~services.risk360.contracts.RiskAssessment` (the aggregation of risk
signals under a policy) and the :class:`~services.risk360.contracts.RiskSignal`
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

from datetime import datetime, timezone
from typing import Any, Optional, Protocol

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
from services.operational_intelligence.models import EvidenceRef

# Canonical measurement-plane value-state authority (honest absence, never 0).
from shared.measurement.value_states import requires_value

# Risk360 Phase-3 domain contracts + dimension registry + repositories.
from services.risk360.contracts import RiskAssessment, RiskSignal
from services.risk360.dimensions import RISK_DIMENSIONS
from services.risk360.store import RiskAssessmentRepository, RiskSignalRepository

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


def _dependency_missing(dep_state: list[Any], projection_id: str) -> bool:
    """True when a sibling projection is missing or not yet available."""
    dep = next((d for d in dep_state if d.projectionId == projection_id), None)
    return dep is None or dep.state != "available"


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
    cannot reach its backing store returns ``None`` / ``[]`` (the provider
    degrades the affected sections) — never raises, never fabricates.

    The two reads are the entire Risk360 input surface: the tenant's latest
    :class:`RiskAssessment` for the subject (the aggregation) and the atomic
    :class:`RiskSignal` records feeding it. Section mapping: ``summary`` /
    ``state`` / ``findings`` render from the assessment (+ its vector
    components), ``evidence`` from the EvidenceRefs both carry, and ``health``
    from the signal sources. Phase 5 wires real detector output here by writing
    typed RiskSignal / RiskAssessment rows these reads consume.
    """

    async def latest_assessment(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> Optional[dict[str, Any]]:
        """The tenant's latest RiskAssessment record for ``subject``, or None."""
        ...

    async def signals(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped RiskSignal records for ``subject`` (empty when none)."""
        ...


class RepositoryRiskSourceReader:
    """Default canonical reader over the Phase-3 risk repositories.

    Reads the tenant-scoped ``RiskAssessmentRepository`` + ``RiskSignalRepository``
    defensively. Any backing-source failure returns ``None`` / ``[]`` for that
    source — the projection degrades, it never crashes.
    """

    def __init__(self) -> None:
        self._assessments = RiskAssessmentRepository()
        self._signals = RiskSignalRepository()

    async def latest_assessment(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> Optional[dict[str, Any]]:
        """The tenant's latest RiskAssessment for the subject (or None).

        ``list_scoped`` returns the tenant's rows newest-created first (created_at
        desc); among them the assessment with the newest ``assessed_at`` is the
        latest statement. Honest absence when the tenant has none — never raises.
        """
        try:
            rows = await self._assessments.list_by_subject(
                tenant_id, subject.kind, subject.id, limit=50
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return None
        rows = [r for r in rows if str(r.get("tenant_id", "")) == tenant_id]
        if not rows:
            return None
        rows.sort(key=lambda r: str(r.get("assessed_at") or ""), reverse=True)
        return rows[0]

    async def signals(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped RiskSignal rows for the subject (empty when none)."""
        try:
            rows = await self._signals.list_by_subject(
                tenant_id, subject.kind, subject.id, limit=100
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        return [r for r in rows if str(r.get("tenant_id", "")) == tenant_id]


class Risk360Provider:
    """Read-only intelligence-projection provider for ``risk360``."""

    projection_id: str = PROJECTION_ID
    contract_version: str = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy: str = "read_only"

    def __init__(self, sources: Optional[RiskSourceReader] = None) -> None:
        # Injected canonical reader (test seam); default reads the Phase-3
        # repositories. Read-only — the provider holds no write path.
        self._sources = (
            sources if sources is not None else RepositoryRiskSourceReader()
        )

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Risk360 projection over the tenant's risk records."""
        tenant_id = request.tenantId
        dep_state = context.dependencyState

        assessment, assessment_degraded = await self._safe_assessment(
            tenant_id, request.subject
        )
        signals, signals_degraded = await self._safe_signals(
            tenant_id, request.subject
        )

        evidence = self._collect_evidence(assessment, signals)

        sections = [
            self._summary_section(request, assessment, assessment_degraded, dep_state),
            self._state_section(request, assessment, assessment_degraded, dep_state),
            self._evidence_section(evidence),
            self._findings_section(request, assessment, assessment_degraded),
            self._health_section(request, assessment, signals, signals_degraded),
        ]
        claims = self._build_claims(request, assessment, signals)

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
            warnings.append(
                "no risk assessment exists for the subject; no summary is rendered"
            )
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["summary"]):
            state = "degraded"
            warnings.append(
                "profile360 dependency not available; summary is degraded"
            )
        elif not assessment.vector.components:
            state = "empty"
            warnings.append(
                "risk assessment records no risk dimensions; summary is empty"
            )

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
                assessment.assessed_at.isoformat()
                if assessment.assessed_at is not None
                else None
            ),
            # Sparse by design: the dimensions this assessment evaluated.
            "dimensionsEvaluated": list(assessment.dimensions),
            "componentsRecorded": len(assessment.vector.components),
            "scoredDimensions": scored,
            "claimState": assessment.claim_state.value,
            "confidence": assessment.confidence,
            "evidenceRefs": [
                ref.model_dump(mode="json") for ref in assessment.evidence_refs
            ],
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
                        "usdValue": (
                            None if amount.usd_value is None else str(amount.usd_value)
                        ),
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
            warnings.append(
                "risk assessment source unavailable; per-dimension state is degraded"
            )
        elif assessment is None:
            state = "missing"
            warnings.append(
                "no risk assessment exists for the subject; no dimension state is rendered"
            )
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["state"]):
            state = "degraded"
            warnings.append(
                "cluster360 dependency not available; risk state is degraded"
            )
        elif not assessment.vector.components:
            state = "empty"
            warnings.append(
                "risk assessment records no risk dimensions; state is empty"
            )

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
                            ref.model_dump(mode="json")
                            for ref in component.evidence_refs
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

    def _evidence_section(self, evidence: list[EvidenceRef]) -> ProjectionSection:
        """evidence — the canonical EvidenceRefs grounding this projection."""
        return ProjectionSection(
            id="evidence",
            state="available" if evidence else "empty",
            title="Evidence",
            content={
                "count": len(evidence),
                "evidence": [e.model_dump(mode="json") for e in evidence],
            },
        )

    def _findings_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        assessment_degraded: bool,
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
            warnings.append(
                "risk assessment source unavailable; findings cannot be derived"
            )
        elif assessment is None:
            state = "missing"
            warnings.append(
                "no risk assessment exists for the subject; no findings are asserted"
            )
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
                "assessmentId": (
                    assessment.assessment_id if assessment is not None else None
                ),
                "findings": [],
            },
            warnings=warnings or None,
        )

    def _health_section(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
        signals_degraded: bool,
    ) -> ProjectionSection:
        """health — detector/source freshness for the signals feeding the read.

        Backed by the tenant's RiskSignal rows: each contributing source's count,
        detector versions and newest observation. No signals yet -> honest
        ``missing`` (no contributing source to assess); an unreadable signal
        source degrades the section content-free.
        """
        state: str = "available"
        warnings: list[str] = []
        if signals_degraded:
            state = "degraded"
            warnings.append("risk signal source unavailable; health is degraded")
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
            observed_at = (
                signal.observed_at.isoformat()
                if signal.observed_at is not None
                else None
            )
            if observed_at is not None and (
                source_state["latestObservedAt"] is None
                or observed_at > source_state["latestObservedAt"]
            ):
                source_state["latestObservedAt"] = observed_at

        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "signalSources": by_source,
            "assessmentFreshness": (
                None
                if assessment is None or assessment.assessed_at is None
                else {
                    "assessmentId": assessment.assessment_id,
                    "assessedAt": assessment.assessed_at.isoformat(),
                }
            ),
        }
        return ProjectionSection(
            id="health",
            state=state,  # type: ignore[arg-type]
            title="Risk health",
            content=content,
            warnings=warnings or None,
        )

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        assessment: Optional[RiskAssessment],
        signals: list[RiskSignal],
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: never an empty envelope)."""
        claims: list[ClaimEnvelope] = []
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)

        if assessment is not None:
            assessment_refs = self._assessment_evidence(assessment)
            if assessment_refs:
                policy = (
                    f" under policy {assessment.policy_id} "
                    f"v{assessment.policy_version}"
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
                        evidenceRefs=list(component.evidence_refs),
                        claims=[
                            f"Risk dimension {component.dimension!r} is "
                            f"{component.state.value} (score "
                            f"{component.score}); claim_state "
                            f"{component.claim_state.value}."
                        ],
                        confidence=component.confidence,
                    )
                )

        if signals:
            # One claim per contributing signal source (detector health truth).
            refs_by_source: dict[str, list[EvidenceRef]] = {}
            for signal in signals:
                refs_by_source.setdefault(signal.source, []).extend(
                    signal.evidence_refs
                )
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
                    )
                )
        return claims

    # ── Canonical read helpers (defensive) ─────────────────────────────────

    async def _safe_assessment(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[Optional[RiskAssessment], bool]:
        """Latest tenant RiskAssessment, or (None, degraded) — never raises."""
        degraded = False
        raw: Optional[dict[str, Any]] = None
        try:
            raw = await self._sources.latest_assessment(
                tenant_id=tenant_id, subject=subject
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return None, True
        if raw is None:
            return None, False
        # Tenant scope is server-authoritative: never project another tenant's
        # assessment/sections/evidence.
        if str(raw.get("tenant_id", "")) != tenant_id:
            return None, False
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
        for raw in raw_rows:
            # Server-authoritative tenant filter; a leaky row is dropped, not
            # surfaced (and never mistaken for a degraded read of this tenant).
            if str(raw.get("tenant_id", "")) != tenant_id:
                continue
            try:
                signals.append(RiskSignal(**raw))
            except Exception:  # noqa: BLE001 - skip an unrenderable signal row
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
    ) -> list[EvidenceRef]:
        """Every canonical EvidenceRef grounding this projection, deduped."""
        refs: list[EvidenceRef] = []
        if assessment is not None:
            refs.extend(Risk360Provider._assessment_evidence(assessment))
        for signal in signals:
            refs.extend(signal.evidence_refs)
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
    registry.register(Risk360Provider(), source="services/risk360")


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
