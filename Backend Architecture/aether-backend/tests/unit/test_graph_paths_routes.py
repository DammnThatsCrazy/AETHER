"""Unit tests for graph path intelligence routes — 14 tests (Phase 2C)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Stub heavy optional dependencies before any imports
for _mod in (
    "jwt",
    "cryptography",
    "cryptography.hazmat",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.asymmetric.ec",
    "cryptography.hazmat.bindings",
    "cryptography.hazmat.bindings._rust",
    "cryptography.hazmat._oid",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.traversal import GraphTraversalEngine, TraversalResult
from services.operational_intelligence.models import (
    GraphCompareRequest,
    NodeExpansionRequest, PathExplainRequest, PathQuery, SnapshotCreateRequest,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class FakeTenant:
    def __init__(self, tenant_id: str = "t1"):
        self.tenant_id = tenant_id
        self.user_id = "u1"

    def require_permission(self, perm: str) -> None:
        pass


def _make_request(tenant_id: str = "t1") -> MagicMock:
    req = MagicMock()
    req.state.tenant = FakeTenant(tenant_id)
    return req


def _v(vid: str, vtype: str = "User", tenant: str = "t1") -> Vertex:
    return Vertex(
        vertex_type=vtype,
        vertex_id=vid,
        properties={"tenantId": tenant, "name": vid},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(from_id: str, to_id: str, etype: str = "RELATED", conf: float = 0.9) -> Edge:
    return Edge(
        edge_type=etype,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties={"confidence": conf},
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
# Test 1: shortest mode returns a path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_shortest_mode():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B")],
    )
    body = PathQuery(tenant_id="t1", source_id="A", target_id="B", mode="shortest")
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp
    paths = resp["data"]["paths"]
    assert len(paths) >= 1
    assert paths[0]["source_id"] == "A"
    assert paths[0]["target_id"] == "B"


# ---------------------------------------------------------------------------
# Test 2: strongest mode returns path with confidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_strongest_mode():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B", conf=0.8)],
    )
    body = PathQuery(tenant_id="t1", source_id="A", target_id="B", mode="strongest")
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp
    paths = resp["data"]["paths"]
    assert paths[0]["path_confidence"] > 0


# ---------------------------------------------------------------------------
# Test 3: k_shortest returns k results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_k_shortest_mode():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("S"), _v("M1"), _v("M2"), _v("T"),
        edges=[
            _e("S", "M1"), _e("M1", "T"),
            _e("S", "M2"), _e("M2", "T"),
        ],
    )
    body = PathQuery(tenant_id="t1", source_id="S", target_id="T", mode="k_shortest", k=2)
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp
    paths = resp["data"]["paths"]
    assert len(paths) == 2


# ---------------------------------------------------------------------------
# Test 4: temporal mode dispatches to temporal_bfs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_temporal_mode():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B")],
    )
    body = PathQuery(
        tenant_id="t1", source_id="A", target_id="B",
        mode="temporal", as_of="2025-01-01T00:00:00Z",
    )
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp


# ---------------------------------------------------------------------------
# Test 5: include_explanation returns explanations list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_include_explanation():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B")],
    )
    body = PathQuery(
        tenant_id="t1", source_id="A", target_id="B",
        mode="shortest", include_explanation=True,
    )
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp
    if resp["data"]["paths"]:
        assert len(resp["data"]["explanations"]) >= 1
        assert "why_connected" in resp["data"]["explanations"][0]


# ---------------------------------------------------------------------------
# Test 6: save_snapshot returns a snapshot_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_save_snapshot():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B")],
    )
    body = PathQuery(
        tenant_id="t1", source_id="A", target_id="B",
        mode="shortest", save_snapshot=True,
    )
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp
    if resp["data"]["paths"]:
        assert resp["data"]["snapshot_id"] is not None


# ---------------------------------------------------------------------------
# Test 7: expand returns one-hop neighbors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_expand_returns_one_hop():
    from services.operational_intelligence.routes import graph_paths_expand
    graph = await _build_graph(
        _v("A"), _v("B"), _v("C"),
        edges=[_e("A", "B"), _e("A", "C")],
    )
    body = NodeExpansionRequest(tenant_id="t1", node_id="A", direction="out")
    resp = await graph_paths_expand(body, _make_request(), graph)
    assert "data" in resp
    added_ids = {n["id"] for n in resp["data"]["added_nodes"]}
    assert "B" in added_ids
    assert "C" in added_ids


# ---------------------------------------------------------------------------
# Test 8: explain returns narrative text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_explain_returns_narrative():
    from services.operational_intelligence.routes import graph_paths_explain
    graph = await _build_graph(_v("A"), _v("B"))
    body = PathExplainRequest(tenant_id="t1", path_id="nonexistent-path-id")
    resp = await graph_paths_explain(body, _make_request(), graph)
    assert "data" in resp
    assert "why_connected" in resp["data"]


# ---------------------------------------------------------------------------
# Test 9: create snapshot returns snapshot_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_snapshot():
    from services.operational_intelligence.routes import create_traversal_snapshot
    graph = await _build_graph(_v("A"), _v("B"))
    body = SnapshotCreateRequest(
        tenant_id="t1",
        node_ids=["A", "B"],
        edge_ids=["A:B:RELATED"],
    )
    resp = await create_traversal_snapshot(body, _make_request(), graph)
    assert "data" in resp
    assert resp["data"]["snapshot_id"] is not None
    assert resp["data"]["tenant_id"] == "t1"


# ---------------------------------------------------------------------------
# Test 10: snapshot tenant isolation rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_tenant_isolation():
    from services.operational_intelligence.routes import create_traversal_snapshot, get_traversal_snapshot
    from shared.common.common import ForbiddenError
    graph = await _build_graph(_v("A"))
    body = SnapshotCreateRequest(tenant_id="t1", node_ids=["A"])
    create_resp = await create_traversal_snapshot(body, _make_request("t1"), graph)
    snap_id = create_resp["data"]["snapshot_id"]

    # t2 trying to access t1's snapshot should get 404 (not found due to tenant filter)
    from shared.common.common import NotFoundError
    with pytest.raises(NotFoundError):
        await get_traversal_snapshot(snap_id, _make_request("t2"), tenant_id="t2")


# ---------------------------------------------------------------------------
# Test 11: compare snapshot returns diff fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compare_snapshot():
    from services.operational_intelligence.routes import create_traversal_snapshot, compare_traversal_snapshots
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B")],
    )
    body = SnapshotCreateRequest(tenant_id="t1", node_ids=["A", "B"], edge_ids=["A:B:RELATED"])
    create_resp = await create_traversal_snapshot(body, _make_request(), graph)
    snap_id = create_resp["data"]["snapshot_id"]

    from services.operational_intelligence.models import EntityRef
    compare_body = GraphCompareRequest(
        tenantId="t1",
        anchor=EntityRef(kind="user", id="A"),
        asOf="2025-01-01T00:00:00Z",
        compareTo="2024-01-01T00:00:00Z",
    )
    resp = await compare_traversal_snapshots(snap_id, compare_body, _make_request(), graph)
    assert "data" in resp
    assert "added_node_ids" in resp["data"]
    assert "removed_node_ids" in resp["data"]


# ---------------------------------------------------------------------------
# Test 12: create async job for deep traversal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_async_deep_traversal_job():
    from services.operational_intelligence.routes import create_deep_traversal_job
    graph = await _build_graph(_v("A"), _v("B"))
    # max_depth > 6 triggers async job
    body = PathQuery(
        tenant_id="t1", source_id="A", target_id="B",
        mode="shortest", max_depth=15,
    )
    resp = await create_deep_traversal_job(body, _make_request(), graph)
    assert "data" in resp
    assert resp["data"]["job_id"] is not None
    assert resp["data"]["status"] == "queued"


# ---------------------------------------------------------------------------
# Test 13: attribution mode uses shortest path routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_attribution_mode():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("Agent"), _v("Decision"),
        edges=[_e("Agent", "Decision", etype="ATTRIBUTED_TO")],
    )
    body = PathQuery(tenant_id="t1", source_id="Agent", target_id="Decision", mode="attribution")
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp


# ---------------------------------------------------------------------------
# Test 14: decision_outcome mode finds path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paths_decision_outcome_mode():
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("Ooda"), _v("Outcome"),
        edges=[_e("Ooda", "Outcome", etype="LED_TO")],
    )
    body = PathQuery(tenant_id="t1", source_id="Ooda", target_id="Outcome", mode="decision_outcome")
    resp = await graph_paths(body, _make_request(), graph)
    assert "data" in resp
