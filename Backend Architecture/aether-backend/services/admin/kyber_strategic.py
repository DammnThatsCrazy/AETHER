"""Kyber strategic observability and revenue intelligence aggregation.

All outputs are internal operator diagnostics. The service aggregates tenant-level
account health and cross-tenant product signals without returning raw tenant
private graph/evidence/event payloads.
"""
from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.intelligence.playbooks import PLAYBOOK_TEMPLATES, build_playbook_performance

Window = Literal["7d", "30d", "90d", "lifetime"]
OpportunityType = Literal[
    "usage_expansion",
    "module_expansion",
    "integration_expansion",
    "services_expansion",
    "enterprise_expansion",
    "government_solution",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _record_time(record: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "computed_at", "started_at", "updated_at"):
        parsed = _parse_time(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _within_window(record: dict[str, Any], window: Window) -> bool:
    if window == "lifetime":
        return True
    timestamp = _record_time(record)
    if timestamp is None:
        return True
    days = int(window[:-1])
    return timestamp >= datetime.now(timezone.utc) - timedelta(days=days)


def _rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 4) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(float(ordered[index]), 4)


def _tenant_id(record: dict[str, Any]) -> str:
    return str(record.get("tenant_id") or "unknown")


class KyberStrategicOverview(BaseModel):
    total_tenants: int
    ooda_enabled_tenants: int
    active_ooda_tenants: int
    recommendations_generated: int
    decisions_recorded: int
    actions_logged: int
    outcomes_observed: int
    outcome_capture_rate: float
    observed_value_total: float
    expected_value_total: float
    pending_value_total: float
    top_recommendation_family: str | None = None
    top_playbook_template: str | None = None
    tenants_ready_for_expansion: int
    tenants_at_risk: int
    model_confidence_health: str
    generated_at: str


class TenantValueHealth(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    plan_tier: str | None = None
    ooda_enabled: bool
    recommendations_generated: int
    recommendations_viewed: int
    decisions_recorded: int
    actions_logged: int
    outcomes_observed: int
    decision_rate: float
    action_rate: float
    outcome_capture_rate: float
    expected_value: float
    observed_value: float
    pending_value: float
    stale_loop_count: int
    incomplete_loop_count: int
    success_rate: float
    average_confidence_delta: float
    tenant_health_score: float
    expansion_score: float
    churn_risk_score: float
    recommended_olympus_action: str


class RecommendationFamilyPerformance(BaseModel):
    recommendation_family: str
    generated: int
    viewed: int
    approved: int
    rejected: int
    deferred: int
    escalated: int
    acted: int
    outcomes_observed: int
    success_count: int
    failure_count: int
    neutral_count: int
    success_rate: float
    outcome_capture_rate: float
    observed_value: float
    expected_value: float
    average_confidence_delta: float
    suppression_rate: float
    recommended_commercialization_status: str


class KyberPlaybookPerformance(BaseModel):
    template_id: str | None = None
    template_name: str | None = None
    category: str
    tenant_adoption_count: int
    runs_total: int
    runs_completed: int
    recommendations_generated: int
    decisions_recorded: int
    actions_logged: int
    outcomes_observed: int
    success_rate: float
    outcome_capture_rate: float
    observed_value: float
    pending_value: float
    stale_run_count: int
    incomplete_run_count: int
    recommended_packaging: str


class ModelConfidenceDriftReport(BaseModel):
    window: Window
    confidence_average: float
    confidence_median: float
    confidence_p10: float
    confidence_p90: float
    average_confidence_delta: float
    freshness_penalty_average: float
    governance_penalty_average: float
    risk_penalty_average: float
    suppression_rate: float
    low_confidence_rate: float
    drift_status: str
    recommended_operator_action: str


class VerticalSolutionSignal(BaseModel):
    solution_key: str
    label: str
    evidence: list[str] = Field(default_factory=list)
    tenant_count: int
    recommendation_families: list[str] = Field(default_factory=list)
    playbook_templates: list[str] = Field(default_factory=list)
    observed_value: float
    adoption_rate: float
    commercial_priority: str
    recommended_next_product_action: str


class RevenueOpportunity(BaseModel):
    opportunity_id: str
    tenant_id: str
    opportunity_type: OpportunityType
    reason: str
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    estimated_value: float
    confidence: float
    recommended_action: str
    created_at: str


class KyberStrategicObservability:
    def __init__(self, tenants: list[dict[str, Any]], recommendations: list[dict[str, Any]], decisions: list[dict[str, Any]], actions: list[dict[str, Any]], outcomes: list[dict[str, Any]], feedback: list[dict[str, Any]], playbooks: list[dict[str, Any]], runs: list[dict[str, Any]], window: Window = "30d") -> None:
        self.window = window
        self.tenants = tenants
        self.recommendations = [item for item in recommendations if _within_window(item, window)]
        self.decisions = [item for item in decisions if _within_window(item, window)]
        self.actions = [item for item in actions if _within_window(item, window)]
        self.outcomes = [item for item in outcomes if _within_window(item, window)]
        self.feedback = [item for item in feedback if _within_window(item, window)]
        self.playbooks = [item for item in playbooks if _within_window(item, window)]
        self.runs = [item for item in runs if _within_window(item, window)]
        self.generated_at = now_iso()

    def response(self, data: Any) -> dict[str, Any]:
        return {
            "window": self.window,
            "generated_at": self.generated_at,
            "data_freshness": self.data_freshness(),
            **data,
        }

    def data_freshness(self) -> dict[str, Any]:
        timestamps = [_record_time(item) for collection in (self.recommendations, self.decisions, self.actions, self.outcomes, self.feedback, self.runs) for item in collection]
        timestamps = [item for item in timestamps if item is not None]
        newest = max(timestamps).isoformat() if timestamps else None
        return {"status": "fresh" if timestamps else "empty", "newest_record_at": newest, "record_count": sum(len(c) for c in (self.recommendations, self.decisions, self.actions, self.outcomes, self.feedback, self.runs))}

    def tenant_ids(self) -> set[str]:
        ids = {str(item.get("id") or item.get("tenant_id")) for item in self.tenants if item.get("id") or item.get("tenant_id")}
        ids |= {_tenant_id(item) for collection in (self.recommendations, self.decisions, self.actions, self.outcomes, self.playbooks, self.runs) for item in collection}
        ids.discard("unknown")
        return ids

    def tenant_meta(self, tenant_id: str) -> dict[str, Any]:
        return next((tenant for tenant in self.tenants if tenant.get("id") == tenant_id or tenant.get("tenant_id") == tenant_id), {})

    def tenant_health(self) -> list[TenantValueHealth]:
        return [self._tenant_health(tenant_id) for tenant_id in sorted(self.tenant_ids())]

    def _tenant_health(self, tenant_id: str) -> TenantValueHealth:
        recs = [r for r in self.recommendations if _tenant_id(r) == tenant_id]
        decs = [d for d in self.decisions if _tenant_id(d) == tenant_id]
        acts = [a for a in self.actions if _tenant_id(a) == tenant_id]
        outs = [o for o in self.outcomes if _tenant_id(o) == tenant_id]
        fb = [f for f in self.feedback if _tenant_id(f) == tenant_id]
        pbs = [p for p in self.playbooks if _tenant_id(p) == tenant_id]
        viewed = sum(1 for r in recs if r.get("status") in {"viewed", "decided"})
        expected = round(sum(_num(r.get("expected_value")) for r in recs), 2)
        observed = round(sum(_num(o.get("value")) for o in outs), 2)
        pending = round(max(expected - observed, 0.0), 2)
        stale = self._stale_recommendations(recs, decs, outs)
        incomplete = max(len(recs) - len(outs), 0)
        success = sum(1 for o in outs if o.get("label") == "success")
        success_rate = _rate(success, len(outs))
        avg_delta = _mean([_num(f.get("confidence_delta")) for f in fb])
        decision_rate = _rate(len(decs), len(recs))
        action_rate = _rate(len(acts), len(decs))
        capture_rate = _rate(len(outs), len(recs))
        tenant_health_score = score_tenant_health(_rate(viewed, len(recs)), decision_rate, action_rate, capture_rate, success_rate, len(stale), incomplete, avg_delta)
        expansion_score = score_expansion(observed, capture_rate, len(pbs), len({r.get("recommendation_type") for r in recs}), 0, avg_delta)
        churn_risk_score = score_churn_risk(_rate(viewed, len(recs)), decision_rate, capture_rate, len(stale), incomplete, avg_delta, len(pbs))
        meta = self.tenant_meta(tenant_id)
        return TenantValueHealth(
            tenant_id=tenant_id,
            tenant_name=meta.get("name"),
            plan_tier=meta.get("plan") or meta.get("plan_tier"),
            ooda_enabled=bool(recs or decs or acts or outs),
            recommendations_generated=len(recs),
            recommendations_viewed=viewed,
            decisions_recorded=len(decs),
            actions_logged=len(acts),
            outcomes_observed=len(outs),
            decision_rate=decision_rate,
            action_rate=action_rate,
            outcome_capture_rate=capture_rate,
            expected_value=expected,
            observed_value=observed,
            pending_value=pending,
            stale_loop_count=len(stale),
            incomplete_loop_count=incomplete,
            success_rate=success_rate,
            average_confidence_delta=avg_delta,
            tenant_health_score=tenant_health_score,
            expansion_score=expansion_score,
            churn_risk_score=churn_risk_score,
            recommended_olympus_action=recommended_olympus_action(tenant_health_score, expansion_score, churn_risk_score),
        )

    def _stale_recommendations(self, recs: list[dict[str, Any]], decs: list[dict[str, Any]], outs: list[dict[str, Any]]) -> list[str]:
        decided = {str(d.get("recommendation_id")) for d in decs}
        observed = {str(o.get("recommendation_id")) for o in outs}
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        stale: list[str] = []
        for rec in recs:
            rec_id = str(rec.get("recommendation_id"))
            timestamp = _record_time(rec)
            if timestamp and timestamp < cutoff and (rec_id not in decided or rec_id not in observed):
                stale.append(rec_id)
        return stale

    def strategic_overview(self) -> KyberStrategicOverview:
        tenants = self.tenant_health()
        family_counts = Counter(str(r.get("recommendation_type") or "unknown") for r in self.recommendations)
        playbook_counts = Counter(str(p.get("template_id") or p.get("category") or "custom") for p in self.playbooks)
        drift = self.model_confidence_drift()
        expected = round(sum(_num(r.get("expected_value")) for r in self.recommendations), 2)
        observed = round(sum(_num(o.get("value")) for o in self.outcomes), 2)
        return KyberStrategicOverview(
            total_tenants=len(self.tenant_ids()),
            ooda_enabled_tenants=sum(1 for t in tenants if t.ooda_enabled),
            active_ooda_tenants=sum(1 for t in tenants if t.recommendations_generated or t.outcomes_observed),
            recommendations_generated=len(self.recommendations),
            decisions_recorded=len(self.decisions),
            actions_logged=len(self.actions),
            outcomes_observed=len(self.outcomes),
            outcome_capture_rate=_rate(len(self.outcomes), len(self.recommendations)),
            observed_value_total=observed,
            expected_value_total=expected,
            pending_value_total=round(max(expected - observed, 0.0), 2),
            top_recommendation_family=family_counts.most_common(1)[0][0] if family_counts else None,
            top_playbook_template=playbook_counts.most_common(1)[0][0] if playbook_counts else None,
            tenants_ready_for_expansion=sum(1 for t in tenants if t.expansion_score >= 0.7),
            tenants_at_risk=sum(1 for t in tenants if t.churn_risk_score >= 0.6),
            model_confidence_health=drift.drift_status,
            generated_at=self.generated_at,
        )

    def family_performance(self) -> list[RecommendationFamilyPerformance]:
        decisions_by_rec = defaultdict(list)
        for decision in self.decisions:
            decisions_by_rec[str(decision.get("recommendation_id"))].append(decision)
        actions_by_decision = defaultdict(list)
        for action in self.actions:
            actions_by_decision[str(action.get("decision_id"))].append(action)
        outcomes_by_rec = defaultdict(list)
        for outcome in self.outcomes:
            outcomes_by_rec[str(outcome.get("recommendation_id"))].append(outcome)
        feedback_by_rec = defaultdict(list)
        for item in self.feedback:
            feedback_by_rec[str(item.get("recommendation_id"))].append(item)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rec in self.recommendations:
            groups[str(rec.get("recommendation_type") or "unknown")].append(rec)
        performances: list[RecommendationFamilyPerformance] = []
        for family, recs in groups.items():
            rec_ids = {str(rec.get("recommendation_id")) for rec in recs}
            family_decisions = [decision for rec_id in rec_ids for decision in decisions_by_rec.get(rec_id, [])]
            decision_ids = {str(decision.get("decision_id")) for decision in family_decisions}
            family_actions = [action for decision_id in decision_ids for action in actions_by_decision.get(decision_id, [])]
            family_outcomes = [outcome for rec_id in rec_ids for outcome in outcomes_by_rec.get(rec_id, [])]
            deltas = [_num(item.get("confidence_delta")) for rec_id in rec_ids for item in feedback_by_rec.get(rec_id, [])]
            statuses = Counter(str(decision.get("decision_status")) for decision in family_decisions)
            success = sum(1 for item in family_outcomes if item.get("label") == "success")
            failure = sum(1 for item in family_outcomes if item.get("label") == "failure")
            neutral = sum(1 for item in family_outcomes if item.get("label") == "neutral")
            suppression_rate = _rate(sum(1 for rec in recs if rec.get("status") == "suppressed"), len(recs))
            performances.append(RecommendationFamilyPerformance(
                recommendation_family=family,
                generated=len(recs),
                viewed=sum(1 for rec in recs if rec.get("status") in {"viewed", "decided"}),
                approved=statuses.get("approved", 0),
                rejected=statuses.get("rejected", 0),
                deferred=statuses.get("deferred", 0),
                escalated=statuses.get("escalated", 0),
                acted=len(family_actions),
                outcomes_observed=len(family_outcomes),
                success_count=success,
                failure_count=failure,
                neutral_count=neutral,
                success_rate=_rate(success, len(family_outcomes)),
                outcome_capture_rate=_rate(len(family_outcomes), len(recs)),
                observed_value=round(sum(_num(item.get("value")) for item in family_outcomes), 2),
                expected_value=round(sum(_num(item.get("expected_value")) for item in recs), 2),
                average_confidence_delta=_mean(deltas),
                suppression_rate=suppression_rate,
                recommended_commercialization_status=commercialization_status(len(recs), _rate(success, len(family_outcomes)), _rate(len(family_outcomes), len(recs)), suppression_rate),
            ))
        return sorted(performances, key=lambda item: (item.observed_value, item.generated), reverse=True)

    def playbook_performance(self) -> list[KyberPlaybookPerformance]:
        templates = {template.template_id: template for template in PLAYBOOK_TEMPLATES}
        category_to_template = {template.category: template for template in PLAYBOOK_TEMPLATES}
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for playbook in self.playbooks:
            template_key = str(playbook.get("template_id") or playbook.get("category") or (playbook.get("recommendation_types") or ["custom"])[0])
            groups[template_key].append(playbook)
        rows: list[KyberPlaybookPerformance] = []
        for key, playbooks in groups.items():
            template = templates.get(key) or category_to_template.get(key)
            category = template.category if template else key
            aggregate = Counter()
            observed = pending = 0.0
            tenant_ids: set[str] = set()
            for playbook in playbooks:
                tenant_ids.add(_tenant_id(playbook))
                runs = [run for run in self.runs if run.get("playbook_id") == playbook.get("playbook_id") and _tenant_id(run) == _tenant_id(playbook)]
                perf = build_playbook_performance(playbook, runs, self.recommendations, self.decisions, self.actions, self.outcomes, self.feedback)
                aggregate.update({
                    "runs_total": perf.runs_total,
                    "runs_completed": perf.runs_completed,
                    "recommendations_generated": perf.recommendations_generated,
                    "decisions_recorded": perf.decisions_recorded,
                    "actions_logged": perf.actions_logged,
                    "outcomes_observed": perf.outcomes_observed,
                    "success_count": perf.success_count,
                    "stale_run_count": perf.stale_run_count,
                    "incomplete_run_count": perf.incomplete_run_count,
                })
                observed += perf.observed_value_total
                pending += perf.pending_value_total
            rows.append(KyberPlaybookPerformance(
                template_id=template.template_id if template else key,
                template_name=template.name if template else str(playbooks[0].get("name") or key),
                category=category,
                tenant_adoption_count=len(tenant_ids),
                runs_total=aggregate["runs_total"],
                runs_completed=aggregate["runs_completed"],
                recommendations_generated=aggregate["recommendations_generated"],
                decisions_recorded=aggregate["decisions_recorded"],
                actions_logged=aggregate["actions_logged"],
                outcomes_observed=aggregate["outcomes_observed"],
                success_rate=_rate(aggregate["success_count"], aggregate["outcomes_observed"]),
                outcome_capture_rate=_rate(aggregate["outcomes_observed"], aggregate["recommendations_generated"]),
                observed_value=round(observed, 2),
                pending_value=round(pending, 2),
                stale_run_count=aggregate["stale_run_count"],
                incomplete_run_count=aggregate["incomplete_run_count"],
                recommended_packaging=recommended_packaging(category, len(tenant_ids), observed, aggregate["runs_total"]),
            ))
        return sorted(rows, key=lambda item: (item.observed_value, item.tenant_adoption_count), reverse=True)

    def model_confidence_drift(self) -> ModelConfidenceDriftReport:
        confidences = [_num((rec.get("confidence") or {}).get("overall")) for rec in self.recommendations]
        freshness = [_num((rec.get("confidence") or {}).get("freshness_penalty")) for rec in self.recommendations]
        governance = [_num((rec.get("confidence") or {}).get("governance_policy_penalty")) for rec in self.recommendations]
        risk = [_num((rec.get("confidence") or {}).get("risk_penalty")) for rec in self.recommendations]
        deltas = [_num(item.get("confidence_delta")) for item in self.feedback]
        suppression_rate = _rate(sum(1 for rec in self.recommendations if rec.get("status") == "suppressed"), len(self.recommendations))
        low_confidence_rate = _rate(sum(1 for value in confidences if value < 0.45), len(confidences))
        status = drift_status(_mean(confidences), _mean(deltas), suppression_rate, low_confidence_rate)
        return ModelConfidenceDriftReport(
            window=self.window,
            confidence_average=_mean(confidences),
            confidence_median=_median(confidences),
            confidence_p10=_percentile(confidences, 0.10),
            confidence_p90=_percentile(confidences, 0.90),
            average_confidence_delta=_mean(deltas),
            freshness_penalty_average=_mean(freshness),
            governance_penalty_average=_mean(governance),
            risk_penalty_average=_mean(risk),
            suppression_rate=suppression_rate,
            low_confidence_rate=low_confidence_rate,
            drift_status=status,
            recommended_operator_action=operator_action_for_drift(status),
        )

    def vertical_solution_signals(self) -> list[VerticalSolutionSignal]:
        family_rows = {row.recommendation_family: row for row in self.family_performance()}
        playbook_rows = self.playbook_performance()
        total_tenants = max(len(self.tenant_ids()), 1)
        solution_map = {
            "fraud_risk": ("Fraud & Risk Intelligence", ["fraud_review", "rewards_optimization"], ["fraud_cluster_review", "reward_eligibility_review"]),
            "agent_governance": ("Enterprise Agent Governance", ["agent_governance"], ["agent_failure_review"]),
            "growth_revenue": ("Revenue Growth Intelligence", ["retention", "expansion", "attribution_optimization"], ["high_ltv_churn_save", "expansion_signal_routing", "campaign_waste_reduction"]),
            "operational_reliability": ("Operational Reliability", ["operational_failure", "journey_optimization"], ["operational_loop_repair", "journey_friction_repair"]),
        }
        signals: list[VerticalSolutionSignal] = []
        for key, (label, families, templates) in solution_map.items():
            tenant_ids: set[str] = set()
            observed = 0.0
            evidence: list[str] = []
            for rec in self.recommendations:
                if rec.get("recommendation_type") in families:
                    tenant_ids.add(_tenant_id(rec))
            for family in families:
                row = family_rows.get(family)
                if row:
                    observed += row.observed_value
                    evidence.append(f"{family}: {row.generated} generated, {row.success_rate:.0%} success")
            for playbook in self.playbooks:
                if playbook.get("template_id") in templates or playbook.get("category") in families:
                    tenant_ids.add(_tenant_id(playbook))
            priority = vertical_priority(len(tenant_ids), observed, _rate(len(tenant_ids), total_tenants))
            signals.append(VerticalSolutionSignal(
                solution_key=key,
                label=label,
                evidence=evidence[:4],
                tenant_count=len(tenant_ids),
                recommendation_families=families,
                playbook_templates=templates,
                observed_value=round(observed, 2),
                adoption_rate=_rate(len(tenant_ids), total_tenants),
                commercial_priority=priority,
                recommended_next_product_action=next_product_action(priority, label),
            ))
        return sorted(signals, key=lambda item: (item.commercial_priority == "strategic", item.observed_value, item.tenant_count), reverse=True)

    def revenue_opportunities(self) -> list[RevenueOpportunity]:
        opportunities: list[RevenueOpportunity] = []
        for health in self.tenant_health():
            if health.expansion_score >= 0.4:
                opportunities.append(RevenueOpportunity(
                    opportunity_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{health.tenant_id}:enterprise:{self.window}")),
                    tenant_id=health.tenant_id,
                    opportunity_type="enterprise_expansion",
                    reason="Tenant is capturing measurable value and has strong OODA adoption.",
                    supporting_metrics=health.model_dump(include={"observed_value", "outcome_capture_rate", "expansion_score", "success_rate"}),
                    estimated_value=round(max(health.observed_value * 0.25, 2500), 2),
                    confidence=min(0.95, max(0.55, health.expansion_score)),
                    recommended_action="Schedule Decision Intelligence Pro / enterprise expansion review.",
                    created_at=self.generated_at,
                ))
            if health.churn_risk_score >= 0.6:
                opportunities.append(RevenueOpportunity(
                    opportunity_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{health.tenant_id}:services:{self.window}")),
                    tenant_id=health.tenant_id,
                    opportunity_type="services_expansion",
                    reason="Tenant has stale or incomplete OODA loops that may need implementation support.",
                    supporting_metrics=health.model_dump(include={"stale_loop_count", "incomplete_loop_count", "outcome_capture_rate", "churn_risk_score"}),
                    estimated_value=round(max(health.pending_value * 0.15, 1000), 2),
                    confidence=min(0.9, max(0.5, health.churn_risk_score)),
                    recommended_action="Offer implementation review to repair incomplete loops and capture outcomes.",
                    created_at=self.generated_at,
                ))
        for signal in self.vertical_solution_signals():
            if signal.commercial_priority in {"high", "strategic"}:
                opportunities.append(RevenueOpportunity(
                    opportunity_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"solution:{signal.solution_key}:{self.window}")),
                    tenant_id="aggregate",
                    opportunity_type="government_solution" if "Fraud" in signal.label or "Governance" in signal.label else "module_expansion",
                    reason=f"{signal.label} is emerging across tenants from aggregate recommendation/playbook evidence.",
                    supporting_metrics=signal.model_dump(include={"tenant_count", "observed_value", "adoption_rate", "commercial_priority"}),
                    estimated_value=round(max(signal.observed_value * 0.3, 5000), 2),
                    confidence={"high": 0.72, "strategic": 0.86}.get(signal.commercial_priority, 0.6),
                    recommended_action=signal.recommended_next_product_action,
                    created_at=self.generated_at,
                ))
        return sorted(opportunities, key=lambda item: (item.confidence, item.estimated_value), reverse=True)


def score_tenant_health(view_rate: float, decision_rate: float, action_rate: float, capture_rate: float, success_rate: float, stale_count: int, incomplete_count: int, avg_delta: float) -> float:
    score = 0.18 * view_rate + 0.20 * decision_rate + 0.16 * action_rate + 0.22 * capture_rate + 0.16 * success_rate + 0.08 * max(0.0, min(1.0, 0.5 + avg_delta))
    penalty = min(0.35, stale_count * 0.03 + incomplete_count * 0.02)
    return round(max(0.0, min(1.0, score - penalty)), 4)


def score_expansion(observed_value: float, capture_rate: float, playbook_usage: int, family_depth: int, integration_usage: int, avg_delta: float) -> float:
    value_score = min(1.0, observed_value / 5000)
    breadth = min(1.0, (playbook_usage * 0.18) + (family_depth * 0.12) + (integration_usage * 0.08))
    delta_score = max(0.0, min(1.0, 0.5 + avg_delta * 4))
    return round(max(0.0, min(1.0, 0.38 * value_score + 0.24 * capture_rate + 0.24 * breadth + 0.14 * delta_score)), 4)


def score_churn_risk(view_rate: float, decision_rate: float, capture_rate: float, stale_count: int, incomplete_count: int, avg_delta: float, playbook_usage: int) -> float:
    low_engagement = (1 - view_rate) * 0.22 + (1 - decision_rate) * 0.20 + (1 - capture_rate) * 0.22
    loop_risk = min(0.28, stale_count * 0.04 + incomplete_count * 0.03)
    confidence_risk = 0.18 if avg_delta < 0 else 0.0
    playbook_risk = 0.10 if playbook_usage == 0 else 0.0
    return round(max(0.0, min(1.0, low_engagement + loop_risk + confidence_risk + playbook_risk)), 4)


def recommended_olympus_action(health: float, expansion: float, churn: float) -> str:
    if expansion >= 0.7:
        return "Prioritize expansion conversation and Decision Intelligence Pro positioning."
    if churn >= 0.6:
        return "Schedule customer success intervention for stale loops and outcome capture."
    if health < 0.35:
        return "Review implementation health and activation blockers."
    return "Monitor value realization and collect ROI proof points."


def commercialization_status(generated: int, success_rate: float, capture_rate: float, suppression_rate: float) -> str:
    if generated == 0:
        return "experimental"
    if suppression_rate >= 0.35 or capture_rate < 0.15:
        return "needs_tuning"
    if generated >= 20 and success_rate >= 0.65 and capture_rate >= 0.5:
        return "premium_module_candidate"
    if generated >= 8 and success_rate >= 0.55:
        return "package_candidate"
    if success_rate >= 0.45 or capture_rate >= 0.35:
        return "promising"
    return "experimental"


def recommended_packaging(category: str, tenant_count: int, observed_value: float, runs_total: int) -> str:
    if tenant_count >= 3 and observed_value >= 5000:
        return f"Package {category.replace('_', ' ')} as premium module collateral."
    if runs_total >= 5 or observed_value > 0:
        return f"Keep {category.replace('_', ' ')} in managed rollout and collect ROI proof."
    return "Keep as internal template until adoption and outcomes increase."


def drift_status(confidence_avg: float, avg_delta: float, suppression_rate: float, low_confidence_rate: float) -> str:
    if suppression_rate >= 0.35 or low_confidence_rate >= 0.35 or avg_delta <= -0.03:
        return "drifting"
    if confidence_avg < 0.5 or avg_delta < 0:
        return "watch"
    return "healthy"


def operator_action_for_drift(status: str) -> str:
    if status == "drifting":
        return "Review scoring weights, weak evidence patterns, and confidence threshold impacts."
    if status == "watch":
        return "Monitor confidence deltas and inspect low-confidence families."
    return "No immediate model action; continue monitoring."


def vertical_priority(tenant_count: int, observed_value: float, adoption_rate: float) -> str:
    if tenant_count >= 5 and observed_value >= 10000 and adoption_rate >= 0.4:
        return "strategic"
    if tenant_count >= 3 or observed_value >= 5000:
        return "high"
    if tenant_count >= 1 or observed_value > 0:
        return "medium"
    return "low"


def next_product_action(priority: str, label: str) -> str:
    if priority == "strategic":
        return f"Create executive roadmap and sales package for {label}."
    if priority == "high":
        return f"Draft vertical packaging and customer proof points for {label}."
    if priority == "medium":
        return f"Continue collecting adoption and ROI evidence for {label}."
    return f"Keep {label} in discovery until stronger aggregate signals emerge."
