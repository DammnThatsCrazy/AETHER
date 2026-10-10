"""Tests for graph replay — temporal BFS must be deterministic and tenant-scoped."""

from __future__ import annotations

import pytest
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex
from shared.graph.traversal import GraphTraversalEngine


def _v(vid: str, vtype: str = "User", created_at: str = "2024-01-01T00:00:00+00:00") -> Vertex:
    return Vertex(vertex_type=vtype, vertex_id=vid, properties={}, created_at=created_at)


def _e(
    from_id: str, to_id: str, etype: str, created_at: str = "2024-06-01T00:00:00+00:00"
) -> Edge:
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        created_at=created_at,
    )


async def _build_client(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


@pytest.mark.asyncio
async def test_temporal_bfs_excludes_edges_after_cutoff() -> None:
    """Edges created after asOf must not appear in temporal BFS."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[
            _e("a", "b", EdgeType.HAS_SESSION, created_at="2024-01-01T00:00:00+00:00"),
            _e("b", "c", EdgeType.VIEWED_PAGE, created_at="2025-01-01T00:00:00+00:00"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.temporal_bfs(
        start_id="a",
        as_of="2024-06-01T00:00:00+00:00",
        depth=2,
        direction="out",
        limit=100,
    )
    node_ids = {n.vertex_id for n in result.nodes}
    assert "b" in node_ids
    assert "c" not in node_ids, "Edge after cutoff must not appear in temporal BFS"


@pytest.mark.asyncio
async def test_temporal_bfs_includes_edges_at_or_before_cutoff() -> None:
    """Edges at or before asOf must be included in temporal BFS."""
    client = await _build_client(
        _v("a"), _v("b"),
        edges=[
            _e("a", "b", EdgeType.HAS_SESSION, created_at="2024-06-01T00:00:00+00:00"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.temporal_bfs(
        start_id="a",
        as_of="2024-06-01T00:00:00+00:00",
        depth=1,
        direction="out",
        limit=100,
    )
    node_ids = {n.vertex_id for n in result.nodes}
    assert "b" in node_ids


@pytest.mark.asyncio
async def test_temporal_bfs_is_deterministic() -> None:
    """Replaying the same temporal BFS query produces the same result."""
    client = await _build_client(
        _v("a"), _v("b"), _v("c"),
        edges=[
            _e("a", "b", EdgeType.HAS_SESSION, created_at="2024-01-01T00:00:00+00:00"),
            _e("a", "c", EdgeType.VIEWED_PAGE, created_at="2024-03-01T00:00:00+00:00"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result1 = await engine.temporal_bfs(
        start_id="a", as_of="2024-06-01T00:00:00+00:00", depth=1, direction="out", limit=100
    )
    result2 = await engine.temporal_bfs(
        start_id="a", as_of="2024-06-01T00:00:00+00:00", depth=1, direction="out", limit=100
    )
    assert {n.vertex_id for n in result1.nodes} == {n.vertex_id for n in result2.nodes}
    assert len(result1.edges) == len(result2.edges)


@pytest.mark.asyncio
async def test_temporal_bfs_a2h_layer_edges_are_replayed() -> None:
    """Temporal BFS must replay A2H edges when they fall within the time window."""
    client = await _build_client(
        _v("agent_1", "Agent"),
        _v("user_1", "User"),
        edges=[
            _e("agent_1", "user_1", EdgeType.NOTIFIES, created_at="2024-01-01T00:00:00+00:00"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.temporal_bfs(
        start_id="agent_1",
        as_of="2024-12-31T00:00:00+00:00",
        depth=1,
        direction="out",
        limit=100,
    )
    edge_types = {e.edge_type for e in result.edges}
    assert EdgeType.NOTIFIES in edge_types
