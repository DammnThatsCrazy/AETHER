"""Tests for synthetic graph replay workloads — idempotency, layer counts, consistency."""

from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_props(tenant_id: str, edge_type: str, from_id: str, to_id: str,
                consent_purpose: str = "") -> dict:
    with backend_path():
        from shared.graph.edge_properties import build_edge_properties
        return build_edge_properties(
            tenant_id=tenant_id,
            edge_type=edge_type,
            from_vertex_id=from_id,
            to_vertex_id=to_id,
            actor_kind="system",
            actor_id="test-replay",
            provenance="test_graph_replay_workloads",
            valid_from=_now(),
            confidence=1.0,
            consent_purpose=consent_purpose,
        )


def test_h2h_replay_creates_expected_edges() -> None:
    with backend_path():
        from shared.graph.edge_properties import build_edge_properties
        from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
        from shared.graph.relationship_layers import RelationshipLayer, get_layer_stats

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "u1", {"tenant_id": "t1"}))
            await client.add_vertex(Vertex(VertexType.SESSION, "s1", {"tenant_id": "t1"}))
            props = build_edge_properties(
                "t1", EdgeType.HAS_SESSION, "u1", "s1",
                actor_kind="system", actor_id="test", provenance="test",
                valid_from=_now(), confidence=1.0,
            )
            edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", props)
            await client.add_edge(edge)
            stats = get_layer_stats([edge])
            assert stats[RelationshipLayer.H2H.value] == 1

        _run(run())


def test_all_four_layers_covered_in_replay() -> None:
    """A complete replay fixture must produce edges in all four layers."""
    with backend_path():
        from shared.graph.edge_properties import build_edge_properties
        from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
        from shared.graph.relationship_layers import RelationshipLayer, get_layer_stats

        async def run():
            client = GraphClient()
            await client.connect()
            for vt, vid in [
                (VertexType.USER, "u1"),
                (VertexType.AGENT, "a1"),
                (VertexType.SESSION, "s1"),
                (VertexType.AGENT, "a2"),
            ]:
                await client.add_vertex(Vertex(vt, vid, {"tenant_id": "t1"}))

            def p(et, f, t, cp=""):
                return build_edge_properties(
                    "t1", et, f, t, actor_kind="system", actor_id="test",
                    provenance="test", valid_from=_now(), confidence=1.0,
                    consent_purpose=cp,
                )

            edges = [
                Edge(EdgeType.HAS_SESSION, "u1", "s1", p(EdgeType.HAS_SESSION, "u1", "s1")),
                Edge(EdgeType.DELEGATES, "u1", "a1", p(EdgeType.DELEGATES, "u1", "a1", "delegation")),
                Edge(EdgeType.NOTIFIES, "a1", "u1", p(EdgeType.NOTIFIES, "a1", "u1", "notification")),
                Edge(EdgeType.HIRED, "a1", "a2", p(EdgeType.HIRED, "a1", "a2")),
            ]
            for e in edges:
                await client.add_edge(e)

            stats = get_layer_stats(edges)
            for layer in (RelationshipLayer.H2H, RelationshipLayer.H2A,
                          RelationshipLayer.A2H, RelationshipLayer.A2A):
                assert stats[layer.value] >= 1, f"Layer {layer.value} has no edges in replay"

        _run(run())


def test_duplicate_replay_is_safe() -> None:
    """Writing the same edge twice (same idempotency_key) should not raise."""
    with backend_path():
        from shared.graph.edge_properties import build_edge_properties
        from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType

        async def run():
            client = GraphClient()
            await client.connect()
            await client.add_vertex(Vertex(VertexType.USER, "u1"))
            await client.add_vertex(Vertex(VertexType.SESSION, "s1"))
            props = build_edge_properties(
                "t1", EdgeType.HAS_SESSION, "u1", "s1",
                actor_kind="system", actor_id="test", provenance="test",
                valid_from=_now(), confidence=1.0,
            )
            edge = Edge(EdgeType.HAS_SESSION, "u1", "s1", props)
            await client.add_edge(edge)
            # Second write — must not raise
            await client.add_edge(edge)

        _run(run())


def test_unknown_edge_counted_as_unknown_in_stats() -> None:
    """An edge with an unmapped type should appear under 'unknown' in get_layer_stats."""
    with backend_path():
        from shared.graph.graph import Edge
        from shared.graph.relationship_layers import get_layer_stats

        edge = Edge("SOME_FUTURE_EDGE_TYPE", "a", "b")
        stats = get_layer_stats([edge])
        assert stats["unknown"] == 1


def test_replay_produces_no_unknown_edges_for_standard_types() -> None:
    """Standard EdgeType values must produce zero 'unknown' edges in stats."""
    with backend_path():
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.relationship_layers import get_layer_stats

        standard_edges = [
            Edge(EdgeType.HAS_SESSION, "u1", "s1"),
            Edge(EdgeType.DELEGATES, "u1", "a1"),
            Edge(EdgeType.NOTIFIES, "a1", "u1"),
            Edge(EdgeType.HIRED, "a1", "a2"),
            Edge(EdgeType.PAYS, "a1", "a2"),
            Edge(EdgeType.CALLED_TOOL, "a1", "t1"),
            Edge(EdgeType.OWNS_ACCOUNT, "u1", "acc1"),
            Edge(EdgeType.HOLDS_TOKEN, "w1", "tok1"),
        ]
        stats = get_layer_stats(standard_edges)
        assert stats["unknown"] == 0, (
            f"Standard edges produced {stats['unknown']} unknown classifications"
        )
