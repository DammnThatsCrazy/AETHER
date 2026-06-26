"""Tests for GraphTraversalEngine new path algorithms: strongest_path, k_shortest_paths, multi_source_bfs."""
from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)
    if "jwt" not in sys.modules:
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "stub",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception,
                ExpiredSignatureError=Exception,
                InvalidTokenError=Exception,
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def _run(coro):
    return asyncio.run(coro)


async def _seed_graph_triangle(client, tenant_id="t1"):
    """Seed a 3-node triangle: A→B (high confidence), A→C→B (lower confidence)."""
    from shared.graph.graph import Edge, Vertex, VertexType

    for vid in ["A", "B", "C"]:
        v = Vertex(VertexType.USER, vid)
        v.properties["tenantId"] = tenant_id  # traversal engine filters on camelCase tenantId
        await client.add_vertex(v)

    # Direct A→B — high confidence
    e_ab = Edge("DELEGATES", "A", "B")
    e_ab.properties["confidence"] = 0.9
    await client.add_edge(e_ab)

    # A→C — lower confidence
    e_ac = Edge("DELEGATES", "A", "C")
    e_ac.properties["confidence"] = 0.5
    await client.add_edge(e_ac)

    # C→B — medium confidence
    e_cb = Edge("DELEGATES", "C", "B")
    e_cb.properties["confidence"] = 0.6
    await client.add_edge(e_cb)


def test_strongest_path_prefers_high_confidence_over_fewer_hops() -> None:
    """strongest_path should prefer the direct A→B edge (confidence 0.9) over A→C→B."""
    with backend_path():
        from shared.graph.graph import GraphClient
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            await _seed_graph_triangle(client)
            engine = GraphTraversalEngine(client)
            result = await engine.strongest_path("A", "B", max_depth=4, tenant_id="t1")
            assert result.nodes, "should find a path"
            # Direct path A→B has higher confidence — only 1 edge
            assert len(result.edges) == 1
            assert result.edges[0].from_vertex_id == "A"
            assert result.edges[0].to_vertex_id == "B"

        _run(run())


def test_k_shortest_paths_returns_k_results() -> None:
    with backend_path():
        from shared.graph.graph import GraphClient
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            await _seed_graph_triangle(client)
            engine = GraphTraversalEngine(client)
            results = await engine.k_shortest_paths("A", "B", k=2, max_depth=4, tenant_id="t1")
            assert len(results) == 2, f"expected 2 paths, got {len(results)}"

        _run(run())


def test_k_shortest_paths_deduplicates() -> None:
    with backend_path():
        from shared.graph.graph import GraphClient
        from shared.graph.path_scoring import make_path_id
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            await _seed_graph_triangle(client)
            engine = GraphTraversalEngine(client)
            results = await engine.k_shortest_paths("A", "B", k=5, max_depth=4, tenant_id="t1")
            path_ids = [make_path_id(r.ordered_node_ids) for r in results]
            assert len(path_ids) == len(set(path_ids)), "returned duplicate paths"

        _run(run())


def test_k_shortest_paths_tenant_isolation() -> None:
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            # Seed tenant t1 triangle
            await _seed_graph_triangle(client, tenant_id="t1")
            # Seed a different-tenant shortcut X→B
            vx = Vertex(VertexType.USER, "X")
            vx.properties["tenant_id"] = "t2"
            await client.add_vertex(vx)
            e = Edge("DELEGATES", "X", "B")
            e.properties["confidence"] = 1.0
            e.properties["tenant_id"] = "t2"
            await client.add_edge(e)

            engine = GraphTraversalEngine(client)
            results = await engine.k_shortest_paths("A", "B", k=3, max_depth=4, tenant_id="t1")
            for r in results:
                for node in r.nodes:
                    assert node.properties.get("tenant_id") in {None, "t1"}

        _run(run())


def test_multi_source_bfs_merges_seeds() -> None:
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            for vid in ["S1", "S2", "T1", "T2"]:
                v = Vertex(VertexType.USER, vid)
                v.properties["tenantId"] = "t1"
                await client.add_vertex(v)
            for (f, t) in [("S1", "T1"), ("S2", "T2")]:
                e = Edge("DELEGATES", f, t)
                await client.add_edge(e)

            engine = GraphTraversalEngine(client)
            result = await engine.multi_source_bfs(
                start_ids=["S1", "S2"], depth=1, direction="out", tenant_id="t1"
            )
            node_ids = {n.vertex_id for n in result.nodes}
            assert "T1" in node_ids, "S1's neighbor T1 should be in merged result"
            assert "T2" in node_ids, "S2's neighbor T2 should be in merged result"

        _run(run())


def test_strongest_path_returns_empty_when_no_path() -> None:
    with backend_path():
        from shared.graph.graph import GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            for vid in ["X", "Y"]:
                v = Vertex(VertexType.USER, vid)
                v.properties["tenant_id"] = "t1"
                await client.add_vertex(v)
            # No edges between X and Y
            engine = GraphTraversalEngine(client)
            result = await engine.strongest_path("X", "Y", max_depth=4, tenant_id="t1")
            assert result.nodes == [] or result.ordered_node_ids == [] or (
                len(result.nodes) == 1 and result.nodes[0].vertex_id == "X"
                and result.ordered_edge_ids == []
            )

        _run(run())
