"""Every migrated call site must return the caller's rows in full.

Each site below used to fetch a GLOBAL page of `limit` vertices and filter it
by tenant afterwards, so the cap was applied before the tenant predicate. These
tests seed more foreign vertices than the cap plus a handful for the caller's
tenant: under the old scan-then-filter pattern the caller's rows sorted past
the cap and the endpoint answered "you have no data". They pass only because
the sites now use `GraphClient.get_vertices_for_tenant`, where the predicate is
inside the query.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dependencies.providers import get_graph  # noqa: E402
from shared.common.common import AetherError  # noqa: E402
from shared.graph.graph import Edge, GraphClient, Vertex  # noqa: E402

# Imported at module scope on purpose. Sibling suites purge ``shared.*`` from
# sys.modules to re-import the graph backend; a route module first imported
# after such a purge would raise a *different* ForbiddenError class than the
# AetherError this file registers a handler for, and the 403 assertion below
# would see the exception escape instead.
from services.cluster.routes import (  # noqa: E402
    _get_cluster_member_vertices,
    _get_tenant_cluster_vertices,
)
from services.kyber_operator.routes import router as kyber_router  # noqa: E402
from services.operational_intelligence.routes import router as graph_router  # noqa: E402
from services.silver.reconciliation import SilverReconciliationWorker  # noqa: E402

MINE = "tenant_mine"
OTHER = "tenant_other"

# Bigger than EVERY cap any migrated site uses (500 for the query budget, 5000
# for cluster reads, 10000 for graph health / the Kyber envelope / silver
# reconciliation), so under the legacy pattern the global page was filled
# entirely by foreign rows before the caller's own rows were ever reached.
FOREIGN = 10_050
OWN = 5

# The largest cap in play; a scoped read of the foreign tenant is bounded by it.
LARGEST_CAP = 10_000


async def _seeded_graph() -> GraphClient:
    """A graph whose foreign rows are inserted first and exceed every cap."""
    client = GraphClient()
    await client.connect()
    for i in range(FOREIGN):
        await client.add_vertex(
            Vertex(
                vertex_id=f"foreign-{i}",
                vertex_type="User",
                properties={"tenantId": OTHER},
            )
        )
    for i in range(OWN):
        await client.add_vertex(
            Vertex(
                vertex_id=f"mine-{i}",
                vertex_type="User",
                properties={"tenantId": MINE},
            )
        )
    return client


def _own_ids() -> set[str]:
    return {f"mine-{i}" for i in range(OWN)}


# ── Fake principals ───────────────────────────────────────────────────────────

class _TenantPrincipal:
    tenant_id = MINE
    user_id = "user_mine"
    permissions = ["read"]

    def require_permission(self, permission: str) -> None:
        return None

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


class _KyberOperator:
    """Passes the legacy Kyber operator gate via an explicit grant."""

    tenant_id = "olympus_operator"
    user_id = "operator_1"
    permissions = ["kyber:operator"]

    def require_permission(self, permission: str) -> None:
        return None

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


def _make_client(router, principal, graph: GraphClient) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def error_handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant = principal
        return await call_next(request)

    app.include_router(router)
    app.dependency_overrides[get_graph] = lambda: graph
    return TestClient(app)


# ── Route-level: Kyber operational envelope ───────────────────────────────────

async def test_kyber_operational_envelope_counts_every_node_of_the_target_tenant():
    """GET /v1/kyber/tenants/{id}/operational-envelope — 10000-row cap.

    Before the migration this fetched a global 10k page and filtered it: with
    10050 foreign vertices ahead of the target tenant, the page was entirely
    foreign and the operator dashboard reported node_count=0 / has_data=False
    for a tenant with live data.
    """
    graph = await _seeded_graph()
    client = _make_client(kyber_router, _KyberOperator(), graph)

    response = client.get(f"/v1/kyber/tenants/{MINE}/operational-envelope")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["tenant_id"] == MINE
    assert data["graph"]["node_count"] == OWN
    assert data["graph"]["has_data"] is True


async def test_kyber_operational_envelope_caps_the_target_tenants_own_rows():
    """The cap now bounds the TARGET tenant's rows, not a global page."""
    graph = await _seeded_graph()
    client = _make_client(kyber_router, _KyberOperator(), graph)

    response = client.get(f"/v1/kyber/tenants/{OTHER}/operational-envelope")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["graph"]["node_count"] == LARGEST_CAP


# ── Route-level: /v1/graph/* ──────────────────────────────────────────────────

@pytest.fixture()
async def graph_client() -> TestClient:
    graph = await _seeded_graph()
    return _make_client(graph_router, _TenantPrincipal(), graph)


async def test_graph_filter_returns_the_callers_rows_in_full(graph_client: TestClient):
    """POST /v1/graph/filter — caller-supplied cap.

    `limit` now bounds the caller's own rows. With 10050 foreign vertices ahead
    of them, the legacy global page of 100 contained none of the caller's 5.
    """
    response = graph_client.post(
        "/v1/graph/filter",
        json={"tenantId": MINE, "filter": {}, "limit": 100},
    )
    assert response.status_code == 200, response.text
    nodes = response.json()["nodes"]
    assert len(nodes) == OWN
    assert {n["id"] for n in nodes} == _own_ids()


async def test_graph_overlay_returns_the_callers_rows_in_full(graph_client: TestClient):
    """POST /v1/graph/overlay — caller-supplied cap."""
    response = graph_client.post(
        "/v1/graph/overlay",
        json={"tenantId": MINE, "overlays": ["risk"], "limit": 100},
    )
    assert response.status_code == 200, response.text
    assert {n["id"] for n in response.json()["nodes"]} == _own_ids()


async def test_graph_health_reports_the_callers_nodes(graph_client: TestClient):
    """GET /v1/graph/health — 10000-row cap, scoped to the effective tenant."""
    response = graph_client.get("/v1/graph/health")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["node_count"] == OWN
    assert data["status"] == "healthy"


async def test_graph_query_full_scan_returns_the_callers_rows(graph_client: TestClient):
    """POST /v1/graph/query without anchors — the 500-node budget branch.

    The foreign rows exceed QUERY_BUDGET_DEFAULTS["max_nodes"], so the legacy
    global page was entirely foreign and the caller saw zero nodes.
    """
    response = graph_client.post(
        "/v1/graph/query",
        json={"tenant_id": MINE, "limit": 100},
    )
    assert response.status_code == 200, response.text
    assert {n["id"] for n in response.json()["nodes"]} == _own_ids()


async def test_graph_facets_counts_every_node_of_the_caller(graph_client: TestClient):
    """POST /v1/graph/facets — global 500-node cap applied before the filter."""
    response = graph_client.post(
        "/v1/graph/facets",
        json={"tenant_id": MINE, "facet_fields": ["node_type"]},
    )
    assert response.status_code == 200, response.text
    facets = response.json()["facets"]
    counts = {v["value"]: v["count"] for v in facets[0]["values"]}
    assert counts.get("User") == OWN


async def test_graph_export_exports_the_callers_rows(graph_client: TestClient):
    """POST /v1/graph/export — caller-supplied cap, bulk path."""
    response = graph_client.post(
        "/v1/graph/export",
        json={"tenant_id": MINE, "format": "jsonl", "limit": 100},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"


async def test_graph_routes_still_reject_a_foreign_tenant_id(graph_client: TestClient):
    """Scoping the read must not have relaxed the isolation check."""
    response = graph_client.post(
        "/v1/graph/filter",
        json={"tenantId": OTHER, "filter": {}, "limit": 100},
    )
    assert response.status_code == 403


# ── App-free: cluster helpers ─────────────────────────────────────────────────

async def test_cluster_vertices_helper_finds_the_tenants_clusters():
    graph = await _seeded_graph()
    for i in range(3):
        await graph.add_vertex(
            Vertex(
                vertex_id=f"cluster-{i}",
                vertex_type="IdentityCluster",
                properties={"tenantId": MINE},
            )
        )

    clusters = await _get_tenant_cluster_vertices(MINE, graph)
    assert {v.vertex_id for v in clusters} == {f"cluster-{i}" for i in range(3)}


async def test_cluster_member_helper_finds_members_behind_foreign_rows():
    graph = await _seeded_graph()
    await graph.add_vertex(
        Vertex(
            vertex_id="cluster-0",
            vertex_type="IdentityCluster",
            properties={"tenantId": MINE},
        )
    )
    await graph.add_edge(
        Edge(
            edge_type="MEMBER_OF_CLUSTER",
            from_vertex_id="mine-0",
            to_vertex_id="cluster-0",
            properties={"tenant_id": MINE},
        )
    )

    members = await _get_cluster_member_vertices("cluster-0", MINE, graph)
    assert {v.vertex_id for v in members} == {"mine-0"}


# ── App-free: silver reconciliation ───────────────────────────────────────────

async def test_reconciliation_sees_the_tenants_orphans_behind_foreign_rows():
    """`SilverReconciliationWorker.run(tenant_id)` is per-tenant by construction.

    Its four scans previously read a global 10k page each; a fleet larger than
    that reported a clean report for a tenant with real orphans.
    """
    graph = await _seeded_graph()
    report = await SilverReconciliationWorker(graph).run(MINE)

    assert report.tenant_id == MINE
    assert report.error_count == 0
    # The five seeded vertices have no edges at all.
    assert set(report.orphaned_vertex_ids) == _own_ids()


async def test_reconciliation_reports_missing_projections_for_the_tenant_only():
    graph = await _seeded_graph()
    report = await SilverReconciliationWorker(graph).run(MINE)

    # "User" is an expected-projection type and none of the seeded rows have a
    # PROJECTS_* edge, so all of the caller's rows must be reported — and none
    # of the foreign ones.
    assert set(report.missing_projection_ids) == _own_ids()
