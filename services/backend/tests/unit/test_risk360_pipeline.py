"""Risk360 Phase-5 deterministic signal→assessment pipeline tests.

Covers detector→signal→assessment end to end: aggregation honesty (no
fabricated zeros, no silent claim escalation), policy projection, exposure
carry, materiality/finding-candidate hook, and reproducible runs (equal
evidence ⇒ equal ``context_hash``/``assessment_id``; changed evidence ⇒ a
different, superseding run identity).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.measurement.value_states import ValueState  # noqa: E402

from services.risk360.contracts import (  # noqa: E402
    EpistemicStatus,
    EvidenceRef,
    RiskSignal,
)
from services.risk360.exposure import exposure_from_rollup  # noqa: E402
from services.risk360.pipeline import (  # noqa: E402
    aggregate_signals,
    assess_subject,
    compute_assessment,
    scored_dimensions,
)
from services.risk360.signals import RiskEvidenceBundle  # noqa: E402
from shared.computation.policies import PolicyOutcome  # noqa: E402


def _signal(dimension, score=None, *, claim=None, source="risk360.test", ref="ev_x"):
    claim = claim or EpistemicStatus.DERIVED
    refs = [EvidenceRef(id=ref, type="model_output", source=source)]
    return RiskSignal(
        signal_id=f"rsk_{dimension}_{score if score is not None else 'ns'}",
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        risk_dimension=dimension,
        claim_state=claim,
        evidence_refs=refs,
        source=source,
        score=score,
    )


# ── aggregation ─────────────────────────────────────────────────────────────

def test_aggregate_scores_strongest_signal_per_dimension():
    vector = aggregate_signals(
        [
            _signal("behavioral", 0.4, source="fraud.signals", ref="a"),
            _signal("behavioral", 0.9, source="fraud.signals", ref="b"),
        ]
    )
    assert scored_dimensions(vector) == {"behavioral": 0.9}
    component = vector.component_for("behavioral")
    assert component.state == ValueState.ESTIMATED
    assert component.claim_state == EpistemicStatus.DERIVED


def test_aggregate_never_escalates_claim_from_mixed_evidence():
    vector = aggregate_signals(
        [
            _signal("identity", 0.5, claim=EpistemicStatus.INFERRED),
            _signal("identity", 0.7, claim=EpistemicStatus.DERIVED),
        ]
    )
    component = vector.component_for("identity")
    assert component.claim_state == EpistemicStatus.DERIVED
    assert component.state == ValueState.ESTIMATED


def test_aggregate_all_observed_claims_observed():
    vector = aggregate_signals(
        [_signal("transaction", 0.0, claim=EpistemicStatus.OBSERVED)]
    )
    component = vector.component_for("transaction")
    assert component.claim_state == EpistemicStatus.OBSERVED
    assert component.state == ValueState.OBSERVED
    assert component.score == 0.0  # a genuine measured zero is honest


def test_unscored_signals_render_insufficient_data_not_a_zero():
    vector = aggregate_signals([_signal("relationship", score=None)])
    component = vector.component_for("relationship")
    assert component.state == ValueState.INSUFFICIENT_DATA
    assert component.score is None


def test_empty_signals_yield_empty_vector():
    vector = aggregate_signals([])
    assert vector.components == []
    # asking for any dimension returns honest absence, not a fabricated 0
    assert vector.component_for("identity").state == ValueState.MISSING_INPUTS


# ── projection + assessment ─────────────────────────────────────────────────

def test_assessment_projections_and_claim_state():
    res = compute_assessment(
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        signals=[
            _signal("fraud", 0.9),
            _signal("identity", 0.8),
        ],
    )
    assert res.outcome == PolicyOutcome.BLOCK
    assert res.aggregate is not None and res.aggregate >= 0.65
    assert res.assessment.vector.component_for("fraud").score == 0.9
    assert res.assessment.claim_state == EpistemicStatus.DERIVED
    assert res.assessment.policy_id == "risk360.standard"


def test_empty_evidence_fails_closed_to_review_with_no_claim():
    res = compute_assessment(
        tenant_id="ten_1", subject_kind="entity", subject_id="ent_1"
    )
    assert res.aggregate is None
    assert res.outcome == PolicyOutcome.REVIEW  # fail closed, never ALLOW
    assert res.assessment.claim_state == EpistemicStatus.UNKNOWN  # no claim made
    assert res.assessment.vector.components == []


def test_assess_subject_wrapper_returns_assessment():
    assessment = assess_subject(
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        signals=[_signal("fraud", 0.9)],
    )
    assert assessment.assessment_id.startswith("ras_")
    assert assessment.run_id is not None


# ── reproducible runs ───────────────────────────────────────────────────────

def test_reproducible_run_equal_evidence_equal_hash():
    signals = [
        _signal("fraud", 0.6, source="fraud.signals"),
        _signal("geographic", 0.9, source="geo.enrichment"),
    ]
    first = compute_assessment(
        tenant_id="ten_1", subject_kind="entity", subject_id="ent_1", signals=signals
    )
    second = compute_assessment(
        tenant_id="ten_1", subject_kind="entity", subject_id="ent_1", signals=signals
    )
    assert first.run.context_hash == second.run.context_hash
    assert first.assessment.assessment_id == second.assessment.assessment_id
    # run ids differ (each run is a distinct substrate row) but the computation
    # identity is equal.
    assert first.run.run_id != second.run.run_id


def test_changed_evidence_changes_run_identity():
    base = [
        _signal("fraud", 0.6, source="fraud.signals"),
        _signal("geographic", 0.9, source="geo.enrichment"),
    ]
    changed = [
        _signal("fraud", 0.9, source="fraud.signals"),
        _signal("geographic", 0.9, source="geo.enrichment"),
    ]
    first = compute_assessment(
        tenant_id="ten_1", subject_kind="entity", subject_id="ent_1", signals=base
    )
    second = compute_assessment(
        tenant_id="ten_1", subject_kind="entity", subject_id="ent_1", signals=changed
    )
    assert first.run.context_hash != second.run.context_hash


# ── evidence bundle path ────────────────────────────────────────────────────

def test_evidence_bundle_converges_into_assessment():
    bundle = RiskEvidenceBundle(
        geo_lookup={
            "state": "ready",
            "asn": 15169,
            "asn_class": "datacenter",
            "provider": "maxmind_geolite2",
            "provider_database_version": "2026.08.0",
            "datacenter_likelihood": 0.9,
        }
    )
    res = compute_assessment(
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        evidence_bundle=bundle,
    )
    assert res.assessment.vector.has_component("geographic")
    assert scored_dimensions(res.assessment.vector)["geographic"] == pytest.approx(0.9)


# ── exposure + materiality candidate ────────────────────────────────────────

def _exposure(usd="1000.00"):
    return exposure_from_rollup(
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        rollup={"total_usd": usd, "rollup_status": "complete", "unpriced_count": 0},
    )


def test_materiality_candidate_block_scenario():
    exposure = _exposure()
    res = compute_assessment(
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        exposure=exposure,
        signals=[_signal("fraud", 0.9), _signal("identity", 0.8)],
    )
    assert res.outcome == PolicyOutcome.BLOCK
    assert res.materiality is not None
    assert res.materiality.score > 0
    # block disposition drives the impact components
    assert res.materiality.components["risk_impact"] == 0.9


def test_empty_assessment_is_not_materiality_scored():
    res = compute_assessment(
        tenant_id="ten_1", subject_kind="entity", subject_id="ent_1"
    )
    # no value-bearing component AND no valued exposure → honest None, never a
    # low-severity finding fabricated from nothing.
    assert res.materiality is None


# ── persistence (risk-lens write path) ──────────────────────────────────────

def _persist_signal(dimension, score):
    return RiskSignal(
        signal_id=f"persist_rsk_{dimension}_{score}",
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        risk_dimension=dimension,
        claim_state=EpistemicStatus.DERIVED,
        evidence_refs=[EvidenceRef(id=f"persist_ev_{dimension}", type="model_output", source="risk360.test")],
        source="risk360.test",
        score=score,
    )


@pytest.mark.asyncio
async def test_persist_assessment_writes_run_assessment_and_signals():
    from services.computation.repositories import ComputedResultsRepository
    from services.risk360.pipeline import persist_assessment
    from services.risk360.store import RiskAssessmentRepository, RiskSignalRepository

    signals = [_persist_signal("behavioral", 0.6), _persist_signal("fraud", 0.5)]
    runs_repo = ComputedResultsRepository()
    assessment_repo = RiskAssessmentRepository()
    signal_repo = RiskSignalRepository()

    res = compute_assessment(
        tenant_id="ten_1",
        subject_kind="entity",
        subject_id="ent_1",
        signals=signals,
    )
    persisted = await persist_assessment(
        res,
        tenant_id="ten_1",
        signals=signals,
        runs_repo=runs_repo,
        assessment_repo=assessment_repo,
        signal_repo=signal_repo,
    )

    # computation_runs row present + linked context hash.
    run_row = await runs_repo.get_run("ten_1", persisted.run.run_id)
    assert run_row is not None
    assert run_row["context_hash"] == persisted.run.context_hash
    assert run_row["definition_id"] == persisted.assessment.policy_id

    # assessment round-trips from the store.
    row = await assessment_repo.get_scoped("ten_1", persisted.assessment.assessment_id)
    assert row is not None
    assert row["subject_id"] == "ent_1"
    assert row["run_id"] == persisted.run.run_id

    # signals landed on risk_signals.
    for signal in signals:
        srow = await signal_repo.get_scoped("ten_1", signal.signal_id)
        assert srow is not None
        assert srow["risk_dimension"] == signal.risk_dimension


@pytest.mark.asyncio
async def test_persist_supersedes_prior_run_on_identical_evidence():
    from services.computation.repositories import ComputedResultsRepository
    from services.risk360.pipeline import persist_assessment
    from services.risk360.store import RiskAssessmentRepository, RiskSignalRepository

    signals = [_persist_signal("behavioral", 0.6), _persist_signal("fraud", 0.5)]
    runs_repo = ComputedResultsRepository()
    assessment_repo = RiskAssessmentRepository()
    signal_repo = RiskSignalRepository()

    first = await persist_assessment(
        compute_assessment(
            tenant_id="ten_1",
            subject_kind="entity",
            subject_id="ent_1",
            signals=signals,
        ),
        tenant_id="ten_1",
        signals=signals,
        runs_repo=runs_repo,
        assessment_repo=assessment_repo,
        signal_repo=signal_repo,
    )

    second = await persist_assessment(
        compute_assessment(
            tenant_id="ten_1",
            subject_kind="entity",
            subject_id="ent_1",
            signals=signals,
        ),
        tenant_id="ten_1",
        signals=signals,
        runs_repo=runs_repo,
        assessment_repo=assessment_repo,
        signal_repo=signal_repo,
    )

    # Determinism: identical evidence → identical assessment id + context hash.
    assert second.assessment.assessment_id == first.assessment.assessment_id
    assert second.run.context_hash == first.run.context_hash
    # But each run is its own substrate row; the later run supersedes the prior.
    assert second.run.run_id != first.run.run_id
    assert second.run.supersedes_run_id == first.run.run_id
    # The assessment row now points at the latest run.
    row = await assessment_repo.get_scoped("ten_1", first.assessment.assessment_id)
    assert row["run_id"] == second.run.run_id
