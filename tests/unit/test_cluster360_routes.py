"""Unit tests for Cluster360 API routes (Phase 5).

Tests GET /v1/clusters, /v1/clusters/{cluster_id}, and all sub-routes via
FastAPI TestClient with an in-memory seeded graph.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient


# ── App factory ───────────────────────────────────────────────────────────────

TENANT = "t-cluster-test"
OTHER_TENANT = "t-other"

CLUSTER_ID = "clus-001"
CLUSTER_ID_2 = "clus-002"
ENTITY_ID_1 = "ent-001"
ENTITY_ID_2 = "ent-002"


@pytest.fixture(scope="module")
def test_app():
    # All imports inside the fixture to avoid function-identity problems when
    # other test modules (e.g. test_api_contracts) reload or remove service
    # modules from sys.modules between collection and fixture execution.
    # The exception handlers must be registered against the classes bound in the
    # router's own namespace (`services.cluster.routes.ForbiddenError`), because
    # that is exactly the class the routes raise — a fresh import of
    # shared.common.common could resolve to a different class object if
    # test_api_contracts reloaded it mid-run, and the handler would never match.
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from shared.graph.graph import GraphClient, Vertex, Edge, VertexType, EdgeType
    from services.cluster.routes import ForbiddenError, NotFoundError, router as cluster_router
    from dependencies.providers import get_graph

    app = FastAPI()

    @app.exception_handler(ForbiddenError)
    async def _forbidden(request, exc):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _not_found(request, exc):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    app.include_router(cluster_router)

    client = GraphClient()

    async def _seed():
        vertices = [
            Vertex(
                VertexType.IDENTITY_CLUSTER,
                CLUSTER_ID,
                {
                    "tenantId": TENANT,
                    "label": "Test Identity Cluster",
                    "member_count": "2",
                    "confidence": "0.95",
                    "lifecycle_state": "active",
                    "risk_score": "0.3",
                    "formation_reason": "shared device fingerprint",
                    "currency": "USD",
                    "transaction_count": "42",
                    "fraud_network_type": None,
                },
            ),
            Vertex(
                VertexType.RISK_CLUSTER,
                CLUSTER_ID_2,
                {
                    "tenantId": TENANT,
                    "label": "High Risk Cluster",
                    "member_count": "1",
                    "confidence": "0.8",
                    "lifecycle_state": "active",
                    "risk_score": "0.85",
                },
            ),
            Vertex(
                "Entity",
                ENTITY_ID_1,
                {
                    "tenantId": TENANT,
                    "label": "alice",
                    "risk_score": "0.2",
                    "revenue": "500.0",
                    "spend": "100.0",
                    "country": "US",
                    "region": "CA",
                    "attributed_campaign_id": "campaign-abc",
                    "acquisition_channel": "organic",
                },
            ),
            Vertex(
                "Entity",
                ENTITY_ID_2,
                {
                    "tenantId": TENANT,
                    "label": "bob",
                    "risk_score": "0.75",
                    "revenue": "200.0",
                    "spend": "50.0",
                    "country": "GB",
                    "region": "London",
                },
            ),
            Vertex(
                "Entity",
                "ent-other",
                {"tenantId": OTHER_TENANT, "label": "other-tenant-entity"},
            ),
        ]
        edges = [
            Edge(
                EdgeType.MEMBER_OF_CLUSTER,
                ENTITY_ID_1,
                CLUSTER_ID,
                {"tenant_id": TENANT},
            ),
            Edge(
                EdgeType.MEMBER_OF_CLUSTER,
                ENTITY_ID_2,
                CLUSTER_ID,
                {"tenant_id": TENANT},
            ),
        ]
        for v in vertices:
            await client.add_vertex(v)
        for e in edges:
            await client.add_edge(e)

    asyncio.run(_seed())

    async def _mock_graph():
        yield client

    app.dependency_overrides[get_graph] = _mock_graph

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        class _FakeTenant:
            tenant_id = TENANT
            is_platform_admin = False
            def require_permission(self, _): pass

        request.state.tenant = _FakeTenant()
        return await call_next(request)

    return TestClient(app)


# ── List clusters ─────────────────────────────────────────────────────────────

def test_list_clusters_returns_tenant_clusters(test_app):
    resp = test_app.get("/v1/clusters", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "clusters" in data and "meta" in data
    ids = {c["cluster_id"] for c in data["clusters"]}
    assert CLUSTER_ID in ids
    assert CLUSTER_ID_2 in ids


def test_list_clusters_cross_tenant_blocked(test_app):
    resp = test_app.get("/v1/clusters", params={"tenant_id": OTHER_TENANT})
    assert resp.status_code == 403


def test_list_clusters_filter_by_type(test_app):
    resp = test_app.get("/v1/clusters", params={"tenant_id": TENANT, "cluster_type": "IdentityCluster"})
    assert resp.status_code == 200
    clusters = resp.json()["data"]["clusters"]
    for c in clusters:
        assert c["cluster_type"] == "IdentityCluster"


def test_list_clusters_pagination(test_app):
    resp1 = test_app.get("/v1/clusters", params={"tenant_id": TENANT, "limit": 1})
    assert resp1.status_code == 200
    data1 = resp1.json()["data"]
    assert len(data1["clusters"]) == 1
    cursor = data1["meta"]["cursor"]
    assert cursor is not None

    resp2 = test_app.get("/v1/clusters", params={"tenant_id": TENANT, "limit": 1, "cursor": cursor})
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    ids1 = {c["cluster_id"] for c in data1["clusters"]}
    ids2 = {c["cluster_id"] for c in data2["clusters"]}
    assert ids1.isdisjoint(ids2)


# ── Get cluster ───────────────────────────────────────────────────────────────

def test_get_cluster_returns_record(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    cluster = resp.json()["data"]
    assert cluster["cluster_id"] == CLUSTER_ID
    assert cluster["cluster_type"] == "IdentityCluster"
    assert cluster["label"] == "Test Identity Cluster"
    assert cluster["tenant_id"] == TENANT


def test_get_cluster_member_count_includes_edges(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    assert resp.json()["data"]["member_count"] == 2


def test_get_cluster_not_found(test_app):
    resp = test_app.get("/v1/clusters/nonexistent-id", params={"tenant_id": TENANT})
    assert resp.status_code == 404


def test_get_cluster_cross_tenant_blocked(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}", params={"tenant_id": OTHER_TENANT})
    assert resp.status_code == 403


# ── Members ───────────────────────────────────────────────────────────────────

def test_get_cluster_members(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/members", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "members" in data
    member_ids = {m["entity_id"] for m in data["members"]}
    assert ENTITY_ID_1 in member_ids
    assert ENTITY_ID_2 in member_ids


def test_get_cluster_members_has_meta(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/members", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    meta = resp.json()["data"]["meta"]
    assert meta["total"] == 2
    assert meta["limit"] == 50


def test_get_cluster_members_pagination(test_app):
    resp1 = test_app.get(
        f"/v1/clusters/{CLUSTER_ID}/members",
        params={"tenant_id": TENANT, "limit": 1},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()["data"]
    assert len(data1["members"]) == 1
    cursor = data1["meta"]["cursor"]

    resp2 = test_app.get(
        f"/v1/clusters/{CLUSTER_ID}/members",
        params={"tenant_id": TENANT, "limit": 1, "cursor": cursor},
    )
    assert resp2.status_code == 200
    ids1 = {m["entity_id"] for m in data1["members"]}
    ids2 = {m["entity_id"] for m in resp2.json()["data"]["members"]}
    assert ids1.isdisjoint(ids2)


# ── Timeline ──────────────────────────────────────────────────────────────────

def test_get_cluster_timeline(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/timeline", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "events" in data
    assert len(data["events"]) >= 1
    ev = data["events"][0]
    assert "event_id" in ev
    assert "event_type" in ev
    assert "timestamp" in ev


# ── Graph ─────────────────────────────────────────────────────────────────────

def test_get_cluster_graph(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/graph", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "nodes" in data
    assert "edges" in data
    node_ids = {n["id"] for n in data["nodes"]}
    assert CLUSTER_ID in node_ids


# ── Economic ──────────────────────────────────────────────────────────────────

def test_get_cluster_economic(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/economic", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cluster_id"] == CLUSTER_ID
    assert "total_revenue" in data
    assert "total_spend" in data
    assert "ltv_estimate" in data
    assert "value_tier" in data
    assert data["total_revenue"] == pytest.approx(700.0)  # 500 + 200


# ── Campaigns ────────────────────────────────────────────────────────────────

def test_get_cluster_campaigns(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/campaigns", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cluster_id"] == CLUSTER_ID
    assert "attributed_campaigns" in data
    campaign_ids = {c["campaign_id"] for c in data["attributed_campaigns"]}
    assert "campaign-abc" in campaign_ids
    assert data["top_acquisition_channel"] == "organic"


# ── Risk ─────────────────────────────────────────────────────────────────────

def test_get_cluster_risk(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/risk", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cluster_id"] == CLUSTER_ID
    assert "aggregate_risk_score" in data
    assert "risk_tier" in data
    assert "high_risk_members" in data
    assert ENTITY_ID_2 in data["high_risk_members"]


def test_get_cluster_risk_high_risk_cluster(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID_2}/risk", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["risk_tier"] == "high"


# ── Geography ────────────────────────────────────────────────────────────────

def test_get_cluster_geography(test_app):
    resp = test_app.get(f"/v1/clusters/{CLUSTER_ID}/geography", params={"tenant_id": TENANT})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cluster_id"] == CLUSTER_ID
    assert "country_distribution" in data
    assert "US" in data["country_distribution"]
    assert "GB" in data["country_distribution"]
    assert data["primary_country"] == "US"
