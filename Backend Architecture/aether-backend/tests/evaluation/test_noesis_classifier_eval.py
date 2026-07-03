"""Classifier evaluation suite for Noesis (P4.3).

Tests the deterministic keyword classifier (_classify) against 60+ annotated
examples covering all 15 supported intents. Asserts:
  - Overall accuracy >= 85%
  - Per-intent recall >= 75% (minimum 1 example per intent)
"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from services.noesis.models import NoesisQueryRequest
from services.noesis.service import NoesisService, Scope
from shared.graph.graph import GraphClient


def _make_service() -> NoesisService:
    graph = MagicMock(spec=GraphClient)
    analytics = MagicMock()
    return NoesisService(graph=graph, analytics=analytics)


def _classify(service: NoesisService, message: str, surface: str = "aether") -> str:
    req = NoesisQueryRequest(message=message, surface=surface)
    scope = Scope(
        surface=surface,
        effective_tenant_id="eval-tenant",
        cross_tenant=False,
        debug_allowed=False,
    )
    plan = service._classify(req, scope)
    return plan.intent


# Each tuple: (message, expected_intent)
EVAL_CASES: list[tuple[str, str]] = [
    # entity_search (7 examples)
    ("Show me all entities", "entity_search"),
    ("Find entities", "entity_search"),
    ("List all records", "entity_search"),
    ("Display tenant entities", "entity_search"),
    ("Search for entities", "entity_search"),
    ("Look up organization records", "entity_search"),
    ("Take me to entity listing", "entity_search"),

    # graph_lookup (5 examples)
    ("Show connections for ent_123", "graph_lookup"),
    ("What is linked to this entity?", "graph_lookup"),
    ("Graph neighbors of wallet w_abc", "graph_lookup"),
    ("Show relationships for ent_xyz", "graph_lookup"),
    ("Find adjacent nodes", "graph_lookup"),

    # alert_lookup (5 examples)
    ("Show me open alerts", "alert_lookup"),
    ("What incidents are unresolved?", "alert_lookup"),
    ("List high-severity alerts", "alert_lookup"),
    ("Are there any warnings?", "alert_lookup"),
    ("Show critical incidents from last 24 hours", "alert_lookup"),

    # tenant_summary (4 examples)
    ("Summarize tenant status", "tenant_summary"),
    ("Give me a tenant overview", "tenant_summary"),
    ("Show tenant summary report", "tenant_summary"),
    ("Customers status lookup", "tenant_summary"),

    # profile_lookup (4 examples)
    ("Show me user profiles", "profile_lookup"),
    ("Look up human identity records", "profile_lookup"),
    ("Find member profiles", "profile_lookup"),
    ("List customer profiles", "profile_lookup"),

    # wallet_lookup (5 examples)
    ("Show all wallets", "wallet_lookup"),
    ("Find wallet 0xABCDEF12", "wallet_lookup"),
    ("Which wallets have high risk?", "wallet_lookup"),
    ("List wallet records", "wallet_lookup"),
    ("wallet address lookup", "wallet_lookup"),

    # agent_lookup (4 examples)
    ("List active agents", "agent_lookup"),
    ("Show failed agent executions", "agent_lookup"),
    ("What agents ran recently?", "agent_lookup"),
    ("Find agent configuration", "agent_lookup"),

    # health_lookup (5 examples)
    ("What is the system health?", "health_lookup"),
    ("Show provider failures", "health_lookup"),
    ("Are any agents unhealthy?", "health_lookup"),
    ("SDK telemetry status", "health_lookup"),
    ("Show system diagnostics", "health_lookup"),

    # campaign_reward_lookup (4 examples)
    ("Show active campaigns", "campaign_reward_lookup"),
    ("What rewards exist?", "campaign_reward_lookup"),
    ("List loyalty incentives", "campaign_reward_lookup"),
    ("Show spending campaigns", "campaign_reward_lookup"),

    # risk_cluster_lookup (5 examples)
    ("Show highest risk entities", "risk_cluster_lookup"),
    ("Find suspicious clusters", "risk_cluster_lookup"),
    ("Entities with anomalous behavior", "risk_cluster_lookup"),
    ("List fraud risk clusters", "risk_cluster_lookup"),
    ("Show anomalous entity clusters", "risk_cluster_lookup"),

    # suggestion_lookup (4 examples)
    ("Show me recent suggestions", "suggestion_lookup"),
    ("List suggestions for entity ent_789", "suggestion_lookup"),
    ("What suggestions exist?", "suggestion_lookup"),
    ("Show OODA suggestions", "suggestion_lookup"),

    # suggestion_summary (4 examples)
    ("Summarize suggestions this week", "suggestion_summary"),
    ("What is the suggestion count?", "suggestion_summary"),
    ("Total recommendations overview", "suggestion_summary"),
    ("How many suggestions were generated?", "suggestion_summary"),

    # suggestion_review_queue (4 examples)
    ("What suggestions need review?", "suggestion_review_queue"),
    ("Show the review queue", "suggestion_review_queue"),
    ("List pending review suggestions", "suggestion_review_queue"),
    ("Suggestions awaiting review", "suggestion_review_queue"),

    # suggestion_explain (3 examples)
    ("Explain suggestion sug_123", "suggestion_explain"),
    ("Why was this recommendation generated?", "suggestion_explain"),
    ("What is the reason for this suggestion?", "suggestion_explain"),

    # suggestion_outcome_lookup (4 examples)
    ("What happened with recent suggestions?", "suggestion_outcome_lookup"),
    ("Show suggestion outcomes", "suggestion_outcome_lookup"),
    ("What was the result of suggestions?", "suggestion_outcome_lookup"),
    ("Show suggestion impact and feedback", "suggestion_outcome_lookup"),

    # sentiment_explain (4 examples)
    ("Why did sentiment toward Product X decline?", "sentiment_explain"),
    ("Explain sentiment about campaign camp_123", "sentiment_explain"),
    ("What is the sentiment toward entity ent_456?", "sentiment_explain"),
    ("How did emotion toward this brand change?", "sentiment_explain"),

    # narrative_analysis (4 examples)
    ("Which narratives are active for this tenant?", "narrative_analysis"),
    ("Show narrative diffusion across the graph", "narrative_analysis"),
    ("Analyze narrative propagation this week", "narrative_analysis"),
    ("What discourse is spreading among users?", "narrative_analysis"),

    # semantic_profile_explain (4 examples)
    ("Explain semantic profile for entity ent_789", "semantic_profile_explain"),
    ("What is the semantic state of profile user_001?", "semantic_profile_explain"),
    ("Show semantic summary for this user", "semantic_profile_explain"),
    ("What semantic stance is active for ent_456?", "semantic_profile_explain"),
]


class TestClassifierEval:
    """Classifier accuracy suite — asserts >= 85% overall and >= 75% per-intent."""

    def setup_method(self):
        self.service = _make_service()

    def test_overall_accuracy(self):
        total = len(EVAL_CASES)
        correct = sum(
            1 for msg, expected in EVAL_CASES
            if _classify(self.service, msg) == expected
        )
        accuracy = correct / total
        assert accuracy >= 0.85, (
            f"Classifier accuracy {accuracy:.1%} ({correct}/{total}) is below 85% threshold.\n"
            + "\n".join(
                f"  FAIL: '{msg}' → {_classify(self.service, msg)!r} (expected {expected!r})"
                for msg, expected in EVAL_CASES
                if _classify(self.service, msg) != expected
            )
        )

    def test_per_intent_recall(self):
        by_intent: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for msg, expected in EVAL_CASES:
            by_intent[expected].append((msg, expected))

        failures: list[str] = []
        for intent, cases in by_intent.items():
            correct = sum(1 for msg, exp in cases if _classify(self.service, msg) == exp)
            recall = correct / len(cases)
            if recall < 0.75:
                failures.append(
                    f"  {intent}: recall={recall:.1%} ({correct}/{len(cases)})"
                )

        assert not failures, "Per-intent recall below 75%:\n" + "\n".join(failures)

    def test_all_intents_covered(self):
        from services.noesis.models import SUPPORTED_INTENTS
        eval_intents = {expected for _, expected in EVAL_CASES}
        missing = SUPPORTED_INTENTS - eval_intents
        assert not missing, f"These intents have no eval examples: {missing}"
