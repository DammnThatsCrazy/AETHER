"""Graph mutations for decision and outcome intelligence relationships."""
from __future__ import annotations

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType

_EVIDENCE_VERTEX_TYPES = {
    "event": VertexType.EVENT,
    "entity": VertexType.ENTITY,
    "edge": VertexType.EXTERNAL_DATA,
    "profile_signal": VertexType.BEHAVIORAL_SIGNAL_NODE,
    "ml_prediction": VertexType.EXTERNAL_DATA,
    "attribution_path": VertexType.EXTERNAL_DATA,
    "economic_state": VertexType.EXTERNAL_DATA,
    "policy": VertexType.POLICY_DECISION,
}


async def _upsert_reference_vertex(
    graph: GraphClient,
    vertex_id: str,
    vertex_type: str,
    tenant_id: str,
    properties: dict | None = None,
) -> None:
    await graph.upsert_vertex(Vertex(vertex_type, vertex_id, {"tenant_id": tenant_id, **(properties or {})}))


async def upsert_recommendation_graph(graph: GraphClient, recommendation: dict) -> None:
    rec_id = recommendation["recommendation_id"]
    tenant_id = recommendation["tenant_id"]
    await graph.upsert_vertex(
        Vertex(
            VertexType.RECOMMENDATION,
            rec_id,
            {"tenant_id": tenant_id, "type": recommendation.get("recommendation_type")},
        )
    )
    source_id = recommendation.get("entity_id") or recommendation.get("population_id")
    if source_id:
        await _upsert_reference_vertex(graph, source_id, VertexType.ENTITY, tenant_id)
        await graph.add_edge(Edge(EdgeType.HAS_RECOMMENDATION, source_id, rec_id, {"tenant_id": tenant_id}))
    for ev in recommendation.get("evidence", []):
        evidence_id = ev.get("source_id") or ev.get("evidence_id")
        if not evidence_id:
            continue
        await _upsert_reference_vertex(
            graph,
            evidence_id,
            _EVIDENCE_VERTEX_TYPES.get(ev.get("source_type"), VertexType.EXTERNAL_DATA),
            tenant_id,
            {"source_type": ev.get("source_type")},
        )
        await graph.add_edge(
            Edge(
                EdgeType.SUPPORTED_BY,
                rec_id,
                evidence_id,
                {"tenant_id": tenant_id, "source_type": ev.get("source_type")},
            )
        )


async def upsert_decision_graph(graph: GraphClient, decision: dict) -> None:
    dec_id = decision["decision_id"]
    tenant_id = decision["tenant_id"]
    await graph.upsert_vertex(
        Vertex(VertexType.DECISION_RECORD, dec_id, {"tenant_id": tenant_id, "status": decision.get("decision_status")})
    )
    await graph.add_edge(Edge(EdgeType.SELECTED_BY, decision["recommendation_id"], dec_id, {"tenant_id": tenant_id}))


async def upsert_action_graph(graph: GraphClient, action: dict) -> None:
    action_id = action["action_id"]
    tenant_id = action["tenant_id"]
    await graph.upsert_vertex(Vertex(VertexType.ACTION_RECORD, action_id, {"tenant_id": tenant_id, "status": action.get("status")}))
    await graph.add_edge(Edge(EdgeType.EXECUTED_AS, action["decision_id"], action_id, {"tenant_id": tenant_id}))


async def upsert_outcome_graph(graph: GraphClient, outcome: dict) -> None:
    outcome_id = outcome["outcome_id"]
    tenant_id = outcome["tenant_id"]
    await graph.upsert_vertex(Vertex(VertexType.OUTCOME_OBSERVATION, outcome_id, {"tenant_id": tenant_id, "label": outcome.get("label")}))
    await graph.add_edge(Edge(EdgeType.PRODUCED, outcome["action_id"], outcome_id, {"tenant_id": tenant_id}))
    await graph.add_edge(
        Edge(
            EdgeType.UPDATES_CONFIDENCE_FOR,
            outcome_id,
            outcome["recommendation_id"],
            {"tenant_id": tenant_id, "confidence_delta": outcome.get("confidence_delta", 0)},
        )
    )
