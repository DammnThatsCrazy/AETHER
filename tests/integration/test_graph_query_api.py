"""Integration tests for the Phase 4 graph query API endpoints.

Tests /query, /facets, /explain, /export, /capabilities via FastAPI TestClient.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest


BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import asyncio

from fastapi.testclient import TestClient


# ── App factory ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_app():
    """Build a minimal FastAPI app with the graph router and seeded in-memory graph."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from shared.graph.graph import GraphClient, Vertex, Edge
    from services.operational_intelligence.routes import router

    from shared.common.common import ForbiddenError as _ForbiddenError
    from fastapi.responses import JSONResponse as _JSONResponse

    app = FastAPI()

    @app.exception_handler(_ForbiddenError)
    async def _forbidden_handler(request, exc):
        return _JSONResponse(status_code=403, content={"error": str(exc)})

    app.include_router(router)

    TENANT = "t-query-test"
    client = GraphClient()

    async def _seed():
        vertices = [
            Vertex("Entity", "e1", {"tenantId": TENANT, "label": "alice", "status": "active", "risk_score": "0.8", "valid_from": "2025-01-01T00:00:00+00:00"}),
            Vertex("Entity", "e2", {"tenantId": TENANT, "label": "bob",   "status": "dormant", "risk_score": "0.2", "valid_from": "2025-01-01T00:00:00+00:00"}),
            Vertex("Agent",  "a1", {"tenantId": TENANT, "label": "agent1", "status": "active", "valid_from": "2025-01-01T00:00:00+00:00"}),
            Vertex("Entity", "e3", {"tenantId": "other-tenant", "label": "eve", "valid_from": "2025-01-01T00:00:00+00:00"}),
        ]
        edges = [
            Edge("SIMILAR_TO", "e1", "e2", {"tenant_id": TENANT, "valid_from": "2025-01-01T00:00:00+00:00"}),
            Edge("DELEGATES", "e1", "a1", {"tenant_id": TENANT, "valid_from": "2025-01-01T00:00:00+00:00"}),
        ]
        for v in vertices:
            await client.add_vertex(v)
        for e in edges:
            await client.add_edge(e)

    asyncio.run(_seed())

    # Override graph dependency
    from dependencies import providers
    original_get_graph = providers.get_graph

    async def _mock_graph():
        yield client

    app.dependency_overrides[original_get_graph] = _mock_graph

    # Inject minimal tenant state into every request
    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        class _FakeTenant:
            tenant_id = TENANT
            is_platform_admin = False
            def require_permission(self, _): pass

        request.state.tenant = _FakeTenant()
        response = await call_next(request)
        return response

    return TestClient(app), TENANT


# ── /query ────────────────────────────────────────────────────────────────────

def test_query_returns_tenant_nodes(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={"tenant_id": tenant})
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data and "meta" in data
    node_ids = {n["id"] for n in data["nodes"]}
    assert "e1" in node_ids
    assert "e3" not in node_ids, "Cross-tenant node must not appear"


def test_query_node_type_filter(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={"tenant_id": tenant, "node_types": ["Agent"]})
    assert resp.status_code == 200
    for n in resp.json()["nodes"]:
        assert n["kind"] == "agent", f"Expected kind=agent, got {n['kind']}"


def test_query_boolean_filter_eq(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={
        "tenant_id": tenant,
        "filter": {
            "logic": "AND",
            "expressions": [{"field": "status", "op": "eq", "value": "active"}],
        },
    })
    assert resp.status_code == 200
    for n in resp.json()["nodes"]:
        assert n["properties"]["status"] == "active"


def test_query_boolean_filter_or(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={
        "tenant_id": tenant,
        "filter": {
            "logic": "OR",
            "expressions": [
                {"field": "status", "op": "eq", "value": "active"},
                {"field": "status", "op": "eq", "value": "dormant"},
            ],
        },
    })
    assert resp.status_code == 200
    node_ids = {n["id"] for n in resp.json()["nodes"]}
    assert "e1" in node_ids
    assert "e2" in node_ids


def test_query_boolean_filter_not(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={
        "tenant_id": tenant,
        "filter": {
            "logic": "NOT",
            "expressions": [{"field": "status", "op": "eq", "value": "active"}],
        },
    })
    assert resp.status_code == 200
    node_ids = {n["id"] for n in resp.json()["nodes"]}
    assert "e1" not in node_ids, "active node should be excluded by NOT filter"
    assert "e2" in node_ids, "dormant node should pass NOT filter"


def test_query_meta_present(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={"tenant_id": tenant})
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    for field in ["node_count", "edge_count", "execution_ms", "query_id", "budget_used", "truncated"]:
        assert field in meta, f"meta missing field: {field}"


def test_query_cursor_pagination(test_app):
    tc, tenant = test_app
    # First page: limit 1
    resp1 = tc.post("/v1/graph/query", json={"tenant_id": tenant, "limit": 1})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["nodes"]) == 1
    cursor = data1["meta"].get("cursor")
    assert cursor is not None, "cursor should be present when more pages remain"

    # Second page using cursor
    resp2 = tc.post("/v1/graph/query", json={"tenant_id": tenant, "limit": 1, "cursor": cursor})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["nodes"]) == 1
    ids1 = {n["id"] for n in data1["nodes"]}
    ids2 = {n["id"] for n in data2["nodes"]}
    assert ids1.isdisjoint(ids2), "Paginated pages must not overlap"


def test_query_with_anchor_bfs(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/query", json={"tenant_id": tenant, "anchors": ["e1"], "depth": 2})
    assert resp.status_code == 200
    node_ids = {n["id"] for n in resp.json()["nodes"]}
    assert "e1" in node_ids


def test_query_cross_tenant_blocked(test_app):
    tc, tenant = test_app
    # Requesting a different tenant_id — middleware injects the real tenant, so
    # _require_read will block mismatched tenant_ids.
    resp = tc.post("/v1/graph/query", json={"tenant_id": "other-tenant"})
    assert resp.status_code == 403


# ── /facets ───────────────────────────────────────────────────────────────────

def test_facets_returns_node_type_counts(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/facets", json={"tenant_id": tenant, "facet_fields": ["node_type"]})
    assert resp.status_code == 200
    data = resp.json()
    assert "facets" in data
    facet_fields = {f["field"] for f in data["facets"]}
    assert "node_type" in facet_fields


def test_facets_with_filter(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/facets", json={
        "tenant_id": tenant,
        "facet_fields": ["node_type"],
        "filter": {
            "logic": "AND",
            "expressions": [{"field": "status", "op": "eq", "value": "active"}],
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    # Only "active" nodes should appear, so no dormant nodes counted
    facets = {f["field"]: f["values"] for f in data["facets"]}
    node_types = facets.get("node_type", [])
    # We have e1 (Entity, active) and a1 (Agent, active) → 2 active nodes
    total = sum(v["count"] for v in node_types)
    assert total == 2, f"Expected 2 active nodes across facets, got {total}"


def test_facets_meta_present(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/facets", json={"tenant_id": tenant})
    assert resp.status_code == 200
    assert "meta" in resp.json()


# ── /explain ──────────────────────────────────────────────────────────────────

def test_explain_returns_query_plan(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/explain", json={
        "tenant_id": tenant,
        "anchors": ["e1"],
        "depth": 2,
        "filter": {
            "logic": "AND",
            "expressions": [{"field": "status", "op": "eq", "value": "active"}],
        },
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "query_plan" in data
    plan = data["query_plan"]
    assert plan["strategy"] == "anchor_bfs"
    assert plan["depth"] == 2
    assert plan["boolean_filter"] is not None


def test_explain_full_scan_without_anchors(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/explain", json={"tenant_id": tenant})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["query_plan"]["strategy"] == "full_scan"
    assert "full_scan_without_anchors" in data["warnings"]


# ── /export ───────────────────────────────────────────────────────────────────

def test_export_returns_job(test_app):
    tc, tenant = test_app
    resp = tc.post("/v1/graph/export", json={"tenant_id": tenant, "format": "jsonl"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "job_id" in data
    assert data["format"] == "jsonl"
    assert data["download_url"] is not None


# ── /capabilities ─────────────────────────────────────────────────────────────

def test_capabilities_returns_all_operators(test_app):
    tc, _ = test_app
    resp = tc.get("/v1/graph/capabilities")
    assert resp.status_code == 200
    data = resp.json()["data"]
    operators = set(data["filter_operators"])
    required = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in",
                "exists", "not_exists", "contains", "starts_with", "between", "threshold"}
    assert required <= operators, f"Missing operators: {required - operators}"


def test_capabilities_has_temporal_info(test_app):
    tc, _ = test_app
    resp = tc.get("/v1/graph/capabilities")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["temporal"]["point_in_time_replay"] is True
    assert "valid_from" in data["temporal"]["bitemporal_fields"]
