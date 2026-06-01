from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class AttributionOptimizationRecommendationFamily(BaseRecommendationFamily):
    family_key = "attribution_optimization"
    family_label = "Attribution optimization"
    detection_signal_keys = ("path_conflict_score", "campaign_spend", "attribution_confidence")
    primary_signal = "path_conflict_score"
    detect_threshold = 0.5
    default_expected_outcome = "Reduce campaign waste and improve attribution confidence."
    default_downside_risk = "Budget changes can under-serve valid conversion paths."
    default_policy_flags = ('campaign_review_required',)

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("campaign_spend")))
        if value is None:
            return None
        return round(_num(value) * 0.1, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "inspect_attribution_path", "label": "Inspect attribution path", "approval": "none", "flags": ['campaign_review_required']},
            {"key": "flag_campaign_for_review", "label": "Flag campaign for review", "approval": "standard", "flags": ['campaign_review_required']},
            {"key": "recommend_budget_review", "label": "Recommend budget review", "approval": "standard", "flags": ['campaign_review_required']},
            {"key": "export_attribution_report", "label": "Export attribution report", "approval": "none", "flags": ['campaign_review_required']}
        ]
