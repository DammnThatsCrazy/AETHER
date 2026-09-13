"""Tests for operational intelligence overlay scoring — no placeholders allowed."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from shared.graph.graph import Edge, GraphClient, Vertex
from services.operational_intelligence.routes import router


FORBIDDEN_STRINGS = [
    "placeholder",
    "future release",
    "scoring engines connect",
]


class Tenant:
    tenant_id = "tenant_a"

    def require_permission(self, permission: str) -> None:
        pass


app = FastAPI()


@app.exception_handler(AetherError)
async def error_handler(request: Request, exc: AetherError) -> JSONResponse:
    return JSONResponse(status_code=exc.code.value, content=exc.to_dict())


@app.middleware("http")
async def inject_tenant(request: Request, call_next):
    request.state.tenant = Tenant()
    return await call_next(request)


app.include_router(router)
client = TestClient(app)


def _assert_no_placeholders(body: dict) -> None:
    body_str = str(body).lower()
    for forbidden in FORBIDDEN_STRINGS:
        assert forbidden.lower() not in body_str, (
            f"Forbidden placeholder string found in response: {forbidden!r}\nBody: {body}"
        )


def test_overlay_has_no_placeholder_strings() -> None:
    response = client.post(
        "/v1/graph/overlay",
        json={"tenantId": "tenant_a", "overlays": ["risk"]},
    )
    assert response.status_code == 200
    _assert_no_placeholders(response.json())


def test_traverse_explainability_has_no_placeholder_strings() -> None:
    response = client.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_1"},
            "depth": 1,
            "overlays": ["trust"],
        },
    )
    assert response.status_code == 200
    _assert_no_placeholders(response.json())


def test_overlay_status_is_computed_or_no_data() -> None:
    """Overlay status must be 'computed' or 'no_data' — never 'placeholder'."""
    response = client.post(
        "/v1/graph/overlay",
        json={"tenantId": "tenant_a", "overlays": ["layer_coverage", "risk", "trust"]},
    )
    assert response.status_code == 200
    body = response.json()
    for overlay in body.get("overlays") or []:
        status = (overlay.get("properties") or {}).get("status", "")
        assert status in ("computed", "no_data"), (
            f"Overlay {overlay['id']} has invalid status: {status!r}"
        )


def test_overlay_no_data_has_reason() -> None:
    """When graph has no data, overlay must include 'reason' field."""
    response = client.post(
        "/v1/graph/overlay",
        json={"tenantId": "tenant_a", "overlays": ["risk"]},
    )
    assert response.status_code == 200
    body = response.json()
    for overlay in body.get("overlays") or []:
        status = (overlay.get("properties") or {}).get("status", "")
        if status == "no_data":
            reason = (overlay.get("properties") or {}).get("reason", "")
            assert reason, "no_data overlay must include a reason"


def test_layer_coverage_overlay_includes_all_four_layers() -> None:
    """When graph has data, layer_coverage overlay must reference all four layers."""
    response = client.post(
        "/v1/graph/overlay",
        json={"tenantId": "tenant_a", "overlays": ["layer_coverage"]},
    )
    assert response.status_code == 200
    body = response.json()
    overlay = next(
        (o for o in (body.get("overlays") or []) if o["id"] == "layer_coverage"),
        None,
    )
    if overlay and (overlay.get("properties") or {}).get("status") == "computed":
        layer_counts = overlay["properties"].get("layer_counts", {})
        for layer in ("H2H", "H2A", "A2H", "A2A"):
            assert layer in layer_counts, f"Layer {layer} missing from layer_coverage overlay"


def test_contracts_endpoint_lists_four_layers() -> None:
    """The /v1/graph/contracts endpoint must list all four relationship layers."""
    response = client.get("/v1/graph/contracts")
    assert response.status_code == 200
    data = response.json()["data"]
    layers = data.get("relationship_layers", [])
    assert "H2H" in layers
    assert "H2A" in layers
    assert "A2H" in layers
    assert "A2A" in layers
