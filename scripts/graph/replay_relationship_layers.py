#!/usr/bin/env python3
"""
Synthetic Graph Replay Workload

Generates N tenants × M users with the full H2H/H2A/A2H/A2A fixture, writes
edges through the in-memory GraphClient (no Neptune required), and reports
per-layer statistics and write latency.

Usage:
    python scripts/graph/replay_relationship_layers.py
    python scripts/graph/replay_relationship_layers.py --tenants 5 --users 100
    python scripts/graph/replay_relationship_layers.py --tenants 1 --users 10 --quiet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))

if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.SimpleNamespace(
        encode=lambda *a, **kw: "stub",
        decode=lambda *a, **kw: {},
        exceptions=types.SimpleNamespace(
            PyJWTError=Exception, ExpiredSignatureError=Exception, InvalidTokenError=Exception
        ),
    )

from datetime import datetime, timezone

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.relationship_layers import RelationshipLayer, get_layer_stats


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _props(tenant_id: str, actor_id: str, source_event_id: str = "") -> dict:
    return build_edge_properties(
        tenant_id=tenant_id,
        edge_type="REPLAY",  # placeholder; callers override
        from_vertex_id="",
        to_vertex_id="",
        actor_kind="system",
        actor_id=actor_id,
        provenance="replay_relationship_layers",
        valid_from=_now(),
        confidence=1.0,
        source_event_id=source_event_id,
        schema_version="1",
        consent_purpose="replay_workload",
    )


async def _add_edge(client: GraphClient, edge: Edge, counters: dict, latencies: list) -> None:
    t0 = time.perf_counter()
    try:
        await client.add_edge(edge)
        latencies.append((time.perf_counter() - t0) * 1000)
        counters["written"] += 1
    except Exception:
        counters["rejected"] += 1


async def build_tenant_graph(
    client: GraphClient,
    tenant_id: str,
    user_count: int,
) -> list[Edge]:
    """Write one full H2H/H2A/A2H/A2A fixture for a single tenant."""
    edges_written: list[Edge] = []
    base_props = lambda et, fid, tid: {  # noqa: E731
        **build_edge_properties(
            tenant_id=tenant_id,
            edge_type=et,
            from_vertex_id=fid,
            to_vertex_id=tid,
            actor_kind="system",
            actor_id=f"replay-system@{tenant_id}",
            provenance="replay_relationship_layers",
            valid_from=_now(),
            confidence=1.0,
            consent_purpose="replay_workload",
        )
    }

    for i in range(user_count):
        uid = f"{tenant_id}-user-{i}"
        aid = f"{tenant_id}-agent-{i}"
        sid = f"{tenant_id}-session-{i}"

        # Vertices
        await client.add_vertex(Vertex(VertexType.USER, uid, {"tenant_id": tenant_id}))
        await client.add_vertex(Vertex(VertexType.AGENT, aid, {"tenant_id": tenant_id}))
        await client.add_vertex(Vertex(VertexType.SESSION, sid, {"tenant_id": tenant_id}))

        # H2H
        h2h = Edge(EdgeType.HAS_SESSION, uid, sid, base_props(EdgeType.HAS_SESSION, uid, sid))
        await client.add_edge(h2h)
        edges_written.append(h2h)

        # H2A
        h2a = Edge(EdgeType.DELEGATES, uid, aid, base_props(EdgeType.DELEGATES, uid, aid))
        await client.add_edge(h2a)
        edges_written.append(h2a)

        # A2H
        a2h = Edge(EdgeType.NOTIFIES, aid, uid, base_props(EdgeType.NOTIFIES, aid, uid))
        await client.add_edge(a2h)
        edges_written.append(a2h)

        if i > 0:
            prev_aid = f"{tenant_id}-agent-{i - 1}"
            # A2A
            a2a = Edge(EdgeType.HIRED, aid, prev_aid, base_props(EdgeType.HIRED, aid, prev_aid))
            await client.add_edge(a2a)
            edges_written.append(a2a)

    return edges_written


async def run(tenants: int, users: int, quiet: bool) -> None:
    client = GraphClient()
    await client.connect()

    total_latencies: list[float] = []
    all_edges: list[Edge] = []
    t_start = time.perf_counter()

    for t in range(tenants):
        tenant_id = f"tenant-{t:04d}"
        t0 = time.perf_counter()
        tenant_edges = await build_tenant_graph(client, tenant_id, users)
        elapsed = (time.perf_counter() - t0) * 1000
        total_latencies.append(elapsed)
        all_edges.extend(tenant_edges)
        if not quiet:
            print(f"  Tenant {tenant_id}: {len(tenant_edges)} edges written in {elapsed:.1f}ms")

    elapsed_total = (time.perf_counter() - t_start) * 1000
    stats = get_layer_stats(all_edges)

    print()
    print("═" * 50)
    print(f"Replay complete — {tenants} tenant(s) × {users} user(s)")
    print(f"Total edges written : {len(all_edges)}")
    print(f"Total time          : {elapsed_total:.1f}ms")
    print()
    print("Edge counts by layer:")
    for layer in (RelationshipLayer.H2H, RelationshipLayer.H2A,
                  RelationshipLayer.A2H, RelationshipLayer.A2A):
        print(f"  {layer.value:8s}: {stats.get(layer.value, 0)}")
    if stats.get("unknown", 0):
        print(f"  {'unknown':8s}: {stats['unknown']}  ← WARNING: unmapped edges")
    print()

    vertices = await client.get_all_vertices()
    print(f"Total vertices in graph : {len(vertices)}")
    print("═" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic graph replay workload")
    parser.add_argument("--tenants", type=int, default=3)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.tenants, args.users, args.quiet))


if __name__ == "__main__":
    main()
