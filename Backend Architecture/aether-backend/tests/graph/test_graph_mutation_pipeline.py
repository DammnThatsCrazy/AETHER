"""Tests for graph mutation pipeline — deterministic, tenant-scoped, replayable."""

from __future__ import annotations

import pytest
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.relationship_layers import RelationshipLayer, classify_edge, classify_edge_type


async def _make_graph_client(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


def _v(vid: str, vtype: str = "User", tenant_id: str = "tenant_a", **props) -> Vertex:
    return Vertex(
        vertex_type=vtype,
        vertex_id=vid,
        properties={"tenant_id": tenant_id, **props},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(
    from_id: str,
    to_id: str,
    etype: str,
    tenant_id: str = "tenant_a",
) -> Edge:
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties={"tenant_id": tenant_id},
        created_at="2024-01-01T00:00:00+00:00",
    )


# ── Layer classification on mutations ─────────────────────────────────────────

def test_a2h_mutation_edge_classified_correctly() -> None:
    edge = _e("agent_1", "user_1", EdgeType.NOTIFIES)
    assert classify_edge(edge) == RelationshipLayer.A2H


def test_h2a_mutation_edge_classified_correctly() -> None:
    edge = _e("user_1", "agent_1", EdgeType.DELEGATES)
    assert classify_edge(edge) == RelationshipLayer.H2A


def test_a2a_mutation_edge_classified_correctly() -> None:
    edge = _e("agent_1", "agent_2", EdgeType.HIRED)
    assert classify_edge(edge) == RelationshipLayer.A2A


def test_h2h_mutation_edge_classified_correctly() -> None:
    edge = _e("user_1", "user_2", EdgeType.SIMILAR_TO)
    assert classify_edge(edge) == RelationshipLayer.H2H


# ── Graph write round-trip (in-memory) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_mutation_add_a2h_edge() -> None:
    """Adding an A2H edge to the graph succeeds and is retrievable."""
    client = await _make_graph_client(
        _v("agent_1", "Agent"),
        _v("user_1", "User"),
    )
    a2h_edge = _e("agent_1", "user_1", EdgeType.NOTIFIES)
    await client.add_edge(a2h_edge)

    edges = await client.get_edges("agent_1", direction="out")
    edge_types = [e.edge_type for e in edges]
    assert EdgeType.NOTIFIES in edge_types


@pytest.mark.asyncio
async def test_graph_mutation_add_h2a_edge() -> None:
    client = await _make_graph_client(
        _v("user_1", "User"),
        _v("agent_1", "Agent"),
    )
    h2a_edge = _e("user_1", "agent_1", EdgeType.DELEGATES)
    await client.add_edge(h2a_edge)

    edges = await client.get_edges("user_1", direction="out")
    edge_types = [e.edge_type for e in edges]
    assert EdgeType.DELEGATES in edge_types


@pytest.mark.asyncio
async def test_graph_mutation_all_four_layers_readable() -> None:
    """After writing edges from all four layers, all are readable."""
    client = await _make_graph_client(
        _v("u1", "User"), _v("u2", "User"),
        _v("a1", "Agent"), _v("a2", "Agent"),
        _v("s1", "Session"),
    )
    await client.add_edge(_e("u1", "s1", EdgeType.HAS_SESSION))     # H2H
    await client.add_edge(_e("u1", "a1", EdgeType.DELEGATES))       # H2A
    await client.add_edge(_e("a1", "u1", EdgeType.NOTIFIES))        # A2H
    await client.add_edge(_e("a1", "a2", EdgeType.HIRED))           # A2A

    edges_from_u1 = await client.get_edges("u1", direction="out")
    edge_types_u1 = {e.edge_type for e in edges_from_u1}
    assert EdgeType.HAS_SESSION in edge_types_u1
    assert EdgeType.DELEGATES in edge_types_u1

    edges_from_a1 = await client.get_edges("a1", direction="out")
    edge_types_a1 = {e.edge_type for e in edges_from_a1}
    assert EdgeType.NOTIFIES in edge_types_a1
    assert EdgeType.HIRED in edge_types_a1


# ── Tenant scope on mutations ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_id_on_added_vertex() -> None:
    """Vertices written to the graph carry tenant_id in properties."""
    client = await _make_graph_client()
    v = _v("user_x", "User", tenant_id="tenant_xyz")
    await client.add_vertex(v)
    retrieved = await client.get_vertex("user_x")
    assert retrieved is not None
    assert retrieved.properties.get("tenant_id") == "tenant_xyz"


@pytest.mark.asyncio
async def test_tenant_id_on_added_edge() -> None:
    """Edges written to the graph carry tenant_id in properties."""
    client = await _make_graph_client(
        _v("u1", "User", tenant_id="t1"),
        _v("a1", "Agent", tenant_id="t1"),
    )
    edge = _e("u1", "a1", EdgeType.DELEGATES, tenant_id="t1")
    await client.add_edge(edge)
    edges = await client.get_edges("u1", direction="out")
    for e in edges:
        if e.edge_type == EdgeType.DELEGATES:
            assert (e.properties or {}).get("tenant_id") == "t1"
