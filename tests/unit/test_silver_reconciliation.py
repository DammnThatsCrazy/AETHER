"""Unit tests for SilverReconciliationWorker — report structure and detection logic."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

from shared.graph.graph import Edge, GraphClient, Vertex, VertexType
from services.silver.reconciliation import ReconciliationReport, SilverReconciliationWorker


async def _fresh_graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


def _v(vid: str, vtype=VertexType.USER, tenant: str = "t1") -> Vertex:
    v = Vertex(vtype, vid)
    v.properties["tenantId"] = tenant
    return v


def _e(from_id: str, to_id: str, etype: str = "DELEGATES", tenant: str = "t1") -> Edge:
    e = Edge(etype, from_id, to_id)
    e.properties["tenant_id"] = tenant
    return e


def _run(coro):
    return asyncio.run(coro)


def test_orphaned_vertices_reported() -> None:
    async def run():
        client = await _fresh_graph()
        # v_orphan has no edges; v_connected has an edge
        await client.add_vertex(_v("v_orphan"))
        await client.add_vertex(_v("v_src"))
        await client.add_vertex(_v("v_dst"))
        await client.add_edge(_e("v_src", "v_dst"))
        worker = SilverReconciliationWorker(client)
        report = await worker.run("t1")
        assert "v_orphan" in report.orphaned_vertex_ids
        assert "v_src" not in report.orphaned_vertex_ids
        assert "v_dst" not in report.orphaned_vertex_ids

    _run(run())


def test_duplicate_edges_reported() -> None:
    async def run():
        client = await _fresh_graph()
        await client.add_vertex(_v("A"))
        await client.add_vertex(_v("B"))
        # Add the same edge twice
        await client.add_edge(_e("A", "B", "DELEGATES"))
        await client.add_edge(_e("A", "B", "DELEGATES"))
        worker = SilverReconciliationWorker(client)
        report = await worker.run("t1")
        assert ("A", "B", "DELEGATES") in report.duplicate_edge_ids

    _run(run())


def test_missing_projections_reported() -> None:
    async def run():
        client = await _fresh_graph()
        # User vertex with no PROJECTS_ edge
        await client.add_vertex(_v("u_no_proj", VertexType.USER))
        # User vertex with a PROJECTS_ edge → should NOT appear in missing
        await client.add_vertex(_v("u_has_proj", VertexType.USER))
        await client.add_vertex(_v("proj_target"))
        e_proj = _e("u_has_proj", "proj_target", "PROJECTS_TO_SILVER")
        await client.add_edge(e_proj)
        worker = SilverReconciliationWorker(client)
        report = await worker.run("t1")
        assert "u_no_proj" in report.missing_projection_ids
        assert "u_has_proj" not in report.missing_projection_ids

    _run(run())


def test_report_structure_and_error_count() -> None:
    async def run():
        client = await _fresh_graph()
        worker = SilverReconciliationWorker(client)
        report = await worker.run("t1")
        assert isinstance(report, ReconciliationReport)
        assert report.tenant_id == "t1"
        assert isinstance(report.orphaned_vertex_ids, list)
        assert isinstance(report.duplicate_edge_ids, list)
        assert isinstance(report.missing_projection_ids, list)
        assert isinstance(report.stale_identity_ids, list)
        assert isinstance(report.error_count, int)
        assert report.error_count == 0

    _run(run())
