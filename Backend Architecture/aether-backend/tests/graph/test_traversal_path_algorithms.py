"""Tests for GraphTraversalEngine new path algorithms — 6 tests."""

from __future__ import annotations

import pytest
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.traversal import GraphTraversalEngine


async def _build_client(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


def _v(vid: str, vtype: str = "User", tenant: str = "t1", **props) -> Vertex:
    return Vertex(
        vertex_type=vtype,
        vertex_id=vid,
        properties={"tenantId": tenant, **props},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(
    from_id: str,
    to_id: str,
    etype: str = "RELATED",
    confidence: float = 1.0,
    causality_class: str = "",
    eid: str = "",  # unused — Edge has no edge_id field; key is (from, to, type)
) -> Edge:
    props: dict = {"confidence": confidence}
    if causality_class:
        props["causality_class"] = causality_class
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties=props,
        created_at="2024-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Test 1: strongest_path prefers high-confidence over short hops
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strongest_path_prefers_high_confidence():
    """strongest_path should choose the higher-confidence path even if it's longer."""
    # Paths: A→B→D (confidence 0.5 each) vs A→C→D (confidence 0.9 each)
    client = await _build_client(
        _v("A"), _v("B"), _v("C"), _v("D"),
        edges=[
            _e("A", "B", confidence=0.5, eid="ab"),
            _e("B", "D", confidence=0.5, eid="bd"),
            _e("A", "C", confidence=0.9, eid="ac"),
            _e("C", "D", confidence=0.9, eid="cd"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.strongest_path("A", "D", max_depth=4, tenant_id="t1")
    assert result.nodes, "Expected a path to be found"
    node_ids = [n.vertex_id for n in result.nodes]
    # A→C→D costs 0.2 each (cost=0.2), A→B→D costs 1.0 each (cost=1.0) → should pick A→C→D
    assert "C" in node_ids


# ---------------------------------------------------------------------------
# Test 2: k_shortest_paths returns up to k results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_k_shortest_paths_returns_k_results():
    """k_shortest_paths should return multiple distinct paths."""
    # Graph with three parallel paths from S to T
    client = await _build_client(
        _v("S"), _v("M1"), _v("M2"), _v("M3"), _v("T"),
        edges=[
            _e("S", "M1", eid="s-m1"), _e("M1", "T", eid="m1-t"),
            _e("S", "M2", eid="s-m2"), _e("M2", "T", eid="m2-t"),
            _e("S", "M3", eid="s-m3"), _e("M3", "T", eid="m3-t"),
        ],
    )
    engine = GraphTraversalEngine(client)
    results = await engine.k_shortest_paths("S", "T", k=3, max_depth=4, tenant_id="t1")
    assert len(results) == 3, f"Expected 3 paths, got {len(results)}"


# ---------------------------------------------------------------------------
# Test 3: k_shortest_paths deduplicates identical paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_k_shortest_paths_deduplicates():
    """k_shortest_paths must not return the same path twice (checked by path_id)."""
    from shared.graph.path_scoring import make_path_id
    client = await _build_client(
        _v("A"), _v("B"),
        edges=[_e("A", "B", eid="ab")],
    )
    engine = GraphTraversalEngine(client)
    results = await engine.k_shortest_paths("A", "B", k=3, max_depth=4, tenant_id="t1")
    path_ids = [make_path_id([n.vertex_id for n in r.nodes]) for r in results]
    assert len(path_ids) == len(set(path_ids)), "Duplicate paths returned"


# ---------------------------------------------------------------------------
# Test 4: k_shortest_paths respects tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_k_shortest_paths_tenant_isolation():
    """k_shortest_paths must not traverse cross-tenant nodes."""
    client = await _build_client(
        _v("A", tenant="t1"),
        _v("CROSS", tenant="t2"),   # cross-tenant middle node
        _v("B", tenant="t1"),
        edges=[
            _e("A", "CROSS", eid="a-cross"),
            _e("CROSS", "B", eid="cross-b"),
        ],
    )
    engine = GraphTraversalEngine(client)
    results = await engine.k_shortest_paths("A", "B", k=3, max_depth=4, tenant_id="t1")
    for result in results:
        node_ids = [n.vertex_id for n in result.nodes]
        assert "CROSS" not in node_ids, "Cross-tenant node leaked into path"


# ---------------------------------------------------------------------------
# Test 5: multi_source_bfs merges results from multiple seeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_source_bfs_merges_seeds():
    """multi_source_bfs should include neighbors of all seeds in the result."""
    client = await _build_client(
        _v("S1"), _v("S2"), _v("N1"), _v("N2"),
        edges=[
            _e("S1", "N1", eid="s1n1"),
            _e("S2", "N2", eid="s2n2"),
        ],
    )
    engine = GraphTraversalEngine(client)
    result = await engine.multi_source_bfs(
        start_ids=["S1", "S2"],
        depth=1,
        direction="out",
        tenant_id="t1",
    )
    node_ids = {n.vertex_id for n in result.nodes}
    assert "N1" in node_ids, "Expected N1 from S1"
    assert "N2" in node_ids, "Expected N2 from S2"


# ---------------------------------------------------------------------------
# Test 6: strongest_path returns empty result when no path exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strongest_path_no_path_returns_empty():
    """strongest_path must return an empty TraversalResult when from and to are disconnected."""
    client = await _build_client(
        _v("X"), _v("Y"),
        # No edges between X and Y
    )
    engine = GraphTraversalEngine(client)
    result = await engine.strongest_path("X", "Y", max_depth=4, tenant_id="t1")
    assert result.nodes == [], "Expected empty nodes for disconnected path"
    assert result.edges == [], "Expected empty edges for disconnected path"
