"""Graph-native OODA recommendation generation inside the intelligence service."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from services.intelligence.decision_models import CandidateAction
from services.intelligence.recommendation_families import RecommendationFamilyRegistry


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernancePolicyGate:
    """Tenant policy gate preserving human approval for critical/high-impact actions."""

    def evaluate(self, action: CandidateAction, confidence_overall: float) -> tuple[str, list[str], float]:
        flags: list[str] = []
        penalty = 0.0
        approval = action.requires_approval_level
        if action.expected_value and action.expected_value >= 500:
            approval = "elevated"
            flags.append("economic_value_review")
            penalty += 0.04
        if "irreversible" in action.policy_flags or "critical" in action.policy_flags:
            approval = "critical"
            flags.append("human_approval_required")
            penalty += 0.10
        if confidence_overall < 0.45:
            flags.append("low_confidence_explanation_required")
            penalty += 0.05
        return approval, flags, min(penalty, 1.0)


class GraphNativeRecommendationEngine:
    def __init__(self, registry: RecommendationFamilyRegistry | None = None) -> None:
        self.registry = registry or RecommendationFamilyRegistry()

    def _snapshot_id(self, tenant_id: str, entity_id: str, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(f"{tenant_id}:{entity_id}:{payload}".encode()).hexdigest()[:16]
        return f"graph-snapshot-{digest}"

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
