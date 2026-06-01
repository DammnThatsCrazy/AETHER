"""Graph-native recommendation scoring utilities."""
from __future__ import annotations

from dataclasses import dataclass

from services.intelligence.decision_models import CandidateAction, RecommendationConfidence


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RecommendationScoreInput:
    deterministic_rule_score: float
    ml_probability_score: float = 0.0
    graph_relevance_score: float = 0.0
    attribution_confidence: float = 0.0
    economic_expected_value: float = 0.0
    risk_penalty: float = 0.0
    freshness_penalty: float = 0.0
    governance_policy_penalty: float = 0.0
    model_version: str | None = None


class RecommendationScorer:
    """Combines rule, ML, graph, attribution, economics, risk, freshness and governance scores."""

    weights = {
        "deterministic_rule_score": 0.24,
        "ml_probability_score": 0.22,
        "graph_relevance_score": 0.16,
        "attribution_confidence": 0.12,
        "economic_value_score": 0.16,
        "risk_penalty": 0.04,
        "freshness_penalty": 0.03,
        "governance_policy_penalty": 0.03,
    }

    def score(self, inp: RecommendationScoreInput) -> RecommendationConfidence:
        economic_value_score = clamp(inp.economic_expected_value / 1000.0) if inp.economic_expected_value > 0 else 0.0
        positive = (
            clamp(inp.deterministic_rule_score) * self.weights["deterministic_rule_score"]
            + clamp(inp.ml_probability_score) * self.weights["ml_probability_score"]
            + clamp(inp.graph_relevance_score) * self.weights["graph_relevance_score"]
            + clamp(inp.attribution_confidence) * self.weights["attribution_confidence"]
            + economic_value_score * self.weights["economic_value_score"]
        )
        penalties = (
            clamp(inp.risk_penalty) * self.weights["risk_penalty"]
            + clamp(inp.freshness_penalty) * self.weights["freshness_penalty"]
            + clamp(inp.governance_policy_penalty) * self.weights["governance_policy_penalty"]
        )
        return RecommendationConfidence(
            overall=round(clamp(positive - penalties), 4),
            deterministic_rule_score=clamp(inp.deterministic_rule_score),
            ml_probability_score=clamp(inp.ml_probability_score),
            graph_relevance_score=clamp(inp.graph_relevance_score),
            attribution_confidence=clamp(inp.attribution_confidence),
            economic_expected_value=inp.economic_expected_value,
            risk_penalty=clamp(inp.risk_penalty),
            freshness_penalty=clamp(inp.freshness_penalty),
            governance_policy_penalty=clamp(inp.governance_policy_penalty),
            model_version=inp.model_version,
        )

    def rank_actions(self, actions: list[CandidateAction]) -> list[CandidateAction]:
        return sorted(actions, key=lambda a: (a.confidence.overall if a.confidence else 0.0, a.expected_value or 0.0), reverse=True)
