"""
GET /v1/capabilities — feature_flags carries the Data Exchange plane switch.

The Data Exchange routers are mounted in main.py only when
``settings.data_exchange.enabled`` is on.  Frontend surfaces therefore read the
canonical capability contract (always-mounted /v1/capabilities) to decide
whether to mount Data Exchange sections at all — so the flag must be present and
mirror the same setting the router mount reads.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from config.settings import DataExchangeConfig, settings
from services.capabilities.routes import router


def _make_app() -> FastAPI:
    """Build a minimal app with the capabilities router and a stubbed tenant.

    Mirror of the route harness used elsewhere (e.g. the suggestion-routes
    smoke suite): a middleware injects a synthetic tenant into
    ``request.state``, and provider-health / consent lookups fall back to the
    guarded ``None`` paths inside the handler.
    """
    app = FastAPI()

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        tenant = MagicMock()
        tenant.tenant_id = "tenant_caps_test"
        tenant.user_id = "user_caps_test"
        tenant.require_permission = MagicMock()
        request.state.tenant = tenant
        return await call_next(request)

    app.include_router(router)
    return app


def _get_feature_flags(client: TestClient) -> dict[str, bool]:
    response = client.get("/v1/capabilities")
    assert response.status_code == 200, response.text
    envelope = response.json()
    return envelope["data"]["feature_flags"]


@pytest.fixture
def client():
    return TestClient(_make_app())


def test_capabilities_feature_flags_include_data_exchange_disabled_by_default(client) -> None:
    """A default (plane-OFF) deployment advertises data_exchange_enabled=false."""
    flags = _get_feature_flags(client)
    assert flags["data_exchange_enabled"] is False


def test_capabilities_feature_flags_mirror_settings_data_exchange_enabled(
    client, monkeypatch
) -> None:
    """The flag tracks settings.data_exchange.enabled exactly (mirrors the
    main.py router-mount gate)."""
    monkeypatch.setattr(settings, "data_exchange", DataExchangeConfig(enabled=True))
    flags = _get_feature_flags(client)
    assert flags["data_exchange_enabled"] is True
