"""Trust-score regression: absent risk evidence must not read as maximum trust,
and evidence coverage must be disclosed."""

from __future__ import annotations

import pytest

from shared.scoring.trust_score import ABSENT_EVIDENCE_PRIOR, TrustScoreComposite


async def test_zero_evidence_is_not_max_trust():
    scorer = TrustScoreComposite()
    score = await scorer.compute("e1", "human", features={})
    # The prior bug produced transaction_trust = 1.0 from no fraud/anomaly evidence.
    assert score.transaction_trust == pytest.approx(ABSENT_EVIDENCE_PRIOR)
    assert score.transaction_trust < 0.5
    assert score.evidence_coverage["transaction"] == "missing"
    assert score.evidence_coverage["observed_components"] == 0
    assert score.score_kind == "heuristic"  # not a calibrated probability


async def test_present_risk_evidence_is_used():
    scorer = TrustScoreComposite()
    # Low fraud + low anomaly => high transaction trust (evidence present).
    score = await scorer.compute(
        "e2", "human",
        features={"fraud_composite_score": 5.0, "anomaly_score": 0.05,
                  "identity_confidence": 0.9, "bot_score": 0.02},
    )
    assert score.transaction_trust > 0.8
    assert score.evidence_coverage["transaction"] == "complete"
    assert score.evidence_coverage["identity"] == "complete"


async def test_high_fraud_evidence_lowers_trust():
    scorer = TrustScoreComposite()
    score = await scorer.compute(
        "e3", "human", features={"fraud_composite_score": 95.0, "anomaly_score": 0.9},
    )
    assert score.transaction_trust < 0.1
    assert score.evidence_coverage["transaction"] == "complete"
