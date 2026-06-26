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
import math
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("fastapi", reason="Backend deps not installed")

# Force the in-memory backend regardless of the ambient CI environment.
# Without this, GraphClient.connect() may prefer Neptune when NEPTUNE_ENDPOINT
# is exported, which would seed random vertices into external infrastructure
# and assert latency against real network RTT rather than local memory.
os.environ["AETHER_ENV"] = "local"
os.environ.pop("NEPTUNE_ENDPOINT", None)


TENANT = "load-test-tenant"
CONCURRENCY = 10  # number of concurrent tasks per test
ITERATIONS = 30   # total requests per test


# ── Helpers ────────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _percentile(latencies: list[float], p: int) -> float:
    """Nearest-rank percentile using ceiling-based index.

    With n=30 and p=95: ceil(30*0.95) - 1 = ceil(28.5) - 1 = 29 - 1 = 28.
    The old floor-based formula gave index 27, which allowed two slow requests
    to exceed the SLO undetected.
    """
    sorted_l = sorted(latencies)
    idx = min(len(sorted_l) - 1, math.ceil(len(sorted_l) * p / 100) - 1)
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
        # depth=3 must actually traverse nodes — assert result is not None was vacuously true
        assert len(result.nodes) > 0, "depth=3 BFS returned no nodes; traversal may have regressed"

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
    from datetime import datetime, timezone
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine

    graph = GraphClient()
    anchor_id, _, _ = await _seed_graph(graph, n_entities=20, n_clusters=3)
    # Set as_of AFTER seeding so created_at timestamps fall before the replay point.
    # Setting as_of to yesterday would exclude all seeded vertices because temporal_bfs
    # uses created_at as the fallback valid_from, and seeded vertices have created_at=now.
    as_of = datetime.now(timezone.utc).isoformat()
    engine = GraphTraversalEngine(graph)

    latencies: list[float] = []

    async def _one_query():
        t0 = time.perf_counter()
        result = await engine.temporal_bfs(anchor_id, as_of=as_of, depth=2, tenant_id=TENANT)
        latencies.append(time.perf_counter() - t0)
        # Temporal BFS must return the seeded nodes, not an empty result
        assert len(result.nodes) > 0, (
            "temporal_bfs returned no nodes; check that as_of is set after seeding "
            f"(as_of={as_of})"
        )

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
    # Add a cross-tenant edge reachable from anchor_a so that the tenant filter is actually
    # exercised. Without this edge, secret_b was only reachable from anchor_b and the test
    # would pass even if the tenant filter were removed entirely.
    await graph.add_edge(Edge(edge_type="RELATED_TO", from_vertex_id=anchor_a,
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
    """Graph traversal must respect the node budget under concurrent load.

    Seeds more than QUERY_BUDGET_DEFAULTS['max_nodes'] reachable vertices so that
    the budget cap is actually exercised — a graph with only 56 nodes can never
    trigger the 500-node limit even if enforcement is removed.
    """
    from shared.graph.graph import GraphClient
    from shared.graph.traversal import GraphTraversalEngine
    from services.operational_intelligence.models import QUERY_BUDGET_DEFAULTS

    max_nodes = QUERY_BUDGET_DEFAULTS["max_nodes"]  # 500

    graph = GraphClient()
    # Seed 550 entities (+ 10 clusters + 1 anchor = 561 total) so there are more than
    # max_nodes reachable nodes; the budget cap must truncate the result.
    anchor_id, _, _ = await _seed_graph(graph, n_entities=550, n_clusters=10)
    engine = GraphTraversalEngine(graph)

    async def _one_query():
        result = await engine.bfs(
            anchor_id, depth=6, direction="out",
            limit=max_nodes, tenant_id=TENANT,
        )
        assert len(result.nodes) <= max_nodes, (
            f"Node budget violated: got {len(result.nodes)}, expected <= {max_nodes}"
        )
        # Budget must have been hit — if result is smaller than the graph but equals
        # the limit, enforcement worked correctly.
        assert len(result.nodes) == max_nodes, (
            f"Budget cap not triggered: got {len(result.nodes)} nodes; "
            f"expected exactly {max_nodes} (graph has 561 reachable nodes)"
        )

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
