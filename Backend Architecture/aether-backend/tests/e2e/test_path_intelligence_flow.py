"""E2E tests for the Path Intelligence flow — 4 tests."""

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
from services.operational_intelligence.models import (
    PathQuery, SnapshotCreateRequest,
)


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


def _v(vid: str, tenant: str = "t1") -> Vertex:
    return Vertex(
        vertex_type="User", vertex_id=vid,
        properties={"tenantId": tenant, "name": vid},
        created_at="2024-01-01T00:00:00+00:00",
    )


def _e(from_id: str, to_id: str, etype: str = "RELATED", conf: float = 0.9) -> Edge:
    return Edge(
        edge_type=etype, from_vertex_id=from_id, to_vertex_id=to_id,
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
# E2E Test 1: Find and inspect shortest path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_find_and_inspect_shortest_path():
    """Full flow: build graph → call /paths (shortest) → verify path structure."""
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("Alice"), _v("Bob"), _v("Carol"),
        edges=[_e("Alice", "Bob"), _e("Bob", "Carol")],
    )
    body = PathQuery(tenant_id="t1", source_id="Alice", target_id="Carol", mode="shortest")
    resp = await graph_paths(body, _make_request(), graph)
    paths = resp["data"]["paths"]
    assert len(paths) >= 1
    path = paths[0]
    assert path["source_id"] == "Alice"
    assert path["target_id"] == "Carol"
    assert path["hop_count"] == 2
    assert "path_id" in path
    assert len(path["ordered_node_ids"]) == 3


# ---------------------------------------------------------------------------
# E2E Test 2: K-shortest returns alternative paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_k_shortest_returns_alternatives():
    """Full flow: k_shortest mode returns multiple distinct paths."""
    from services.operational_intelligence.routes import graph_paths
    graph = await _build_graph(
        _v("S"), _v("M1"), _v("M2"), _v("T"),
        edges=[
            _e("S", "M1", conf=0.8), _e("M1", "T", conf=0.8),
            _e("S", "M2", conf=0.9), _e("M2", "T", conf=0.9),
        ],
    )
    body = PathQuery(tenant_id="t1", source_id="S", target_id="T", mode="k_shortest", k=2)
    resp = await graph_paths(body, _make_request(), graph)
    paths = resp["data"]["paths"]
    assert len(paths) == 2

    # Path IDs must be distinct
    path_ids = [p["path_id"] for p in paths]
    assert len(set(path_ids)) == 2, "K-paths must have distinct path_ids"


# ---------------------------------------------------------------------------
# E2E Test 3: Save and compare snapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_save_and_compare_snapshot():
    """Full flow: create snapshot → compare vs live graph → check diff fields."""
    from services.operational_intelligence.routes import (
        create_traversal_snapshot, compare_traversal_snapshots,
    )
    from services.operational_intelligence.models import GraphCompareRequest, EntityRef
    graph = await _build_graph(
        _v("A"), _v("B"),
        edges=[_e("A", "B")],
    )
    # Create snapshot
    snap_body = SnapshotCreateRequest(
        tenant_id="t1",
        node_ids=["A", "B"],
        edge_ids=["A:B:RELATED"],
    )
    snap_resp = await create_traversal_snapshot(snap_body, _make_request(), graph)
    snap_id = snap_resp["data"]["snapshot_id"]
    assert snap_id is not None

    # Add a new vertex to live graph
    await graph.add_vertex(_v("C"))

    # Compare snapshot vs. live graph
    compare_body = GraphCompareRequest(
        tenantId="t1",
        anchor=EntityRef(kind="user", id="A"),
        asOf="2025-01-01T00:00:00Z",
        compareTo="2024-01-01T00:00:00Z",
    )
    compare_resp = await compare_traversal_snapshots(snap_id, compare_body, _make_request(), graph)
    data = compare_resp["data"]
    assert "added_node_ids" in data
    assert "removed_node_ids" in data
    assert data["snapshot_id"] == snap_id


# ---------------------------------------------------------------------------
# E2E Test 4: Link snapshot to investigation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_link_snapshot_to_investigation():
    """Full flow: create snapshot → create investigation → attach snapshot → get paths."""
    from services.operational_intelligence.routes import create_traversal_snapshot
    from services.investigation.routes import (
        attach_snapshot_to_investigation, get_investigation_paths,
    )
    from services.investigation.routes import SnapshotAttachRequest

    graph = await _build_graph(_v("A"), _v("B"), edges=[_e("A", "B")])
    snap_body = SnapshotCreateRequest(
        tenant_id="t1", node_ids=["A", "B"],
        edge_ids=["A:B:RELATED"], path_ids=["test-path-001"],
    )
    snap_resp = await create_traversal_snapshot(snap_body, _make_request(), graph)
    snap_id = snap_resp["data"]["snapshot_id"]

    # Create a fake investigation case directly in the repo
    from repositories.repos import InvestigationRepository
    inv_repo = InvestigationRepository()
    case = {
        "id": "case-001",
        "tenantId": "t1",
        "title": "Test investigation",
        "status": "open",
        "subjects": [],
        "evidence": [],
        "annotations": [],
        "createdBy": "user-001",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    }
    await inv_repo.insert("case-001", case)

    # Attach snapshot to investigation
    attach_body = SnapshotAttachRequest(tenantId="t1", snapshot_id=snap_id)
    attach_resp = await attach_snapshot_to_investigation("case-001", attach_body, _make_request())
    assert "data" in attach_resp
    assert attach_resp["data"]["snapshot_id"] == snap_id

    # Get investigation paths
    paths_resp = await get_investigation_paths("case-001", _make_request(), tenantId="t1")
    assert paths_resp["data"]["snapshot_id"] == snap_id
    assert "test-path-001" in paths_resp["data"]["path_ids"]
