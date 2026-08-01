"""End-to-end integration tests for the mounted ``/v1/activation`` routes.

The unit suite (`test_activation_*`) drives ``ActivationService`` directly. These
tests exercise the **HTTP surface** instead: a scoped FastAPI app that mounts the
real ``activation_router``, injects an authenticated tenant onto
``request.state.tenant`` exactly as the auth middleware does, and walks the full
self-serve flow through ``TestClient``. This proves the routes, the
``require_permission`` edge, the in-process ``/v1/batch`` reuse seam, the Bronze
first-value proof, and the ``complete`` gate all work together over HTTP — not
just at the service layer.

The activation package is flag-gated OFF in production (mounted only when
``AETHER_ACTIVATION_ENABLED=true``); the mount decision itself is covered by
``test_activation_mount_gating.py``. Here the router is included unconditionally,
which is exactly what the gate does when the flag is on.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.activation.routes import router as activation_router

from .conftest import _Tenant


def _client(tenant_id: str = "tenant-http") -> TestClient:
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


def test_full_self_serve_flow_over_http() -> None:
    """plan -> sdk -> keys -> (complete refused) -> test-event -> first value -> complete."""
    client = _client()

    # A lazily-created record for an authenticated caller starts verified.
    status = _data(client.get("/v1/activation/status"))
    assert status["state"] in {"not_started", "account_verified"}

    # select-plan records the tier and derives billing state (pending without an
    # active Stripe subscription) — the tier is the durable outcome.
    planned = _data(client.post("/v1/activation/select-plan", json={"plan_tier": "P2"}))
    assert planned["selected_plan_tier"] == "P2"
    assert planned["state"] in {"plan_selected", "billing_pending", "billing_active"}

    sdks = _data(client.post("/v1/activation/sdk-selection", json={"platforms": ["web"]}))
    assert "web" in sdks["sdk_selection"] and sdks["state"] == "sdk_selected"

    keys = _data(client.post("/v1/activation/create-sdk-keys", json={"count": 1, "label": "http key"}))
    assert keys["state"] == "waiting_for_event"
    assert keys["keys"] and keys["keys"][0].get("key"), "raw key must be returned once"

    # No durable event yet -> not ready, and complete is refused with 409.
    fv = _data(client.get("/v1/activation/first-value"))
    assert fv["ready"] is False and fv["state"] == "waiting_for_event"
    refused = client.post("/v1/activation/complete")
    assert refused.status_code == 409, refused.text

    # A real event through the in-process /v1/batch path proves first value.
    ev = _data(client.post("/v1/activation/test-event", json={"event_type": "track"}))
    assert ev["results"] and ev["results"][0]["status"] == "accepted"
    assert ev["state"] in {"event_received", "first_value_ready"}

    ready = _data(client.get("/v1/activation/first-value"))
    assert ready["ready"] is True and ready["state"] == "first_value_ready"
    assert ready["evidence"], "first-value evidence must reference the real Bronze row"

    assert _data(client.post("/v1/activation/complete"))["state"] == "complete"


def test_status_reports_derived_billing_state_over_http() -> None:
    """The status read exposes a derived (read-only) billing_state field."""
    status = _data(_client().get("/v1/activation/status"))
    assert "billing_state" in status


def test_select_plan_rejects_bad_tier_with_422() -> None:
    """Pydantic validation on the mounted route rejects a non-P1..P4 tier."""
    resp = _client().post("/v1/activation/select-plan", json={"plan_tier": "GOLD"})
    assert resp.status_code == 422, resp.text
