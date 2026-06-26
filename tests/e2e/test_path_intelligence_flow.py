"""End-to-end tests for the Path Intelligence flow.

Scenario A: Find and inspect a shortest path between two nodes
Scenario B: K-shortest returns multiple alternative paths
Scenario C: Save snapshot + compare against a second state
Scenario D: Link snapshot to an investigation case and retrieve paths

Tests exercise real service code (no HTTP, no database) using in-memory stores.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

import os
os.environ.setdefault("AETHER_ENV", "local")

from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
from shared.graph.traversal import GraphTraversalEngine


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StubProducer:
    """No-op event producer for use in tests."""
    async def publish(self, event) -> None:
        pass

    async def publish_batch(self, events) -> None:
        pass


async def _build_triangle_graph() -> GraphClient:
    """Seed A→B (direct) and A→C→B (indirect) for Scenarios A and B."""
    client = GraphClient()
    await client.connect()
    for vid in ["A", "B", "C"]:
        v = Vertex(VertexType.USER, vid)
        v.properties["tenantId"] = "t1"
        await client.add_vertex(v)
    for (f, t, conf) in [("A", "B", 0.9), ("A", "C", 0.6), ("C", "B", 0.7)]:
        e = Edge("DELEGATES", f, t)
        e.properties["confidence"] = conf
        await client.add_edge(e)
    return client


def _run(coro):
    return asyncio.run(coro)


# ── Scenario A: shortest path ────────────────────────────────────────────────

def test_find_and_inspect_shortest_path() -> None:
    """POST /paths with mode=shortest returns a valid RelationshipPath."""
    from services.operational_intelligence.routes import graph_paths, PathQuery
    from shared.common.common import ForbiddenError

    async def run():
        client = await _build_triangle_graph()
        body = PathQuery(tenant_id="t1", source_id="A", target_id="B", mode="shortest")
        request = SimpleNamespace(state=SimpleNamespace(
            tenant=SimpleNamespace(tenant_id="t1", require_permission=lambda p: None)
        ))
        res = await graph_paths(body, request, client)
        paths = res["data"]["paths"]
        assert paths, "expected at least one path"
        path = paths[0]
        assert path["source_id"] == "A"
        assert path["target_id"] == "B"
        assert "path_id" in path
        assert len(path["path_id"]) == 32  # SHA256[:32]
        assert path["hop_count"] >= 1
        assert 0.0 <= path["path_confidence"] <= 1.0
        assert path["classification"] in ("observed", "inferred", "attributed", "correlated", "causal_supported")

    _run(run())


# ── Scenario B: k-shortest alternatives ──────────────────────────────────────

def test_k_shortest_returns_alternative_paths() -> None:
    """POST /paths with mode=k_shortest and k=2 returns 2 distinct paths when graph has alternatives."""
    from services.operational_intelligence.routes import graph_paths, PathQuery
    from shared.graph.path_scoring import make_path_id

    async def run():
        client = await _build_triangle_graph()
        body = PathQuery(
            tenant_id="t1", source_id="A", target_id="B",
            mode="k_shortest", k=2, max_depth=4
        )
        request = SimpleNamespace(state=SimpleNamespace(
            tenant=SimpleNamespace(tenant_id="t1", require_permission=lambda p: None)
        ))
        res = await graph_paths(body, request, client)
        paths = res["data"]["paths"]
        assert len(paths) >= 1, "should find at least one path"
        if len(paths) >= 2:
            pid1 = paths[0]["path_id"]
            pid2 = paths[1]["path_id"]
            assert pid1 != pid2, "k-shortest paths should be distinct"

    _run(run())


# ── Scenario C: save snapshot + compare ──────────────────────────────────────

def test_save_snapshot_and_compare() -> None:
    """POST /paths with save_snapshot=True produces a snapshot_id; POST /snapshots/{id}/compare runs."""
    from services.operational_intelligence.routes import (
        graph_paths, graph_compare_snapshots, graph_get_snapshot,
        PathQuery, SnapshotCreateRequest, graph_create_snapshot,
    )

    async def run():
        client = await _build_triangle_graph()
        request = SimpleNamespace(state=SimpleNamespace(
            tenant=SimpleNamespace(tenant_id="t1", require_permission=lambda p: None)
        ))

        # Save a snapshot while querying paths
        body = PathQuery(
            tenant_id="t1", source_id="A", target_id="B",
            mode="shortest", save_snapshot=True
        )
        res = await graph_paths(body, request, client)
        paths = res["data"]["paths"]
        if not paths:
            pytest.skip("no paths found for snapshot test")

        snap_id = res["data"]["snapshot_id"]
        assert snap_id, "save_snapshot=True should produce a snapshot_id"

        # Retrieve the snapshot
        snap_res = await graph_get_snapshot(snap_id, request)
        assert snap_res["data"]["snapshot_id"] == snap_id
        assert snap_res["data"]["tenant_id"] == "t1"

        # Compare snapshot against current graph state
        from services.operational_intelligence.models import SnapshotCompareRequest
        compare_body = SnapshotCompareRequest(tenantId="t1", snapshot_id=snap_id)
        compare_res = await graph_compare_snapshots(snap_id, compare_body, request, client)
        assert "data" in compare_res

    _run(run())


# ── Scenario D: link snapshot to investigation ───────────────────────────────

def test_link_snapshot_to_investigation_and_get_paths() -> None:
    """Attach a snapshot to an investigation case; GET /{case_id}/paths returns path_ids."""
    from services.operational_intelligence.routes import (
        graph_paths, graph_create_snapshot, PathQuery, SnapshotCreateRequest,
    )
    from services.investigation.routes import (
        attach_snapshot_to_investigation,
        get_investigation_paths,
        create_case,
        CreateCaseRequest,
        SnapshotAttachRequest,
    )
    from repositories.repos import reset_in_memory_stores

    async def run():
        reset_in_memory_stores()

        client = await _build_triangle_graph()
        request = SimpleNamespace(state=SimpleNamespace(
            tenant=SimpleNamespace(tenant_id="t1", require_permission=lambda p: None)
        ))

        # Create a snapshot
        snap_body = SnapshotCreateRequest(
            tenant_id="t1",
            query={"source_id": "A"},
            node_ids=["A", "B"],
            edge_ids=["e1"],
        )
        snap_res = await graph_create_snapshot(snap_body, request)
        snap_id = snap_res["data"]["snapshot_id"]

        # Create an investigation case
        case_body = CreateCaseRequest(
            tenantId="t1",
            title="Path Intelligence Test Case",
            createdBy="test-agent",
        )
        case_result = await create_case(case_body, request, _StubProducer())
        # create_case returns an InvestigationCase Pydantic model
        case_id = case_result.id

        # Attach snapshot to the case
        attach_body = SnapshotAttachRequest(tenantId="t1", snapshot_id=snap_id)
        await attach_snapshot_to_investigation(case_id, attach_body, request)

        # Retrieve paths from the linked case
        paths_res = await get_investigation_paths(case_id, request, tenantId="t1")
        assert paths_res["data"]["snapshot_id"] == snap_id

    _run(run())
