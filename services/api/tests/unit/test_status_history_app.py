"""App-boundary tests for the public ``GET /v1/status/history`` feed.

The unit suite (``test_status_history.py``) mounts the gateway router alone.
These drive the REAL ``main.create_app()`` so the full middleware chain runs:
the route must be reachable without credentials (it is listed in
``feature_gate.PUBLIC_PATHS``), classified by the route registry, and answered
with the same CORS headers every other public endpoint gets for the site
origins in ``CORS_ORIGINS``.

``main`` builds the whole app at import time, so this module is isolated.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AETHER_ENV", "local")

import main as main_module  # noqa: E402
from config.settings import settings  # noqa: E402
from ingestion.gateway import status_history as sh  # noqa: E402
from ingestion.gateway import status_history_repository as repo_mod  # noqa: E402
from shared.rate_limit.feature_gate import PUBLIC_PATHS  # noqa: E402


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _no_pool():
        return None

    monkeypatch.setattr(repo_mod, "get_pool", _no_pool)
    monkeypatch.setattr(sh, "service", sh.StatusHistoryService())
    monkeypatch.setattr(sh, "rate_limiter", sh.PublicIpRateLimiter(1000))
    repo_mod.reset_status_history_store()
    return TestClient(main_module.create_app())


def test_history_route_is_public():
    assert "/v1/status/history" in PUBLIC_PATHS


def test_history_is_served_without_credentials(client: TestClient):
    response = client.get("/v1/status/history?days=90")

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["components"], list)
    assert body["incidents"] == []
    assert response.headers["cache-control"] == sh.CACHE_CONTROL


def test_history_answers_site_origins_with_cors_headers(client: TestClient):
    origin = settings.api.cors_origins[0]
    response = client.get("/v1/status/history", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin

    preflight = client.options(
        "/v1/status/history",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin


def test_history_does_not_open_the_tenant_status_routes(client: TestClient):
    """Only the exact history path is public; its /v1/status siblings are not."""
    assert client.get("/v1/status/incidents").status_code in (401, 403)
