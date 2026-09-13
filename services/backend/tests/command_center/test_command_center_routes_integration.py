"""End-to-end integration tests for the mounted ``/v1/command-center`` route.

The unit suite drives ``CommandCenterService`` directly; this suite exercises the
**HTTP surface**: a scoped FastAPI app mounts the real ``command_center`` router,
injects an authenticated tenant onto ``request.state.tenant`` exactly as the auth
middleware does, and calls the endpoint through ``TestClient``. This proves the
route, the ``require_permission(read)`` edge, and — critically — the
operator-leak guard: a tenant Command Center response must carry NO operator-only
fields (no agent/ops-alert data, no operator briefings, no Kyber internals).

The package is flag-gated OFF in production (mounted only when
``AETHER_COMMAND_CENTER_ENABLED=true``); here the router is included
unconditionally, which is exactly what the gate does when the flag is on.
"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from repositories.repos import CampaignRepository
from services.command_center.routes import router as command_center_router
from services.intelligence.repositories import (
    OutcomeRepository,
    RecommendationRepository,
)

from .conftest import _Tenant

_ALL_SECTIONS = {
    "activation",
    "value_strip",
    "ops_feed",
    "graph_snapshot",
    "campaign_movement",
    "data_confidence",
    "integration_health",
    "outcomes",
    "next_best_actions",
}

# Fields/markers that are operator-only and must NEVER surface in a tenant view.
# ``tenant_impact._safe_incident`` explicitly forbids the first four; the rest
# name operator-only services and admin twins the aggregator must never import.
_OPERATOR_LEAK_MARKERS = (
    "affected_tenants",
    "affected_services",
    "internal_notes",
    "root_cause",
    "ops_alert",
    "briefing",
    "/v1/admin/kyber",
    "kyber_operator",
    "internal_summary",
)


def _client(tenant_id: str = "cc-http", permissions=None) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = _Tenant(tenant_id, permissions)
        return await call_next(request)

    app.include_router(command_center_router)
    return TestClient(app)


def _seed(tenant_id: str) -> None:
    """Seed a campaign + a completed ledger loop so several sections go live."""

    async def _run() -> None:
        await CampaignRepository().insert(
            f"{tenant_id}-camp",
            {
                "tenant_id": tenant_id,
                "name": "HTTP Campaign",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        await RecommendationRepository().insert(
            f"{tenant_id}-rec",
            {
                "tenant_id": tenant_id,
                "recommendation_id": f"{tenant_id}-rec",
                "recommendation_type": "growth",
                "expected_value": 100,
                "status": "viewed",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        await OutcomeRepository().insert(
            f"{tenant_id}-out",
            {
                "tenant_id": tenant_id,
                "recommendation_id": f"{tenant_id}-rec",
                "label": "success",
                "value": 120,
                "created_at": "2026-01-02T00:00:00Z",
            },
        )

    asyncio.run(_run())


def test_command_center_returns_200_with_all_sections() -> None:
    _seed("cc-http")
    resp = _client().get("/v1/command-center")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"

    data = body["data"]
    assert data["tenant_id"] == "cc-http"
    assert set(data["sections"].keys()) == _ALL_SECTIONS

    # Every section carries an honest state + provenance.
    for key, env in data["sections"].items():
        assert env["key"] == key
        assert env["state"] in {
            "live",
            "no_data",
            "not_configured",
            "unavailable",
            "error",
        }
        assert env["source"]

    # The seeded campaign + ledger drive their sections live over HTTP.
    assert data["sections"]["campaign_movement"]["state"] == "live"
    assert data["sections"]["value_strip"]["state"] == "live"
    assert data["sections"]["outcomes"]["state"] == "live"


def test_read_permission_is_enforced() -> None:
    """A caller without ``read`` is refused with 403 at the route boundary."""
    resp = _client(permissions=set()).get("/v1/command-center")
    assert resp.status_code == 403, resp.text


def test_response_carries_no_operator_only_fields() -> None:
    """Operator-leak guard: no agent/ops, briefings, or Kyber internals present."""
    _seed("cc-http")
    resp = _client().get("/v1/command-center")
    assert resp.status_code == 200, resp.text
    blob = resp.text.lower()
    for marker in _OPERATOR_LEAK_MARKERS:
        assert marker.lower() not in blob, f"operator-only marker leaked: {marker}"
