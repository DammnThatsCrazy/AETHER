"""Route-level tests for POST /v1/campaign-sources/{connector_id}/reconnect.

The reconnect endpoint is the honest in-place re-credential path for a
degraded / failed / disabled / revoked ad source. It mirrors the sibling
``/connect`` route tests in ``test_campaign_registry_api.py`` (scoped FastAPI
app, tenant injected via middleware, AetherError mapped to its HTTP code), and
it pins the wire contract:

* 404 for an unknown connector_id;
* 409 for an ACTIVE + HEALTHY row (a healthy source does not need
  re-credentialing; disable it first for the disable→enable path);
* 200 that replaces the stored credential set on the SAME row (connector_id and
  sync history preserved) and resets health/error state to the never-synced
  baseline — never claiming the source is Ready/healthy again;
* a DISABLED row stays disabled after re-credentialing (a re-credential is not
  a re-activation).
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from shared.common.common import AetherError
    from services.campaign.routes import sources_router
    from services.measurement.repositories.measurement_connector_repo import (
        MeasurementConnectorRepository,
        _reset_local_connectors,
    )

    _FASTAPI_AVAILABLE = True
except (ImportError, Exception):
    _FASTAPI_AVAILABLE = False
    FastAPI = None
    TestClient = None
    MeasurementConnectorRepository = None
    _reset_local_connectors = None


pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="FastAPI app not importable (missing dependencies)",
)

GOOGLE_CONFIG_A: dict[str, str] = {
    "customer_id": "123-456",
    "developer_token": "dev-token",
    "client_id": "client-id",
    "client_secret": "client-secret",
    "refresh_token": "rt-secret",
}
GOOGLE_CONFIG_B: dict[str, str] = {
    "customer_id": "123-456",
    "developer_token": "dev-token-B",
    "client_id": "client-id",
    "client_secret": "client-secret-B",
    "refresh_token": "rt-secret-B",
}

_TENANT_HEADER = "x-test-tenant"
_DEFAULT_TENANT = "reconnect-tenant"


class _CampaignTestTenant:
    def __init__(self, tenant_id: str = _DEFAULT_TENANT) -> None:
        self.tenant_id = tenant_id

    def require_permission(self, permission: str) -> None:
        return None


def _build_app():
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _error_handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = _CampaignTestTenant(
            request.headers.get(_TENANT_HEADER, _DEFAULT_TENANT)
        )
        return await call_next(request)

    app.include_router(sources_router)
    return app


@pytest.fixture(autouse=True)
def _local_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool() -> None:
        return None

    monkeypatch.setattr(
        "services.measurement.repositories.measurement_connector_repo.get_pool",
        no_pool,
    )
    _reset_local_connectors()
    yield
    _reset_local_connectors()


@pytest.fixture()
def client():
    if not _FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not available")
    return TestClient(_build_app())


# ── sync-test helpers (repo is plain local-memory async; run it per call) ──

def _create_google_source() -> str:
    async def _do() -> str:
        created = await MeasurementConnectorRepository().create(
            tenant_id=_DEFAULT_TENANT, connector_type="google_ads", name="Google",
            config=GOOGLE_CONFIG_A,
        )
        return created["connector_id"]
    return asyncio.run(_do())


def _mark_healthy(connector_id: str) -> None:
    async def _do() -> None:
        await MeasurementConnectorRepository().record_sync(
            _DEFAULT_TENANT, connector_id, success=True, health_status="healthy"
        )
    asyncio.run(_do())


def _degrade(connector_id: str) -> None:
    async def _do() -> None:
        await MeasurementConnectorRepository().record_sync(
            _DEFAULT_TENANT, connector_id, success=False, health_status="error"
        )
    asyncio.run(_do())


def _get_source(connector_id: str) -> dict:
    async def _do() -> dict:
        row = await MeasurementConnectorRepository().get(_DEFAULT_TENANT, connector_id)
        assert row is not None
        return row
    return asyncio.run(_do())


def _set_status(connector_id: str, status: str) -> None:
    async def _do() -> None:
        await MeasurementConnectorRepository().set_status(
            _DEFAULT_TENANT, connector_id, status
        )
    asyncio.run(_do())


def _row_count() -> int:
    async def _do() -> int:
        rows = await MeasurementConnectorRepository().list_for_tenant(_DEFAULT_TENANT)
        return len(rows)
    return asyncio.run(_do())


class TestCampaignSourceReconnectEndpoint:
    def test_reconnect_unknown_connector_is_404(self, client):
        resp = client.post(
            "/v1/campaign-sources/does-not-exist/reconnect",
            json={"secret_config": GOOGLE_CONFIG_B},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["status"] == 404

    def test_reconnect_healthy_active_row_is_409(self, client):
        connector_id = _create_google_source()
        _mark_healthy(connector_id)

        resp = client.post(
            f"/v1/campaign-sources/{connector_id}/reconnect",
            json={"secret_config": GOOGLE_CONFIG_B},
        )
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert "active and healthy" in body["detail"]
        # The healthy row must not be touched.
        stored = _get_source(connector_id)
        assert stored["config"] == GOOGLE_CONFIG_A
        assert stored["health_status"] == "healthy"

    def test_reconnect_degraded_row_replaces_config_in_place(self, client):
        connector_id = _create_google_source()
        _degrade(connector_id)

        resp = client.post(
            f"/v1/campaign-sources/{connector_id}/reconnect",
            json={"secret_config": GOOGLE_CONFIG_B},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["reconnected"] is True
        assert data["connector_id"] == connector_id
        assert data["source"]["connector_id"] == connector_id
        # Honest post-state: health reset to never-synced, never Ready/healthy.
        assert data["source"]["health_status"] == "unknown"
        assert data["source"]["error_count"] == 0
        assert data["source"]["secret_configured"] is True

        # SAME row retained — exactly one row, config replaced, health reset.
        stored = _get_source(connector_id)
        assert stored["connector_id"] == connector_id
        assert stored["config"] == GOOGLE_CONFIG_B
        assert stored["health_status"] == "unknown"
        assert stored["error_count"] == 0
        assert _row_count() == 1

    def test_reconnect_disabled_row_keeps_it_disabled(self, client):
        connector_id = _create_google_source()
        _set_status(connector_id, "disabled")

        resp = client.post(
            f"/v1/campaign-sources/{connector_id}/reconnect",
            json={"secret_config": GOOGLE_CONFIG_B},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "disabled"
        stored = _get_source(connector_id)
        assert stored["status"] == "disabled"
        assert stored["config"] == GOOGLE_CONFIG_B

    def test_reconnect_partial_credential_set_is_400(self, client):
        connector_id = _create_google_source()
        _degrade(connector_id)

        resp = client.post(
            f"/v1/campaign-sources/{connector_id}/reconnect",
            json={"secret_config": {"refresh_token": "rt-secret-B"}},
        )
        assert resp.status_code == 400, resp.text
        assert "Incomplete google_ads credential set" in resp.json()["detail"]
