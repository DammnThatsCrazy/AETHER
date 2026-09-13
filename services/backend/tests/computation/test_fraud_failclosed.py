"""Fraud regression: an evaluation FAILURE must fail closed (route to review),
never silently become a benign/cleared outcome."""

from __future__ import annotations

from services.fraud.evaluation import FraudEvaluationService


def test_failed_evaluation_fails_closed_not_benign():
    svc = FraudEvaluationService()
    decision = svc._failed_decision("t1", "wallet", "w1")
    # The prior bug returned decision="monitor", risk_tier="low" (reads as clear).
    assert decision.decision == "review"
    assert decision.risk_tier != "low"
    assert decision.review_state == "required"
    assert decision.evaluation_state == "failed"
    assert "not cleared" in decision.machine_explanation.lower()
