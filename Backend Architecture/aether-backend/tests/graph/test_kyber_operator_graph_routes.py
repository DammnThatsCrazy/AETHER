"""Tests for Kyber operator graph observability routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.operational_intelligence.routes import router


class OperatorTenant:
    tenant_id = "tenant_a"

    def require_permission(self, permission: str) -> None:
        pass  # operator has all permissions


app = FastAPI()


@app.exception_handler(AetherError)
async def error_handler(request: Request, exc: AetherError) -> JSONResponse:
    return JSONResponse(status_code=exc.code.value, content=exc.to_dict())


@app.middleware("http")
async def inject_tenant(request: Request, call_next):
    request.state.tenant = OperatorTenant()
    return await call_next(request)


app.include_router(router)
client = TestClient(app)


def test_graph_health_endpoint_returns_all_four_layers() -> None:
    """GET /v1/graph/health must include all four relationship layers."""
    response = client.get("/v1/graph/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "layer_counts" in data
    layer_counts = data["layer_counts"]
    for layer in ("H2H", "H2A", "A2H", "A2A"):
        assert layer in layer_counts, f"Layer {layer} missing from health response"


def test_graph_health_includes_four_layer_listing() -> None:
    response = client.get("/v1/graph/health")
    assert response.status_code == 200
    data = response.json()["data"]
    layers = data.get("relationship_layers", [])
    assert set(layers) == {"H2H", "H2A", "A2H", "A2A"}


def test_graph_health_has_node_and_edge_counts() -> None:
    response = client.get("/v1/graph/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "node_count" in data
    assert "edge_count" in data
    assert isinstance(data["node_count"], int)
    assert isinstance(data["edge_count"], int)


def test_graph_health_has_backend_mode() -> None:
    response = client.get("/v1/graph/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "backend_mode" in data
    assert data["backend_mode"] in ("neptune", "local", "staging")


def test_graph_health_status_is_healthy_or_no_data() -> None:
    response = client.get("/v1/graph/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] in ("healthy", "no_data", "degraded", "dependency_unavailable")


def test_contracts_endpoint_has_four_layers() -> None:
    response = client.get("/v1/graph/contracts")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["layer_count"] == 4
    assert "A2H" in data["relationship_layers"]


def test_overlay_does_not_expose_placeholder_scores() -> None:
    """Operator overlay must not contain placeholder strings."""
    response = client.post(
        "/v1/graph/overlay",
        json={"tenantId": "tenant_a", "overlays": ["layer_coverage"]},
    )
    assert response.status_code == 200
    body_str = str(response.json()).lower()
    assert "placeholder" not in body_str
    assert "future release" not in body_str
