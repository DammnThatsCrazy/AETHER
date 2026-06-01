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


def test_recommendation_family_registry_registers_all_families():
    from services.intelligence.recommendation_families.registry import RecommendationFamilyRegistry

    registry = RecommendationFamilyRegistry()
    family_keys = {family.family_key for family in registry.families}
    assert family_keys == {
        "retention",
        "expansion",
        "fraud_review",
        "attribution_optimization",
        "journey_optimization",
        "agent_governance",
        "rewards_optimization",
        "operational_failure",
    }


@pytest.mark.parametrize("signals,family_key,action_key", [
    ({"churn_probability": 0.8, "ltv_predicted_usd": 1000}, "retention", "human_review_retention_offer"),
    ({"usage_growth": 0.9, "ltv_predicted_usd": 1200}, "expansion", "create_expansion_review"),
    ({"anomaly_score": 0.9, "suspicious_cluster_score": 0.8}, "fraud_review", "open_fraud_investigation"),
    ({"path_conflict_score": 0.8, "campaign_spend": 2000}, "attribution_optimization", "inspect_attribution_path"),
    ({"dropoff_rate": 0.8, "friction_score": 0.7}, "journey_optimization", "open_journey_investigation"),
    ({"agent_failure_rate": 0.5, "agent_spend_rate": 300}, "agent_governance", "require_human_approval"),
    ({"reward_eligibility_score": 0.9, "economic_expected_value": 100}, "rewards_optimization", "approve_reward_review"),
    ({"integration_error_rate": 0.5, "incident_cost_avoided_usd": 250}, "operational_failure", "inspect_integration"),
])
def test_each_recommendation_family_detects_scores_actions_and_evidence(signals, family_key, action_key):
    from services.intelligence.recommendation_families.base import RecommendationGenerationContext
    from services.intelligence.recommendation_families.registry import RecommendationFamilyRegistry

    registry = RecommendationFamilyRegistry()
    family = registry.get(family_key)
    assert family is not None
    context = RecommendationGenerationContext(tenant_id="tenant-1", entity_id="entity-1", signals=signals)
    assert family.detect(context)
    confidence = family.score(context)
    assert 0 <= confidence.overall <= 1
    actions = family.generate_candidate_actions(context)
    assert actions[0].action_key == action_key
    assert family.build_evidence(context)
    rec = family.generate(context)
    assert rec.recommendation_type == family_key
    assert rec.candidate_actions
    assert rec.evidence
    assert rec.graph_snapshot_id


def test_registry_suppresses_low_confidence_and_preserves_governance_flags():
    from services.intelligence.recommendation_families.base import RecommendationGenerationContext
    from services.intelligence.recommendation_families.registry import RecommendationFamilyRegistry

    context = RecommendationGenerationContext(
        tenant_id="tenant-1",
        entity_id="entity-1",
        signals={"recommendation_family": "agent_governance", "agent_failure_rate": 0.31, "agent_spend_rate": 1000},
    )
    rec = RecommendationFamilyRegistry(confidence_threshold=0.99).generate_top_recommendation(context)
    assert rec.status == "suppressed"
    assert "below_confidence_threshold" in rec.policy_governance_flags
    assert "human_approval_required" in rec.policy_governance_flags
    assert rec.required_approval_level == "critical"


def test_graph_native_engine_can_generate_multiple_families_and_legacy_top_recommendation():
    from services.intelligence.ooda_engine import GraphNativeRecommendationEngine

    engine = GraphNativeRecommendationEngine()
    legacy = engine.generate_for_entity("tenant-1", "entity-1", {"churn_probability": 0.8, "ltv_predicted_usd": 1000})
    assert legacy.recommendation_type == "retention"
    assert "consent_required" in legacy.policy_governance_flags

    recs = engine.generate_all_for_entity(
        "tenant-1",
        "entity-1",
        {"churn_probability": 0.8, "usage_growth": 0.9, "ltv_predicted_usd": 1000},
    )
    assert {rec.recommendation_type for rec in recs} >= {"retention", "expansion"}


def test_playbook_templates_and_create_from_template_contracts():
    from services.intelligence.playbooks import PLAYBOOK_TEMPLATES, playbook_from_template, template_by_id

    assert len(PLAYBOOK_TEMPLATES) == 8
    categories = {template.category for template in PLAYBOOK_TEMPLATES}
    assert categories >= {"retention", "expansion", "fraud_review", "operational_failure"}
    template = template_by_id("high_ltv_churn_save")
    assert template is not None
    playbook = playbook_from_template(template, "tenant-1")
    assert playbook.tenant_id == "tenant-1"
    assert playbook.recommendation_types == ["retention"]
    assert playbook.candidate_actions
    assert playbook.enabled is True


def test_playbook_trigger_evaluation_match_and_no_match():
    from services.intelligence.playbooks import evaluate_trigger

    playbook = {
        "trigger": {"signals": {"churn_probability": {"gte": 0.55}, "trust_score": {"gte": 0.4}}, "match": "all"}
    }
    matched, matches, skipped = evaluate_trigger(playbook, {"churn_probability": 0.7, "trust_score": 0.8})
    assert matched is True
    assert matches == {"churn_probability": True, "trust_score": True}
    assert skipped is None

    matched, matches, skipped = evaluate_trigger(playbook, {"churn_probability": 0.7, "trust_score": 0.2})
    assert matched is False
    assert matches["trust_score"] is False
    assert skipped == "trigger_conditions_not_met"


def test_playbook_performance_aggregation_detects_value_and_incomplete_runs():
    from services.intelligence.playbooks import build_playbook_performance

    playbook = {"playbook_id": "pb-1", "tenant_id": "tenant-1"}
    runs = [
        {"run_id": "run-1", "playbook_id": "pb-1", "tenant_id": "tenant-1", "status": "completed", "generated_recommendation_ids": ["rec-1"], "outcome_ids": ["out-1"]},
        {"run_id": "run-2", "playbook_id": "pb-1", "tenant_id": "tenant-1", "status": "running", "generated_recommendation_ids": ["rec-2"]},
    ]
    recommendations = [
        {"recommendation_id": "rec-1", "tenant_id": "tenant-1", "playbook_id": "pb-1", "expected_value": 100, "computed_at": "2026-05-01T00:00:00+00:00"},
        {"recommendation_id": "rec-2", "tenant_id": "tenant-1", "playbook_id": "pb-1", "expected_value": 50, "computed_at": "2026-01-01T00:00:00+00:00"},
    ]
    decisions = [{"decision_id": "dec-1", "recommendation_id": "rec-1", "tenant_id": "tenant-1"}]
    actions = [{"action_id": "act-1", "decision_id": "dec-1", "tenant_id": "tenant-1"}]
    outcomes = [{"outcome_id": "out-1", "action_id": "act-1", "recommendation_id": "rec-1", "tenant_id": "tenant-1", "label": "success", "value": 75}]
    feedback = [{"recommendation_id": "rec-1", "tenant_id": "tenant-1", "confidence_delta": 0.05}]

    performance = build_playbook_performance(playbook, runs, recommendations, decisions, actions, outcomes, feedback)
    assert performance.runs_total == 2
    assert performance.runs_completed == 1
    assert performance.recommendations_generated == 2
    assert performance.observed_value_total == 75
    assert performance.pending_value_total == 75
    assert performance.success_rate == 1
    assert performance.outcome_capture_rate == 0.5
    assert performance.average_confidence_delta == 0.05
    assert performance.incomplete_run_count == 1
    assert performance.stale_run_count >= 1
