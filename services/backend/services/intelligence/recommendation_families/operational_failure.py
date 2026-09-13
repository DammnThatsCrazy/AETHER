from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class OperationalFailureRecommendationFamily(BaseRecommendationFamily):
    family_key = "operational_failure"
    family_label = "Operational failure"
    detection_signal_keys = ("stale_loop_count", "failed_action_count", "missing_outcome_count", "integration_error_rate", "workflow_latency")
    primary_signal = "integration_error_rate"
    detect_threshold = 0.25
    default_expected_outcome = "Resolve broken operational loops and recover missing outcomes."
    default_downside_risk = "Reruns can duplicate work if idempotency is not verified."
    default_policy_flags = ('ops_review_required',)

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("incident_cost_avoided_usd")))
        if value is None:
            return None
        return round(_num(value) * 1.0, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "inspect_integration", "label": "Inspect integration", "approval": "none", "flags": ['ops_review_required']},
            {"key": "create_support_ticket", "label": "Create support ticket", "approval": "standard", "flags": ['ops_review_required']},
            {"key": "notify_tenant_admin", "label": "Notify tenant admin", "approval": "standard", "flags": ['ops_review_required']},
            {"key": "rerun_playbook", "label": "Rerun playbook", "approval": "elevated", "flags": ['ops_review_required']},
            {"key": "open_operational_investigation", "label": "Open operational investigation", "approval": "none", "flags": ['ops_review_required']}
        ]
