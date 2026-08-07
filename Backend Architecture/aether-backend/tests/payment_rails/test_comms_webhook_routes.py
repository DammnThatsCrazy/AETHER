"""ADR-C11 route enforcement — comms webhooks never accept a tenant header.

Route-level proof (the unit tests prove the registry + schemes in isolation; this
proves the *routes* enforce ADR-C11):

* A comms connector on the legacy ``X-Aether-Tenant-ID`` route is a permanent
  400 denial, even with the header present and a valid signature.
* The ``/comms/{connector}/{endpoint_id}`` route resolves tenant ownership
  server-side from the durable ``whe_`` registry — no tenant header — and a
  genuine generic Aether HMAC verifies end to end.
* Unknown/revoked endpoints and unknown connectors return a uniform 404.
* Non-comms connectors keep the legacy header route (regression guard).
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.common.common import AetherError  # noqa: E402
from services.integrations.connectors.routes import (  # noqa: E402
    router as connectors_router,
    webhook_public_router,
)
from services.integrations.connectors.service import connector_service  # noqa: E402
from services.integrations.providers.payment_rails.webhook_endpoints import (  # noqa: E402
    DOMAIN_COMMS,
    webhook_endpoint_registry,
)
from services.security.integration_security import sign_payload  # noqa: E402

KLAVIYO_PAYLOAD = {
    "data": [
        {
            "id": "evt_comms_route_1",
            "type": "event",
            "attributes": {
                "metric": {"data": {"attributes": {"name": "Delivered Email"}}},
                "datetime": "2026-07-01T12:00:00Z",
                "event_properties": {"$email": "person@example.com", "$message": "msg_5"},
            },
        }
    ]
}


def _make_app() -> FastAPI:
    """Minimal app: the two connector routers + Aether error handling + tenant stub."""
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _aether_errors(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request, call_next):
        request.state.tenant = _FakeTenant()
        return await call_next(request)

    app.include_router(connectors_router)
    app.include_router(webhook_public_router)
    return app


class _FakeTenant:
    tenant_id = "tenantA"
    user_id = "user_test"

    @staticmethod
    def require_permission(_perm: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _fresh_stores():
    reset_in_memory_stores()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


# ── ADR-C11: comms connectors are permanently denied on the tenant-header route ─


def test_comms_connector_denied_on_tenant_header_route(client):
    """klaviyo is a comms connector → the legacy header route is a permanent 400."""
    raw_body = json.dumps(KLAVIYO_PAYLOAD).encode()
    headers = sign_payload("pk_abc123", raw_body)
    resp = client.post(
        "/v1/integrations/webhooks/klaviyo",
        headers={
            "X-Aether-Tenant-ID": "tenantA",
            **headers,
            "content-type": "application/json",
        },
        content=raw_body,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "durable endpoint id" in body.get("detail", "")
    assert "/comms/" in body.get("detail", "")


def test_unknown_connector_on_header_route_is_404(client):
    resp = client.post("/v1/integrations/webhooks/nope")
    assert resp.status_code == 404


def test_non_comms_connector_keeps_legacy_header_route(client):
    """shopify passes the comms gate — it fails later on the missing tenant header,
    proving the ADR denial is specific to comms connectors."""
    resp = client.post("/v1/integrations/webhooks/shopify", content=b"{}")
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "X-Aether-Tenant-ID header is required" in detail
    assert "durable endpoint id" not in detail


# ── ADR-C11: /comms/{connector}/{endpoint_id} resolves tenant server-side ─────


def test_comms_endpoint_route_unknown_endpoint_is_404(client):
    resp = client.post("/v1/integrations/webhooks/comms/klaviyo/whe_nonexistent")
    assert resp.status_code == 404
    # uniform denial — the same body for a non-comms connector on this route
    resp2 = client.post("/v1/integrations/webhooks/comms/shopify/whe_nonexistent")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_comms_endpoint_route_happy_path(client):
    """Server-resolved tenant + connector secret + genuine HMAC → accepted 2xx."""
    await connector_service.configure(
        "tenantA", "klaviyo", enabled=True, credential="pk_abc123"
    )
    ep = await webhook_endpoint_registry.create(
        "tenantA", "klaviyo", "sandbox",
        created_by="admin", domain=DOMAIN_COMMS,
    )
    raw_body = json.dumps(KLAVIYO_PAYLOAD).encode()
    headers = sign_payload("pk_abc123", raw_body)

    with patch(
        "services.comms.ingest.ingest_normalized_events",
        new=AsyncMock(return_value={"communications": 1, "catalog": 0, "identities": 0, "skipped": 0}),
    ):
        resp = client.post(
            f"/v1/integrations/webhooks/comms/klaviyo/{ep['endpoint_id']}",
            headers={**headers, "content-type": "application/json"},
            content=raw_body,
        )
    assert resp.status_code == 200, resp.text
    data = resp.json().get("data", {})
    assert data.get("accepted") is True
    assert data.get("events_ingested") == 1


@pytest.mark.asyncio
async def test_comms_endpoint_route_bad_signature_denied(client):
    """A wrong-secret HMAC is denied (400) — the endpoint id alone is not auth."""
    await connector_service.configure(
        "tenantA", "klaviyo", enabled=True, credential="pk_abc123"
    )
    ep = await webhook_endpoint_registry.create(
        "tenantA", "klaviyo", "sandbox",
        created_by="admin", domain=DOMAIN_COMMS,
    )
    raw_body = json.dumps(KLAVIYO_PAYLOAD).encode()
    headers = sign_payload("pk_wrong", raw_body)
    resp = client.post(
        f"/v1/integrations/webhooks/comms/klaviyo/{ep['endpoint_id']}",
        headers={**headers, "content-type": "application/json"},
        content=raw_body,
    )
    assert resp.status_code == 400
    assert "rejected" in resp.json().get("detail", "")


# ── Tenant-admin endpoint management surface ──────────────────────────────────


def test_mint_comms_webhook_endpoint_route(client):
    resp = client.post("/v1/integrations/connectors/klaviyo/webhook-endpoints",
                       json={"environment": "sandbox"})
    assert resp.status_code == 200, resp.text
    data = resp.json().get("data", {})
    assert data["endpoint_id"].startswith("whe_")
    assert data["domain"] == "comms"
    assert data["webhook_path"].startswith("/v1/integrations/webhooks/comms/klaviyo/")


def test_mint_endpoint_for_non_comms_connector_is_404(client):
    resp = client.post("/v1/integrations/connectors/shopify/webhook-endpoints",
                       json={"environment": "sandbox"})
    assert resp.status_code == 404
