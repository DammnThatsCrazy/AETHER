from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class ExpansionRecommendationFamily(BaseRecommendationFamily):
    family_key = "expansion"
    family_label = "Expansion"
    detection_signal_keys = ("usage_growth", "account_health", "relationship_influence_score")
    primary_signal = "usage_growth"
    detect_threshold = 0.55
    default_expected_outcome = "Identify high-fit expansion opportunities for account teams."
    default_downside_risk = "Over-routing low-fit accounts can create sales noise."
    default_policy_flags = ('sales_review_required',)

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("ltv_predicted_usd")))
        if value is None:
            return None
        return round(_num(value) * 0.12, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "create_expansion_review", "label": "Create expansion review", "approval": "standard", "flags": ['sales_review_required']},
            {"key": "route_to_sales", "label": "Route to sales", "approval": "standard", "flags": ['sales_review_required']},
            {"key": "recommend_upgrade_path", "label": "Recommend upgrade path", "approval": "standard", "flags": ['sales_review_required']},
            {"key": "open_expansion_investigation", "label": "Open expansion investigation", "approval": "none", "flags": ['sales_review_required']}
        ]
