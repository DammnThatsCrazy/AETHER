"""Security tests for the backend-owned local development identity."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Response
from fastapi import FastAPI

from repositories.repos import reset_in_memory_stores
from services.auth import dev_routes
from services.auth.sessions import session_service
from shared.common.common import ForbiddenError

def request(host: str):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def route_paths(app: FastAPI) -> set[str]:
    """All route paths on the app, descending into included routers.

    FastAPI mounts included routers as ``_IncludedRouter`` entries that have no
    ``path`` of their own; their routes live on ``original_router``.
    """
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(inner.routes)
    return paths


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_loopback_issues_random_durable_session_not_api_key():
    first = await dev_routes.create_development_session(
        request("127.0.0.1"), Response()
    )
    second = await dev_routes.create_development_session(
        request("::1"), Response()
    )
    first_data = first["data"]
    second_data = second["data"]

    assert "api_key" not in first_data
    assert first_data["session"]["token"].startswith("sess_")
    assert first_data["session"]["token"] != second_data["session"]["token"]
    stored = await session_service.validate_session(first_data["session"]["token"])
    assert stored["tenant_id"] == first_data["tenant_id"]
    assert stored["metadata"]["source"] == "loopback_development_session"


@pytest.mark.asyncio
async def test_non_loopback_client_is_refused():
    with pytest.raises(ForbiddenError):
        await dev_routes.create_development_session(
            request("192.0.2.10"), Response()
        )


@pytest.mark.asyncio
async def test_staging_and_production_are_refused(monkeypatch):
    for env in ("staging", "production"):
        monkeypatch.setattr(
            dev_routes.settings, "env", SimpleNamespace(value=env)
        )
        with pytest.raises(ForbiddenError):
            await dev_routes.create_development_session(
                request("127.0.0.1"), Response()
            )


def test_router_is_unmounted_from_staging_and_production():
    for env in ("staging", "production"):
        app = FastAPI()
        dev_routes.mount_development_auth(app, env)
        assert "/v1/auth/development-session" not in route_paths(app)

    local_app = FastAPI()
    dev_routes.mount_development_auth(local_app, "local")
    assert "/v1/auth/development-session" in route_paths(local_app)
