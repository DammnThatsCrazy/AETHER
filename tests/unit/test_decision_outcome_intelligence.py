from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))


def test_recommendation_scorer_penalizes_risk_and_governance():
    from services.intelligence.scoring import RecommendationScorer, RecommendationScoreInput

    scorer = RecommendationScorer()
    strong = scorer.score(RecommendationScoreInput(
        deterministic_rule_score=0.9,
        ml_probability_score=0.8,
        graph_relevance_score=0.7,
        attribution_confidence=0.7,
        economic_expected_value=500,
    ))
    penalized = scorer.score(RecommendationScoreInput(
        deterministic_rule_score=0.9,
        ml_probability_score=0.8,
        graph_relevance_score=0.7,
        attribution_confidence=0.7,
        economic_expected_value=500,
        risk_penalty=1.0,
        freshness_penalty=1.0,
        governance_policy_penalty=1.0,
    ))
    assert strong.overall > penalized.overall
    assert 0 <= penalized.overall <= 1


def test_recommendation_schema_requires_entity_or_population():
    from services.intelligence.decision_models import CandidateAction, Recommendation, RecommendationConfidence

    confidence = RecommendationConfidence(overall=0.5, deterministic_rule_score=0.5)
    action = CandidateAction(action_key="review", action_type="manual", label="Review", confidence=confidence)
    with pytest.raises(ValueError, match="entity_id or population_id"):
        Recommendation(
            recommendation_id="rec-1",
            tenant_id="tenant-1",
            recommendation_type="retention",
            recommended_action=action,
            candidate_actions=[action],
            confidence=confidence,
            expected_outcome="Improve retention",
            evidence=[],
            computed_at="2026-05-31T00:00:00Z",
            required_approval_level="standard",
        )


def test_ooda_engine_generates_governed_recommendation():
    from services.intelligence.ooda_engine import GraphNativeRecommendationEngine

    rec = GraphNativeRecommendationEngine().generate_for_entity(
        "tenant-1", "entity-1", {"churn_probability": 0.8, "ltv_predicted_usd": 1200, "trust_score": 0.9}
    )
    assert rec.tenant_id == "tenant-1"
    assert rec.entity_id == "entity-1"
    assert rec.candidate_actions
    assert rec.evidence
    assert rec.required_approval_level in {"standard", "elevated", "critical"}
    assert "consent_required" in rec.policy_governance_flags
