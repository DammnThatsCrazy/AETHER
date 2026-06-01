"""Graph-native OODA recommendation generation inside the intelligence service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.intelligence.decision_models import Recommendation
from services.intelligence.recommendation_families import RecommendationFamilyRegistry, RecommendationGenerationContext
from services.intelligence.recommendation_families.base import GovernancePolicyGate


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GraphNativeRecommendationEngine:
    """Backward-compatible facade over the recommendation family registry."""

    def __init__(self, registry: RecommendationFamilyRegistry | None = None, confidence_threshold: float = 0.0) -> None:
        self.registry = registry or RecommendationFamilyRegistry(confidence_threshold=confidence_threshold)
        self.policy_gate = GovernancePolicyGate()

    def _context(self, tenant_id: str, entity_id: str | None, signals: dict[str, Any] | None = None, population_id: str | None = None) -> RecommendationGenerationContext:
        signals = signals or {}
        return RecommendationGenerationContext(
            tenant_id=tenant_id,
            entity_id=entity_id,
            population_id=population_id,
            signals=signals,
            profile_context=dict(signals.get("profile_context", {})),
            graph_context=dict(signals.get("graph_context", {})),
            attribution_context=dict(signals.get("attribution_context", {})),
            economic_context=dict(signals.get("economic_context", {})),
            ml_context=dict(signals.get("ml_context", {})),
            governance_context=dict(signals.get("governance_context", {})),
            computed_at=now_iso(),
        )

    def generate_for_entity(self, tenant_id: str, entity_id: str, signals: dict[str, Any] | None = None) -> Recommendation:
        """Return the highest-ranked recommendation for legacy callers."""
        return self.registry.generate_top_recommendation(self._context(tenant_id, entity_id, signals))

    def generate_all_for_entity(self, tenant_id: str, entity_id: str, signals: dict[str, Any] | None = None) -> list[Recommendation]:
        """Return all matching family recommendations ranked by confidence and value."""
        return self.registry.generate_recommendations(self._context(tenant_id, entity_id, signals))
