"""Unit tests for repository↔graph identity-edge reconciliation.

Covers the core diff (``reconcile_identity_edges``) — in-sync, drift, tenant
isolation, run-record persistence — plus the tenant + Kyber-operator route
surfaces.

Runs entirely against the in-memory backends (AETHER_ENV=local): the
``IdentityResolutionRepository`` edge store and a fresh in-memory
``GraphClient``. No DB, no Redis, no HTTP server. Follows the
``reset_in_memory_stores()`` + sys.path-insert pattern from
test_identity_fragment_repair.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Stub heavy optional dependencies before imports
_STUBBED: list[str] = []
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
        _STUBBED.append(_mod)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.graph.graph import Edge, GraphClient  # noqa: E402
from services.identity.graph_reconciliation import (  # noqa: E402
    _run_store,
    get_latest_reconciliation_run,
    reconcile_identity_edges,
)
from services.identity.models import ConfidenceTier, EdgeType  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402

SAME_AS = EdgeType.SAME_AS.value


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


class _StubProducer:
    """Records published events so drift emission can be asserted."""

    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event) -> None:
        self.published.append(event)


async def _fresh_graph() -> GraphClient:
    graph = GraphClient()
    await graph.connect()
    return graph


async def _seed_repo_edge(
    repo: IdentityResolutionRepository,
    tenant_id: str,
    source: str,
    target: str,
) -> dict:
    return await repo.create_identity_edge(
        tenant_id=tenant_id,
        source_entity_id=source,
        target_entity_id=target,
        edge_type=EdgeType.SAME_AS,
        confidence=1.0,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        reason_codes=["same_user_id"],
        source_event_ids=["evt-1"],
    )


async def _seed_graph_edge(
    graph: GraphClient,
    tenant_id: str,
    source: str,
    target: str,
) -> None:
    await graph.add_edge(Edge(
        edge_type=SAME_AS,
        from_vertex_id=source,
        to_vertex_id=target,
        properties={"tenant_id": tenant_id, "edge_id": f"{source}->{target}"},
    ))


# ---------------------------------------------------------------------------
# In-sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_sync_reports_no_drift():
    tenant = "tenant-recon-insync"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()

    await _seed_repo_edge(repo, tenant, "ent-a", "ent-b")
    await _seed_graph_edge(graph, tenant, "ent-a", "ent-b")

    result = await reconcile_identity_edges(
        tenant, repo=repo, graph=graph, producer=_StubProducer()
    )

    assert result["tenant_id"] == tenant
    assert result["in_sync"] is True
    assert result["drift_count"] == 0
    assert result["drift"] == []
    assert result["checked"] == 1
    assert "computed_at" in result


# ---------------------------------------------------------------------------
# Drift: repo has an edge the graph lacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_edge_missing_in_graph_is_drift():
    tenant = "tenant-recon-drift"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()
    producer = _StubProducer()

    # Repo edge with NO matching graph mirror.
    await _seed_repo_edge(repo, tenant, "ent-a", "ent-b")

    result = await reconcile_identity_edges(
        tenant, repo=repo, graph=graph, producer=producer
    )

    assert result["in_sync"] is False
    assert result["drift_count"] == 1
    item = result["drift"][0]
    assert item["type"] == "missing_in_graph"
    assert item["source"] == "ent-a"
    assert item["target"] == "ent-b"
    assert item["detail"]

    # Best-effort drift event emitted on the existing reconciliation topic.
    assert len(producer.published) == 1
    assert producer.published[0].topic.value == "aether.reconciliation.drift_detected"
    assert producer.published[0].tenant_id == tenant


@pytest.mark.asyncio
async def test_graph_edge_missing_in_repo_is_drift():
    tenant = "tenant-recon-orphan"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()

    # A repo edge so the source vertex is in scope, plus an extra graph-only edge.
    await _seed_repo_edge(repo, tenant, "ent-a", "ent-b")
    await _seed_graph_edge(graph, tenant, "ent-a", "ent-b")   # in sync
    await _seed_graph_edge(graph, tenant, "ent-a", "ent-z")   # orphan in graph

    result = await reconcile_identity_edges(
        tenant, repo=repo, graph=graph, producer=_StubProducer()
    )

    assert result["in_sync"] is False
    drift_types = {(d["type"], d["target"]) for d in result["drift"]}
    assert ("missing_in_repo", "ent-z") in drift_types
    assert result["drift_count"] == 1


@pytest.mark.asyncio
async def test_entity_scoped_reconciliation():
    tenant = "tenant-recon-scoped"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()

    await _seed_repo_edge(repo, tenant, "ent-a", "ent-b")  # drift (no graph mirror)
    await _seed_repo_edge(repo, tenant, "ent-c", "ent-d")  # would drift too
    await _seed_graph_edge(graph, tenant, "ent-c", "ent-d")

    # Scope to ent-a only: only its edge is checked.
    result = await reconcile_identity_edges(
        tenant, entity_ids=["ent-a"], repo=repo, graph=graph, producer=_StubProducer()
    )
    assert result["checked"] == 1
    assert result["drift_count"] == 1
    assert result["drift"][0]["source"] == "ent-a"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation():
    tenant_a = "tenant-A"
    tenant_b = "tenant-B"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()

    # Tenant A: repo + graph agree on a SAME_AS edge sharing source vertex X.
    await _seed_repo_edge(repo, tenant_a, "vtx-X", "vtx-Y")
    await _seed_graph_edge(graph, tenant_a, "vtx-X", "vtx-Y")

    # Tenant B: repo edge with no graph mirror (would be drift for B), plus a
    # tenant-B graph edge hanging off the SAME source vertex X.
    await _seed_repo_edge(repo, tenant_b, "vtx-X", "vtx-Q")
    await _seed_graph_edge(graph, tenant_b, "vtx-X", "vtx-W")

    result_a = await reconcile_identity_edges(
        tenant_a, repo=repo, graph=graph, producer=_StubProducer()
    )

    # Tenant A sees only its own edge; tenant B's repo/graph edges never leak.
    assert result_a["in_sync"] is True
    assert result_a["drift_count"] == 0
    assert result_a["checked"] == 1

    # Tenant B, reconciled on its own, still surfaces its drift.
    result_b = await reconcile_identity_edges(
        tenant_b, repo=repo, graph=graph, producer=_StubProducer()
    )
    b_targets = {d["target"] for d in result_b["drift"]}
    assert "vtx-Q" in b_targets  # repo edge missing in graph
    assert "vtx-W" in b_targets  # graph edge missing in repo


# ---------------------------------------------------------------------------
# Run-record persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_record_persisted():
    tenant = "tenant-recon-persist"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()

    await _seed_repo_edge(repo, tenant, "ent-a", "ent-b")  # drift

    result = await reconcile_identity_edges(
        tenant, repo=repo, graph=graph, producer=_StubProducer()
    )

    # A durable run record exists for this tenant and mirrors the summary.
    runs = await _run_store().find(tenant_id=tenant)
    assert len(runs) >= 1
    latest = await get_latest_reconciliation_run(tenant)
    assert latest is not None
    assert latest["tenant_id"] == tenant
    assert latest["drift_count"] == result["drift_count"] == 1
    assert latest["in_sync"] is False
    assert latest["scope"] == "tenant"


@pytest.mark.asyncio
async def test_persist_false_skips_run_record():
    tenant = "tenant-recon-nopersist"
    repo = IdentityResolutionRepository()
    graph = await _fresh_graph()
    await _seed_repo_edge(repo, tenant, "ent-a", "ent-b")

    await reconcile_identity_edges(
        tenant, repo=repo, graph=graph, producer=_StubProducer(), persist=False
    )
    assert await get_latest_reconciliation_run(tenant) is None


# ---------------------------------------------------------------------------
# Route surfaces
# ---------------------------------------------------------------------------


class _Tenant:
    def __init__(self, tenant_id, permissions):
        self.tenant_id = tenant_id
        self.user_id = "operator-1"
        self.permissions = list(permissions)

    def require_permission(self, perm: str) -> None:
        from shared.common.common import ForbiddenError
        if perm not in self.permissions and "admin" not in self.permissions:
            raise ForbiddenError(f"Missing permission: {perm}")

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions or "admin" in self.permissions


class _Request:
    def __init__(self, tenant):
        self.state = MagicMock()
        self.state.tenant = tenant
        self.client = None
        self.headers = {}


@pytest.mark.asyncio
async def test_get_route_returns_envelope():
    from services.identity import reconciliation_routes as rr

    request = _Request(_Tenant("tenant-route-get", {"read"}))
    response = await rr.get_identity_reconciliation(request, refresh=True)

    assert "data" in response
    assert response["data"]["tenant_id"] == "tenant-route-get"
    assert response["data"]["in_sync"] is True
    assert response["data"]["fresh"] is True


@pytest.mark.asyncio
async def test_admin_route_rejects_non_operator():
    from shared.common.common import ForbiddenError
    from services.identity import reconciliation_routes as rr

    # Even a role-admin Aether tenant is not a Kyber operator.
    request = _Request(_Tenant("tenant-route-admin", {"admin"}))
    body = rr.ReconciliationTriggerRequest(tenant_id="tenant-x")

    with pytest.raises(ForbiddenError):
        await rr.trigger_identity_reconciliation(body, request)


@pytest.mark.asyncio
async def test_admin_route_allows_kyber_operator():
    from services.identity import reconciliation_routes as rr

    operator = _Tenant("olympus-op", {"kyber:operator"})
    request = _Request(operator)
    body = rr.ReconciliationTriggerRequest(tenant_id="tenant-target")

    response = await rr.trigger_identity_reconciliation(body, request)
    assert "data" in response
    assert response["data"]["tenant_id"] == "tenant-target"
    assert "drift_count" in response["data"]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def cleanup_stubs():
    yield
    for mod in _STUBBED:
        sys.modules.pop(mod, None)
