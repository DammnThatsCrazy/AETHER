"""Identity reads require the ``read`` permission, not only a tenant."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity.identity import routes
from shared.decorators import register_error_handlers
from shared.auth.auth import Role, TenantContext

READ_ROUTES = [
    "/v1/identity/entities/e-1",
    "/v1/identity/entities/e-1/aliases",
    "/v1/identity/entities/e-1/graph",
    "/v1/identity/entities/e-1/audit",
    "/v1/identity/conflicts",
    "/v1/identity/profiles/u-1",
    "/v1/identity/profiles/u-1/graph",
]


def _client(permissions: list[str], role: Role = Role.VIEWER) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(routes.router)

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = TenantContext(tenant_id="t-1", role=role, permissions=permissions)
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", READ_ROUTES)
def test_a_credential_without_read_is_refused(path):
    assert _client(["write"]).get(path).status_code == 403


@pytest.mark.parametrize("path", READ_ROUTES)
def test_a_credential_with_read_gets_past_the_permission_check(path):
    # Nothing is stored for these ids, so a permitted read answers 404 (or 200 for the
    # list); what matters is that it is no longer refused.
    assert _client(["read"]).get(path).status_code != 403


@pytest.mark.parametrize("path", READ_ROUTES)
def test_an_admin_is_not_refused(path):
    assert _client([], role=Role.ADMIN).get(path).status_code != 403
