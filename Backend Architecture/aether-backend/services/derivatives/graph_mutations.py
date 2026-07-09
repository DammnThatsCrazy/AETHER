"""Derivatives graph projections — deterministic, tenant-scoped,
evidence-bearing. Orders/fills/positions stay silver facts; only accounts,
venues, markets, and material relationships project into the graph."""

from __future__ import annotations

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from services.derivatives.foundation import utc_now_iso

_PROVENANCE = "derivatives_intelligence"


def build_account_mutations(account: dict) -> tuple[list[Vertex], list[Edge]]:
    """TRADING_ACCOUNT vertex + AUTHENTICATES edge to the venue, plus
    DELEGATES_TRADING_TO (H2A) when the account is agent-directed with a
    resolved human owner."""
    tenant_id = account["tenant_id"]
    account_vid = f"trading_account:{account['trading_account_id']}"
    venue_vid = f"market_venue:{account['venue_id']}"

    vertices = [
        Vertex(
            vertex_id=account_vid,
            vertex_type=VertexType.TRADING_ACCOUNT,
            properties={
                "tenant_id": tenant_id,
                "venue_id": account["venue_id"],
                "connector_state": account.get("connector_state", "configured"),
            },
        ),
        Vertex(
            vertex_id=venue_vid,
            vertex_type=VertexType.MARKET_VENUE,
            properties={"tenant_id": "platform", "venue_id": account["venue_id"]},
        ),
    ]
    edges = [
        Edge(
            edge_type=EdgeType.AUTHENTICATES,
            from_vertex_id=account_vid,
            to_vertex_id=venue_vid,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.AUTHENTICATES,
                from_vertex_id=account_vid,
                to_vertex_id=venue_vid,
                actor_kind="service",
                actor_id="derivatives_registry",
                provenance=_PROVENANCE,
                valid_from=utc_now_iso(),
                source_event_id=account.get("idempotency_key", ""),
                authority_type="read_only",
            ),
        ),
    ]

    owner_kind = account.get("owner_entity_kind")
    owner_id = account.get("owner_entity_id")
    if owner_kind == "human" and owner_id and account.get("agent_directed"):
        owner_vid = f"entity:human:{owner_id}"
        agent_vid = f"agent:{account.get('agent_id', 'unresolved')}"
        edges.append(Edge(
            edge_type=EdgeType.DELEGATES_TRADING_TO,
            from_vertex_id=owner_vid,
            to_vertex_id=agent_vid,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.DELEGATES_TRADING_TO,
                from_vertex_id=owner_vid,
                to_vertex_id=agent_vid,
                actor_kind="human",
                actor_id=owner_id,
                provenance=_PROVENANCE,
                valid_from=utc_now_iso(),
                source_event_id=account.get("idempotency_key", ""),
            ),
        ))
    return vertices, edges


def build_position_mutations(position: dict) -> tuple[list[Vertex], list[Edge]]:
    """HOLDS_POSITION edge from the owning account to the market vertex —
    the position itself remains a silver fact (cardinality)."""
    tenant_id = position["tenant_id"]
    account_vid = f"trading_account:{position['trading_account_id']}"
    market_vid = f"derivative_market:{position['canonical_market_id']}"
    vertices = [
        Vertex(
            vertex_id=market_vid,
            vertex_type=VertexType.MARKET,
            properties={
                "tenant_id": "platform",
                "canonical_market_id": position["canonical_market_id"],
            },
        ),
    ]
    edges = [
        Edge(
            edge_type=EdgeType.HOLDS_POSITION,
            from_vertex_id=account_vid,
            to_vertex_id=market_vid,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.HOLDS_POSITION,
                from_vertex_id=account_vid,
                to_vertex_id=market_vid,
                actor_kind="service",
                actor_id="derivatives_positions",
                provenance=_PROVENANCE,
                valid_from=position.get("updated_at") or utc_now_iso(),
                source_event_id=position.get("position_id", ""),
                status=position.get("status", "unknown"),
                side=position.get("side", "unknown"),
            ),
        ),
    ]
    return vertices, edges
