from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))


def test_recommendation_scorer_penalizes_risk_and_governance():
    from services.intelligence.scoring import RecommendationScoreInput, RecommendationScorer

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
    from services.intelligence.decision_models import (
        CandidateAction,
        Recommendation,
        RecommendationConfidence,
    )

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


def test_decision_outcome_feature_flags_default_to_gradual_rollout_disabled(monkeypatch):
    for key in (
        "AETHER_RECOMMENDATIONS_ENABLED",
        "AETHER_DECISION_RECORDS_ENABLED",
        "AETHER_OUTCOME_FEEDBACK_ENABLED",
        "AETHER_PLAYBOOKS_ENABLED",
        "KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    from config.settings import DecisionOutcomeIntelligenceConfig

    cfg = DecisionOutcomeIntelligenceConfig()
    assert cfg.recommendations_enabled is False
    assert cfg.decision_records_enabled is False
    assert cfg.outcome_feedback_enabled is False
    assert cfg.playbooks_enabled is False
    assert cfg.kyber_observability_enabled is False


def test_recommendation_family_registry_selects_non_retention_family():
    from services.intelligence.recommendation_families import RecommendationFamilyRegistry

    registry = RecommendationFamilyRegistry()
    family = registry.detect({"fraud_probability": 0.91, "expected_value_usd": 750})
    assert family.family_key == "fraud_review"
    rec = family.emit("tenant-1", "entity-1", {"fraud_probability": 0.91, "expected_value_usd": 750})
    assert rec.recommendation_type == "fraud_review"
    assert rec.required_approval_level in {"elevated", "critical"}
    assert rec.evidence


@pytest.mark.parametrize("signal,family_key", [
    ({"churn_probability": 0.8}, "retention"),
    ({"expansion_probability": 0.8}, "expansion"),
    ({"fraud_probability": 0.8}, "fraud_review"),
    ({"attribution_waste_probability": 0.8}, "attribution_optimization"),
    ({"journey_dropoff_probability": 0.8}, "journey_optimization"),
    ({"agent_risk_probability": 0.8}, "agent_governance"),
    ({"reward_optimization_probability": 0.8}, "rewards_optimization"),
    ({"operational_failure_probability": 0.8}, "operational_failure"),
])
def test_each_recommendation_family_generates_evidence_and_actions(signal, family_key):
    from services.intelligence.recommendation_families import RecommendationFamilyRegistry

    family = RecommendationFamilyRegistry().get(family_key)
    assert family is not None
    rec = family.emit("tenant-1", "entity-1", {**signal, "expected_value_usd": 100})
    assert rec.recommendation_type == family_key
    assert rec.candidate_actions
    assert rec.evidence
    assert rec.expected_outcome


def test_outcome_ledger_detects_stale_incomplete_and_failed_loops():
    from services.intelligence.outcome_ledger import OutcomeLedgerAggregator

    recs = [
        {"recommendation_id": "rec-old", "tenant_id": "tenant-1", "entity_id": "entity-1", "recommendation_type": "retention", "expected_value": 100, "computed_at": "2026-01-01T00:00:00+00:00", "status": "generated"},
        {"recommendation_id": "rec-fail", "tenant_id": "tenant-1", "entity_id": "entity-2", "recommendation_type": "fraud_review", "expected_value": 50, "computed_at": "2026-05-01T00:00:00+00:00", "status": "viewed"},
    ]
    outcomes = [{"outcome_id": "out-1", "recommendation_id": "rec-fail", "tenant_id": "tenant-1", "label": "failure", "value": -10}]
    ledger = OutcomeLedgerAggregator().build(recs, [], [], outcomes)
    assert ledger["summary"]["stale_loops"] == 1
    assert ledger["summary"]["incomplete_loops"] == 2
    assert ledger["summary"]["failed_loops"] == 1
    assert ledger["summary"]["observed_value"] == -10
