from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class RewardsOptimizationRecommendationFamily(BaseRecommendationFamily):
    family_key = "rewards_optimization"
    family_label = "Rewards optimization"
    detection_signal_keys = ("reward_eligibility_score", "fraud_risk_score", "campaign_alignment")
    primary_signal = "reward_eligibility_score"
    detect_threshold = 0.55
    default_expected_outcome = "Improve reward efficiency while controlling fraud and policy risk."
    default_downside_risk = "Suppressing valid rewards can reduce engagement."
    default_policy_flags = ('reward_policy_review',)

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("economic_expected_value")))
        if value is None:
            return None
        return round(_num(value) * 1.0, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "approve_reward_review", "label": "Approve reward review", "approval": "standard", "flags": ['reward_policy_review']},
            {"key": "defer_reward", "label": "Defer reward", "approval": "standard", "flags": ['reward_policy_review']},
            {"key": "inspect_reward_eligibility", "label": "Inspect reward eligibility", "approval": "none", "flags": ['reward_policy_review']},
            {"key": "suppress_suspicious_reward", "label": "Suppress suspicious reward", "approval": "elevated", "flags": ['reward_policy_review']}
        ]
