"""Operational playbook templates, evaluation, and ROI aggregation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from services.intelligence.decision_models import ApprovalLevel, CandidateAction, PlaybookDefinition
from services.intelligence.ooda_engine import GraphNativeRecommendationEngine
from services.intelligence.outcome_ledger import OutcomeLedgerAggregator
from services.intelligence.recommendation_families.base import RecommendationGenerationContext


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlaybookTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    category: str
    trigger_schema: dict[str, Any]
    default_candidate_actions: list[CandidateAction] = Field(default_factory=list)
    default_approval_level: ApprovalLevel = "standard"
    expected_outcome_types: list[str] = Field(default_factory=list)
    recommended_integrations: list[str] = Field(default_factory=list)
    created_at: str


class PlaybookPerformance(BaseModel):
    playbook_id: str
    tenant_id: str
    runs_total: int = 0
    runs_completed: int = 0
    recommendations_generated: int = 0
    decisions_recorded: int = 0
    actions_logged: int = 0
    outcomes_observed: int = 0
    success_count: int = 0
    failure_count: int = 0
    neutral_count: int = 0
    expected_value_total: float = 0.0
    observed_value_total: float = 0.0
    pending_value_total: float = 0.0
    outcome_capture_rate: float = 0.0
    success_rate: float = 0.0
    average_confidence_delta: float = 0.0
    stale_run_count: int = 0
    incomplete_run_count: int = 0


class PlaybookEvaluationResult(BaseModel):
    playbook_id: str
    tenant_id: str
    matched: bool
    trigger_matches: dict[str, bool] = Field(default_factory=dict)
    generated_recommendation_ids: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None
    evaluated_at: str


def _action(key: str, label: str, approval: ApprovalLevel = "standard", integration: str | None = None) -> CandidateAction:
    return CandidateAction(
        action_key=key,
        action_type="playbook_step",
        label=label,
        description=f"Playbook-guided step: {label}.",
        integration=integration,
        expected_outcome="Create a governed recommendation loop that can be measured in the Outcome Ledger.",
        requires_approval_level=approval,
        policy_flags=["human_review_required"] if approval != "none" else ["explanation_required"],
    )


def _trigger(signals: dict[str, dict[str, float]]) -> dict[str, Any]:
    return {"signals": signals, "match": "any"}


TEMPLATE_CREATED_AT = "2026-01-01T00:00:00+00:00"
PLAYBOOK_TEMPLATES: list[PlaybookTemplate] = [
    PlaybookTemplate(
        template_id="high_ltv_churn_save",
        name="High-LTV Churn Save",
        description="Detect high-value entities with churn risk and route a governed save workflow.",
        category="retention",
        trigger_schema=_trigger({"churn_probability": {"gte": 0.55}, "ltv_predicted_usd": {"gte": 100}, "trust_score": {"gte": 0.35}, "engagement_decline": {"gte": 0.2}}),
        default_candidate_actions=[_action("review_retention_offer", "Review retention offer"), _action("route_customer_success", "Route to customer success")],
        default_approval_level="standard",
        expected_outcome_types=["retention_saved", "churn_prevented", "value_recovered"],
        recommended_integrations=["crm", "slack", "ticketing"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="expansion_signal_routing",
        name="Expansion Signal Routing",
        description="Route expansion-ready accounts to sales with evidence and approval context.",
        category="expansion",
        trigger_schema=_trigger({"usage_growth": {"gte": 0.25}, "account_health": {"gte": 0.6}, "relationship_influence_score": {"gte": 0.45}, "ltv_predicted_usd": {"gte": 250}}),
        default_candidate_actions=[_action("route_to_sales", "Route to sales", integration="crm"), _action("recommend_upgrade_path", "Recommend upgrade path")],
        expected_outcome_types=["expansion_review_created", "upgrade_accepted"],
        recommended_integrations=["crm", "slack"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="fraud_cluster_review",
        name="Fraud Cluster Review",
        description="Review suspicious clusters before rewards, campaigns, or automated actions proceed.",
        category="fraud_review",
        trigger_schema=_trigger({"suspicious_cluster_score": {"gte": 0.55}, "anomaly_score": {"gte": 0.6}, "trust_score": {"lte": 0.45}, "shared_wallet_count": {"gte": 2}, "velocity_score": {"gte": 0.55}}),
        default_candidate_actions=[_action("open_fraud_investigation", "Open fraud investigation", "elevated"), _action("step_up_verification", "Step-up verification", "elevated")],
        default_approval_level="elevated",
        expected_outcome_types=["fraud_prevented", "false_positive_cleared"],
        recommended_integrations=["ticketing", "webhook"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="campaign_waste_reduction",
        name="Campaign Waste Reduction",
        description="Find low-ROAS or conflicted attribution paths and route spend reviews.",
        category="attribution_optimization",
        trigger_schema=_trigger({"campaign_spend": {"gte": 1000}, "roas": {"lte": 1.0}, "attribution_confidence": {"lte": 0.55}, "conversion_rate": {"lte": 0.08}, "path_conflict_score": {"gte": 0.5}}),
        default_candidate_actions=[_action("flag_campaign_review", "Flag campaign for review"), _action("export_attribution_report", "Export attribution report", "none")],
        expected_outcome_types=["waste_reduced", "budget_reallocated"],
        recommended_integrations=["marketing_automation", "webhook"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="journey_friction_repair",
        name="Journey Friction Repair",
        description="Turn high-friction journey signals into product or support repair loops.",
        category="journey_optimization",
        trigger_schema=_trigger({"dropoff_rate": {"gte": 0.35}, "friction_score": {"gte": 0.5}, "repeated_failure_event": {"gte": 1}, "conversion_probability": {"lte": 0.5}}),
        default_candidate_actions=[_action("create_product_task", "Create product task", integration="ticketing"), _action("trigger_onboarding_support", "Trigger onboarding support")],
        expected_outcome_types=["dropoff_reduced", "conversion_improved"],
        recommended_integrations=["ticketing", "slack"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="agent_failure_review",
        name="Agent Failure Review",
        description="Escalate failing or expensive agent behavior into human-governed diagnostics.",
        category="agent_governance",
        trigger_schema=_trigger({"agent_failure_rate": {"gte": 0.2}, "tool_error_rate": {"gte": 0.15}, "unauthorized_attempts": {"gte": 1}, "agent_spend_rate": {"gte": 0.5}, "approval_escalation_rate": {"gte": 0.2}}),
        default_candidate_actions=[_action("require_human_approval", "Require human approval", "elevated"), _action("open_kyber_diagnostic", "Open Kyber diagnostic", "standard")],
        default_approval_level="elevated",
        expected_outcome_types=["agent_risk_reduced", "tool_errors_reduced"],
        recommended_integrations=["kyber", "slack"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="reward_eligibility_review",
        name="Reward Eligibility Review",
        description="Balance reward value, eligibility, and fraud risk before issuing rewards.",
        category="rewards_optimization",
        trigger_schema=_trigger({"reward_eligibility_score": {"gte": 0.55}, "fraud_risk_score": {"lte": 0.45}, "referral_value": {"gte": 25}, "campaign_alignment": {"gte": 0.5}, "economic_expected_value": {"gte": 10}}),
        default_candidate_actions=[_action("approve_reward_review", "Approve reward review"), _action("inspect_reward_eligibility", "Inspect reward eligibility", "none")],
        expected_outcome_types=["reward_approved", "reward_deferred", "fraud_prevented"],
        recommended_integrations=["rewards", "webhook"],
        created_at=TEMPLATE_CREATED_AT,
    ),
    PlaybookTemplate(
        template_id="operational_loop_repair",
        name="Operational Loop Repair",
        description="Detect stale or incomplete OODA loops and repair integration/workflow failures.",
        category="operational_failure",
        trigger_schema=_trigger({"stale_loop_count": {"gte": 1}, "missing_outcome_count": {"gte": 1}, "failed_action_count": {"gte": 1}, "integration_error_rate": {"gte": 0.1}, "workflow_latency": {"gte": 3600}}),
        default_candidate_actions=[_action("inspect_integration", "Inspect integration"), _action("create_support_ticket", "Create support ticket", integration="ticketing"), _action("rerun_playbook", "Rerun playbook")],
        expected_outcome_types=["loop_repaired", "outcome_captured", "integration_restored"],
        recommended_integrations=["ticketing", "slack", "webhook"],
        created_at=TEMPLATE_CREATED_AT,
    ),
]


def template_by_id(template_id: str) -> PlaybookTemplate | None:
    return next((template for template in PLAYBOOK_TEMPLATES if template.template_id == template_id), None)


def playbook_from_template(template: PlaybookTemplate, tenant_id: str, overrides: dict[str, Any] | None = None) -> PlaybookDefinition:
    overrides = overrides or {}
    now = now_iso()
    return PlaybookDefinition(
        playbook_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=str(overrides.get("name") or template.name),
        description=str(overrides.get("description") or template.description),
        trigger=str(overrides.get("trigger") or template.trigger_schema),
        recommendation_types=[str(overrides.get("category") or template.category)],
        candidate_actions=overrides.get("candidate_actions") or template.default_candidate_actions,
        approval_level=overrides.get("approval_level") or template.default_approval_level,
        enabled=bool(overrides.get("enabled", True)),
        created_at=now,
        updated_at=now,
    )


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_trigger(playbook: dict[str, Any], signals: dict[str, Any]) -> tuple[bool, dict[str, bool], str | None]:
    trigger = playbook.get("trigger") or {}
    if isinstance(trigger, str):
        try:
            import ast
            trigger = ast.literal_eval(trigger)
        except (SyntaxError, ValueError):
            trigger = {"signals": {}}
    rules = trigger.get("signals", {}) if isinstance(trigger, dict) else {}
    if not rules:
        return True, {}, None
    matches: dict[str, bool] = {}
    for key, rule in rules.items():
        value = _num(signals.get(key))
        ok = True
        if "gte" in rule:
            ok = ok and value >= _num(rule.get("gte"))
        if "lte" in rule:
            ok = ok and value <= _num(rule.get("lte"))
        matches[key] = ok
    mode = trigger.get("match", "any") if isinstance(trigger, dict) else "any"
    matched = all(matches.values()) if mode == "all" else any(matches.values())
    return matched, matches, None if matched else "trigger_conditions_not_met"


def build_playbook_performance(
    playbook: dict[str, Any],
    runs: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
) -> PlaybookPerformance:
    playbook_id = str(playbook.get("playbook_id"))
    tenant_id = str(playbook.get("tenant_id"))
    rec_ids = {str(rec.get("recommendation_id")) for rec in recommendations if rec.get("playbook_id") == playbook_id}
    run_rec_ids = {str(rec_id) for run in runs for rec_id in run.get("generated_recommendation_ids", run.get("recommendation_ids", []))}
    rec_ids |= run_rec_ids
    recs = [rec for rec in recommendations if str(rec.get("recommendation_id")) in rec_ids]
    rec_id_set = {str(rec.get("recommendation_id")) for rec in recs}
    decs = [decision for decision in decisions if str(decision.get("recommendation_id")) in rec_id_set]
    decision_ids = {str(decision.get("decision_id")) for decision in decs}
    acts = [action for action in actions if str(action.get("decision_id")) in decision_ids]
    action_ids = {str(action.get("action_id")) for action in acts}
    outs = [outcome for outcome in outcomes if str(outcome.get("action_id")) in action_ids or str(outcome.get("recommendation_id")) in rec_id_set]
    completed = [run for run in runs if run.get("status") == "completed"]
    success = sum(1 for outcome in outs if outcome.get("label") == "success")
    failure = sum(1 for outcome in outs if outcome.get("label") == "failure")
    neutral = sum(1 for outcome in outs if outcome.get("label") == "neutral")
    expected = sum(_num(rec.get("expected_value")) for rec in recs)
    observed = sum(_num(outcome.get("value")) for outcome in outs)
    deltas = [_num(item.get("confidence_delta")) for item in feedback if str(item.get("recommendation_id")) in rec_id_set]
    stale = OutcomeLedgerAggregator().build(recs, decs, acts, outs, feedback, [playbook], runs)["summary"].get("stale_loops", 0)
    incomplete = sum(1 for run in runs if run.get("status") not in {"completed", "cancelled"} or not run.get("outcome_ids"))
    return PlaybookPerformance(
        playbook_id=playbook_id,
        tenant_id=tenant_id,
        runs_total=len(runs),
        runs_completed=len(completed),
        recommendations_generated=len(recs),
        decisions_recorded=len(decs),
        actions_logged=len(acts),
        outcomes_observed=len(outs),
        success_count=success,
        failure_count=failure,
        neutral_count=neutral,
        expected_value_total=round(expected, 2),
        observed_value_total=round(observed, 2),
        pending_value_total=round(max(expected - observed, 0.0), 2),
        outcome_capture_rate=round(len(outs) / len(recs), 4) if recs else 0.0,
        success_rate=round(success / len(outs), 4) if outs else 0.0,
        average_confidence_delta=round(sum(deltas) / len(deltas), 4) if deltas else 0.0,
        stale_run_count=int(stale),
        incomplete_run_count=incomplete,
    )


def generate_for_playbook(engine: GraphNativeRecommendationEngine, tenant_id: str, playbook: dict[str, Any], signals: dict[str, Any], entity_id: str | None, population_id: str | None) -> list:
    requested = (playbook.get("recommendation_types") or [None])[0]
    enriched = {**signals}
    if requested:
        enriched["recommendation_family"] = requested
    context = RecommendationGenerationContext(
        tenant_id=tenant_id,
        entity_id=entity_id,
        population_id=population_id,
        signals=enriched,
        profile_context=dict(enriched.get("profile_context", {})),
        graph_context=dict(enriched.get("graph_context", {})),
        attribution_context=dict(enriched.get("attribution_context", {})),
        economic_context=dict(enriched.get("economic_context", {})),
        ml_context=dict(enriched.get("ml_context", {})),
        governance_context=dict(enriched.get("governance_context", {})),
        computed_at=now_iso(),
    )
    return engine.registry.generate_recommendations(context)
