"""Risk360 deterministic signal→assessment pipeline (Phase 5).

This module is the Risk360 **evaluation runtime**: the pure, deterministic path
that turns detector evidence into a scored, policy-projected assessment per
subject. It owns NO thresholds and NO canonical truth — it delegates:

* **Step (a) — converge.** Raw producer artifacts (fraud result, fraud-network
  evidence, device risk, geo enrichment, behavioral scan, trust vector) become
  typed :class:`~services.risk360.contracts.RiskSignal`(s) via
  :func:`services.risk360.signals.adapt_producer_signal`.
* **Step (b) — aggregate.** Signals collapse into a sparse
  :class:`~services.risk360.contracts.RiskVector`: one
  :class:`RiskComponent` per dimension that has signals, scored only when a
  signal carries a real 0–1 score (never a fabricated zero; a dimension with
  signals but no usable number renders ``insufficient_data``).
* **Step (c) — project.** The vector projects through a registered
  :class:`~services.risk360.policies.RiskPolicy` (its ``DecisionPolicy`` owns the
  thresholds; there is no universal risk meaning, so the same vector projects
  differently under different policies).
* **Step (d) — record.** :func:`compute_assessment` returns the
  :class:`~services.risk360.contracts.RiskAssessment` together with a
  :class:`~services.risk360.contracts.RiskAssessmentRun` whose ``context_hash``
  is the deterministic :meth:`ComputationContext.context_hash` of everything the
  assessment depended on (subject, policy, exposure, evidence digest) — two
  identical computations share a hash, and a restatement supersedes rather than
  forks.
* **Step (e) — finding candidate.** :func:`materiality_candidate` runs the
  materiality hook so downstream finding ladders can compare apples to apples.

Honesty contract
----------------

* A dimension with no signal stays ABSENT from the vector — it is never coerced
  to a ``0`` (see :class:`RiskVector.component_for`).
* A dimension whose signals carry no usable numeric renders
  ``ValueState.INSUFFICIENT_DATA`` with ``score=None`` — never an invented
  probability from an uncalibrated heuristic.
* An aggregated component's ``claim_state`` never escalates its inputs: a
  derived/inferred detector condition aggregates to ``derived`` (an
  *aggregation* is itself a derivation); only all-``observed`` contributors
  yield an ``observed`` component.
* Aggregation is deterministic over its inputs (sort-stable, no clock/uuid), so
  ``compute_assessment`` over equal evidence yields an equal ``context_hash``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Sequence

from shared.computation.context import ComputationContext
from shared.measurement.value_states import ValueState
from shared.computation.policies import PolicyOutcome

from services.operational_intelligence.models import (
    EntityRef,
    EvidenceRef,
    GraphSnapshotRef,
)

from .contracts import (
    EpistemicStatus,
    ExposureAssessment,
    RiskAssessment,
    RiskAssessmentRun,
    RiskComponent,
    RiskSignal,
    RiskVector,
)
from .dimensions import RISK_DIMENSION_KEYS
from .materiality import materiality_for_assessment
from .policies import DEFAULT_POLICY_ID, RiskPolicy, policy
from .signals import RiskEvidenceBundle, signals_from_evidence_bundle
from .store import RiskAssessmentRepository, RiskSignalRepository


# ═══════════════════════════════════════════════════════════════════════════
# Step (b) — aggregation
# ═══════════════════════════════════════════════════════════════════════════

def _dedupe_evidence_refs(refs: Sequence[EvidenceRef]) -> list[EvidenceRef]:
    """Stable, order-preserving dedupe of evidence refs by id."""
    seen: set[str] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


def _component_for_dimension(dimension: str, signals: Sequence[RiskSignal]) -> RiskComponent:
    """Collapse every signal on one risk dimension into a single component.

    Score = the strongest value-bearing signal score on the dimension (weakest-
    link/conservative: the highest observed/estimated risk wins). Signals that
    carry no usable numeric contribute evidence but not a score; a dimension with
    ONLY unscored signals renders ``insufficient_data`` (honest non-value state),
    never a fabricated number.

    Claim state never escalates inputs: an aggregation of detector output is a
    derivation, so mixed/derived contributors yield ``derived``. Only when every
    value-bearing contributor is a direct ``observed`` measurement does the
    component claim ``observed`` (a genuine direct read).
    """
    value_bearing = [s for s in signals if s.score is not None]
    all_refs = _dedupe_evidence_refs(
        ref for s in signals for ref in s.evidence_refs
    )

    if not value_bearing:
        return RiskComponent(
            dimension=dimension,
            state=ValueState.INSUFFICIENT_DATA,
            claim_state=EpistemicStatus.UNKNOWN,
            evidence_refs=all_refs,
        )

    best = max(value_bearing, key=lambda s: float(s.score or 0.0))
    all_observed = all(
        s.claim_state == EpistemicStatus.OBSERVED for s in value_bearing
    )
    confidences = [
        s.confidence for s in value_bearing if s.confidence is not None
    ]
    return RiskComponent(
        dimension=dimension,
        state=ValueState.OBSERVED if all_observed else ValueState.ESTIMATED,
        score=float(best.score),
        claim_state=EpistemicStatus.OBSERVED if all_observed else EpistemicStatus.DERIVED,
        confidence=max(confidences) if confidences else None,
        evidence_refs=all_refs,
    )


def _dimension_order(dimension: str) -> int:
    """Canonical registry ordering for deterministic component lists."""
    try:
        return list(RISK_DIMENSION_KEYS).index(dimension)
    except ValueError:
        return len(RISK_DIMENSION_KEYS)


def aggregate_signals(signals: Sequence[RiskSignal]) -> RiskVector:
    """Aggregate RiskSignals into a sparse RiskVector.

    One component per dimension that received signals; dimensions with no signal
    stay absent (see :class:`RiskVector.component_for` for honest absence).
    Deterministic: components are emitted in canonical dimension order.
    """
    by_dim: dict[str, list[RiskSignal]] = {}
    for signal in signals:
        by_dim.setdefault(signal.risk_dimension, []).append(signal)
    components = [
        _component_for_dimension(dimension, by_dim[dimension])
        for dimension in sorted(by_dim, key=_dimension_order)
    ]
    return RiskVector(components=components)


def scored_dimensions(vector: RiskVector) -> dict[str, float]:
    """Map dimension → score for every value-bearing component (nothing else)."""
    return {
        c.dimension: float(c.score)
        for c in vector.components
        if c.score is not None
    }


# ═══════════════════════════════════════════════════════════════════════════
# Step (d) — run identity over the computation substrate
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AssessmentResult:
    """The outcome of one :func:`compute_assessment` call."""

    assessment: RiskAssessment
    run: RiskAssessmentRun
    aggregate: Optional[float]
    outcome: PolicyOutcome
    materiality: Any = None  # Optional comparison-plane MaterialityResult


def _format_decimal(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except Exception:  # noqa: BLE001 - best-effort canonical string form
        return str(value)


def _evidence_digest(signals: Sequence[RiskSignal]) -> list[str]:
    """Sort-stable digest of the evidence that produced an assessment.

    Signal ids are themselves content-derived (no uuid/clock) and ordering is
    normalized, so equal evidence → equal digest regardless of arrival order.
    """
    return sorted(s.signal_id for s in signals)


def assessment_computation_context(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    policy_row: RiskPolicy,
    signals: Sequence[RiskSignal],
    vector: RiskVector,
    aggregate: Optional[float],
    outcome: PolicyOutcome,
    exposure: Optional[ExposureAssessment],
    baseline_present: bool,
    snapshot: Optional[GraphSnapshotRef] = None,
    as_of: Optional[str] = None,
) -> ComputationContext:
    """The canonical computation scope that produced an assessment.

    Everything the assessment depended on is in the identity hash: subject,
    policy row, the sorted evidence digest, the resulting vector, the exposure
    figure, and the presence of a peer baseline. Identical inputs ⇒ identical
    ``context_hash()``; a restatement (late data) changes the hash and therefore
    supersedes rather than silently overwrites the earlier run.
    """
    aggregate_repr = None if aggregate is None else f"{float(aggregate):.4f}"
    exposure_usd = _format_decimal(
        exposure.economic_value.usd_value
        if exposure is not None and exposure.economic_value is not None
        else None
    )
    return ComputationContext(
        tenant_id=tenant_id,
        subject_type=subject_kind,
        subject_id=subject_id,
        grain="subject",
        dimensions={
            "risk360": {
                "policy_id": policy_row.policy_id,
                "policy_version": policy_row.policy_version,
                "outcome": outcome.value,
                "aggregate": aggregate_repr,
                "vector": {
                    c.dimension: (
                        float(c.score) if c.score is not None else c.state.value
                    )
                    for c in vector.components
                },
                "evidence": _evidence_digest(signals),
                "exposure_usd": exposure_usd,
                "baseline": baseline_present,
            }
        },
        as_of=snapshot.asOf if snapshot is not None else as_of,
        graph_snapshot_id=(
            snapshot.graph_snapshot_id if snapshot is not None else None
        ),
        policy_version=policy_row.policy_version,
        model_version="risk360.aggregation.1",
    )


def compute_assessment(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    policy_id: str = DEFAULT_POLICY_ID,
    signals: Sequence[RiskSignal] = (),
    evidence_bundle: Optional[RiskEvidenceBundle] = None,
    exposure: Optional[ExposureAssessment] = None,
    subject_ref: Optional[EntityRef] = None,
    snapshot: Optional[GraphSnapshotRef] = None,
    baseline: Optional[RiskVector] = None,
    observed_at: Optional[datetime] = None,
) -> AssessmentResult:
    """Run the full deterministic detector→assessment computation.

    Steps (a)→(e): any ``evidence_bundle`` is first converged to signals, then
    signals are aggregated, projected under the registered ``policy_id``, and
    wrapped in a :class:`RiskAssessment` + :class:`RiskAssessmentRun`.

    ``baseline`` (peer/comparison context, optional) never fabricates subject
    scores — the subject vector is computed from the subject's OWN signals only.
    Baseline presence is recorded in the run identity so an assessment computed
    under a different peer baseline is recognized as a different computation.
    """
    effective_signals = list(signals)
    if evidence_bundle is not None:
        effective_signals.extend(
            signals_from_evidence_bundle(
                evidence_bundle,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )

    policy_row = policy(policy_id)
    vector = aggregate_signals(effective_signals)
    aggregate, outcome = policy_row.decide(vector)

    as_of = (
        snapshot.asOf
        if snapshot is not None
        else (observed_at.isoformat() if observed_at is not None else None)
    )
    context = assessment_computation_context(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        policy_row=policy_row,
        signals=effective_signals,
        vector=vector,
        aggregate=aggregate,
        outcome=outcome,
        exposure=exposure,
        baseline_present=baseline is not None,
        snapshot=snapshot,
        as_of=as_of,
    )
    context_hash = context.context_hash()
    assessment_id = f"ras_{context_hash}"

    # The run is minted FIRST so the assessment can reference the run id it was
    # produced by (a fresh substrate row per run; the assessment links to it).
    run = RiskAssessmentRun.from_context(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        context=context,
        created_at=observed_at,
    )

    # An assessment with zero recorded components makes NO claim about the
    # subject (honest ``unknown``); one with components derives a score.
    claim_state = (
        EpistemicStatus.DERIVED if vector.components else EpistemicStatus.UNKNOWN
    )

    assessment = RiskAssessment(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        subject_ref=subject_ref,
        policy_id=policy_row.policy_id,
        policy_version=policy_row.policy_version,
        dimensions=[c.dimension for c in vector.components],
        vector=vector,
        exposure=exposure,
        claim_state=claim_state,
        evidence_refs=_dedupe_evidence_refs(
            ref for s in effective_signals for ref in s.evidence_refs
        ),
        snapshot=snapshot,
        run_id=run.run_id,
        assessed_at=observed_at,
    )
    materiality = materiality_for_assessment(
        assessment, outcome=outcome, exposure=exposure
    )
    return AssessmentResult(
        assessment=assessment,
        run=run,
        aggregate=aggregate,
        outcome=outcome,
        materiality=materiality,
    )


def assess_subject(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    policy_id: str = DEFAULT_POLICY_ID,
    signals: Sequence[RiskSignal] = (),
    evidence_bundle: Optional[RiskEvidenceBundle] = None,
    exposure: Optional[ExposureAssessment] = None,
    subject_ref: Optional[EntityRef] = None,
    snapshot: Optional[GraphSnapshotRef] = None,
    baseline: Optional[RiskVector] = None,
    observed_at: Optional[datetime] = None,
) -> RiskAssessment:
    """Convenience wrapper returning just the :class:`RiskAssessment`."""
    return compute_assessment(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        policy_id=policy_id,
        signals=signals,
        evidence_bundle=evidence_bundle,
        exposure=exposure,
        subject_ref=subject_ref,
        snapshot=snapshot,
        baseline=baseline,
        observed_at=observed_at,
    ).assessment


def materiality_candidate(
    assessment: RiskAssessment,
    outcome: PolicyOutcome,
    exposure: Optional[ExposureAssessment] = None,
) -> Any:
    """Findings-candidate materiality hook (step (e)).

    Thin wrapper over :func:`services.risk360.materiality.materiality_for_assessment`
    returning the comparison-plane ``MaterialityResult`` (or ``None`` when the
    assessment records nothing evidence-backed — such an assessment is simply
    not materiality-scored, never silently scored as low-severity).
    """
    return materiality_for_assessment(
        assessment, outcome=outcome, exposure=exposure
    )


async def persist_assessment(
    result: AssessmentResult,
    *,
    tenant_id: str,
    signals: Sequence[RiskSignal] = (),
    signal_repo: Optional[RiskSignalRepository] = None,
    assessment_repo: Optional[RiskAssessmentRepository] = None,
    runs_repo: Optional[Any] = None,
) -> AssessmentResult:
    """Persist one computed assessment end-to-end (the risk-lens write path).

    Writes three things so the read-only lens can surface a freshly computed
    assessment:

    * the run that produced it, appended to the substrate's ``computation_runs``
      (append-only; repeating identical evidence under an unchanged policy mints
      a *new* run id and records ``supersedes_run_id`` pointing at the prior run
      for the same assessment id — a restatement never overwrites silently);
    * the assessment itself onto ``risk_assessments`` (idempotent on
      ``assessment_id``, which is content-derived);
    * the contributing ``signals`` onto ``risk_signals``.

    All repositories are injectable (defaults construct the auto-created local
    JSONB stores / in-memory computation substrate).
    """
    from services.computation.repositories import ComputedResultsRepository  # noqa: PLC0415

    signal_repo = signal_repo or RiskSignalRepository()
    assessment_repo = assessment_repo or RiskAssessmentRepository()
    runs_repo = runs_repo or ComputedResultsRepository()

    assessment = result.assessment
    run = result.run

    # Supersession: determinism means identical evidence ⇒ identical
    # assessment_id; the *prior* stored assessment row carries the run that
    # produced it, so the fresh run records it as its predecessor.
    supersedes_run_id: Optional[str] = None
    prior = await assessment_repo.get_scoped(tenant_id, assessment.assessment_id)
    if prior is not None and prior.get("run_id") not in (None, run.run_id):
        supersedes_run_id = prior["run_id"]
        run = run.model_copy(update={"supersedes_run_id": supersedes_run_id})

    await runs_repo.insert_run(
        {
            "run_id": run.run_id,
            "tenant_id": tenant_id,
            "definition_id": assessment.policy_id or "risk360.assessment",
            "definition_version": assessment.policy_version or "1",
            "context_hash": run.context_hash,
            "status": "completed",
            "data": {
                "assessment_id": assessment.assessment_id,
                "subject_kind": assessment.subject_kind,
                "subject_id": assessment.subject_id,
                "claim_state": assessment.claim_state.value,
                "dimensions": assessment.dimensions,
            },
        }
    )

    for signal in signals:
        await signal_repo.upsert_scoped(
            tenant_id, signal.signal_id, signal.model_dump(mode="json")
        )

    stored = await assessment_repo.upsert_scoped(
        tenant_id,
        assessment.assessment_id,
        assessment.model_dump(mode="json"),
    )
    stored_assessment = RiskAssessment(**stored) if stored else assessment

    return AssessmentResult(
        assessment=stored_assessment,
        run=run,
        aggregate=result.aggregate,
        outcome=result.outcome,
        materiality=result.materiality,
    )


__all__ = [
    "AssessmentResult",
    "aggregate_signals",
    "assess_subject",
    "assessment_computation_context",
    "compute_assessment",
    "materiality_candidate",
    "persist_assessment",
    "scored_dimensions",
]
