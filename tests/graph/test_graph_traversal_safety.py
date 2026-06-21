"""Tests for traversal safety — depth limits, result caps, and A2A cycle detection."""

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
    for prefix in ("shared",):
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    if "jwt" not in sys.modules:
        sys.modules["jwt"] = types.SimpleNamespace(
            encode=lambda *a, **kw: "stub",
            decode=lambda *a, **kw: {},
            exceptions=types.SimpleNamespace(
                PyJWTError=Exception, ExpiredSignatureError=Exception, InvalidTokenError=Exception
            ),
        )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


def _run(coro):
    return asyncio.run(coro)


def test_traversal_result_has_a2a_cycles_detected_field() -> None:
    with backend_path():
        from shared.graph.traversal import TraversalResult
        r = TraversalResult()
        assert hasattr(r, "a2a_cycles_detected")
        assert isinstance(r.a2a_cycles_detected, list)


def test_bfs_respects_depth_limit() -> None:
    """BFS with depth=1 must not return nodes 2+ hops away."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "n1"))
            await client.add_vertex(Vertex(VertexType.USER, "n2"))
            await client.add_vertex(Vertex(VertexType.USER, "n3"))
            await client.add_edge(Edge("RELATED", "n1", "n2"))
            await client.add_edge(Edge("RELATED", "n2", "n3"))
            engine = GraphTraversalEngine(client)
            result = await engine.bfs("n1", depth=1, direction="out")
            node_ids = {n.vertex_id for n in result.nodes}
            assert "n2" in node_ids
            assert "n3" not in node_ids, "depth=1 should not reach n3 (2 hops away)"

        _run(run())


def test_bfs_respects_result_limit() -> None:
    """BFS with limit=2 must not return more than 2 nodes."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            root = "root"
            await client.add_vertex(Vertex(VertexType.USER, root))
            for i in range(10):
                vid = f"neighbor-{i}"
                await client.add_vertex(Vertex(VertexType.USER, vid))
                await client.add_edge(Edge("RELATED", root, vid))
            engine = GraphTraversalEngine(client)
            result = await engine.bfs(root, depth=1, limit=2)
            assert len(result.nodes) <= 2, f"limit=2 violated; got {len(result.nodes)} nodes"

        _run(run())


def test_a2a_cycle_detected_in_bfs() -> None:
    """BFS must detect A2A cycle when an agent is re-visited via HIRED edges."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.AGENT, "a1"))
            await client.add_vertex(Vertex(VertexType.AGENT, "a2"))
            # A2A cycle: a1 → a2 → a1
            await client.add_edge(Edge("HIRED", "a1", "a2"))
            await client.add_edge(Edge("HIRED", "a2", "a1"))
            engine = GraphTraversalEngine(client)
            result = await engine.bfs("a1", depth=3, direction="out")
            assert len(result.a2a_cycles_detected) > 0, (
                "Expected A2A cycle to be detected for a1→a2→a1"
            )

        _run(run())


def test_no_false_positive_cycles_in_h2h_traversal() -> None:
    """BFS over non-A2A edge types must not produce cycle detections."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.traversal import GraphTraversalEngine

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "u1"))
            await client.add_vertex(Vertex(VertexType.SESSION, "s1"))
            await client.add_vertex(Vertex(VertexType.SESSION, "s2"))
            await client.add_edge(Edge("HAS_SESSION", "u1", "s1"))
            await client.add_edge(Edge("HAS_SESSION", "u1", "s2"))
            engine = GraphTraversalEngine(client)
            result = await engine.bfs("u1", depth=2, direction="out")
            assert result.a2a_cycles_detected == [], (
                f"H2H traversal should not produce cycle detections; got {result.a2a_cycles_detected}"
            )

        _run(run())


def test_get_layer_subgraph_respects_max_hops() -> None:
    """get_layer_subgraph with max_hops=1 must not traverse 2-hop neighbors."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.relationship_layers import RelationshipLayer, get_layer_subgraph

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "root", {"tenant_id": "t1"}))
            await client.add_vertex(Vertex(VertexType.SESSION, "hop1", {"tenant_id": "t1"}))
            await client.add_vertex(Vertex(VertexType.SESSION, "hop2", {"tenant_id": "t1"}))
            await client.add_edge(Edge("HAS_SESSION", "root", "hop1"))
            await client.add_edge(Edge("HAS_SESSION", "hop1", "hop2"))

            result = await get_layer_subgraph(
                client, "root", RelationshipLayer.H2H, tenant_id="t1", max_hops=1
            )
            vertex_ids = {v["id"] for v in result["vertices"]}
            assert "hop1" in vertex_ids
            assert "hop2" not in vertex_ids, "max_hops=1 should not include hop2"

        _run(run())


def test_get_layer_subgraph_respects_max_results() -> None:
    """get_layer_subgraph with max_results=3 must return at most 3 vertices."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.relationship_layers import RelationshipLayer, get_layer_subgraph

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "root", {"tenant_id": "t1"}))
            for i in range(10):
                vid = f"sess-{i}"
                await client.add_vertex(Vertex(VertexType.SESSION, vid, {"tenant_id": "t1"}))
                await client.add_edge(Edge("HAS_SESSION", "root", vid))

            result = await get_layer_subgraph(
                client, "root", RelationshipLayer.H2H, tenant_id="t1", max_results=3
            )
            assert result["vertex_count"] <= 3

        _run(run())


def test_get_cross_layer_paths_respects_max_depth() -> None:
    """get_cross_layer_paths must not exceed max_depth agents."""
    with backend_path():
        from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
        from shared.graph.relationship_layers import get_cross_layer_paths

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "user1"))
            for i in range(5):
                aid = f"agent-{i}"
                await client.add_vertex(Vertex(VertexType.AGENT, aid))
                await client.add_edge(Edge("DELEGATES", "user1", aid))

            paths = await get_cross_layer_paths(client, "user1", max_depth=2)
            assert len(paths) <= 2, f"Expected at most 2 paths (max_depth=2), got {len(paths)}"

        _run(run())
