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


def test_traverse_route_validates_and_returns_anchor_node() -> None:
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
    assert body["nodes"][0]["properties"]["contractStage"] == "skeleton"
    assert body["overlays"][0]["id"] == "risk"
    assert body["explainability"]["summary"].startswith("Graph traversal contract validated")


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


def test_contracts_diagnostic_endpoint_lists_graph_surface() -> None:
    response = client.get("/v1/graph/contracts")

    assert response.status_code == 200
    assert response.json()["data"]["routes"] == ["traverse", "path", "temporal", "overlay", "filter"]
