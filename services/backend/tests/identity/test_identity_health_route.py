"""Regression: ``GET /v1/identity/health`` through FastAPI's response validation.

On the staging stack the endpoint answered 500 with::

    1 validation error: ('response', 'status') Input should be 'healthy',
    'degraded' or 'unhealthy' — input: 'success'

The route returns the standard ``APIResponse`` envelope (``{"data": {...},
"status": "success", ...}``) but declared ``response_model=IdentityHealthResponse``
— the *inner* model — so FastAPI validated the envelope's ``status`` against the
health literal. The existing unit tests call the coroutine directly and never
exercise response-model serialization; these go through a real ASGI app.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.identity import routes


def _client(repo) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request, call_next):
        request.state.tenant = SimpleNamespace(tenant_id="tenant-health")
        return await call_next(request)

    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _repo(*, ping=True, counts=None, counts_error=None):
    repo = SimpleNamespace()
    repo.ping = AsyncMock(return_value=ping)
    repo.get_identity_health = AsyncMock(
        return_value=counts or {}, side_effect=counts_error
    )
    return repo


@pytest.fixture
def use_repo(monkeypatch):
    def _use(repo):
        monkeypatch.setattr(routes, "_get_resolution_repo", lambda: repo)
        return _client(repo)
    return _use


def test_health_is_200_and_reports_real_counts(use_repo):
    client = use_repo(_repo(counts={
        "total_subjects": 15, "total_aliases": 4, "total_clusters": 2,
        "open_conflicts": 1, "recent_merges": 3, "recent_splits": 0,
    }))

    response = client.get("/v1/identity/health")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["status"] == "healthy"
    assert data["resolver_enabled"] is True
    assert data["tenant_id"] == "tenant-health"
    assert (data["total_entities"], data["total_aliases"], data["total_clusters"]) == (15, 4, 2)
    assert (data["open_conflicts"], data["recent_merges"]) == (1, 3)
    assert "request_id" in body["meta"]


def test_health_is_degraded_not_500_when_the_db_is_unreachable(use_repo):
    client = use_repo(_repo(ping=False))

    response = client.get("/v1/identity/health")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "degraded"
    assert data["resolver_enabled"] is False
    assert data["total_entities"] == 0


def test_health_is_degraded_when_counts_fail(use_repo):
    client = use_repo(_repo(counts_error=RuntimeError("relation missing")))

    response = client.get("/v1/identity/health")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "degraded"


def test_openapi_documents_the_enveloped_health_shape():
    app = FastAPI()
    app.include_router(routes.router)
    schema = app.openapi()
    ref = schema["paths"]["/v1/identity/health"]["get"]["responses"]["200"][
        "content"]["application/json"]["schema"]["$ref"]
    envelope = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert set(envelope["properties"]) >= {"data", "status", "timestamp", "meta"}
    inner = schema["components"]["schemas"]["IdentityHealthResponse"]
    assert inner["properties"]["status"]["enum"] == ["healthy", "degraded", "unhealthy"]
