"""Tests for H2A (Human-to-Agent) relationship layer."""

from __future__ import annotations

import pytest
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex
from shared.graph.relationship_layers import RelationshipLayer, classify_edge, classify_edge_type, get_layer_stats
from shared.graph.traversal import GraphTraversalEngine


def _v(vid: str, vtype: str, tenant_id: str = "tenant_a") -> Vertex:
    return Vertex(
        vertex_type=vtype,
        vertex_id=vid,
        properties={"tenant_id": tenant_id},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(from_id: str, to_id: str, etype: str, tenant_id: str = "tenant_a") -> Edge:
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties={"tenant_id": tenant_id},
        created_at="2024-01-01T00:00:00+00:00",
    )


async def _build_client(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


# ── H2A edge type classification ──────────────────────────────────────────────

def test_delegates_is_h2a() -> None:
    assert classify_edge_type(EdgeType.DELEGATES) == RelationshipLayer.H2A


def test_launched_by_is_h2a() -> None:
    assert classify_edge_type(EdgeType.LAUNCHED_BY) == RelationshipLayer.H2A


def test_interacts_with_is_h2a() -> None:
    assert classify_edge_type(EdgeType.INTERACTS_WITH) == RelationshipLayer.H2A


def test_attributed_to_is_h2a() -> None:
    assert classify_edge_type(EdgeType.ATTRIBUTED_TO) == RelationshipLayer.H2A


# ── H2A is distinct from A2H ──────────────────────────────────────────────────

def test_h2a_is_not_a2h() -> None:
    """H2A (human delegates to agent) is a different layer from A2H (agent notifies human)."""
    h2a_layer = classify_edge_type(EdgeType.DELEGATES)
    a2h_layer = classify_edge_type(EdgeType.NOTIFIES)
    assert h2a_layer != a2h_layer
    assert h2a_layer == RelationshipLayer.H2A
    assert a2h_layer == RelationshipLayer.A2H


# ── H2A traversal ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_h2a_delegation_edge_traversable() -> None:
    client = await _build_client(
        _v("user_1", "User"),
        _v("agent_1", "Agent"),
        edges=[_e("user_1", "agent_1", EdgeType.DELEGATES)],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("user_1", depth=1, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert "agent_1" in node_ids
    edge_types = {e.edge_type for e in result.edges}
    assert EdgeType.DELEGATES in edge_types


@pytest.mark.asyncio
async def test_h2a_layer_counted_in_stats() -> None:
    edges = [
        _e("user_1", "agent_1", EdgeType.DELEGATES),
        _e("user_1", "agent_2", EdgeType.DELEGATES),
    ]
    stats = get_layer_stats(edges)
    assert stats["H2A"] == 2
    assert stats["H2H"] == 0
    assert stats["A2H"] == 0
    assert stats["A2A"] == 0


# ── Cross-layer path: H2A → A2A ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_layer_h2a_to_a2a_path() -> None:
    """User → (H2A) → Agent → (A2A) → Agent path must be reachable in BFS depth=2."""
    client = await _build_client(
        _v("user_1", "User"),
        _v("agent_1", "Agent"),
        _v("agent_2", "Agent"),
        edges=[
            _e("user_1", "agent_1", EdgeType.DELEGATES),   # H2A
            _e("agent_1", "agent_2", EdgeType.HIRED),       # A2A
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("user_1", depth=2, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert "agent_1" in node_ids
    assert "agent_2" in node_ids


# ── Cross-layer path: H2A → A2H ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_layer_h2a_then_a2h_return() -> None:
    """User → (H2A) → Agent → (A2H) → User loop must be traversable at depth=2."""
    client = await _build_client(
        _v("user_1", "User"),
        _v("agent_1", "Agent"),
        edges=[
            _e("user_1", "agent_1", EdgeType.DELEGATES),   # H2A
            _e("agent_1", "user_1", EdgeType.NOTIFIES),    # A2H
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("user_1", depth=2, direction="out")
    edge_types = {e.edge_type for e in result.edges}
    assert EdgeType.DELEGATES in edge_types
