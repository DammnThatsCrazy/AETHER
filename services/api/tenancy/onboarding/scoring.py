"""Scoring and customer-success trigger helpers for implementation onboarding."""
from __future__ import annotations

from collections import Counter
from typing import Any

SEVERITY_PENALTY = {"low": 5, "medium": 12, "high": 22, "critical": 35}


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _completed_required_ratio(steps: list[dict[str, Any]]) -> float:
    required = [s for s in steps if s.get("required", True) and s.get("status") != "skipped"]
    if not required:
        return 1.0
    return sum(1 for s in required if s.get("status") == "completed") / len(required)


def category_completed(steps: list[dict[str, Any]], category: str) -> bool:
    cats = [s for s in steps if s.get("category") == category and s.get("required", True)]
    return bool(cats) and all(s.get("status") in {"completed", "skipped"} for s in cats)


def title_completed(steps: list[dict[str, Any]], token: str) -> bool:
    token = token.lower()
    return any(token in s.get("title", "").lower() and s.get("status") == "completed" for s in steps)


def implementation_health_score(steps: list[dict[str, Any]], blockers: list[dict[str, Any]], metrics: dict[str, Any] | None = None) -> int:
    metrics = metrics or {}
    score = 55 * _completed_required_ratio(steps)
    readiness_flags = [
        metrics.get("sdk_live") or category_completed(steps, "sdk"),
        metrics.get("event_mapping_health") or category_completed(steps, "events"),
        metrics.get("graph_active") or category_completed(steps, "graph"),
        metrics.get("recommendation_ready") or category_completed(steps, "intelligence"),
        metrics.get("playbook_ready") or category_completed(steps, "playbooks"),
        metrics.get("integration_ready") or category_completed(steps, "integrations"),
        metrics.get("outcome_ready") or category_completed(steps, "outcomes"),
    ]
    score += 45 * (sum(1 for f in readiness_flags if f) / len(readiness_flags))
    open_blockers = [b for b in blockers if b.get("status") in {"open", "in_progress"}]
    score -= sum(SEVERITY_PENALTY.get(b.get("severity", "medium"), 12) for b in open_blockers)
    return clamp_score(score)


def go_live_readiness_score(steps: list[dict[str, Any]], blockers: list[dict[str, Any]], criteria: dict[str, Any], metrics: dict[str, Any] | None = None) -> int:
    metrics = metrics or {}
    checks = [
        metrics.get("sdk_live") or category_completed(steps, "sdk"),
        metrics.get("required_events_received") or category_completed(steps, "events"),
        metrics.get("identity_resolution_verified") or category_completed(steps, "identity"),
        metrics.get("graph_active") or criteria.get("graph_active") is False or category_completed(steps, "graph"),
        metrics.get("recommendations_enabled") or category_completed(steps, "intelligence"),
        metrics.get("required_playbooks_configured") or category_completed(steps, "playbooks"),
        metrics.get("required_integrations_configured") or category_completed(steps, "integrations"),
        metrics.get("required_audit_exports_configured") or title_completed(steps, "audit export") or not metrics.get("audit_exports_required", False),
    ]
    score = 100 * (sum(1 for c in checks if c) / len(checks))
    if any(b.get("status") in {"open", "in_progress"} and b.get("severity") == "critical" for b in blockers):
        score = min(score, 60)
    return clamp_score(score)


def value_readiness_score(steps: list[dict[str, Any]], criteria: dict[str, Any], metrics: dict[str, Any] | None = None) -> int:
    metrics = metrics or {}
    checks = [
        metrics.get("recommendations_generated") or category_completed(steps, "intelligence"),
        metrics.get("recommendations_viewed", False),
        metrics.get("decisions_recorded", False),
        metrics.get("actions_logged", False),
        metrics.get("outcomes_observed") or criteria.get("outcomes_observed") is False or category_completed(steps, "outcomes"),
        metrics.get("outcome_ledger_populated") or title_completed(steps, "outcome ledger"),
        metrics.get("success_criteria_met", False),
    ]
    return clamp_score(100 * (sum(1 for c in checks if c) / len(checks)))


def expansion_readiness_score(plan: dict[str, Any], steps: list[dict[str, Any]], blockers: list[dict[str, Any]], metrics: dict[str, Any] | None = None) -> int:
    metrics = metrics or {}
    open_blockers = [b for b in blockers if b.get("status") in {"open", "in_progress"}]
    checks = [
        plan.get("status") in {"value_proven", "expansion_ready"} or metrics.get("value_proven"),
        metrics.get("outcome_capture_rate", 0) >= 0.5 or category_completed(steps, "outcomes"),
        metrics.get("playbook_roi", 0) > 0,
        metrics.get("integration_adoption", 0) >= 0.5 or category_completed(steps, "integrations"),
        metrics.get("observed_value", 0) >= metrics.get("value_threshold", 1),
        metrics.get("package_fit_signals", 0) > 0,
        len(open_blockers) <= 1,
    ]
    return clamp_score(100 * (sum(1 for c in checks if c) / len(checks)))


def infer_stage(steps: list[dict[str, Any]], plan: dict[str, Any]) -> str:
    if plan.get("status") == "expansion_ready":
        return "expansion_ready"
    if plan.get("status") == "value_proven":
        return "value_proven"
    ordered = [
        ("outcomes", "outcomes_capturing"), ("integrations", "integrations_connected"), ("playbooks", "playbooks_configured"),
        ("intelligence", "recommendations_enabled"), ("graph", "graph_active"), ("events", "event_mapping_in_progress"),
        ("sdk", "sdk_live"), ("tenant_setup", "tenant_created"), ("contract", "signed"),
    ]
    for category, stage in ordered:
        if category_completed(steps, category):
            return stage
    return plan.get("onboarding_stage", "signed")


def generate_customer_success_triggers(plan: dict[str, Any], steps: list[dict[str, Any]], blockers: list[dict[str, Any]], metrics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    metrics = metrics or {}
    counts = Counter(s.get("category") for s in steps if s.get("status") == "completed")
    total_by_cat = Counter(s.get("category") for s in steps)
    triggers: list[dict[str, Any]] = []

    def add(trigger_type: str, severity: str, reason: str, action: str, support: dict[str, Any]) -> None:
        triggers.append({"trigger_type": trigger_type, "severity": severity, "reason": reason, "recommended_action": action, "supporting_metrics": support})

    if total_by_cat["sdk"] and counts["sdk"] == 0:
        add("sdk_stalled", "high", "SDK installation is not complete.", "Schedule an SDK pairing session and verify tenant API key scope.", {"sdk_steps_completed": counts["sdk"], "sdk_steps_total": total_by_cat["sdk"]})
    if total_by_cat["events"] and counts["events"] < total_by_cat["events"]:
        add("event_mapping_stalled", "medium", "Required event mapping remains incomplete.", "Review event taxonomy with tenant implementation owner.", {"events_completed": counts["events"], "events_total": total_by_cat["events"]})
    if total_by_cat["graph"] and counts["graph"] < total_by_cat["graph"] and counts["events"] > 0:
        add("graph_not_activating", "high", "Graph activation lags behind event and identity setup.", "Inspect graph build jobs and identity joins in Kyber.", {"graph_completed": counts["graph"], "events_completed": counts["events"]})
    if metrics.get("recommendations_generated", 0) > 0 and metrics.get("recommendations_viewed", 0) == 0:
        add("recommendations_not_viewed", "medium", "Recommendations exist but have not been viewed.", "Run tenant enablement and confirm notification delivery.", metrics)
    if metrics.get("recommendations_viewed", 0) > 0 and metrics.get("decisions_recorded", 0) == 0:
        add("decisions_not_recorded", "medium", "Recommendations are viewed without decision records.", "Coach tenant champions on decision capture workflow.", metrics)
    if metrics.get("decisions_recorded", 0) > 0 and metrics.get("actions_logged", 0) == 0:
        add("actions_not_logged", "medium", "Decision records exist without action logs.", "Connect action integrations or enable manual action logging.", metrics)
    if metrics.get("actions_logged", 0) > 0 and metrics.get("outcomes_observed", 0) == 0:
        add("outcomes_not_captured", "high", "Actions are logged but outcomes are not captured.", "Configure outcome ledger feeds and first-value proof review.", metrics)
    if counts["playbooks"] and metrics.get("playbook_runs", 0) == 0:
        add("playbooks_unused", "medium", "Playbooks are configured but have not run.", "Review trigger rules and launch a guided playbook run.", {"playbooks_configured": counts["playbooks"], **metrics})
    if metrics.get("integration_failures", 0) > 0:
        add("integrations_failed", "high", "One or more onboarding integrations are failing.", "Inspect integration credentials and retry failed dispatches.", metrics)
    if plan.get("value_readiness_score", 0) >= 80 or metrics.get("value_proven"):
        add("value_proven", "low", "Tenant has enough captured value for an executive proof point.", "Schedule value review and document ROI evidence.", {"value_readiness_score": plan.get("value_readiness_score", 0), **metrics})
    if plan.get("expansion_readiness_score", 0) >= 80 or metrics.get("expansion_ready"):
        add("expansion_ready", "low", "Tenant shows expansion readiness signals.", "Prepare package expansion recommendation and commercial handoff.", {"expansion_readiness_score": plan.get("expansion_readiness_score", 0), **metrics})
    return triggers
