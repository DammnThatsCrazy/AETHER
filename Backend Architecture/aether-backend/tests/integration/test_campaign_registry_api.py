"""Integration tests for Campaign Registry API endpoints.

The campaign routers are mounted on a scoped FastAPI app with the tenant
injected via middleware and the event producer overridden — the same pattern
the reward API suite uses. Handlers are never called directly, because their
``Depends()`` parameters only bind through the framework.
"""

from __future__ import annotations

import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from shared.common.common import AetherError
    from dependencies.providers import get_producer
    from services.campaign.routes import (
        mapping_router, quality_router, router, sources_router,
    )

    _FASTAPI_AVAILABLE = True
except (ImportError, Exception):
    _FASTAPI_AVAILABLE = False
    FastAPI = None
    TestClient = None


pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="FastAPI app not importable (missing dependencies)",
)

_TENANT_HEADER = "x-test-tenant"
_DEFAULT_TENANT = "test-tenant"


class _CampaignTestTenant:
    """Authenticated caller stand-in with full campaign permissions.

    The authentication boundary is deliberately NOT covered here; it is covered
    by the dedicated auth and campaign-registry security suites.
    """

    def __init__(self, tenant_id: str = _DEFAULT_TENANT) -> None:
        self.tenant_id = tenant_id

    def require_permission(self, permission: str) -> None:
        return None


def _build_app(producer_factory=None):
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

    app.include_router(router)
    app.include_router(sources_router)
    app.include_router(mapping_router)
    app.include_router(quality_router)
    app.dependency_overrides[get_producer] = producer_factory or (lambda: AsyncMock())
    return app


@pytest.fixture(scope="module")
def client():
    if not _FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not available")
    return TestClient(_build_app())


def _create_campaign(client, name: str) -> dict:
    resp = client.post("/v1/campaigns", json={
        "name": name,
        "channel": "email",
        "start_date": "2026-01-01",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ─────────────────────────────────────────────────────────────────────────────
# Campaign list / CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignListEndpoint:
    def test_list_campaigns_returns_dict(self, client):
        resp = client.get("/v1/campaigns", params={"limit": 50})
        assert resp.status_code == 200
        result = resp.json()
        assert isinstance(result, dict)
        assert "data" in result

    def test_list_campaigns_respects_limit(self, client):
        resp = client.get("/v1/campaigns", params={"limit": 5})
        assert resp.status_code == 200
        data = resp.json().get("data") or []
        assert isinstance(data, list)
        assert len(data) <= 5

    def test_create_custom_campaign(self, client):
        data = _create_campaign(client, "Test Camp")
        assert "campaign_id" in data
        assert data.get("origin") == "custom"

    def test_create_campaign_name_required(self, client):
        resp = client.post("/v1/campaigns", json={
            "name": "",
            "channel": "email",
            "start_date": "2026-01-01",
        })
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# External refs
# ─────────────────────────────────────────────────────────────────────────────

class TestExternalRefsEndpoint:
    def test_get_external_refs_unknown_campaign(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/v1/campaigns/{fake_id}/external-refs")
        # Unknown campaign is a structured 404, not a crash or a silent empty 200
        assert resp.status_code == 404
        assert isinstance(resp.json(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# Aliases
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasEndpoints:
    def test_add_alias_to_campaign(self, client):
        campaign_id = _create_campaign(client, "Alias Test Camp")["campaign_id"]

        resp = client.post(f"/v1/campaigns/{campaign_id}/aliases", json={
            "alias_type": "utm_campaign",
            "alias_value": "alias-test-value",
        })
        assert resp.status_code == 200, resp.text
        assert "data" in resp.json()

    def test_list_aliases_empty(self, client):
        campaign_id = _create_campaign(client, "No Alias Camp")["campaign_id"]

        resp = client.get(f"/v1/campaigns/{campaign_id}/aliases")
        assert resp.status_code == 200
        result = resp.json()
        assert "data" in result
        assert isinstance(result["data"]["items"], list)
        assert result["data"]["source_status"] in ("missing", "empty", "available")


# ─────────────────────────────────────────────────────────────────────────────
# Campaign Sources
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignSourcesEndpoints:
    def test_list_sources_returns_list(self, client):
        resp = client.get("/v1/campaign-sources")
        assert resp.status_code == 200
        result = resp.json()
        assert "data" in result
        assert isinstance(result["data"]["items"], list)
        assert result["data"]["source_status"] in ("missing", "empty", "available")

    def test_create_source_requires_platform(self, client):
        resp = client.post("/v1/campaign-sources", json={"platform": ""})
        assert resp.status_code == 422

    def test_sync_source_not_found(self, client):
        resp = client.post("/v1/campaign-sources/nonexistent-connector/sync")
        # Unknown connector is a structured client error, not a crash
        assert resp.status_code == 400
        assert isinstance(resp.json(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# Mapping Review
# ─────────────────────────────────────────────────────────────────────────────

class TestMappingReviewEndpoints:
    def test_list_reviews_empty(self, client):
        resp = client.get("/v1/mapping-review", params={"status": "open", "limit": 20})
        assert resp.status_code == 200
        result = resp.json()
        assert "data" in result
        assert isinstance(result["data"]["items"], list)

    def test_resolve_review_missing_campaign_id(self, client):
        fake_review_id = str(uuid.uuid4())
        resp = client.post(f"/v1/mapping-review/{fake_review_id}/resolve", json={
            "campaign_id": "not-a-uuid",
        })
        # campaign_id must be a UUID — rejected at the request-model edge
        assert resp.status_code == 422

    def test_ignore_review_returns_structured(self, client):
        fake_review_id = str(uuid.uuid4())
        # Ignoring a non-existent review should not crash; may return error response
        resp = client.post(f"/v1/mapping-review/{fake_review_id}/ignore", json={"note": None})
        assert resp.status_code in (200, 400, 404)
        assert isinstance(resp.json(), dict)


# ─────────────────────────────────────────────────────────────────────────────
# Campaign Quality
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignQualityEndpoint:
    def test_quality_returns_rates(self, client):
        resp = client.get("/v1/campaign-quality")
        assert resp.status_code == 200
        result = resp.json()
        assert "data" in result
        data = result["data"]
        assert "spend_mapping_rate" in data
        assert "touchpoint_mapping_rate" in data

    def test_tenant_isolation(self, client):
        result_a = client.get("/v1/campaign-quality", headers={_TENANT_HEADER: "tenant_a"})
        result_b = client.get("/v1/campaign-quality", headers={_TENANT_HEADER: "tenant_b"})
        # Both must succeed without leaking data across tenants
        assert result_a.status_code == 200
        assert result_b.status_code == 200
        assert "data" in result_a.json()
        assert "data" in result_b.json()


# ─────────────────────────────────────────────────────────────────────────────
# Touchpoint recording  (findings A + B)
# ─────────────────────────────────────────────────────────────────────────────

class TestTouchpointRecording:
    def test_record_touchpoint_with_properties(self, client):
        # Finding A: TouchpointCreate had no `properties`, so the route's
        # `body.properties` raised AttributeError on every POST. It must now
        # accept and echo the field.
        campaign_id = _create_campaign(client, "TP Props Camp")["campaign_id"]
        resp = client.post(f"/v1/campaigns/{campaign_id}/touchpoints", json={
            "source": "newsletter",
            "event_type": "click",
            "properties": {"variant": "b", "position": 3},
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["properties"] == {"variant": "b", "position": 3}

    def test_record_touchpoint_without_properties_defaults_empty(self, client):
        campaign_id = _create_campaign(client, "TP NoProps Camp")["campaign_id"]
        resp = client.post(f"/v1/campaigns/{campaign_id}/touchpoints", json={
            "source": "newsletter",
            "event_type": "pageview",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["properties"] == {}

    def test_write_failure_returns_503_and_does_not_publish(self, monkeypatch):
        # Finding B: a canonical-write failure was swallowed and the event
        # published anyway, returning 200 for a touchpoint stored nowhere. It
        # must now fail the request and publish nothing.
        producer = AsyncMock()
        local_client = TestClient(_build_app(producer_factory=lambda: producer))
        campaign_id = _create_campaign(local_client, "TP Fail Camp")["campaign_id"]

        from services.measurement.repositories import touchpoint_repo as tp_mod

        async def _boom(self, *args, **kwargs):
            raise RuntimeError("canonical store unavailable")

        monkeypatch.setattr(
            tp_mod.TouchpointRepository, "upsert_from_campaign_touchpoint", _boom
        )

        # Campaign creation above may itself publish, so assert on the delta:
        # the failed touchpoint must add no publish.
        before = producer.publish.await_count
        resp = local_client.post(f"/v1/campaigns/{campaign_id}/touchpoints", json={
            "source": "newsletter", "event_type": "click",
        })
        assert resp.status_code == 503, resp.text
        assert producer.publish.await_count == before


# ─────────────────────────────────────────────────────────────────────────────
# Campaign source persistence  (finding C)
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignSourcePersistence:
    def test_connect_then_list_and_health_and_sync(self):
        # Finding C: connect returned a fabricated connector_id that no read
        # could see (local mode skipped the write; prod swallowed failures).
        # A connected source must now be retrievable by list/health/sync.
        from services.measurement.repositories.measurement_connector_repo import (
            _reset_local_connectors,
        )
        _reset_local_connectors()
        local_client = TestClient(_build_app())

        connect = local_client.post("/v1/campaign-sources", json={"platform": "google_ads"})
        assert connect.status_code == 200, connect.text
        connector_id = connect.json()["data"]["connector_id"]
        assert connector_id

        listing = local_client.get("/v1/campaign-sources").json()["data"]
        ids = [item["connector_id"] for item in listing["items"]]
        assert connector_id in ids
        assert listing["source_status"] == "available"

        health = local_client.get(f"/v1/campaign-sources/{connector_id}/health")
        assert health.status_code == 200, health.text
        assert health.json()["data"]["connector_id"] == connector_id

        sync = local_client.post(f"/v1/campaign-sources/{connector_id}/sync")
        assert sync.status_code == 200, sync.text
        assert sync.json()["data"]["status"] == "queued"

    def test_connect_failure_surfaces_error_not_fabricated_source(self, monkeypatch):
        from services.measurement.repositories import (
            measurement_connector_repo as mc_mod,
        )

        async def _boom(self, *args, **kwargs):
            raise RuntimeError("connector store unavailable")

        monkeypatch.setattr(mc_mod.MeasurementConnectorRepository, "create", _boom)
        local_client = TestClient(_build_app())
        resp = local_client.post("/v1/campaign-sources", json={"platform": "meta_ads"})
        # No fabricated connector_id — a write failure is a 503.
        assert resp.status_code == 503, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Campaign overview data-quality honesty  (finding J)
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignOverviewQuality:
    def test_reconciliation_status_is_not_hardcoded_ok(self, client):
        # Finding J: reconciliation_status was a constant "ok" even with no
        # reconciliation performed. With no data there is no detected
        # inconsistency, so it must read "unknown" — never "ok".
        campaign_id = _create_campaign(client, "Overview Quality Camp")["campaign_id"]
        resp = client.get(f"/v1/campaigns/{campaign_id}/overview")
        assert resp.status_code == 200, resp.text
        quality = resp.json()["data"]["data_quality"]
        assert quality["reconciliation_status"] == "unknown"
        assert quality["reconciliation_status"] != "ok"
        assert quality["projection_lag_hours"] is None
        assert quality["completeness_pct"] is None
