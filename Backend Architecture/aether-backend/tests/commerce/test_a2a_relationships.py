"""Tests for A2A (Agent-to-Agent) relationship layer."""

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


# ── A2A edge type classification ──────────────────────────────────────────────

def test_pays_is_a2a() -> None:
    assert classify_edge_type(EdgeType.PAYS) == RelationshipLayer.A2A


def test_consumes_is_a2a() -> None:
    assert classify_edge_type(EdgeType.CONSUMES) == RelationshipLayer.A2A


def test_hired_is_a2a() -> None:
    assert classify_edge_type(EdgeType.HIRED) == RelationshipLayer.A2A


def test_deployed_is_a2a() -> None:
    assert classify_edge_type(EdgeType.DEPLOYED) == RelationshipLayer.A2A


def test_called_is_a2a() -> None:
    assert classify_edge_type(EdgeType.CALLED) == RelationshipLayer.A2A


def test_composed_with_is_a2a() -> None:
    assert classify_edge_type(EdgeType.COMPOSED_WITH) == RelationshipLayer.A2A


def test_governed_by_is_a2a() -> None:
    assert classify_edge_type(EdgeType.GOVERNED_BY) == RelationshipLayer.A2A


def test_depends_on_is_a2a() -> None:
    assert classify_edge_type(EdgeType.DEPENDS_ON) == RelationshipLayer.A2A


# ── A2A traversal ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a2a_hired_edge_traversable() -> None:
    client = await _build_client(
        _v("agent_1", "Agent"),
        _v("agent_2", "Agent"),
        edges=[_e("agent_1", "agent_2", EdgeType.HIRED)],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("agent_1", depth=1, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert "agent_2" in node_ids
    edge_types = {e.edge_type for e in result.edges}
    assert EdgeType.HIRED in edge_types


@pytest.mark.asyncio
async def test_a2a_multi_hop_hiring_chain() -> None:
    """Agent hiring chains must be traversable at appropriate depth."""
    client = await _build_client(
        _v("agent_1", "Agent"),
        _v("agent_2", "Agent"),
        _v("agent_3", "Agent"),
        edges=[
            _e("agent_1", "agent_2", EdgeType.HIRED),
            _e("agent_2", "agent_3", EdgeType.HIRED),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("agent_1", depth=2, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert "agent_2" in node_ids
    assert "agent_3" in node_ids


@pytest.mark.asyncio
async def test_a2a_economic_payment_edge() -> None:
    """A2A PAYS edge from agent to agent must be traversable."""
    client = await _build_client(
        _v("agent_1", "Agent"),
        _v("agent_2", "Agent"),
        edges=[_e("agent_1", "agent_2", EdgeType.PAYS)],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("agent_1", depth=1, direction="out")
    edge_types = {e.edge_type for e in result.edges}
    assert EdgeType.PAYS in edge_types


@pytest.mark.asyncio
async def test_a2a_layer_counted_in_stats() -> None:
    edges = [
        _e("a1", "a2", EdgeType.HIRED),
        _e("a1", "a2", EdgeType.PAYS),
        _e("a1", "s1", EdgeType.CONSUMES),
    ]
    stats = get_layer_stats(edges)
    assert stats["A2A"] == 3
    assert stats["H2H"] == 0
    assert stats["H2A"] == 0
    assert stats["A2H"] == 0


# ── A2A tenant isolation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a2a_edge_carries_tenant_id() -> None:
    client = await _build_client(
        _v("agent_1", "Agent", tenant_id="tenant_x"),
        _v("agent_2", "Agent", tenant_id="tenant_x"),
    )
    edge = _e("agent_1", "agent_2", EdgeType.HIRED, tenant_id="tenant_x")
    await client.add_edge(edge)
    edges = await client.get_edges("agent_1", direction="out")
    for e in edges:
        if e.edge_type == EdgeType.HIRED:
            assert (e.properties or {}).get("tenant_id") == "tenant_x"
