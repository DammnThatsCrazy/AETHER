"""Tests for GraphTraversalEngine — BFS traversal, shortest path, and temporal BFS."""

from __future__ import annotations

import pytest
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.traversal import GraphTraversalEngine


async def _build_client(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()  # in-memory
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


def _v(vid: str, vtype: str = "User", **props) -> Vertex:
    return Vertex(vertex_type=vtype, vertex_id=vid, properties=props)


def _e(from_id: str, to_id: str, etype: str = "RELATED", created_at: str = "2024-01-01T00:00:00+00:00") -> Edge:
    return Edge(edge_type=etype, from_vertex_id=from_id, to_vertex_id=to_id, created_at=created_at)


# ── BFS traversal ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bfs_single_hop():
    """BFS depth=1 returns direct neighbours only."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"), _v("d"),
        edges=[_e("a", "b"), _e("a", "c"), _e("d", "a")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("a", depth=1, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert node_ids == {"b", "c"}
    assert len(result.edges) == 2


@pytest.mark.asyncio
async def test_bfs_multi_hop():
    """BFS depth=2 reaches two hops from start."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[_e("a", "b"), _e("b", "c")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("a", depth=2, direction="out")
    node_ids = {n.vertex_id for n in result.nodes}
    assert node_ids == {"b", "c"}


@pytest.mark.asyncio
async def test_bfs_both_direction():
    """BFS with direction=both traverses inbound and outbound edges."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[_e("b", "a"), _e("a", "c")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("a", depth=1, direction="both")
    node_ids = {n.vertex_id for n in result.nodes}
    assert node_ids == {"b", "c"}


@pytest.mark.asyncio
async def test_bfs_edge_type_filter():
    """BFS only follows edges of the specified type."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[_e("a", "b", "OWNS_WALLET"), _e("a", "c", "HAS_SESSION")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("a", depth=1, direction="out", edge_types=["OWNS_WALLET"])
    node_ids = {n.vertex_id for n in result.nodes}
    assert node_ids == {"b"}
    assert "c" not in node_ids


@pytest.mark.asyncio
async def test_bfs_limit():
    """BFS respects the node limit."""
    verts = [_v(str(i)) for i in range(10)]
    edges = [_e("0", str(i)) for i in range(1, 10)]
    client = await _build_client(*verts, edges=edges)
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("0", depth=1, direction="out", limit=3)
    assert len(result.nodes) <= 3


@pytest.mark.asyncio
async def test_bfs_no_cycles():
    """BFS does not visit the same node twice even with bidirectional edges."""
    client = await _build_client(
        _v("a"), _v("b"),
        edges=[_e("a", "b"), _e("b", "a")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.bfs("a", depth=5, direction="both")
    node_ids = [n.vertex_id for n in result.nodes]
    assert node_ids.count("b") == 1


# ── Shortest path ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shortest_path_direct():
    """Shortest path between directly connected nodes returns one edge."""
    client = await _build_client(
        _v("a"), _v("b"),
        edges=[_e("a", "b")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.shortest_path("a", "b")
    node_ids = [n.vertex_id for n in result.nodes]
    assert "a" in node_ids and "b" in node_ids
    assert len(result.edges) == 1


@pytest.mark.asyncio
async def test_shortest_path_two_hops():
    """Shortest path finds a 2-hop route."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[_e("a", "b"), _e("b", "c")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.shortest_path("a", "c")
    node_ids = [n.vertex_id for n in result.nodes]
    assert "a" in node_ids and "b" in node_ids and "c" in node_ids


@pytest.mark.asyncio
async def test_shortest_path_no_route():
    """Shortest path returns empty result when no route exists."""
    client = await _build_client(
        _v("a"), _v("b"),
        edges=[],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.shortest_path("a", "b")
    assert result.nodes == []
    assert result.edges == []


@pytest.mark.asyncio
async def test_shortest_path_same_node():
    """Shortest path from a node to itself returns that node."""
    client = await _build_client(_v("a"))
    engine = GraphTraversalEngine(client)
    result = await engine.shortest_path("a", "a")
    assert len(result.nodes) == 1
    assert result.nodes[0].vertex_id == "a"


# ── Temporal BFS ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_temporal_bfs_excludes_future_edges():
    """Temporal BFS omits edges created after as_of."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[
            _e("a", "b", created_at="2023-06-01T00:00:00+00:00"),
            _e("a", "c", created_at="2025-06-01T00:00:00+00:00"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.temporal_bfs("a", as_of="2024-01-01T00:00:00+00:00", depth=1)
    node_ids = {n.vertex_id for n in result.nodes}
    assert "b" in node_ids
    assert "c" not in node_ids


@pytest.mark.asyncio
async def test_temporal_bfs_includes_edges_at_boundary():
    """Temporal BFS includes edges where created_at == as_of."""
    client = await _build_client(
        _v("a"), _v("b"),
        edges=[_e("a", "b", created_at="2024-01-01T00:00:00+00:00")],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.temporal_bfs("a", as_of="2024-01-01T00:00:00+00:00", depth=1)
    assert any(n.vertex_id == "b" for n in result.nodes)
