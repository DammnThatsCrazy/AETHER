"""Mobile -> web journey handoff: single-use, tenant/app bound, never merges identities."""
from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from journeys.handoff import routes as handoff_routes
from journeys.handoff.service import (
    hash_token, issue_handoff, list_handoffs, redeem_handoff,
)
from repositories import journey_handoff_repo as repo_mod

T, APP = "tenant-a", "shop-app"


@pytest.fixture(autouse=True)
def _clean():
    repo_mod.reset_journey_handoff_memory()
    yield
    repo_mod.reset_journey_handoff_memory()


async def _issue(**kw):
    base = dict(
        tenant_id=T, app_namespace=APP, journey_id="jrn-1", session_id="mob-sess",
        anonymous_id="anon-mobile", platform="ios",
    )
    base.update(kw)
    return await issue_handoff(**base)


async def _redeem(token, **kw):
    base = dict(
        tenant_id=T, app_namespace=APP, token=token, session_id="web-sess",
        anonymous_id="anon-web", platform="web",
    )
    base.update(kw)
    return await redeem_handoff(**base)


@pytest.mark.asyncio
async def test_redeem_returns_explicit_link_without_identity_merge():
    issued = await _issue()
    link, reason = await _redeem(issued["token"])
    assert reason == ""
    assert link["link_basis"] == "explicit_handoff"
    assert link["identity_merge"] == "not_performed"
    assert link["journey_id"] == "jrn-1"
    assert link["from"] == {"session_id": "mob-sess", "anonymous_id": "anon-mobile", "platform": "ios"}
    assert link["to"]["session_id"] == "web-sess" and link["to"]["platform"] == "web"


@pytest.mark.asyncio
async def test_token_is_single_use_even_under_concurrent_redeem():
    issued = await _issue()
    results = await asyncio.gather(
        *[_redeem(issued["token"], session_id=f"web-{i}") for i in range(8)]
    )
    assert sum(1 for link, _ in results if link) == 1
    assert {reason for link, reason in results if not link} == {"already_redeemed"}


@pytest.mark.asyncio
async def test_only_the_hash_is_stored():
    issued = await _issue()
    stored = repo_mod._MEM
    assert hash_token(issued["token"]) in stored
    assert issued["token"] not in repr(stored)


@pytest.mark.asyncio
async def test_other_tenant_or_app_cannot_redeem():
    issued = await _issue()
    assert (await _redeem(issued["token"], tenant_id="tenant-b"))[1] == "wrong_scope"
    assert (await _redeem(issued["token"], app_namespace="other-app"))[1] == "wrong_scope"
    link, _ = await _redeem(issued["token"])
    assert link is not None, "a wrong-scope attempt must not consume the token"


@pytest.mark.asyncio
async def test_expired_and_forged_tokens_are_rejected():
    issued = await _issue(ttl_seconds=30)
    repo_mod._MEM[hash_token(issued["token"])]["expires_at"] = repo_mod.utc_now().replace(year=2020)
    assert (await _redeem(issued["token"]))[1] == "expired"
    assert (await _redeem("hnd_" + "x" * 43))[1] == "not_found"
    assert (await _redeem("not-a-token"))[1] == "invalid_request"


@pytest.mark.asyncio
async def test_same_session_redeem_is_rejected():
    issued = await _issue()
    link, reason = await _redeem(issued["token"], session_id="mob-sess")
    assert link is None and reason == "same_session"


@pytest.mark.asyncio
async def test_journey_listing_shows_issued_and_redeemed_state():
    a = await _issue()
    await _issue(session_id="mob-2")
    await _redeem(a["token"])
    items = await list_handoffs(T, "jrn-1")
    assert {i["state"] for i in items} == {"issued", "redeemed"}
    redeemed = next(i for i in items if i["state"] == "redeemed")
    assert redeemed["link_basis"] == "explicit_handoff"
    assert not any("token" in k for i in items for k in i)
    assert await list_handoffs("tenant-b", "jrn-1") == []


def _request(site_ids=(APP,)):
    tenant = SimpleNamespace(
        tenant_id=T, site_ids=list(site_ids), require_permission=lambda _: None,
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.fixture
def enabled(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(
        settings, "identity_continuity",
        dataclasses.replace(settings.identity_continuity, journey_handoff_enabled=True),
    )


@pytest.mark.asyncio
async def test_routes_require_consent_on_both_ends(monkeypatch, enabled):
    from governance.consent import authority
    from shared.common.common import BadRequestError

    granted = {"anon-mobile"}

    async def evaluate(tenant_id, anonymous_id):
        return (anonymous_id in granted, "identity_link_consent_required", {})

    monkeypatch.setattr(authority, "evaluate_identity_link_consent", evaluate)
    issued = (await handoff_routes.issue(
        handoff_routes.IssueRequest(
            journey_id="jrn-1", session_id="mob-sess", anonymous_id="anon-mobile", platform="ios"
        ), _request(),
    ))["data"]
    redeem_body = handoff_routes.RedeemRequest(
        token=issued["token"], session_id="web-sess", anonymous_id="anon-web", platform="web"
    )
    with pytest.raises(BadRequestError):
        await handoff_routes.redeem(redeem_body, _request())
    granted.add("anon-web")
    out = await handoff_routes.redeem(redeem_body, _request())
    assert out["data"]["link_basis"] == "explicit_handoff", (
        "a consent-rejected attempt must not have consumed the token"
    )


@pytest.mark.asyncio
async def test_routes_are_off_by_default_and_hide_failure_reason(monkeypatch):
    from governance.consent import authority
    from shared.common.common import NotFoundError

    with pytest.raises(NotFoundError):
        await handoff_routes.issue(
            handoff_routes.IssueRequest(journey_id="j", session_id="s", anonymous_id="a"),
            _request(),
        )

    async def allow(tenant_id, anonymous_id):
        return True, "", {}

    monkeypatch.setattr(authority, "evaluate_identity_link_consent", allow)
    from config.settings import settings

    monkeypatch.setattr(
        settings, "identity_continuity",
        dataclasses.replace(settings.identity_continuity, journey_handoff_enabled=True),
    )
    with pytest.raises(NotFoundError):
        await handoff_routes.redeem(
            handoff_routes.RedeemRequest(
                token="hnd_forged-token-value", session_id="w", anonymous_id="a2"
            ),
            _request(),
        )
