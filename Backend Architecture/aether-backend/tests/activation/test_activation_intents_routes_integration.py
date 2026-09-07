"""WS-3 intent + connect-plan endpoints over HTTP (route surface).

Mirrors the sibling ``test_activation_routes_integration`` harness: a scoped
FastAPI app mounts the real ``activation_router`` and injects an authenticated
tenant onto ``request.state.tenant``. Exercises the additive intent/plan surface:

    GET  /v1/activation/intents           intent picker (catalog projection)
    POST /v1/activation/intents           durable intent selection
    GET  /v1/activation/plan              recommended connect plan
    POST /v1/activation/connect-action    run one connect step via connector_service

The plan is derived from the SAME tenant connector rows the Settings surface
reads, so a connect action taken here must show up in the very next plan read.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.activation.routes import router as activation_router

from .conftest import _Tenant


def _client(tenant_id: str = "tenant-ws3") -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = _Tenant(tenant_id)
        return await call_next(request)

    app.include_router(activation_router)
    return TestClient(app)


def _data(resp) -> dict:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    return body["data"]


def test_intent_picker_http() -> None:
    data = _data(_client().get("/v1/activation/intents"))
    intents = data["intents"]
    assert [i["token"] for i in intents] == [
        "grow_revenue",
        "run_advertising",
        "know_customers",
        "engage_customers",
        "understand_behavior",
        "grow_community",
        "support_customers",
        "streamline_work",
    ]
    assert len(data["experience_categories"]) == 8
    assert all(i["label"] and i["recommended_categories"] for i in intents)


def test_plan_needs_selection_before_intents_http() -> None:
    data = _data(_client().get("/v1/activation/plan"))
    assert data["needs_selection"] is True
    assert data["categories"] == []


def test_select_intents_then_plan_over_http() -> None:
    client = _client("tenant-ws3-plan")
    saved = _data(
        client.post(
            "/v1/activation/intents",
            json={"intents": ["run_advertising", "grow_revenue"]},
        )
    )
    assert saved["intents"] == ["grow_revenue", "run_advertising"]

    plan = _data(client.get("/v1/activation/plan"))
    assert plan["needs_selection"] is False
    assert plan["selected_intents"] == ["grow_revenue", "run_advertising"]
    commerce = plan["categories"][0]
    assert commerce["experience_category"] == "commerce_revenue"
    assert commerce["integrations"], "commerce block carries connect steps"
    # Fresh tenant -> every commerce integration offers create_tenant_integration.
    for integration in commerce["integrations"]:
        assert integration["connectable"] is True
        assert integration["connection_state"] == "available"
        assert integration["next_action"] == "create_tenant_integration"
        assert integration["can_act"] is True


def test_connect_action_then_plan_reflects_the_new_row_http() -> None:
    """A connect action is immediately visible in the next plan read."""
    client = _client("tenant-ws3-ca")
    _data(client.post("/v1/activation/intents", json={"intents": ["grow_revenue"]}))

    result = _data(
        client.post(
            "/v1/activation/connect-action",
            json={"family": "shopify", "action": "create_tenant_integration"},
        )
    )
    assert result["ok"] is True
    assert result["connection_state"] == "credential_waiting"
    assert result["next_action"] == "configure_credential"

    plan = _data(client.get("/v1/activation/plan"))
    shopify = _plan_integration(plan, "shopify")
    assert shopify["connection_state"] == "credential_waiting"
    assert shopify["next_action"] == "configure_credential"
    assert shopify["record"] is not None


def test_connect_action_rejects_unknown_action_with_400_http() -> None:
    resp = _client().post(
        "/v1/activation/connect-action",
        json={"family": "shopify", "action": "teleport"},
    )
    assert resp.status_code == 400, resp.text


def test_connect_action_rejects_non_selfserve_family_with_400_http() -> None:
    resp = _client().post(
        "/v1/activation/connect-action",
        json={"family": "google_ads", "action": "create_tenant_integration"},
    )
    assert resp.status_code == 400, resp.text


def _plan_integration(plan: dict, family: str) -> dict:
    for block in plan["categories"]:
        for integration in block["integrations"]:
            if integration["family"] == family:
                return integration
    raise AssertionError(f"{family} not present in plan")
