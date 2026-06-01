"""Registry for graph-native recommendation families."""
from __future__ import annotations

from services.intelligence.decision_models import Recommendation
from services.intelligence.recommendation_families.agent_governance import AgentGovernanceRecommendationFamily
from services.intelligence.recommendation_families.attribution_optimization import AttributionOptimizationRecommendationFamily
from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext
from services.intelligence.recommendation_families.expansion import ExpansionRecommendationFamily
from services.intelligence.recommendation_families.fraud_review import FraudReviewRecommendationFamily
from services.intelligence.recommendation_families.journey_optimization import JourneyOptimizationRecommendationFamily
from services.intelligence.recommendation_families.operational_failure import OperationalFailureRecommendationFamily
from services.intelligence.recommendation_families.retention import RetentionRecommendationFamily
from services.intelligence.recommendation_families.rewards_optimization import RewardsOptimizationRecommendationFamily


class RecommendationFamilyRegistry:
    def __init__(self, families: list[BaseRecommendationFamily] | None = None, confidence_threshold: float = 0.0) -> None:
        self.confidence_threshold = confidence_threshold
        self._families = families or [
            RetentionRecommendationFamily(),
            ExpansionRecommendationFamily(),
            FraudReviewRecommendationFamily(),
            AttributionOptimizationRecommendationFamily(),
            JourneyOptimizationRecommendationFamily(),
            AgentGovernanceRecommendationFamily(),
            RewardsOptimizationRecommendationFamily(),
            OperationalFailureRecommendationFamily(),
        ]

    @property
    def families(self) -> list[BaseRecommendationFamily]:
        return list(self._families)

    def get(self, family_key: str) -> BaseRecommendationFamily | None:
        return next((family for family in self._families if family.family_key == family_key), None)

    def matching_families(self, context: RecommendationGenerationContext) -> list[BaseRecommendationFamily]:
        requested = context.value("recommendation_family") or context.value("recommendation_type")
        if requested:
            family = self.get(str(requested))
            return [family] if family is not None else []
        matches = [family for family in self._families if family.detect(context)]
        return matches or [self.get("retention") or self._families[0]]

    def generate_recommendations(self, context: RecommendationGenerationContext) -> list[Recommendation]:
        recommendations = [family.generate(context) for family in self.matching_families(context)]
        for rec in recommendations:
            if rec.confidence.overall < self.confidence_threshold:
                rec.status = "suppressed"
                rec.policy_governance_flags = sorted(set(rec.policy_governance_flags + ["below_confidence_threshold"]))
        return sorted(
            recommendations,
            key=lambda rec: (rec.status != "suppressed", rec.confidence.overall, rec.expected_value or 0.0),
            reverse=True,
        )

    def generate_top_recommendation(self, context: RecommendationGenerationContext) -> Recommendation:
        return self.generate_recommendations(context)[0]
