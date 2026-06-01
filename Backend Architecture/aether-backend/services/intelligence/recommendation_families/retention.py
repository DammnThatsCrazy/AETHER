from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class RetentionRecommendationFamily(BaseRecommendationFamily):
    family_key = "retention"
    family_label = "Retention"
    primary_signal = "churn_probability"
    detect_threshold = 0.55
    default_expected_outcome = "Reduce churn risk and recover projected value."
    default_downside_risk = "Over-contact risk if consent, frequency, or recency policies are not satisfied."
    default_policy_flags = ("consent_required", "frequency_cap_required")

    def detect(self, context: RecommendationGenerationContext) -> bool:
        explicit = context.value("recommendation_family") or context.value("recommendation_type")
        if explicit:
            return explicit == self.family_key
        # Backward-compatible default: legacy callers with sparse signals still receive retention.
        other_family_signals = {
            "usage_growth", "anomaly_score", "suspicious_cluster_score", "velocity_score",
            "path_conflict_score", "dropoff_rate", "agent_failure_rate",
            "reward_eligibility_score", "integration_error_rate",
        }
        if "churn_probability" not in context.signals and any(key in context.signals for key in other_family_signals):
            return False
        return _num(context.value("churn_probability"), 0.62) >= self.detect_threshold and _num(context.value("ltv_predicted_usd"), 420.0) >= 100

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        return round(_num(context.value("ltv_predicted_usd"), 420.0) * 0.18, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "human_review_retention_offer", "type": "manual_or_system_triggered", "label": "Review retention offer", "description": "Create a consent-compliant retention touch with human approval before execution.", "expected_value": value, "approval": "standard", "flags": ["consent_required", "frequency_cap_required"], "integration": str(context.value("preferred_integration", "notification_or_crm"))},
            {"key": "open_investigation", "label": "Open investigation workflow", "description": "Inspect graph evidence, attribution path, and churn signals before action.", "expected_value": round(_num(context.value("ltv_predicted_usd"), 420.0) * 0.04, 2), "approval": "none", "flags": ["explanation_required"]},
            {"key": "route_to_customer_success", "label": "Route to customer success", "description": "Create a customer success review task for the at-risk entity.", "expected_value": value, "approval": "standard", "flags": ["human_review_required"]},
        ]
