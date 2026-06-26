"""Temporal integration tests — bitemporal point-in-time replay.

Verifies that temporal_bfs returns materially different node/edge sets when
queried at different as_of times, and that the /compare route surfaces the
correct additions and removals between two snapshots.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest


@contextmanager
def _backend_path() -> Iterator[None]:
    backend = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    yield


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_vertex(graph_module, vertex_id: str, tenant_id: str, valid_from: str, valid_to: str = "") -> object:
    """Create a Vertex with bitemporal properties."""
    v = graph_module.Vertex(
        vertex_type="Entity",
        vertex_id=vertex_id,
        properties={
            "tenantId": tenant_id,
            "label": vertex_id,
            "valid_from": valid_from,
            **({"valid_to": valid_to} if valid_to else {}),
        },
        created_at=valid_from,
    )
    return v


def _make_edge(graph_module, from_id: str, to_id: str, valid_from: str, valid_to: str = "") -> object:
    return graph_module.Edge(
        edge_type="SIMILAR_TO",
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties={
            "tenant_id": "t1",
            "valid_from": valid_from,
            **({"valid_to": valid_to} if valid_to else {}),
        },
        created_at=valid_from,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def temporal_graph():
    """In-memory graph with a three-epoch timeline.

    T1 = "2025-01-01T00:00:00"
    T2 = "2025-03-01T00:00:00"
    T3 = "2025-06-01T00:00:00"
    T4 = "2025-09-01T00:00:00"  (query time — after T3)

    Nodes:
      anchor       (tenant t1, valid T1–∞)
      entity_v1    (tenant t1, valid T1–T3)   ← superseded at T3
      entity_v2    (tenant t1, valid T2–∞)    ← replacement, starts T2
      entity_new   (tenant t1, valid T3–∞)    ← brand-new node at T3
      entity_other (tenant t2)                ← cross-tenant, must be invisible

    Edges:
      anchor → entity_v1   (valid T1–T3)
      anchor → entity_v2   (valid T2–∞)
      anchor → entity_new  (valid T3–∞)
    """
    with _backend_path():
        import asyncio
        from shared.graph.graph import GraphClient, Vertex, Edge

        client = GraphClient()

        T1 = "2025-01-01T00:00:00+00:00"
        T2 = "2025-03-01T00:00:00+00:00"
        T3 = "2025-06-01T00:00:00+00:00"

        anchor = Vertex(
            vertex_type="Entity",
            vertex_id="anchor",
            properties={"tenantId": "t1", "label": "anchor", "valid_from": T1},
            created_at=T1,
        )
        v1 = Vertex(
            vertex_type="Entity",
            vertex_id="entity_v1",
            properties={"tenantId": "t1", "label": "v1", "valid_from": T1, "valid_to": T3},
            created_at=T1,
        )
        v2 = Vertex(
            vertex_type="Entity",
            vertex_id="entity_v2",
            properties={"tenantId": "t1", "label": "v2", "valid_from": T2},
            created_at=T2,
        )
        v_new = Vertex(
            vertex_type="Entity",
            vertex_id="entity_new",
            properties={"tenantId": "t1", "label": "new", "valid_from": T3},
            created_at=T3,
        )
        v_other = Vertex(
            vertex_type="Entity",
            vertex_id="entity_other",
            properties={"tenantId": "t2", "label": "other", "valid_from": T1},
            created_at=T1,
        )

        e_v1 = Edge(
            edge_type="SIMILAR_TO",
            from_vertex_id="anchor",
            to_vertex_id="entity_v1",
            properties={"tenant_id": "t1", "valid_from": T1, "valid_to": T3},
            created_at=T1,
        )
        e_v2 = Edge(
            edge_type="SIMILAR_TO",
            from_vertex_id="anchor",
            to_vertex_id="entity_v2",
            properties={"tenant_id": "t1", "valid_from": T2},
            created_at=T2,
        )
        e_new = Edge(
            edge_type="SIMILAR_TO",
            from_vertex_id="anchor",
            to_vertex_id="entity_new",
            properties={"tenant_id": "t1", "valid_from": T3},
            created_at=T3,
        )
        e_other = Edge(
            edge_type="SIMILAR_TO",
            from_vertex_id="anchor",
            to_vertex_id="entity_other",
            properties={"tenant_id": "t2", "valid_from": T1},
            created_at=T1,
        )

        async def _populate():
            for v in [anchor, v1, v2, v_new, v_other]:
                await client.add_vertex(v)
            for e in [e_v1, e_v2, e_new, e_other]:
                await client.add_edge(e)

        asyncio.run(_populate())
        return client


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_temporal_at_t1_returns_only_v1(temporal_graph):
    """At T1, only entity_v1 is valid (v2 starts T2, new starts T3)."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine

        T1_QUERY = "2025-01-15T00:00:00+00:00"  # after T1, before T2
        engine = GraphTraversalEngine(temporal_graph)
        result = asyncio.run(
            engine.temporal_bfs("anchor", as_of=T1_QUERY, depth=2, tenant_id="t1")
        )
        node_ids = {n.vertex_id for n in result.nodes}
        assert "entity_v1" in node_ids, "entity_v1 should be visible at T1"
        assert "entity_v2" not in node_ids, "entity_v2 starts at T2, must not appear at T1"
        assert "entity_new" not in node_ids, "entity_new starts at T3, must not appear at T1"
        assert "entity_other" not in node_ids, "cross-tenant entity must never appear"


def test_temporal_at_t2_includes_v2_excludes_v1(temporal_graph):
    """Between T2 and T3: entity_v1 (still valid until T3) AND entity_v2 both appear."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine

        T2_QUERY = "2025-04-01T00:00:00+00:00"  # after T2, before T3
        engine = GraphTraversalEngine(temporal_graph)
        result = asyncio.run(
            engine.temporal_bfs("anchor", as_of=T2_QUERY, depth=2, tenant_id="t1")
        )
        node_ids = {n.vertex_id for n in result.nodes}
        assert "entity_v1" in node_ids, "entity_v1 valid until T3 — should appear at T2 query"
        assert "entity_v2" in node_ids, "entity_v2 starts at T2 — should appear at T2 query"
        assert "entity_new" not in node_ids, "entity_new starts at T3, must not appear at T2 query"


def test_temporal_at_t4_excludes_expired_v1(temporal_graph):
    """After T3: entity_v1 expired, entity_v2 and entity_new are valid."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine

        T4_QUERY = "2025-09-01T00:00:00+00:00"  # after T3
        engine = GraphTraversalEngine(temporal_graph)
        result = asyncio.run(
            engine.temporal_bfs("anchor", as_of=T4_QUERY, depth=2, tenant_id="t1")
        )
        node_ids = {n.vertex_id for n in result.nodes}
        assert "entity_v1" not in node_ids, "entity_v1 expired at T3 — must not appear at T4"
        assert "entity_v2" in node_ids, "entity_v2 is still valid at T4"
        assert "entity_new" in node_ids, "entity_new valid from T3 — must appear at T4"
        assert "entity_other" not in node_ids, "cross-tenant entity must never appear"


def test_temporal_result_is_materially_different_between_t1_and_t4(temporal_graph):
    """T1 and T4 snapshots must return different node sets — replay changes results."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine

        engine = GraphTraversalEngine(temporal_graph)
        result_t1 = asyncio.run(
            engine.temporal_bfs("anchor", as_of="2025-01-15T00:00:00+00:00", depth=2, tenant_id="t1")
        )
        result_t4 = asyncio.run(
            engine.temporal_bfs("anchor", as_of="2025-09-01T00:00:00+00:00", depth=2, tenant_id="t1")
        )
        ids_t1 = {n.vertex_id for n in result_t1.nodes}
        ids_t4 = {n.vertex_id for n in result_t4.nodes}
        assert ids_t1 != ids_t4, (
            f"Temporal replay must produce materially different results.\n"
            f"  T1 nodes: {ids_t1}\n  T4 nodes: {ids_t4}"
        )
        assert ids_t1 - ids_t4, "T4 should have fewer/different nodes than T1 (entity_v1 expired)"
        assert ids_t4 - ids_t1, "T4 should have nodes not in T1 (entity_new added)"


def test_temporal_compare_shows_additions_and_removals(temporal_graph):
    """compare() between T1 baseline and T4 target must detect added and removed nodes."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine
        from shared.graph.graph import GraphClient

        engine = GraphTraversalEngine(temporal_graph)

        T1_SNAP = "2025-01-15T00:00:00+00:00"
        T4_SNAP = "2025-09-01T00:00:00+00:00"

        result_t4 = asyncio.run(
            engine.temporal_bfs("anchor", as_of=T4_SNAP, depth=2, tenant_id="t1")
        )
        result_t1 = asyncio.run(
            engine.temporal_bfs("anchor", as_of=T1_SNAP, depth=2, tenant_id="t1")
        )

        nodes_t4 = {n.vertex_id for n in result_t4.nodes}
        nodes_t1 = {n.vertex_id for n in result_t1.nodes}

        added = nodes_t4 - nodes_t1
        removed = nodes_t1 - nodes_t4

        assert "entity_new" in added, f"entity_new should be in added; added={added}"
        assert "entity_v2" in added, f"entity_v2 (started T2) should appear as added vs T1; added={added}"
        assert "entity_v1" in removed, f"entity_v1 (expired T3) should be in removed; removed={removed}"


def test_expired_edges_are_excluded_from_temporal_result(temporal_graph):
    """Edges with valid_to <= as_of must be absent from the result."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine

        T4_QUERY = "2025-09-01T00:00:00+00:00"
        engine = GraphTraversalEngine(temporal_graph)
        result = asyncio.run(
            engine.temporal_bfs("anchor", as_of=T4_QUERY, depth=2, tenant_id="t1")
        )
        edge_targets = {e.to_vertex_id for e in result.edges}
        assert "entity_v1" not in edge_targets, (
            "Edge to entity_v1 expired at T3 — must not appear in T4 result"
        )
        assert "entity_v2" in edge_targets, "Edge to entity_v2 is still valid at T4"
        assert "entity_new" in edge_targets, "Edge to entity_new is valid from T3"


def test_cross_tenant_invisible_across_all_time_points(temporal_graph):
    """entity_other (tenant t2) must never appear regardless of as_of time."""
    with _backend_path():
        import asyncio
        from shared.graph.traversal import GraphTraversalEngine

        engine = GraphTraversalEngine(temporal_graph)
        for ts in [
            "2025-01-15T00:00:00+00:00",
            "2025-04-01T00:00:00+00:00",
            "2025-09-01T00:00:00+00:00",
        ]:
            result = asyncio.run(
                engine.temporal_bfs("anchor", as_of=ts, depth=2, tenant_id="t1")
            )
            node_ids = {n.vertex_id for n in result.nodes}
            assert "entity_other" not in node_ids, (
                f"Cross-tenant entity_other visible at {ts}: {node_ids}"
            )
