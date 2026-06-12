from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.operational_intelligence.routes import router


class Tenant:
    tenant_id = "tenant_a"

    def require_permission(self, permission: str) -> None:
        assert permission == "read"


app = FastAPI()


@app.exception_handler(AetherError)
async def aether_error_handler(request: Request, exc: AetherError) -> JSONResponse:
    return JSONResponse(status_code=exc.code.value, content=exc.to_dict())


@app.middleware("http")
async def inject_tenant(request: Request, call_next):
    request.state.tenant = Tenant()
    return await call_next(request)


app.include_router(router)
client = TestClient(app)


def test_traverse_route_returns_anchor_node_with_no_skeleton_stage() -> None:
    response = client.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_1", "label": "Ada"},
            "depth": 1,
            "overlays": ["risk"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"][0]["id"] == "user_1"
    # contractStage: skeleton is not a valid production field — it must not appear
    props = body["nodes"][0].get("properties") or {}
    assert "contractStage" not in props or props.get("contractStage") != "skeleton"
    assert body["overlays"][0]["id"] == "risk"
    # Explainability must not claim placeholder/future-release — must describe real layer counts
    summary = body["explainability"]["summary"]
    assert "placeholder" not in summary.lower()
    assert "future release" not in summary.lower()
    assert "H2H=" in summary or "no graph records" in summary


def test_traverse_overlay_status_is_computed_or_no_data() -> None:
    response = client.post(
        "/v1/graph/traverse",
        json={
            "tenantId": "tenant_a",
            "start": {"kind": "user", "id": "user_1", "label": "Ada"},
            "depth": 1,
            "overlays": ["layer_coverage"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    overlay = body["overlays"][0]
    assert overlay["id"] == "layer_coverage"
    # overlay must have status=computed or status=no_data, never placeholder
    status = (overlay.get("properties") or {}).get("status", "")
    assert status in ("computed", "no_data"), f"unexpected overlay status: {status!r}"


def test_path_route_uses_frontend_alias_for_from_entity() -> None:
    response = client.post(
        "/v1/graph/path",
        json={
            "tenantId": "tenant_a",
            "from": {"kind": "user", "id": "user_1"},
            "to": {"kind": "wallet", "id": "wallet_1"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [node["properties"]["role"] for node in body["nodes"]] == ["from", "to"]


def test_route_rejects_tenant_body_mismatch() -> None:
    response = client.post(
        "/v1/graph/filter",
        json={"tenantId": "tenant_b", "filter": {"kinds": ["user"]}},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "tenantId does not match authenticated tenant"


def test_contracts_diagnostic_endpoint_lists_graph_surface_with_four_layers() -> None:
    response = client.get("/v1/graph/contracts")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["routes"] == ["traverse", "path", "temporal", "overlay", "filter"]
    # All four relationship layers must be declared
    layers = data["relationship_layers"]
    assert "H2H" in layers
    assert "H2A" in layers
    assert "A2H" in layers
    assert "A2A" in layers
    assert data["layer_count"] == 4


def test_overlay_route_returns_computed_scores_not_placeholder() -> None:
    response = client.post(
        "/v1/graph/overlay",
        json={
            "tenantId": "tenant_a",
            "overlays": ["risk", "layer_coverage"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    summary = (body.get("explainability") or {}).get("summary", "")
    assert "placeholder" not in summary.lower()
    assert "future release" not in summary.lower()
    # status must be no_data or Overlay computed
    assert "no graph records" in summary or "Overlay computed" in summary


def test_overlay_no_data_is_explicit() -> None:
    """When graph has no records, overlay must return explicit no_data status, not mislead."""
    response = client.post(
        "/v1/graph/overlay",
        json={
            "tenantId": "tenant_a",
            "overlays": ["trust"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    # Must be explicit — either has nodes+edges or no_data
    if body.get("overlays"):
        for overlay in body["overlays"]:
            status = (overlay.get("properties") or {}).get("status", "")
            assert status in ("computed", "no_data"), f"overlay status must be computed or no_data, got {status!r}"
