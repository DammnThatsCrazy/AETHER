from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class FraudReviewRecommendationFamily(BaseRecommendationFamily):
    family_key = "fraud_review"
    family_label = "Fraud review"
    detection_signal_keys = ("fraud_probability", "anomaly_score", "suspicious_cluster_score", "velocity_score", "fraud_risk_score")
    primary_signal = "suspicious_cluster_score"
    detect_threshold = 0.5
    default_expected_outcome = "Reduce fraud loss while preserving analyst review."
    default_downside_risk = "False positives can add customer friction."
    default_policy_flags = ('fraud_review_required', 'human_approval_required')

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("exposure_usd")))
        if value is None:
            return None
        return round(_num(value) * 1.0, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "open_fraud_investigation", "label": "Open fraud investigation", "approval": "elevated", "flags": ['fraud_review_required', 'human_approval_required']},
            {"key": "step_up_verification", "label": "Step-up verification", "approval": "elevated", "flags": ['fraud_review_required', 'human_approval_required']},
            {"key": "suppress_reward_action", "label": "Suppress reward/action", "approval": "elevated", "flags": ['fraud_review_required', 'human_approval_required']},
            {"key": "manual_review", "label": "Manual review", "approval": "standard", "flags": ['fraud_review_required', 'human_approval_required']}
        ]
