from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class JourneyOptimizationRecommendationFamily(BaseRecommendationFamily):
    family_key = "journey_optimization"
    family_label = "Journey optimization"
    detection_signal_keys = ("dropoff_rate", "friction_score", "conversion_probability")
    primary_signal = "dropoff_rate"
    detect_threshold = 0.5
    default_expected_outcome = "Reduce journey friction and improve conversion probability."
    default_downside_risk = "Premature optimization can distract from higher-impact segments."
    default_policy_flags = ('journey_review_required',)

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("journey_value_usd")))
        if value is None:
            return None
        return round(_num(value) * 1.0, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "open_journey_investigation", "label": "Open journey investigation", "approval": "none", "flags": ['journey_review_required']},
            {"key": "create_product_task", "label": "Create product task", "approval": "standard", "flags": ['journey_review_required']},
            {"key": "trigger_onboarding_support", "label": "Trigger onboarding support", "approval": "standard", "flags": ['journey_review_required']},
            {"key": "monitor_segment", "label": "Monitor segment", "approval": "none", "flags": ['journey_review_required']}
        ]
