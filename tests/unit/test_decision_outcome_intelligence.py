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


def test_outcome_ledger_summary_and_groupings_include_value_and_loop_health():
    from services.intelligence.outcome_ledger import OutcomeLedgerAggregator

    recommendations = [
        {
            "recommendation_id": "rec-success",
            "tenant_id": "tenant-1",
            "entity_id": "entity-1",
            "recommendation_type": "retention",
            "expected_value": 100,
            "status": "viewed",
            "computed_at": "2026-05-30T00:00:00+00:00",
        },
        {
            "recommendation_id": "rec-stale",
            "tenant_id": "tenant-1",
            "entity_id": "entity-2",
            "recommendation_type": "retention",
            "expected_value": 80,
            "status": "generated",
            "computed_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "recommendation_id": "rec-failure",
            "tenant_id": "tenant-1",
            "entity_id": "entity-1",
            "recommendation_type": "risk_review",
            "expected_value": 40,
            "status": "decided",
            "computed_at": "2026-05-30T00:00:00+00:00",
        },
    ]
    decisions = [
        {"decision_id": "dec-success", "recommendation_id": "rec-success", "tenant_id": "tenant-1"},
        {"decision_id": "dec-failure", "recommendation_id": "rec-failure", "tenant_id": "tenant-1"},
    ]
    actions = [
        {"action_id": "act-success", "decision_id": "dec-success", "tenant_id": "tenant-1"},
        {"action_id": "act-failure", "decision_id": "dec-failure", "tenant_id": "tenant-1"},
    ]
    outcomes = [
        {"outcome_id": "out-success", "recommendation_id": "rec-success", "entity_id": "entity-1", "tenant_id": "tenant-1", "label": "success", "value": 70},
        {"outcome_id": "out-failure", "recommendation_id": "rec-failure", "entity_id": "entity-1", "tenant_id": "tenant-1", "label": "failure", "value": -10},
    ]
    feedback = [
        {"recommendation_id": "rec-success", "outcome_id": "out-success", "confidence_delta": 0.05, "created_at": "2026-05-31T00:00:00+00:00"},
        {"recommendation_id": "rec-failure", "outcome_id": "out-failure", "confidence_delta": -0.05, "created_at": "2026-05-31T01:00:00+00:00"},
    ]
    playbooks = [{"playbook_id": "pb-1", "name": "Churn save", "tenant_id": "tenant-1"}]
    runs = [{"run_id": "run-1", "playbook_id": "pb-1", "tenant_id": "tenant-1", "recommendation_ids": ["rec-success"], "status": "completed"}]

    ledger = OutcomeLedgerAggregator().build(recommendations, decisions, actions, outcomes, feedback, playbooks, runs)
    summary = ledger["summary"]

    assert summary["recommendations_generated"] == 3
    assert summary["recommendations_viewed"] == 2
    assert summary["decisions_recorded"] == 2
    assert summary["actions_logged"] == 2
    assert summary["outcomes_observed"] == 2
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["neutral_count"] == 0
    assert summary["success_rate"] == 0.5
    assert summary["outcome_capture_rate"] == pytest.approx(0.6667)
    assert summary["expected_value"] == 220
    assert summary["observed_value"] == 60
    assert summary["pending_value"] == 160
    assert summary["stale_loops"] == 1
    assert summary["incomplete_loops"] == 1
    assert summary["failed_loops"] == 1
    assert summary["confidence_delta_total"] == 0

    by_type = {item["key"]: item for item in ledger["by_recommendation_type"]}
    assert by_type["retention"]["expected_value"] == 180
    assert by_type["retention"]["observed_value"] == 70
    assert by_type["risk_review"]["failure_count"] == 1
    assert ledger["by_playbook"][0]["playbook_name"] == "Churn save"
    assert ledger["by_playbook"][0]["observed_value"] == 70
