"""Governed trust VECTOR: named dimensions with per-dimension evidence coverage,
versioned weights, and multiple use-case composites derived from one vector.

These tests complement ``test_trust_evidence.py`` (the zero-evidence fix) and
must not weaken it: absence is still never read as trust on any dimension.
"""

from __future__ import annotations

import pytest

from shared.scoring.trust_score import (
    WEIGHTS_VERSION,
    TrustScore,
    TrustScoreComposite,
)
from shared.scoring.trust_vector import (
    ABSENT_AUTOMATION_PRIOR,
    ABSENT_RECENCY_PRIOR,
    BASE_COMPOSITE_WEIGHTS,
    INVERTED_DIMENSIONS,
    TRUST_DIMENSIONS,
    TrustVector,
)

_CLEAN_AGENT = {
    "fraud_composite_score": 2.0,
    "anomaly_score": 0.02,
    "identity_confidence": 0.9,
    "bot_score": 0.95,      # clearly automated
    "session_score": 0.9,
    "churn_risk": 0.05,
    "evidence_recency": 0.9,
}


async def test_vector_exposes_all_six_named_dimensions():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e1", "agent", features=_CLEAN_AGENT)

    assert isinstance(score, TrustScore)
    assert isinstance(score.trust_vector, TrustVector)
    dims = score.trust_vector.dimensions()
    assert set(dims) == set(TRUST_DIMENSIONS)
    assert set(TRUST_DIMENSIONS) == {
        "identity_assurance", "transaction_integrity", "behavioral_reliability",
        "automation_likelihood", "source_coverage", "evidence_recency",
    }
    # Every dimension carries its OWN coverage + observation.
    for dim in dims.values():
        assert dim.coverage in {"complete", "partial", "missing"}
        assert 0.0 <= dim.value <= 1.0
        assert isinstance(dim.observed, bool)


async def test_weights_version_is_stamped_on_output():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e2", "human", features=_CLEAN_AGENT)
    assert score.weights_version == WEIGHTS_VERSION
    payload = score.to_dict()
    assert payload["weights_version"] == WEIGHTS_VERSION
    assert payload["trust_vector"]["weights_version"] == WEIGHTS_VERSION


async def test_base_composite_is_derived_from_and_consistent_with_vector():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e3", "human", features=_CLEAN_AGENT)

    # The scalar is a view over the vector, not an independent number.
    assert score.composite == pytest.approx(
        score.trust_vector.composite(BASE_COMPOSITE_WEIGHTS)
    )
    # Backward-compatible: still the legacy 0.40/0.35/0.25 weighting.
    expected = (
        0.40 * score.transaction_trust
        + 0.35 * score.identity_trust
        + 0.25 * score.behavioral_trust
    )
    assert score.composite == pytest.approx(expected)


async def test_use_case_composites_are_distinct_derivations():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e4", "agent", features=_CLEAN_AGENT)

    uc = score.use_case_composites
    assert set(uc) == {"reward_eligibility_trust", "agent_delegation_trust"}
    reward = uc["reward_eligibility_trust"]
    delegation = uc["agent_delegation_trust"]

    # Distinct weightings => distinct policies, not one universal scalar.
    assert reward["weights"] != delegation["weights"]

    # For a clearly-automated but otherwise clean entity, delegation trust
    # (automation expected, not penalized) must exceed reward-eligibility trust
    # (which penalizes automation and leans on identity assurance).
    assert delegation["value"] > reward["value"]

    # Each composite discloses how much of its weight is evidence-backed.
    assert reward["evidence_backed_weight"] == pytest.approx(1.0)
    assert delegation["evidence_backed_weight"] == pytest.approx(1.0)


async def test_automation_is_trust_inverted_only_where_a_composite_says_so():
    # A weight on automation_likelihood contributes (1 - value), and only the
    # reward composite carries that weight; delegation excludes it entirely.
    assert "automation_likelihood" in INVERTED_DIMENSIONS
    assert "automation_likelihood" not in BASE_COMPOSITE_WEIGHTS


async def test_zero_evidence_vector_uses_conservative_priors_not_trust():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e5", "human", features={})

    dims = score.trust_vector.dimensions()
    # Automation from silence is UNKNOWN (neutral prior), never "definitely human".
    assert dims["automation_likelihood"].value == pytest.approx(ABSENT_AUTOMATION_PRIOR)
    assert dims["automation_likelihood"].coverage == "missing"
    assert dims["automation_likelihood"].observed is False
    # Recency from silence is stale (low prior), never fresh.
    assert dims["evidence_recency"].value == pytest.approx(ABSENT_RECENCY_PRIOR)
    assert dims["evidence_recency"].coverage == "missing"
    # No signals => source coverage is zero and disclosed as missing.
    assert dims["source_coverage"].value == pytest.approx(0.0)
    assert dims["source_coverage"].coverage == "missing"
    # The legacy zero-evidence fix is untouched.
    assert dims["transaction_integrity"].coverage == "missing"
    assert score.evidence_coverage["observed_components"] == 0


async def test_source_coverage_tracks_observed_signals():
    scorer = TrustScoreComposite()
    # 3 of 7 signals present: fraud, anomaly, identity_confidence.
    score = await scorer.compute(
        "e6", "human",
        features={"fraud_composite_score": 5.0, "anomaly_score": 0.1,
                  "identity_confidence": 0.8},
    )
    src = score.trust_vector.dimensions()["source_coverage"]
    assert src.value == pytest.approx(3 / 7)
    assert src.coverage == "partial"


async def test_evidence_recency_from_age_days_decays():
    scorer = TrustScoreComposite()
    fresh = await scorer.compute("e7", "human", features={"evidence_age_days": 0})
    half = await scorer.compute("e8", "human", features={"evidence_age_days": 15})
    stale = await scorer.compute("e9", "human", features={"evidence_age_days": 60})

    r = lambda s: s.trust_vector.dimensions()["evidence_recency"].value
    assert r(fresh) == pytest.approx(1.0)
    assert r(half) == pytest.approx(0.5)
    assert r(stale) == pytest.approx(0.0)  # beyond window, clamped
    assert half.trust_vector.dimensions()["evidence_recency"].observed is True


async def test_to_dict_shape_is_additive_and_serializable():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e10", "human", features=_CLEAN_AGENT)
    payload = score.to_dict()

    # Legacy keys preserved.
    for key in ("transaction_trust", "identity_trust", "behavioral_trust",
                "composite", "evidence_coverage", "score_kind"):
        assert key in payload
    # New governed keys added.
    assert set(payload["trust_vector"]["dimensions"]) == set(TRUST_DIMENSIONS)
    assert payload["use_case_composites"].keys() == {
        "reward_eligibility_trust", "agent_delegation_trust"}
    assert payload["trust_vector"]["inverted_dimensions"] == ["automation_likelihood"]
