"""Graph mutations for decision and outcome intelligence relationships.

All writes route through the canonical Graph Mutation Gateway (WP2.5): at
mode=off the gateway projects exactly what a direct ``upsert_vertex`` /
``add_edge`` did before; at shadow/enforce each write is recorded in the
append-only mutation ledger (nodes as ``node_versioned``, edges as
``edge_created``).
"""
from __future__ import annotations

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent

_ACTOR = "intelligence_projector"

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
    gateway: GraphMutationGateway,
    vertex_id: str,
    vertex_type: str,
    tenant_id: str,
    properties: dict | None = None,
) -> None:
    await gateway.apply(vertex_intent(
        Vertex(vertex_type, vertex_id, {"tenant_id": tenant_id, **(properties or {})}),
        operation="node_versioned",
        tenant_id=tenant_id,
        actor_id=_ACTOR,
    ))


async def upsert_recommendation_graph(graph: GraphClient, recommendation: dict) -> None:
    gateway = GraphMutationGateway(graph_client=graph)
    rec_id = recommendation["recommendation_id"]
    tenant_id = recommendation["tenant_id"]
    await gateway.apply(vertex_intent(
        Vertex(
            VertexType.RECOMMENDATION,
            rec_id,
            {"tenant_id": tenant_id, "type": recommendation.get("recommendation_type")},
        ),
        operation="node_versioned",
        tenant_id=tenant_id,
        actor_id=_ACTOR,
    ))
    source_id = recommendation.get("entity_id") or recommendation.get("population_id")
    if source_id:
        await _upsert_reference_vertex(gateway, source_id, VertexType.ENTITY, tenant_id)
        await gateway.apply(edge_intent(
            # HAS_RECOMMENDATION is an A2H edge — enforce-mode validation
            # requires consent_purpose; "personalization" is the registry
            # purpose whose data categories cover recommendations.
            Edge(EdgeType.HAS_RECOMMENDATION, source_id, rec_id,
                 {"tenant_id": tenant_id, "consent_purpose": "personalization"}),
            tenant_id=tenant_id, actor_id=_ACTOR, subject_kind="entity", subject_id=source_id,
        ))
    for ev in recommendation.get("evidence", []):
        evidence_id = ev.get("source_id") or ev.get("evidence_id")
        if not evidence_id:
            continue
        await _upsert_reference_vertex(
            gateway,
            evidence_id,
            _EVIDENCE_VERTEX_TYPES.get(ev.get("source_type"), VertexType.EXTERNAL_DATA),
            tenant_id,
            {"source_type": ev.get("source_type")},
        )
        await gateway.apply(edge_intent(
            # SUPPORTED_BY is an A2H edge — consent_purpose required in enforce.
            Edge(
                EdgeType.SUPPORTED_BY,
                rec_id,
                evidence_id,
                {
                    "tenant_id": tenant_id,
                    "source_type": ev.get("source_type"),
                    "consent_purpose": "personalization",
                },
            ),
            tenant_id=tenant_id, actor_id=_ACTOR, subject_kind="recommendation", subject_id=rec_id,
            evidence_refs=[str(evidence_id)],
        ))


async def upsert_decision_graph(graph: GraphClient, decision: dict) -> None:
    gateway = GraphMutationGateway(graph_client=graph)
    dec_id = decision["decision_id"]
    tenant_id = decision["tenant_id"]
    await gateway.apply(vertex_intent(
        Vertex(VertexType.DECISION_RECORD, dec_id, {"tenant_id": tenant_id, "status": decision.get("decision_status")}),
        operation="node_versioned", tenant_id=tenant_id, actor_id=_ACTOR,
    ))
    await gateway.apply(edge_intent(
        # SELECTED_BY is an A2H edge — consent_purpose required in enforce.
        Edge(EdgeType.SELECTED_BY, decision["recommendation_id"], dec_id,
             {"tenant_id": tenant_id, "consent_purpose": "personalization"}),
        tenant_id=tenant_id, actor_id=_ACTOR, subject_kind="decision", subject_id=dec_id,
    ))


async def upsert_action_graph(graph: GraphClient, action: dict) -> None:
    gateway = GraphMutationGateway(graph_client=graph)
    action_id = action["action_id"]
    tenant_id = action["tenant_id"]
    await gateway.apply(vertex_intent(
        Vertex(VertexType.ACTION_RECORD, action_id, {"tenant_id": tenant_id, "status": action.get("status")}),
        operation="node_versioned", tenant_id=tenant_id, actor_id=_ACTOR,
    ))
    await gateway.apply(edge_intent(
        Edge(EdgeType.EXECUTED_AS, action["decision_id"], action_id, {"tenant_id": tenant_id}),
        tenant_id=tenant_id, actor_id=_ACTOR, subject_kind="action", subject_id=action_id,
    ))


async def upsert_outcome_graph(graph: GraphClient, outcome: dict) -> None:
    gateway = GraphMutationGateway(graph_client=graph)
    outcome_id = outcome["outcome_id"]
    tenant_id = outcome["tenant_id"]
    await gateway.apply(vertex_intent(
        Vertex(VertexType.OUTCOME_OBSERVATION, outcome_id, {"tenant_id": tenant_id, "label": outcome.get("label")}),
        operation="node_versioned", tenant_id=tenant_id, actor_id=_ACTOR,
    ))
    await gateway.apply(edge_intent(
        Edge(EdgeType.PRODUCED, outcome["action_id"], outcome_id, {"tenant_id": tenant_id}),
        tenant_id=tenant_id, actor_id=_ACTOR, subject_kind="outcome", subject_id=outcome_id,
    ))
    await gateway.apply(edge_intent(
        Edge(
            EdgeType.UPDATES_CONFIDENCE_FOR,
            outcome_id,
            outcome["recommendation_id"],
            {"tenant_id": tenant_id, "confidence_delta": outcome.get("confidence_delta", 0)},
        ),
        tenant_id=tenant_id, actor_id=_ACTOR, subject_kind="outcome", subject_id=outcome_id,
    ))
