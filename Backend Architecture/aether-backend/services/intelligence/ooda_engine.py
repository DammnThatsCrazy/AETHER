"""Graph-native OODA recommendation generation inside the intelligence service."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from services.intelligence.decision_models import CandidateAction
from services.intelligence.recommendation_families import RecommendationFamilyRegistry


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GraphNativeRecommendationEngine:
    def __init__(self, registry: RecommendationFamilyRegistry | None = None) -> None:
        self.registry = registry or RecommendationFamilyRegistry()

    def __init__(self, registry: RecommendationFamilyRegistry | None = None, confidence_threshold: float = 0.0) -> None:
        self.registry = registry or RecommendationFamilyRegistry(confidence_threshold=confidence_threshold)
        self.policy_gate = GovernancePolicyGate()

    def generate_for_entity(self, tenant_id: str, entity_id: str, signals: dict[str, Any] | None = None):
        """Generate one governed recommendation using the configured family registry."""
        signals = signals or {}
        family = self.registry.detect(signals, graph_context=signals.get("graph_context"), profile_context=signals.get("profile_context"))
        enriched_signals = {**signals, "graph_snapshot_id": self._snapshot_id(tenant_id, entity_id, signals)}
        return family.emit(
            tenant_id,
            entity_id,
            enriched_signals,
            graph_context=signals.get("graph_context"),
            profile_context=signals.get("profile_context"),
        )

    def generate_for_entity(self, tenant_id: str, entity_id: str, signals: dict[str, Any] | None = None) -> Recommendation:
        """Return the highest-ranked recommendation for legacy callers."""
        return self.registry.generate_top_recommendation(self._context(tenant_id, entity_id, signals))

    def generate_all_for_entity(self, tenant_id: str, entity_id: str, signals: dict[str, Any] | None = None) -> list[Recommendation]:
        """Return all matching family recommendations ranked by confidence and value."""
        return self.registry.generate_recommendations(self._context(tenant_id, entity_id, signals))
