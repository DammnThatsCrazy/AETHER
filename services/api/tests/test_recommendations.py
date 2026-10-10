"""Tests for the recommendations service — repository and routes."""
from __future__ import annotations

import pytest

from repositories.repos import BaseRepository, RecommendationRepository, reset_in_memory_stores


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


# ── Repository tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendation_repository_lifecycle():
    repo = RecommendationRepository()
    rec = {
        "recommendation_id": "r1",
        "entity_id": "e1",
        "tenant_id": "t1",
        "status": "pending_review",
        "retarget_score": 7.5,
        "recommended_platform": "twitter_ads",
        "recommended_creative_theme": "yield_and_rewards",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    await repo.create(rec)

    fetched = await repo.get("r1", "t1")
    assert fetched is not None
    assert fetched["status"] == "pending_review"

    updated = await repo.update_status("r1", "t1", "approved", reviewed_by="analyst1")
    assert updated["status"] == "approved"
    assert updated["reviewed_by"] == "analyst1"


@pytest.mark.asyncio
async def test_recommendation_repository_tenant_isolation():
    repo = RecommendationRepository()
    await repo.create({"recommendation_id": "r1", "entity_id": "e1", "tenant_id": "t1", "status": "pending_review"})
    assert await repo.get("r1", "t2") is None


@pytest.mark.asyncio
async def test_list_for_entity_with_status_filter():
    repo = RecommendationRepository()
    for i, status in enumerate(["pending_review", "approved", "rejected"]):
        await repo.create({
            "recommendation_id": f"r{i}",
            "entity_id": "e1",
            "tenant_id": "t1",
            "status": status,
            "created_at": f"2026-01-0{i+1}T00:00:00+00:00",
        })
    pending = await repo.list_for_entity("e1", "t1", status="pending_review")
    assert len(pending) == 1
    assert pending[0]["recommendation_id"] == "r0"

    all_recs = await repo.list_for_entity("e1", "t1")
    assert len(all_recs) == 3


# ── Route authorization ────────────────────────────────────────────────────


class _FakeProvider:
    def __init__(self):
        self.calls = []

    async def execute(self, method, payload):
        self.calls.append((method, payload))
        return {"ok": True}


class _FakeGateway:
    def __init__(self):
        self.provider = _FakeProvider()

    async def get(self, platform, tenant_id):
        return self.provider


def _client(permissions, user_id="user-7", tenant_id="t1", role=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dependencies.providers import get_provider_gateway
    from intelligence.recommendations import routes
    from shared.auth.auth import Role, TenantContext
    from shared.decorators import register_error_handlers

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(routes.router)
    gateway = _FakeGateway()
    app.dependency_overrides[get_provider_gateway] = lambda: gateway

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = TenantContext(
            tenant_id=tenant_id, user_id=user_id, role=role or Role.VIEWER, permissions=permissions,
        )
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False), gateway


async def _seed(rec_id="r1", tenant_id="t1"):
    await RecommendationRepository().create({
        "recommendation_id": rec_id, "entity_id": "e1", "tenant_id": tenant_id,
        "status": "pending_review", "retarget_score": 8.0,
        "recommended_platform": "twitter_ads",
        "recommended_audience_segment": "seg", "recommended_bid_usd": 1.0,
        "recommended_creative_theme": "general_reengagement",
        "created_at": "2026-01-01T00:00:00+00:00",
    })


@pytest.mark.asyncio
async def test_a_read_only_credential_cannot_approve_or_reject():
    await _seed()
    client, gateway = _client(["read"])
    assert client.post("/v1/recommendations/r1/approve", json={}).status_code == 403
    assert client.post("/v1/recommendations/r1/reject", json={"reason": "no"}).status_code == 403
    assert gateway.provider.calls == []  # nothing was pushed to an ad platform
    assert (await RecommendationRepository().get("r1", "t1"))["status"] == "pending_review"


@pytest.mark.asyncio
async def test_a_credential_without_read_cannot_list_or_see_status():
    await _seed()
    client, _ = _client(["write"])
    assert client.get("/v1/recommendations/e1").status_code == 403
    assert client.get("/v1/recommendations/r1/status").status_code == 403


@pytest.mark.asyncio
async def test_the_reviewer_is_the_authenticated_caller_not_the_request_body():
    await _seed()
    client, gateway = _client(["write"], user_id="user-7")
    resp = client.post("/v1/recommendations/r1/approve", json={"reviewed_by": "someone-else", "review_notes": "ok"})
    assert resp.status_code == 200
    assert resp.json()["data"]["reviewed_by"] == "user-7"
    assert len(gateway.provider.calls) == 1
    # The push is recorded: the row is executed and an audit entry names the caller.
    stored = await RecommendationRepository().get("r1", "t1")
    assert stored["status"] == "executed" and stored["reviewed_by"] == "user-7"
    audit = await BaseRepository("consent_audit_log").find_many(filters={"tenant_id": "t1"})
    assert [a["executed_by"] for a in audit] == ["user-7"]


@pytest.mark.asyncio
async def test_a_failed_ad_platform_push_returns_the_recommendation_to_review():
    await _seed()
    client, gateway = _client(["write"])

    async def boom(method, payload):
        raise RuntimeError("platform down")

    gateway.provider.execute = boom
    resp = client.post("/v1/recommendations/r1/approve", json={})
    assert resp.status_code == 502
    stored = await RecommendationRepository().get("r1", "t1")
    assert stored["status"] == "pending_review"
    assert "platform down" in stored["review_notes"]


@pytest.mark.asyncio
async def test_reject_records_the_caller_and_other_tenants_cannot_touch_it():
    await _seed()
    other, gateway = _client(["write"], tenant_id="t2")
    assert other.post("/v1/recommendations/r1/approve", json={}).status_code == 404
    assert other.post("/v1/recommendations/r1/reject", json={"reason": "x"}).status_code == 404
    assert gateway.provider.calls == []

    client, _ = _client(["write"], user_id="user-9")
    resp = client.post("/v1/recommendations/r1/reject", json={"reviewed_by": "forged", "reason": "off-brand"})
    assert resp.status_code == 200
    assert resp.json()["data"]["reviewed_by"] == "user-9"
