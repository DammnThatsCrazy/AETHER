"""Graph mutations for decision and outcome intelligence relationships."""
from __future__ import annotations

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType


async def upsert_recommendation_graph(graph: GraphClient, recommendation: dict) -> None:
    rec_id = recommendation["recommendation_id"]
    tenant_id = recommendation["tenant_id"]
    await graph.add_vertex(Vertex(VertexType.RECOMMENDATION, rec_id, {"tenant_id": tenant_id, "type": recommendation.get("recommendation_type")}))
    source_id = recommendation.get("entity_id") or recommendation.get("population_id")
    if source_id:
        await graph.add_edge(Edge(EdgeType.HAS_RECOMMENDATION, source_id, rec_id, {"tenant_id": tenant_id}))
    for ev in recommendation.get("evidence", []):
        await graph.add_edge(Edge(EdgeType.SUPPORTED_BY, rec_id, ev.get("source_id", ev.get("evidence_id")), {"tenant_id": tenant_id, "source_type": ev.get("source_type")}))


async def upsert_decision_graph(graph: GraphClient, decision: dict) -> None:
    dec_id = decision["decision_id"]
    tenant_id = decision["tenant_id"]
    await graph.add_vertex(Vertex(VertexType.DECISION_RECORD, dec_id, {"tenant_id": tenant_id, "status": decision.get("decision_status")}))
    await graph.add_edge(Edge(EdgeType.SELECTED_BY, decision["recommendation_id"], dec_id, {"tenant_id": tenant_id}))


async def upsert_action_graph(graph: GraphClient, action: dict) -> None:
    action_id = action["action_id"]
    tenant_id = action["tenant_id"]
    await graph.add_vertex(Vertex(VertexType.ACTION_RECORD, action_id, {"tenant_id": tenant_id, "status": action.get("status")}))
    await graph.add_edge(Edge(EdgeType.EXECUTED_AS, action["decision_id"], action_id, {"tenant_id": tenant_id}))


async def upsert_outcome_graph(graph: GraphClient, outcome: dict) -> None:
    outcome_id = outcome["outcome_id"]
    tenant_id = outcome["tenant_id"]
    await graph.add_vertex(Vertex(VertexType.OUTCOME_OBSERVATION, outcome_id, {"tenant_id": tenant_id, "label": outcome.get("label")}))
    await graph.add_edge(Edge(EdgeType.PRODUCED, outcome["action_id"], outcome_id, {"tenant_id": tenant_id}))
    await graph.add_edge(Edge(EdgeType.UPDATES_CONFIDENCE_FOR, outcome_id, outcome["recommendation_id"], {"tenant_id": tenant_id, "confidence_delta": outcome.get("confidence_delta", 0)}))
