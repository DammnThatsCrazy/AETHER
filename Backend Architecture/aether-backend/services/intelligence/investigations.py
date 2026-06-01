"""Recommendation investigation workspace composition."""
from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.service.intelligence.investigations")


async def _find_many(repo, filters: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    if repo is None:
        return []
    return await repo.find_many(filters, limit=limit)


async def build_recommendation_investigation(
    *,
    tenant_id: str,
    recommendation: dict[str, Any],
    decisions_repo,
    actions_repo,
    outcomes_repo,
    graph=None,
) -> dict[str, Any]:
    """Compose a tenant-isolated, explainable investigation bundle for one recommendation."""
    recommendation_id = recommendation.get("recommendation_id") or recommendation.get("id")
    recommendation_type = recommendation.get("recommendation_type")
    entity_id = recommendation.get("entity_id")
    decisions = await _find_many(decisions_repo, {"tenant_id": tenant_id, "recommendation_id": recommendation_id}, limit=100)
    actions = []
    for decision in decisions:
        decision_id = decision.get("decision_id")
        if decision_id:
            actions.extend(await _find_many(actions_repo, {"tenant_id": tenant_id, "decision_id": decision_id}, limit=100))
    outcomes = await _find_many(outcomes_repo, {"tenant_id": tenant_id, "recommendation_id": recommendation_id}, limit=100)
    tenant_outcomes = await _find_many(outcomes_repo, {"tenant_id": tenant_id}, limit=200)
    prior_similar = [
        outcome for outcome in tenant_outcomes
        if outcome.get("recommendation_id") != recommendation_id
        and (not recommendation_type or outcome.get("outcome_type") == recommendation_type)
    ][:25]

    graph_edges: list[dict[str, Any]] = []
    if graph is not None and recommendation_id:
        try:
            neighbors = await graph.get_neighbors(recommendation_id, direction="both")
            graph_edges = [
                {"id": vertex.vertex_id, "type": vertex.vertex_type, "properties": vertex.properties}
                for vertex in neighbors[:50]
                if getattr(vertex, "properties", {}).get("tenant_id") in {None, tenant_id}
            ]
        except Exception as exc:  # pragma: no cover - optional graph context must degrade gracefully
            logger.warning(f"recommendation investigation graph lookup skipped: {exc}")

    evidence = recommendation.get("evidence", [])
    return {
        "recommendation": recommendation,
        "confidence_breakdown": recommendation.get("confidence", {}),
        "evidence": evidence,
        "related_profile": {"entity_id": entity_id, "population_id": recommendation.get("population_id")},
        "related_graph_edges": graph_edges,
        "related_events": [item for item in evidence if item.get("source_type") == "event"],
        "attribution_path": next((item for item in evidence if item.get("source_type") == "attribution_path"), None),
        "candidate_actions": recommendation.get("candidate_actions", []),
        "decision_history": decisions,
        "action_history": actions,
        "outcome_history": outcomes,
        "prior_similar_outcomes": prior_similar,
        "governance_flags": recommendation.get("policy_governance_flags", []),
        "data_freshness": recommendation.get("data_freshness", {}),
        "suppression_reason": recommendation.get("policy_governance_flags", []) if recommendation.get("status") == "suppressed" else [],
    }
