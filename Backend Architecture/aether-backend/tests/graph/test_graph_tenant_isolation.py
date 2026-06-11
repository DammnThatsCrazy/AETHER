"""Tests for graph tenant isolation — cross-tenant traversal must fail closed."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.operational_intelligence.routes import router


class TenantA:
    tenant_id = "tenant_a"

    def require_permission(self, permission: str) -> None:
        assert permission == "read"


class TenantB:
    tenant_id = "tenant_b"

    def require_permission(self, permission: str) -> None:
        assert permission == "read"


def _make_app(tenant) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def error_handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant = tenant
        return await call_next(request)

    app.include_router(router)
    return app


client_a = TestClient(_make_app(TenantA()))
client_b = TestClient(_make_app(TenantB()))


def test_tenant_a_cannot_traverse_with_tenant_b_id() -> None:
    """Tenant A client sending tenantId=tenant_b must receive 403."""
    response = client_a.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_b",
            "start": {"kind": "user", "id": "user_from_b"},
            "depth": 2,
        },
    )
    assert response.status_code == 403
    assert "tenantId does not match" in response.json()["error"]["message"]


def test_tenant_b_cannot_traverse_with_tenant_a_id() -> None:
    """Tenant B client sending tenantId=tenant_a must receive 403."""
    response = client_b.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_from_a"},
            "depth": 2,
        },
    )
    assert response.status_code == 403


def test_tenant_a_cannot_path_through_tenant_b_id() -> None:
    """Path request with mismatched tenant must be rejected."""
    response = client_a.post(
        "/v1/graph/path",
        json={
            "tenantId": "tenant_b",
            "from": {"kind": "user", "id": "user_1"},
            "to": {"kind": "agent", "id": "agent_1"},
        },
    )
    assert response.status_code == 403


def test_tenant_a_cannot_overlay_tenant_b() -> None:
    """Overlay request with mismatched tenant must be rejected."""
    response = client_a.post(
        "/v1/graph/overlay",
        json={
            "tenantId": "tenant_b",
            "overlays": ["risk"],
        },
    )
    assert response.status_code == 403


def test_tenant_a_cannot_filter_with_tenant_b_id() -> None:
    """Filter request with mismatched tenant must be rejected."""
    response = client_a.post(
        "/v1/graph/filter",
        json={
            "tenantId": "tenant_b",
            "filter": {"kinds": ["user"]},
        },
    )
    assert response.status_code == 403


def test_correct_tenant_id_is_accepted() -> None:
    """Matching tenantId must be accepted (200 OK)."""
    response = client_a.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_1"},
            "depth": 1,
        },
    )
    assert response.status_code == 200


def test_traverse_result_does_not_include_other_tenant_role() -> None:
    """Traverse result nodes must not carry another tenant's tenantId in properties."""
    response = client_a.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_1"},
            "depth": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    for node in body.get("nodes", []):
        props = node.get("properties") or {}
        if "tenantId" in props:
            assert props["tenantId"] == "tenant_a", (
                f"Node carries foreign tenantId: {props['tenantId']}"
            )
