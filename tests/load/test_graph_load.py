"""Graph load smoke tests — pytest-based concurrent graph query tests.

These tests verify that the graph traversal engine handles concurrent requests
within the defined SLO budgets. They use the in-memory GraphClient so no
external dependencies are required.

SLO targets from UNIVERSAL_GRAPH_RUNBOOK.md:
  - BFS traversal (depth 3)  P95 < 800ms
  - Graph query (depth 2)    P95 < 500ms
  - Temporal replay          P95 < 1000ms

Tests run concurrent async tasks; latency percentiles are checked at the end.
If a percentile exceeds the threshold the test fails — this is intentional so
the test suite acts as a regression guard for traversal performance.
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("fastapi", reason="Backend deps not installed")


TENANT = "load-test-tenant"
CONCURRENCY = 10  # number of concurrent tasks per test
ITERATIONS = 30   # total requests per test


# ── Helpers ────────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _percentile(latencies: list[float], p: int) -> float:
    sorted_l = sorted(latencies)
    idx = max(0, int(len(sorted_l) * p / 100) - 1)
    return sorted_l[idx]


async def _seed_graph(graph, n_entities: int = 20, n_clusters: int = 3):
    """Seed a graph with entities, clusters, and edges for realistic traversal."""
    from shared.graph.graph import Vertex, Edge

    cluster_ids = [f"cluster-{_uid()}" for _ in range(n_clusters)]
    entity_ids = [f"entity-{_uid()}" for _ in range(n_entities)]
    anchor_id = f"anchor-{_uid()}"

    await graph.add_vertex(Vertex(
        vertex_id=anchor_id,
        vertex_type="anchor",
        properties={"tenantId": TENANT},
    ))

    for cid in cluster_ids:
        await graph.add_vertex(Vertex(
            vertex_id=cid,
            vertex_type="cluster",
            properties={"tenantId": TENANT, "cluster_type": "identity"},
        ))

    for i, eid in enumerate(entity_ids):
        cid = cluster_ids[i % len(cluster_ids)]
        await graph.add_vertex(Vertex(
            vertex_id=eid,
            vertex_type="human",
            properties={
                "tenantId": TENANT,
                "risk_score": (i % 10) / 10.0,
                "trust_score": 1.0 - (i % 10) / 10.0,
                "lifecycle_state": "active",
            },
        ))
        await graph.add_edge(Edge(
            edge_type="MEMBER_OF_CLUSTER",
            from_vertex_id=eid,
            to_vertex_id=cid,
            properties={"tenantId": TENANT, "confidence": 0.9},
        ))
        await graph.add_edge(Edge(
            edge_type="RELATED_TO",
            from_vertex_id=anchor_id,
            to_vertex_id=eid,
            properties={"tenantId": TENANT},
        ))

    return anchor_id, cluster_ids, entity_ids


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_bfs_depth2_latency():
    """Concurrent BFS depth=2 traversals must complete with P95 < 500ms."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id, _, _ = await _seed_graph(graph, n_entities=30, n_clusters=5)
    engine = GraphTraversalEngine(graph)

    latencies: list[float] = []

    async def _one_query():
        t0 = time.perf_counter()
        result = await engine.bfs(anchor_id, depth=2, direction="out", tenant_id=TENANT)
        latencies.append(time.perf_counter() - t0)
        # Basic sanity: result must have nodes
        assert len(result.nodes) > 0

    # Run ITERATIONS total across CONCURRENCY concurrent workers
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _bounded():
        async with sem:
            await _one_query()

    await asyncio.gather(*[_bounded() for _ in range(ITERATIONS)])

    p95 = _percentile(latencies, 95)
    p50 = _percentile(latencies, 50)
    # Convert to ms for readability in assertion messages
    assert p95 < 0.500, (
        f"BFS depth=2 P95 latency {p95 * 1000:.1f}ms exceeds 500ms SLO. "
        f"P50={p50 * 1000:.1f}ms over {ITERATIONS} requests ({CONCURRENCY} concurrent)"
    )


@pytest.mark.asyncio
async def test_concurrent_bfs_depth3_latency():
    """Concurrent BFS depth=3 traversals must complete with P95 < 800ms."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id, _, _ = await _seed_graph(graph, n_entities=40, n_clusters=5)
    engine = GraphTraversalEngine(graph)

    latencies: list[float] = []

    async def _one_query():
        t0 = time.perf_counter()
        result = await engine.bfs(anchor_id, depth=3, direction="both", tenant_id=TENANT)
        latencies.append(time.perf_counter() - t0)
        assert result is not None

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _bounded():
        async with sem:
            await _one_query()

    await asyncio.gather(*[_bounded() for _ in range(ITERATIONS)])

    p95 = _percentile(latencies, 95)
    assert p95 < 0.800, (
        f"BFS depth=3 P95 latency {p95 * 1000:.1f}ms exceeds 800ms SLO "
        f"over {ITERATIONS} requests"
    )


@pytest.mark.asyncio
async def test_concurrent_temporal_bfs_latency():
    """Concurrent temporal BFS queries must complete with P95 < 1000ms."""
    from datetime import datetime, timedelta, timezone
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id, _, _ = await _seed_graph(graph, n_entities=20, n_clusters=3)
    engine = GraphTraversalEngine(graph)

    as_of = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    latencies: list[float] = []

    async def _one_query():
        t0 = time.perf_counter()
        result = await engine.temporal_bfs(anchor_id, as_of=as_of, depth=2, tenant_id=TENANT)
        latencies.append(time.perf_counter() - t0)
        assert result is not None

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _bounded():
        async with sem:
            await _one_query()

    await asyncio.gather(*[_bounded() for _ in range(ITERATIONS)])

    p95 = _percentile(latencies, 95)
    assert p95 < 1.000, (
        f"Temporal BFS P95 latency {p95 * 1000:.1f}ms exceeds 1000ms SLO "
        f"over {ITERATIONS} requests"
    )


@pytest.mark.asyncio
async def test_tenant_isolation_under_concurrent_load():
    """Concurrent cross-tenant BFS must never leak nodes across tenant boundaries."""
    from shared.graph.graph import GraphClient, Vertex, Edge
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    engine = GraphTraversalEngine(graph)

    tenant_a = "load-tenant-a"
    tenant_b = "load-tenant-b"

    anchor_a = f"anchor-a-{_uid()}"
    anchor_b = f"anchor-b-{_uid()}"
    secret_b = f"secret-b-{_uid()}"

    await graph.add_vertex(Vertex(vertex_id=anchor_a, vertex_type="anchor", properties={"tenantId": tenant_a}))
    await graph.add_vertex(Vertex(vertex_id=anchor_b, vertex_type="anchor", properties={"tenantId": tenant_b}))
    await graph.add_vertex(Vertex(vertex_id=secret_b, vertex_type="human",
                                  properties={"tenantId": tenant_b, "label": "should-not-leak"}))
    await graph.add_edge(Edge(edge_type="RELATED_TO", from_vertex_id=anchor_b,
                              to_vertex_id=secret_b, properties={"tenantId": tenant_b}))

    violations: list[str] = []

    async def _query_tenant_a(_: int):
        result = await engine.bfs(anchor_a, depth=3, direction="both", tenant_id=tenant_a)
        for node in result.nodes:
            if node.properties.get("tenantId") != tenant_a:
                violations.append(f"Cross-tenant node {node.vertex_id} leaked into tenant_a result")

    await asyncio.gather(*[_query_tenant_a(i) for i in range(CONCURRENCY)])
    assert not violations, f"Tenant isolation failures under concurrent load: {violations}"


@pytest.mark.asyncio
async def test_query_budget_enforcement_under_load():
    """Graph traversal must respect depth and node budgets under concurrent load."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id, _, _ = await _seed_graph(graph, n_entities=50, n_clusters=5)
    engine = GraphTraversalEngine(graph)

    async def _one_query():
        # depth=6 is the maximum allowed; result must not exceed QUERY_BUDGET max_nodes
        result = await engine.bfs(anchor_id, depth=6, direction="out", tenant_id=TENANT)
        assert len(result.nodes) <= 500, f"Node budget exceeded: {len(result.nodes)} nodes"

    await asyncio.gather(*[_one_query() for _ in range(CONCURRENCY)])


@pytest.mark.asyncio
async def test_all_results_valid_under_concurrent_load():
    """All concurrent BFS results must have consistent structure (no partial results)."""
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id, _, _ = await _seed_graph(graph, n_entities=25, n_clusters=4)
    engine = GraphTraversalEngine(graph)

    results = []

    async def _one_query():
        r = await engine.bfs(anchor_id, depth=2, direction="out", tenant_id=TENANT)
        results.append(r)

    await asyncio.gather(*[_one_query() for _ in range(ITERATIONS)])

    # All concurrent results must have the same node set (deterministic)
    node_sets = [frozenset(n.vertex_id for n in r.nodes) for r in results]
    first = node_sets[0]
    for i, ns in enumerate(node_sets[1:], 1):
        assert ns == first, (
            f"Non-deterministic BFS result at iteration {i}: "
            f"expected {len(first)} nodes, got {len(ns)}"
        )
