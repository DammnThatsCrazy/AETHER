"""The Kyber fleet aggregate is mounted and stays operator-only."""
from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402  (requires AETHER_ENV=local before settings load)
from governance.kyber import aggregate  # noqa: E402
from shared.auth.auth import Role, TenantContext  # noqa: E402
from shared.decorators import register_error_handlers  # noqa: E402


def _paths(app) -> set[str]:
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if getattr(route, "path", None) is not None:
            paths.add(route.path)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(inner.routes)
    return paths


def test_the_fleet_aggregate_route_is_mounted_in_the_application():
    assert "/v1/kyber/aggregate/fleet" in _paths(main.app)


def test_an_aether_tenant_admin_is_refused():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(aggregate.router)

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = TenantContext(tenant_id="t1", role=Role.ADMIN, permissions=[])
        request.state.tenant_id = "t1"
        return await call_next(request)

    resp = TestClient(app, raise_server_exceptions=False).get("/v1/kyber/aggregate/fleet")
    assert resp.status_code == 403
