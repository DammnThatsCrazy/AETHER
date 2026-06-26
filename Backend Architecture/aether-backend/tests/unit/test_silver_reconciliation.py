"""Unit tests for Silver Reconciliation Worker — 4 tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in (
    "jwt", "cryptography", "cryptography.hazmat",
    "cryptography.hazmat.primitives", "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.asymmetric.ec", "cryptography.hazmat.bindings",
    "cryptography.hazmat.bindings._rust", "cryptography.hazmat._oid",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os
os.environ.setdefault("AETHER_ENV", "local")

from shared.graph.graph import Edge, GraphClient, Vertex
from services.silver.reconciliation import SilverReconciliationWorker


def _v(vid: str, vtype: str = "User", tenant: str = "t1", **props) -> Vertex:
    return Vertex(
        vertex_type=vtype,
        vertex_id=vid,
        properties={"tenantId": tenant, **props},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(from_id: str, to_id: str, etype: str = "RELATED") -> Edge:
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties={},
        created_at="2024-01-01T00:00:00+00:00",
    )


async def _build_graph(*vertices: Vertex, edges: list[Edge] | None = None) -> GraphClient:
    client = GraphClient()
    await client.connect()
    for v in vertices:
        await client.add_vertex(v)
    for e in (edges or []):
        await client.add_edge(e)
    return client


# ---------------------------------------------------------------------------
# Test 1: Orphaned vertices detected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconciliation_finds_orphaned_vertices():
    """Vertices with no edges should be reported as orphaned."""
    graph = await _build_graph(
        _v("connected"), _v("orphan"),
        edges=[_e("connected", "connected")],  # self-loop to give 'connected' edges
    )
    worker = SilverReconciliationWorker(graph)
    report = await worker.run("t1")
    assert "orphan" in report.orphaned_vertex_ids
    assert "connected" not in report.orphaned_vertex_ids


# ---------------------------------------------------------------------------
# Test 2: Duplicate edges detected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconciliation_finds_duplicate_edges():
    """Identical (from, to, type) pairs added twice should be flagged."""
    graph = await _build_graph(_v("A"), _v("B"))
    await graph.add_edge(_e("A", "B", "RELATED"))
    await graph.add_edge(_e("A", "B", "RELATED"))  # duplicate
    worker = SilverReconciliationWorker(graph)
    report = await worker.run("t1")
    assert ("A", "B", "RELATED") in report.duplicate_edge_ids


# ---------------------------------------------------------------------------
# Test 3: Missing Silver projections detected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconciliation_finds_missing_projections():
    """User vertices without PROJECTS_* outbound edges should be flagged."""
    graph = await _build_graph(
        _v("user_no_proj", vtype="User"),
        _v("other"),
        edges=[_e("user_no_proj", "other", "RELATED")],  # non-projection edge
    )
    worker = SilverReconciliationWorker(graph)
    report = await worker.run("t1")
    assert "user_no_proj" in report.missing_projection_ids


# ---------------------------------------------------------------------------
# Test 4: Report structure is well-formed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconciliation_report_structure():
    """ReconciliationReport must include all required fields."""
    graph = await _build_graph(_v("A"), _v("B"), edges=[_e("A", "B")])
    worker = SilverReconciliationWorker(graph)
    report = await worker.run("t1")
    assert report.tenant_id == "t1"
    assert isinstance(report.orphaned_vertex_ids, list)
    assert isinstance(report.duplicate_edge_ids, list)
    assert isinstance(report.missing_projection_ids, list)
    assert isinstance(report.stale_identity_ids, list)
    assert isinstance(report.error_count, int)
    assert report.computed_at is not None
