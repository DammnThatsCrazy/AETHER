"""Identity routes must declare the envelope they actually return.

Every identity route returns ``APIResponse(...).to_dict()``. Declaring the bare
payload as ``response_model`` made FastAPI validate the envelope against it and
answer 500. Staging rehearsal run 43365158651 hit this on
``POST /v1/identity/resolve``. These tests send real HTTP requests, so FastAPI's
response validation runs; calling the route function directly skips it.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from config.settings import settings
from identity.identity import routes


class _Tenant:
    tenant_id = "tenant-envelope-contract"

    def require_permission(self, permission):
        return None


def _client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request, call_next):
        request.state.tenant = _Tenant()
        return await call_next(request)

    app.include_router(routes.router)
    app.include_router(routes.router_admin)
    return TestClient(app)


@pytest.mark.parametrize("router", [routes.router, routes.router_admin])
def test_every_identity_response_model_is_the_api_envelope(router):
    # A plain ``dict`` model accepts the envelope; only pydantic models can
    # reject it.
    declared = [
        r for r in router.routes
        if isinstance(r, APIRoute) and isinstance(r.response_model, type)
        and issubclass(r.response_model, BaseModel)
    ]
    assert declared
    for route in declared:
        fields = set(route.response_model.model_fields)
        assert {"data", "status", "timestamp", "meta"} <= fields, (
            f"{sorted(route.methods)} {route.path} declares {route.response_model.__name__}, "
            "not the APIResponse envelope it returns"
        )


def test_resolve_returns_a_blocked_envelope_over_http_when_disabled(monkeypatch):
    monkeypatch.setattr(
        settings, "identity_continuity",
        replace(settings.identity_continuity, resolution_enabled=False),
    )
    response = _client().post("/v1/identity/resolve", json={
        "event_id": "envelope-1", "anonymous_id": "anonymous-1",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["decision"] == "blocked"
    assert body["data"]["blocked_reason"] == "identity_resolution_disabled"
    assert body["data"]["tenant_id"] == _Tenant.tenant_id
