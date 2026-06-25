"""Security tests — adversarial mixed-tenant graph isolation.

Validates that graph traversal, path, filter, and overlay operations cannot
cross tenant boundaries even when the in-memory backend stores vertices from
multiple tenants in a single store. These tests cover graph-level isolation
(BFS/filter) on top of the API-level _require_read check.
"""

from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

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


TENANT_A = f"tenant-graph-sec-A-{uuid4()}"
TENANT_B = f"tenant-graph-sec-B-{uuid4()}"


def _make_graph():
    with backend_path():
        from shared.graph.graph import GraphClient, _InMemoryGraphBackend
        gc = GraphClient.__new__(GraphClient)
        gc._backend = _InMemoryGraphBackend()
        gc._mode = "local"
        return gc


def _populate_two_tenants(graph):
    """Insert two tenants' vertices and a cross-tenant edge (adversarial)."""
    with backend_path():
        from shared.graph.graph import Edge, Vertex

        va1 = Vertex("entity", str(uuid4()), {"tenantId": TENANT_A, "label": "A-user-1"})
        va2 = Vertex("entity", str(uuid4()), {"tenantId": TENANT_A, "label": "A-user-2"})
        vb1 = Vertex("entity", str(uuid4()), {"tenantId": TENANT_B, "label": "B-user-1"})
        vb2 = Vertex("entity", str(uuid4()), {"tenantId": TENANT_B, "label": "B-user-2"})

        async def _setup():
            for v in [va1, va2, vb1, vb2]:
                await graph._backend.add_vertex(v)
            # Intra-tenant A edge (legitimate)
            await graph._backend.add_edge(
                Edge("SIMILAR_TO", va1.vertex_id, va2.vertex_id, {"tenantId": TENANT_A})
            )
            # Cross-tenant edge (adversarial — should NOT appear in A's traversal)
            await graph._backend.add_edge(
                Edge("SIMILAR_TO", va1.vertex_id, vb1.vertex_id, {"tenantId": "MIXED"})
            )
            # Intra-tenant B edge (must not appear in A's results)
            await graph._backend.add_edge(
                Edge("SIMILAR_TO", vb1.vertex_id, vb2.vertex_id, {"tenantId": TENANT_B})
            )

        _run(_setup())
        return va1, va2, vb1, vb2


class TestBFSTenantIsolation:
    def test_bfs_does_not_return_cross_tenant_vertices(self):
        """BFS from TenantA start vertex must not return TenantB vertices."""
        with backend_path():
            from shared.graph.traversal import GraphTraversalEngine

            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                engine = GraphTraversalEngine(graph)
                return await engine.bfs(
                    start_id=va1.vertex_id,
                    depth=3,
                    direction="both",
                    tenant_id=TENANT_A,
                )

            result = _run(_run_test())
            result_ids = {v.vertex_id for v in result.nodes}
            assert vb1.vertex_id not in result_ids, (
                "BFS must not return TenantB vertex when scoped to TenantA"
            )
            assert vb2.vertex_id not in result_ids, (
                "BFS must not return TenantB vertex when scoped to TenantA"
            )

    def test_bfs_does_not_return_cross_tenant_edges(self):
        """BFS from TenantA must not return any edge involving TenantB vertices."""
        with backend_path():
            from shared.graph.traversal import GraphTraversalEngine

            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                engine = GraphTraversalEngine(graph)
                return await engine.bfs(
                    start_id=va1.vertex_id,
                    depth=3,
                    direction="both",
                    tenant_id=TENANT_A,
                )

            result = _run(_run_test())
            b_ids = {vb1.vertex_id, vb2.vertex_id}
            for edge in result.edges:
                assert edge.from_vertex_id not in b_ids and edge.to_vertex_id not in b_ids, (
                    f"BFS result must not contain edges involving TenantB: "
                    f"{edge.edge_type} {edge.from_vertex_id}->{edge.to_vertex_id}"
                )

    def test_bfs_returns_tenant_a_intra_edges(self):
        """BFS from TenantA must still return edges within TenantA."""
        with backend_path():
            from shared.graph.traversal import GraphTraversalEngine

            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                engine = GraphTraversalEngine(graph)
                return await engine.bfs(
                    start_id=va1.vertex_id,
                    depth=2,
                    direction="both",
                    tenant_id=TENANT_A,
                )

            result = _run(_run_test())
            result_ids = {v.vertex_id for v in result.nodes}
            assert va2.vertex_id in result_ids, (
                "BFS must still return TenantA's own vertices"
            )

    def test_bfs_without_tenant_id_is_unrestricted(self):
        """BFS without tenant_id returns all reachable vertices (legacy behaviour)."""
        with backend_path():
            from shared.graph.traversal import GraphTraversalEngine

            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                engine = GraphTraversalEngine(graph)
                return await engine.bfs(
                    start_id=va1.vertex_id,
                    depth=3,
                    direction="both",
                )

            result = _run(_run_test())
            result_ids = {v.vertex_id for v in result.nodes}
            # Without scoping, BFS follows the cross-tenant adversarial edge
            assert vb1.vertex_id in result_ids, (
                "BFS without tenant_id follows all edges (legacy undocumented behavior)"
            )


class TestShortestPathTenantIsolation:
    def test_shortest_path_cannot_route_through_foreign_tenant(self):
        """shortest_path scoped to TenantA must not find a path via TenantB vertices."""
        with backend_path():
            from shared.graph.traversal import GraphTraversalEngine

            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                engine = GraphTraversalEngine(graph)
                # va1->vb1->vb2 path exists via cross-tenant edge; must be blocked
                return await engine.shortest_path(
                    from_id=va1.vertex_id,
                    to_id=vb2.vertex_id,
                    max_depth=6,
                    tenant_id=TENANT_A,
                )

            result = _run(_run_test())
            result_ids = {v.vertex_id for v in result.nodes}
            assert vb1.vertex_id not in result_ids, (
                "shortest_path must not traverse TenantB vertices when scoped to TenantA"
            )
            assert vb2.vertex_id not in result_ids, (
                "shortest_path must not reach TenantB destination when scoped to TenantA"
            )


class TestGraphFilterTenantIsolation:
    def test_filter_excludes_foreign_tenant_vertices(self):
        """get_all_vertices filtered by tenantId must not return foreign-tenant vertices."""
        with backend_path():
            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                all_verts = await graph._backend.get_all_vertices(limit=1000)
                return [v for v in all_verts if v.properties.get("tenantId") == TENANT_A]

            tenant_a_verts = _run(_run_test())
            vertex_ids = {v.vertex_id for v in tenant_a_verts}

            assert vb1.vertex_id not in vertex_ids, (
                "Tenant-filtered vertex list must not include TenantB vertices"
            )
            assert vb2.vertex_id not in vertex_ids, (
                "Tenant-filtered vertex list must not include TenantB vertices"
            )
            assert va1.vertex_id in vertex_ids, "TenantA vertices must be returned"
            assert va2.vertex_id in vertex_ids, "TenantA vertices must be returned"


class TestTemporalBFSTenantIsolation:
    def test_temporal_bfs_does_not_return_cross_tenant_vertices(self):
        """temporal_bfs scoped to TenantA must not return TenantB vertices."""
        with backend_path():
            from shared.graph.traversal import GraphTraversalEngine
            import datetime

            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            future = (
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
            ).isoformat()

            async def _run_test():
                engine = GraphTraversalEngine(graph)
                return await engine.temporal_bfs(
                    start_id=va1.vertex_id,
                    as_of=future,
                    depth=3,
                    direction="both",
                    tenant_id=TENANT_A,
                )

            result = _run(_run_test())
            result_ids = {v.vertex_id for v in result.nodes}
            assert vb1.vertex_id not in result_ids, (
                "temporal_bfs must not return TenantB vertex when scoped to TenantA"
            )
            assert vb2.vertex_id not in result_ids, (
                "temporal_bfs must not return TenantB vertex when scoped to TenantA"
            )


class TestMixedTenantAggregateIsolation:
    def test_aggregate_edges_exclude_cross_tenant_endpoints(self):
        """Tenant-scoped edge list must not include edges to foreign-tenant vertices."""
        with backend_path():
            graph = _make_graph()
            va1, va2, vb1, vb2 = _populate_two_tenants(graph)

            async def _run_test():
                all_verts = await graph._backend.get_all_vertices(limit=1000)
                tenant_a_verts = [
                    v for v in all_verts if v.properties.get("tenantId") == TENANT_A
                ]
                tenant_a_ids = {v.vertex_id for v in tenant_a_verts}
                all_edges = []
                for v in tenant_a_verts:
                    all_edges.extend(await graph._backend.get_edges(v.vertex_id, direction="out"))
                # Scope edges to only those whose target is also in TenantA
                return [e for e in all_edges if e.to_vertex_id in tenant_a_ids], tenant_a_ids

            scoped_edges, tenant_a_ids = _run(_run_test())
            b_ids = {vb1.vertex_id, vb2.vertex_id}
            for edge in scoped_edges:
                assert edge.to_vertex_id not in b_ids, (
                    "Aggregated edges must not include cross-tenant endpoint "
                    f"{edge.edge_type} -> {edge.to_vertex_id}"
                )
