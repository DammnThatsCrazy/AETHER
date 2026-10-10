"""Tests for A2H (Agent-to-Human) relationship layer."""

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


# ── A2H edge type classification ──────────────────────────────────────────────

def test_notifies_is_a2h() -> None:
    assert classify_edge_type(EdgeType.NOTIFIES) == RelationshipLayer.A2H


def test_recommends_is_a2h() -> None:
    assert classify_edge_type(EdgeType.RECOMMENDS) == RelationshipLayer.A2H


def test_delivers_to_is_a2h() -> None:
    assert classify_edge_type(EdgeType.DELIVERS_TO) == RelationshipLayer.A2H


def test_escalates_to_is_a2h() -> None:
    assert classify_edge_type(EdgeType.ESCALATES_TO) == RelationshipLayer.A2H


def test_has_recommendation_is_a2h() -> None:
    assert classify_edge_type(EdgeType.HAS_RECOMMENDATION) == RelationshipLayer.A2H


def test_supported_by_is_a2h() -> None:
    assert classify_edge_type(EdgeType.SUPPORTED_BY) == RelationshipLayer.A2H


def test_selected_by_is_a2h() -> None:
    assert classify_edge_type(EdgeType.SELECTED_BY) == RelationshipLayer.A2H


# ── A2H edge direction ─────────────────────────────────────────────────────────

def test_a2h_notification_edge_direction_agent_to_user() -> None:
    """A2H edges go FROM agent TO user — notify, recommend, deliver, escalate."""
    edge = _e("agent_1", "user_1", EdgeType.NOTIFIES)
    layer = classify_edge(edge)
    assert layer == RelationshipLayer.A2H


# ── A2H traversal ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a2h_edges_are_traversable() -> None:
    """Agent-to-human edges must be reachable via BFS traversal."""
    client = await _build_client(
        _v("agent_1", "Agent"),
        _v("user_1", "User"),
        edges=[_e("agent_1", "user_1", EdgeType.NOTIFIES)],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("agent_1", depth=1, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert "user_1" in node_ids
    edge_types = {e.edge_type for e in result.edges}
    assert EdgeType.NOTIFIES in edge_types


@pytest.mark.asyncio
async def test_a2h_layer_counted_in_stats() -> None:
    """get_layer_stats must count A2H edges separately from other layers."""
    edges = [
        _e("agent_1", "user_1", EdgeType.NOTIFIES),
        _e("agent_1", "user_1", EdgeType.RECOMMENDS),
        _e("agent_1", "user_1", EdgeType.ESCALATES_TO),
    ]
    stats = get_layer_stats(edges)
    assert stats["A2H"] == 3
    assert stats["H2H"] == 0
    assert stats["H2A"] == 0
    assert stats["A2A"] == 0


@pytest.mark.asyncio
async def test_multiple_a2h_edge_types_on_same_agent() -> None:
    """An agent can have multiple A2H relationships to the same or different users."""
    client = await _build_client(
        _v("agent_1", "Agent"),
        _v("user_1", "User"),
        _v("user_2", "User"),
        edges=[
            _e("agent_1", "user_1", EdgeType.NOTIFIES),
            _e("agent_1", "user_1", EdgeType.RECOMMENDS),
            _e("agent_1", "user_2", EdgeType.ESCALATES_TO),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("agent_1", depth=1, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert "user_1" in node_ids
    assert "user_2" in node_ids


# ── Tenant isolation for A2H ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a2h_edge_carries_tenant_id() -> None:
    """A2H edges must carry tenant_id in their properties."""
    client = await _build_client(
        _v("agent_1", "Agent", tenant_id="tenant_xyz"),
        _v("user_1", "User", tenant_id="tenant_xyz"),
    )
    edge = _e("agent_1", "user_1", EdgeType.NOTIFIES, tenant_id="tenant_xyz")
    await client.add_edge(edge)
    edges = await client.get_edges("agent_1", direction="out")
    for e in edges:
        if e.edge_type == EdgeType.NOTIFIES:
            assert (e.properties or {}).get("tenant_id") == "tenant_xyz"
