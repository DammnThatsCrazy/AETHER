"""
Aether Shared — @aether/graph/relationship_layers
Classifies graph edges into three relationship layers:
  H2H (Human-to-Human)  — existing behavioral analytics
  H2A (Human-to-Agent)   — delegation, attribution, reward passthrough
  A2A (Agent-to-Agent)    — orchestration, hiring, payments, protocol composition

Used by: Analytics, Agent, Commerce, On-Chain services.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from shared.graph.graph import EdgeType, Vertex, Edge, VertexType, GraphClient
from shared.logger.logger import get_logger

logger = get_logger("aether.graph.layers")


# ═══════════════════════════════════════════════════════════════════════════
# RELATIONSHIP LAYERS
# ═══════════════════════════════════════════════════════════════════════════

class RelationshipLayer(str, Enum):
    H2H = "H2H"   # Human-to-Human
    H2A = "H2A"   # Human-to-Agent
    A2A = "A2A"   # Agent-to-Agent


# Edge classification map — maps every EdgeType to its primary layer
_EDGE_LAYER_MAP: dict[str, RelationshipLayer] = {
    # H2H — Existing behavioral analytics edges
    EdgeType.HAS_SESSION: RelationshipLayer.H2H,
    EdgeType.VIEWED_PAGE: RelationshipLayer.H2H,
    EdgeType.TRIGGERED_EVENT: RelationshipLayer.H2H,
    EdgeType.USED_DEVICE: RelationshipLayer.H2H,
    EdgeType.BELONGS_TO: RelationshipLayer.H2H,
    EdgeType.RESOLVED_AS: RelationshipLayer.H2H,
    EdgeType.ENRICHED_BY: RelationshipLayer.H2H,
    EdgeType.HAS_FINGERPRINT: RelationshipLayer.H2H,
    EdgeType.SEEN_FROM_IP: RelationshipLayer.H2H,
    EdgeType.LOCATED_IN: RelationshipLayer.H2H,
    EdgeType.HAS_EMAIL: RelationshipLayer.H2H,
    EdgeType.HAS_PHONE: RelationshipLayer.H2H,
    EdgeType.OWNS_WALLET: RelationshipLayer.H2H,
    EdgeType.MEMBER_OF_CLUSTER: RelationshipLayer.H2H,
    EdgeType.SIMILAR_TO: RelationshipLayer.H2H,
    EdgeType.IP_MAPS_TO: RelationshipLayer.H2H,

    # H2A — Human-to-Agent edges
    EdgeType.LAUNCHED_BY: RelationshipLayer.H2A,
    EdgeType.DELEGATES: RelationshipLayer.H2A,
    EdgeType.INTERACTS_WITH: RelationshipLayer.H2A,
    EdgeType.ATTRIBUTED_TO: RelationshipLayer.H2A,

    # A2A — Agent-to-Agent / protocol edges
    EdgeType.PAYS: RelationshipLayer.A2A,
    EdgeType.CONSUMES: RelationshipLayer.A2A,
    EdgeType.HIRED: RelationshipLayer.A2A,
    EdgeType.DEPLOYED: RelationshipLayer.A2A,
    EdgeType.CALLED: RelationshipLayer.A2A,
    EdgeType.COMPOSED_WITH: RelationshipLayer.A2A,
    EdgeType.UPGRADED: RelationshipLayer.A2A,
    EdgeType.GOVERNED_BY: RelationshipLayer.A2A,
    EdgeType.DEPENDS_ON: RelationshipLayer.A2A,
    EdgeType.PERFORMED_ACTION: RelationshipLayer.A2A,
}


# ═══════════════════════════════════════════════════════════════════════════
# CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

def classify_edge(edge: Edge) -> RelationshipLayer:
    """Classify an edge into its relationship layer (H2H, H2A, or A2A)."""
    layer = _EDGE_LAYER_MAP.get(edge.edge_type)
    if layer is None:
        logger.warning(f"Unknown edge type for layer classification: {edge.edge_type}")
        return RelationshipLayer.H2H  # Default to H2H for unknown edges
    return layer


def classify_edge_type(edge_type: str) -> RelationshipLayer:
    """Classify an edge type string into its relationship layer."""
    layer = _EDGE_LAYER_MAP.get(edge_type)
    if layer is None:
        return RelationshipLayer.H2H
    return layer


# ═══════════════════════════════════════════════════════════════════════════
# LAYER VERTEX SETS
# ═══════════════════════════════════════════════════════════════════════════

H2H_VERTEX_TYPES = frozenset({
    VertexType.USER, VertexType.SESSION, VertexType.DEVICE,
    VertexType.PAGE_VIEW, VertexType.EVENT, VertexType.COMPANY,
    VertexType.EMAIL, VertexType.PHONE, VertexType.WALLET,
    VertexType.DEVICE_FINGERPRINT, VertexType.IP_ADDRESS,
    VertexType.LOCATION, VertexType.IDENTITY_CLUSTER,
})

H2A_VERTEX_TYPES = frozenset({
    VertexType.USER, VertexType.AGENT, VertexType.SERVICE,
    VertexType.CAMPAIGN,
})

A2A_VERTEX_TYPES = frozenset({
    VertexType.AGENT, VertexType.SERVICE, VertexType.CONTRACT,
    VertexType.PROTOCOL, VertexType.PAYMENT, VertexType.ACTION_RECORD,
})


# ═══════════════════════════════════════════════════════════════════════════
# QUERY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

async def get_layer_subgraph(
    graph_client: GraphClient,
    user_id: str,
    layer: RelationshipLayer,
) -> dict:
    """
    Get the subgraph for a specific relationship layer starting from a user vertex.
    Returns dict with 'vertices' and 'edges' lists.
    """
    allowed_vertex_types = {
        RelationshipLayer.H2H: H2H_VERTEX_TYPES,
        RelationshipLayer.H2A: H2A_VERTEX_TYPES,
        RelationshipLayer.A2A: A2A_VERTEX_TYPES,
    }[layer]

    allowed_edge_types = {
        et for et, el in _EDGE_LAYER_MAP.items() if el == layer
    }

    # Get all neighbors from the user vertex, filtering by layer
    vertices: list[Vertex] = []

    neighbors = await graph_client.get_neighbors(user_id, direction="both")
    for neighbor in neighbors:
        if neighbor.vertex_type in allowed_vertex_types:
            vertices.append(neighbor)

    return {
        "layer": layer.value,
        "root_user_id": user_id,
        "vertices": [
            {"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties}
            for v in vertices
        ],
        "vertex_count": len(vertices),
        "edge_types": sorted(allowed_edge_types),
    }


async def get_cross_layer_paths(
    graph_client: GraphClient,
    user_id: str,
) -> list[dict]:
    """
    Find cross-layer paths: Human → Agent → Agent chains.
    Traces H2A delegation into A2A orchestration.
    """
    paths: list[dict] = []

    # Step 1: Find agents launched/delegated by user (H2A layer)
    agents = await graph_client.get_neighbors(
        user_id, edge_type=EdgeType.DELEGATES, direction="out"
    )
    launched = await graph_client.get_neighbors(
        user_id, edge_type=EdgeType.LAUNCHED_BY, direction="in"
    )
    all_agents = {a.vertex_id: a for a in agents + launched}

    # Step 2: For each agent, find A2A connections
    for agent_id, agent in all_agents.items():
        hired = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.HIRED, direction="out"
        )
        consumed = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.CONSUMES, direction="out"
        )
        deployed = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.DEPLOYED, direction="out"
        )

        if hired or consumed or deployed:
            paths.append({
                "user_id": user_id,
                "agent_id": agent_id,
                "agent_type": agent.properties.get("model_name", "unknown"),
                "h2a_edge": "DELEGATES",
                "a2a_connections": {
                    "hired_agents": [h.vertex_id for h in hired],
                    "consumed_services": [c.vertex_id for c in consumed],
                    "deployed_contracts": [d.vertex_id for d in deployed],
                },
            })

    return paths


def get_layer_stats(edges: list[Edge]) -> dict[str, int]:
    """Count edges by relationship layer."""
    counts = {layer.value: 0 for layer in RelationshipLayer}
    for edge in edges:
        layer = classify_edge(edge)
        counts[layer.value] += 1
    return counts
