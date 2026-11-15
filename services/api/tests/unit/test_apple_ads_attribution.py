"""Apple Ads attribution-token exchange: server-verified, replay-safe, flag-gated."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from journeys.measurement.repositories import activity_repo, touchpoint_repo
from journeys.traffic import apple_ads_attribution as mod

pytestmark = pytest.mark.asyncio
T = "tenant-aa"

APPLE_OK = {
    "attribution": True, "orgId": 40669820, "campaignId": 542370539, "conversionType": "Download",
    "claimType": "Click", "adGroupId": 542317095, "countryOrRegion": "US", "keywordId": 87675432,
    "adId": 542317136, "unexpected": "dropped",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    async def no_pool(self):
        return None

    monkeypatch.setattr(activity_repo.ActivityRepository, "_pool", no_pool)
    monkeypatch.setattr(touchpoint_repo.TouchpointRepository, "_pool", no_pool)
    activity_repo._local_store.clear()
    touchpoint_repo._local_store.clear()
    monkeypatch.setattr(
        mod.settings, "mobile", dataclasses.replace(mod.settings.mobile, apple_ads_attribution_enabled=True),
    )
    yield
    activity_repo._local_store.clear()
    touchpoint_repo._local_store.clear()


def _apple(monkeypatch, status=200, body=None, exc=None):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["content_type"] = request.headers.get("content-type")
        seen["url"] = str(request.url)
        if exc:
            raise exc
        return httpx.Response(status, json=body if body is not None else {})

    real = httpx.AsyncClient

    def client(*a, **k):
        return real(transport=httpx.MockTransport(handler), timeout=k.get("timeout"))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return seen


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=SimpleNamespace(tenant_id=T)))


def _body(token="tok-1", anon="anon-ios"):
    return mod.AppleAdsResolve(token=token, anonymous_id=anon, session_id="s1", install_id="i1")


async def test_attributed_token_is_recorded_server_side(monkeypatch):
    seen = _apple(monkeypatch, body=APPLE_OK)
    out = await mod.resolve_apple_ads_attribution(_body(), _req())
    assert seen["body"] == b"tok-1" and seen["content_type"] == "text/plain"
    assert seen["url"] == mod.APPLE_ADS_ATTRIBUTION_URL
    assert out["resolved"] is True
    assert out["evidence"]["entry_method"] == "ios_apple_ads_attribution"
    assert out["evidence"]["proof_level"] == "platform_verified"
    assert out["evidence"]["campaign_id"] == "542370539"
    assert "unexpected" not in str(out)
    [activity] = activity_repo._local_store.values()
    assert activity["anonymous_id"] == "anon-ios" and activity["tenant_id"] == T
    assert activity["entry_method"] == "ios_apple_ads_attribution"
    assert activity["activity_type"] == "app_install_attributed"
    assert "tok-1" not in str(activity)  # only the hash is stored
    [tp] = touchpoint_repo._local_store.values()
    assert tp["external_campaign_id"] == "542370539" and tp["campaign_resolution_status"] == "unresolved"
    assert tp["is_click_through"] is True and tp["proof_level"] == "platform_verified"
    # The activity carries the touchpoint reference the journey compiler reads.
    assert activity["silver_table"] == "silver_campaign_touchpoint_facts"
    assert activity["silver_fact_id"] == tp["touchpoint_id"]


async def test_replayed_token_cannot_attribute_a_second_device(monkeypatch):
    _apple(monkeypatch, body=APPLE_OK)
    first = await mod.resolve_apple_ads_attribution(_body(anon="anon-1"), _req())
    again = await mod.resolve_apple_ads_attribution(_body(anon="anon-1"), _req())
    other = await mod.resolve_apple_ads_attribution(_body(anon="anon-2"), _req())
    assert first["resolved"] and again["resolved"]
    assert other == {"resolved": False, "status": "token_already_bound"}
    assert len(activity_repo._local_store) == 1 and len(touchpoint_repo._local_store) == 1


@pytest.mark.parametrize("status,body,expected", [
    (404, {}, "pending"),
    (400, {}, "invalid"),
    (500, {}, "unavailable"),
    (200, {"attribution": False, "orgId": 1}, "not_attributed"),
])
async def test_non_attributed_outcomes_record_nothing(monkeypatch, status, body, expected):
    _apple(monkeypatch, status=status, body=body)
    out = await mod.resolve_apple_ads_attribution(_body(), _req())
    assert out["resolved"] is False and out["status"] == expected
    if expected == "pending":
        assert out["retry_after_seconds"] == 5
    assert activity_repo._local_store == {} and touchpoint_repo._local_store == {}


async def test_transport_failure_is_unavailable(monkeypatch):
    _apple(monkeypatch, exc=httpx.ConnectError("down"))
    out = await mod.resolve_apple_ads_attribution(_body(), _req())
    assert out == {"resolved": False, "status": "unavailable"}


async def test_impression_claims_are_view_through(monkeypatch):
    _apple(monkeypatch, body={**APPLE_OK, "claimType": "Impression"})
    await mod.resolve_apple_ads_attribution(_body(), _req())
    [tp] = touchpoint_repo._local_store.values()
    assert tp["is_view_through"] is True and tp["is_click_through"] is False


async def test_route_is_off_by_default(monkeypatch):
    monkeypatch.setattr(
        mod.settings, "mobile", dataclasses.replace(mod.settings.mobile, apple_ads_attribution_enabled=False),
    )
    with pytest.raises(HTTPException) as err:
        await mod.resolve_apple_ads_attribution(_body(), _req())
    assert err.value.status_code == 404


async def test_blank_and_extra_fields_are_rejected():
    with pytest.raises(ValueError):
        mod.AppleAdsResolve(token="  ", anonymous_id="a")
    with pytest.raises(ValueError):
        mod.AppleAdsResolve(token="t", anonymous_id="a", proof_level="cryptographic")


def _rebuild_spies(monkeypatch, *, activity_queued: int):
    from journeys.measurement import activity_rebuild
    from journeys.measurement.engine import journey_compiler

    calls = {"activities": [], "touchpoints": []}

    async def request_for_activities(activities):
        calls["activities"].append([a.get("anonymous_id") for a in activities])
        return activity_queued

    async def rebuild_affected_by_touchpoint(self, tenant_id, touchpoint_id):
        calls["touchpoints"].append((tenant_id, touchpoint_id))
        return [{"journey_id": "j1"}]

    monkeypatch.setattr(activity_rebuild, "request_for_activities", request_for_activities)
    monkeypatch.setattr(journey_compiler.JourneyCompiler, "rebuild_affected_by_touchpoint",
                        rebuild_affected_by_touchpoint)
    return calls


async def test_recorded_attribution_requests_a_debounced_journey_rebuild(monkeypatch):
    calls = _rebuild_spies(monkeypatch, activity_queued=1)
    _apple(monkeypatch, body=APPLE_OK)
    out = await mod.resolve_apple_ads_attribution(_body(), _req())
    assert out["resolved"] is True
    assert calls["activities"] == [["anon-ios"]]
    assert calls["touchpoints"] == []  # the debounced path took it


async def test_attribution_rebuilds_through_the_touchpoint_when_activity_rebuild_is_off(monkeypatch):
    calls = _rebuild_spies(monkeypatch, activity_queued=0)
    _apple(monkeypatch, body=APPLE_OK)
    await mod.resolve_apple_ads_attribution(_body(), _req())
    [tp] = touchpoint_repo._local_store.values()
    assert calls["touchpoints"] == [(T, tp["touchpoint_id"])]


async def test_a_failed_rebuild_never_loses_the_attribution(monkeypatch):
    from journeys.measurement import activity_rebuild

    async def broken(activities):
        raise RuntimeError("compiler down")

    monkeypatch.setattr(activity_rebuild, "request_for_activities", broken)
    _apple(monkeypatch, body=APPLE_OK)
    out = await mod.resolve_apple_ads_attribution(_body(), _req())
    assert out["resolved"] is True
    assert len(activity_repo._local_store) == 1 and len(touchpoint_repo._local_store) == 1


async def test_a_token_bound_elsewhere_requests_no_rebuild(monkeypatch):
    _apple(monkeypatch, body=APPLE_OK)
    await mod.resolve_apple_ads_attribution(_body(anon="anon-1"), _req())
    calls = _rebuild_spies(monkeypatch, activity_queued=1)
    other = await mod.resolve_apple_ads_attribution(_body(anon="anon-2"), _req())
    assert other["status"] == "token_already_bound"
    assert calls == {"activities": [], "touchpoints": []}
