"""Verified source-link placement model, redirect proof flow, and handoffs.

Runs entirely against the in-memory repository fallback (no database), in the
style of tests/unit/test_verified_referral_links.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from services.traffic import referral_links as referral_module
from services.traffic.referral_links import VerifiedReferralLinkRepository

DESTINATION = "https://app.example.test/welcome?utm_source=partner"
HUMAN_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MACHINE_UA = "Mozilla/5.0 (compatible; Slackbot-LinkExpanding 1.0)"


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(referral_module, "_pool", no_pool)
    referral_module.reset_verified_referral_links_for_tests()
    yield
    referral_module.reset_verified_referral_links_for_tests()


async def _create_link(repo: VerifiedReferralLinkRepository, **overrides):
    params = {
        "placement_id": "newsletter-footer",
        "source_class": "owned_referral",
        "destination_url": DESTINATION,
        "referral_mediation_type": "partner_referral",
    }
    params.update(overrides)
    return await repo.create("tenant-a", **params)


# ---------------------------------------------------------------------------
# Placement model + vocabulary validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_validates_vocabulary_against_generated_registry():
    repo = VerifiedReferralLinkRepository()
    with pytest.raises(ValueError, match="source_class"):
        await _create_link(repo, source_class="not-a-class")
    with pytest.raises(ValueError, match="channel_family"):
        await _create_link(repo, channel_family="not-a-family")
    with pytest.raises(ValueError, match="economic_class"):
        await _create_link(repo, economic_class="not-a-class")
    with pytest.raises(ValueError, match="http"):
        await _create_link(repo, destination_url="javascript:alert(1)")
    with pytest.raises(ValueError, match="max_uses"):
        await _create_link(repo, max_uses=0)

    link, token = await _create_link(repo, metadata={"label": "Q3", "evil": "x"})
    assert token
    # source_class defaults channel_family/economic_class from the registry.
    assert link["source_class"] == "owned_referral"
    assert link["channel_family"] == "referral"
    assert link["economic_class"] == "unpaid"
    assert link["destination_url"] == DESTINATION
    # Metadata is allowlist-filtered.
    assert link["metadata"] == {"label": "Q3"}
    assert "token_hash" not in link


@pytest.mark.asyncio
async def test_legacy_source_class_alias_is_normalized():
    repo = VerifiedReferralLinkRepository()
    link, _token = await _create_link(repo, source_class="direct")
    assert link["source_class"] == "direct_unknown"


# ---------------------------------------------------------------------------
# Redirect flow: immutable use + handoff mint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_redirect_creates_immutable_use_and_one_time_handoff():
    repo = VerifiedReferralLinkRepository()
    link, token = await _create_link(repo)

    result = await repo.resolve_redirect(token, user_agent=HUMAN_UA)

    assert result is not None
    assert result["destination_url"] == DESTINATION
    assert result["is_machine"] is False
    assert result["handoff_token"]
    # Handoff token is stored hash-only.
    assert result["handoff_token"] not in repr(
        referral_module._LOCAL_SOURCE_LINK_HANDOFFS
    )
    use = referral_module._LOCAL_LINK_USE_RECORDS[result["use_id"]]
    assert use["tenant_id"] == "tenant-a"
    assert use["verified_referral_link_id"] == str(link["verified_referral_link_id"])
    assert use["placement_id"] == "newsletter-footer"
    assert use["ua_class"] == "browser"
    assert use["is_machine"] is False
    assert use["handoff_minted"] is True
    assert use["correlated_at"] is None
    refreshed = await repo.get("tenant-a", link["verified_referral_link_id"])
    assert refreshed["use_count"] == 1


@pytest.mark.asyncio
async def test_invalid_redirect_conditions_are_a_uniform_none():
    repo = VerifiedReferralLinkRepository()

    # Unknown token.
    assert await repo.resolve_redirect("unknown-token", user_agent=HUMAN_UA) is None

    # Expired link.
    expired_link, expired_token = await _create_link(
        repo, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    referral_module._LOCAL_VERIFIED_REFERRAL_LINKS[
        str(expired_link["verified_referral_link_id"])
    ]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await repo.resolve_redirect(expired_token, user_agent=HUMAN_UA) is None

    # Revoked link.
    revoked_link, revoked_token = await _create_link(repo)
    await repo.revoke("tenant-a", revoked_link["verified_referral_link_id"])
    assert await repo.resolve_redirect(revoked_token, user_agent=HUMAN_UA) is None

    # Not yet valid.
    _early_link, early_token = await _create_link(
        repo, valid_from=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert await repo.resolve_redirect(early_token, user_agent=HUMAN_UA) is None

    # Wrong environment.
    _staging_link, staging_token = await _create_link(repo, environment="staging")
    assert (
        await repo.resolve_redirect(
            staging_token, environment="production", user_agent=HUMAN_UA
        )
        is None
    )

    # Link without a destination cannot redirect.
    _bare_link, bare_token = await _create_link(repo, destination_url=None)
    assert await repo.resolve_redirect(bare_token, user_agent=HUMAN_UA) is None

    # No handoffs or uses were minted by any rejected attempt.
    assert referral_module._LOCAL_SOURCE_LINK_HANDOFFS == {}
    assert referral_module._LOCAL_LINK_USE_RECORDS == {}


@pytest.mark.asyncio
async def test_max_uses_budget_is_enforced():
    repo = VerifiedReferralLinkRepository()
    _link, token = await _create_link(repo, max_uses=1)

    first = await repo.resolve_redirect(token, user_agent=HUMAN_UA)
    second = await repo.resolve_redirect(token, user_agent=HUMAN_UA)

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_machine_user_agent_use_is_flagged_and_mints_no_handoff():
    repo = VerifiedReferralLinkRepository()
    link, token = await _create_link(repo)

    result = await repo.resolve_redirect(token, user_agent=MACHINE_UA)

    assert result is not None
    assert result["is_machine"] is True
    assert result["handoff_token"] is None
    assert result["destination_url"] == DESTINATION
    use = referral_module._LOCAL_LINK_USE_RECORDS[result["use_id"]]
    assert use["is_machine"] is True
    assert use["ua_class"] == "link_preview"
    assert use["handoff_minted"] is False
    assert referral_module._LOCAL_SOURCE_LINK_HANDOFFS == {}
    # Machine traffic never burns the human use budget.
    refreshed = await repo.get("tenant-a", link["verified_referral_link_id"])
    assert refreshed["use_count"] == 0


# ---------------------------------------------------------------------------
# Handoff consumption: one-time, replay-rejected, correlated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_is_consumed_once_and_replay_is_rejected_and_recorded():
    repo = VerifiedReferralLinkRepository()
    link, token = await _create_link(repo)
    redirect = await repo.resolve_redirect(token, user_agent=HUMAN_UA)
    handoff_token = redirect["handoff_token"]

    claim, status = await repo.consume_handoff(
        "tenant-a", handoff_token, source_event_id="event-1"
    )

    assert status == "consumed"
    assert claim["verified_referral_link_id"] == str(link["verified_referral_link_id"])
    assert claim["placement_id"] == "newsletter-footer"
    assert claim["entry_method"] == "verified_source_link"
    assert claim["proof_level"] == "server_observed"
    assert claim["source_class"] == "owned_referral"
    assert claim["channel_family"] == "referral"
    assert claim["economic_class"] == "unpaid"
    assert claim["actor_type"] == "human"
    # Consumption correlates the immutable redirect use.
    use = referral_module._LOCAL_LINK_USE_RECORDS[redirect["use_id"]]
    assert use["correlated_at"] is not None

    # A different event replaying the token is rejected and recorded.
    replay_claim, replay_status = await repo.consume_handoff(
        "tenant-a", handoff_token, source_event_id="event-2"
    )
    assert replay_claim is None
    assert replay_status == "replayed"
    handoff = next(iter(referral_module._LOCAL_SOURCE_LINK_HANDOFFS.values()))
    assert handoff["replay_count"] == 1

    # Durable pipeline replay of the SAME event stays idempotent.
    same_claim, same_status = await repo.consume_handoff(
        "tenant-a", handoff_token, source_event_id="event-1"
    )
    assert same_status == "consumed"
    assert same_claim == claim


@pytest.mark.asyncio
async def test_handoff_expiry_and_wrong_tenant_are_rejected():
    repo = VerifiedReferralLinkRepository()
    _link, token = await _create_link(repo)
    redirect = await repo.resolve_redirect(token, user_agent=HUMAN_UA)
    handoff_token = redirect["handoff_token"]

    wrong_tenant_claim, wrong_tenant_status = await repo.consume_handoff(
        "tenant-b", handoff_token
    )
    assert wrong_tenant_claim is None
    assert wrong_tenant_status == "not_found"

    handoff = next(iter(referral_module._LOCAL_SOURCE_LINK_HANDOFFS.values()))
    handoff["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired_claim, expired_status = await repo.consume_handoff(
        "tenant-a", handoff_token
    )
    assert expired_claim is None
    assert expired_status == "expired"


@pytest.mark.asyncio
async def test_revoking_the_link_invalidates_outstanding_handoffs():
    repo = VerifiedReferralLinkRepository()
    link, token = await _create_link(repo)
    redirect = await repo.resolve_redirect(token, user_agent=HUMAN_UA)
    await repo.revoke("tenant-a", link["verified_referral_link_id"])

    claim, status = await repo.consume_handoff(
        "tenant-a", redirect["handoff_token"]
    )
    assert claim is None
    assert status == "link_inactive"


@pytest.mark.asyncio
async def test_handoff_claim_carries_campaign_binding_only_when_present():
    repo = VerifiedReferralLinkRepository()
    campaign_id = "f113dca1-8b82-4d94-ac2a-c111a6e44c09"

    _bound, bound_token = await _create_link(repo, campaign_id=campaign_id)
    bound_redirect = await repo.resolve_redirect(bound_token, user_agent=HUMAN_UA)
    bound_claim, _ = await repo.consume_handoff(
        "tenant-a", bound_redirect["handoff_token"]
    )
    assert bound_claim["campaign_id"] == campaign_id

    _unbound, unbound_token = await _create_link(repo)
    unbound_redirect = await repo.resolve_redirect(unbound_token, user_agent=HUMAN_UA)
    unbound_claim, _ = await repo.consume_handoff(
        "tenant-a", unbound_redirect["handoff_token"]
    )
    assert unbound_claim["campaign_id"] is None


# ---------------------------------------------------------------------------
# Route-level redirect behavior
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, user_agent: str) -> None:
        self.headers = {"user-agent": user_agent}


@pytest.mark.asyncio
async def test_redirect_route_appends_handoff_and_rejects_uniformly(monkeypatch):
    from services.traffic import routes

    repo = VerifiedReferralLinkRepository()
    monkeypatch.setattr(routes, "_verified_referral_links", repo)
    _link, token = await _create_link(repo)

    response = await routes.redirect_verified_source_link(
        token, _FakeRequest(HUMAN_UA)
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://app.example.test/welcome")
    assert "utm_source=partner" in location
    assert "aether_ref=" in location
    # The visible aether_ref is the one-time handoff, never the link token.
    assert token not in location

    with pytest.raises(HTTPException) as unknown:
        await routes.redirect_verified_source_link(
            "unknown-token", _FakeRequest(HUMAN_UA)
        )
    assert unknown.value.status_code == 404
    assert unknown.value.detail == "Not found"


@pytest.mark.asyncio
async def test_redirect_route_still_redirects_machines_without_handoff(monkeypatch):
    from services.traffic import routes

    repo = VerifiedReferralLinkRepository()
    monkeypatch.setattr(routes, "_verified_referral_links", repo)
    _link, token = await _create_link(repo)

    response = await routes.redirect_verified_source_link(
        token, _FakeRequest(MACHINE_UA)
    )
    assert response.status_code == 302
    assert response.headers["location"] == DESTINATION
    assert "aether_ref" not in response.headers["location"]


# ---------------------------------------------------------------------------
# Dispatcher: aether_ref resolves handoff tokens with one-time semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_resolves_handoff_token_and_rejects_replay(monkeypatch):
    from services.silver import dispatcher as dispatcher_module

    repo = VerifiedReferralLinkRepository()
    monkeypatch.setattr(dispatcher_module, "_verified_referral_links", repo)
    _link, token = await _create_link(repo)
    redirect = await repo.resolve_redirect(token, user_agent=HUMAN_UA)
    handoff_token = redirect["handoff_token"]

    def event_with_token(event_id: str) -> dict:
        return {
            "type": "page",
            "messageId": event_id,
            "timestamp": "2026-07-23T12:00:00Z",
            "context": {
                "tenantId": "tenant-a",
                "trafficSource": {"referralToken": handoff_token},
                "page": {
                    "url": f"https://app.example.test/welcome?aether_ref={handoff_token}"
                },
            },
        }

    first = event_with_token("event-1")
    await dispatcher_module._resolve_verified_referral(first)
    claim = first.get("_verified_referral")
    assert claim is not None
    assert claim["entry_method"] == "verified_source_link"
    assert claim["proof_level"] == "server_observed"
    assert handoff_token not in repr(first)

    # A different event replaying the same handoff gains nothing.
    replayed = event_with_token("event-2")
    await dispatcher_module._resolve_verified_referral(replayed)
    assert replayed.get("_verified_referral") is None
    assert handoff_token not in repr(replayed)

    # Durable replay of the first event is idempotent.
    durable = event_with_token("event-1")
    await dispatcher_module._resolve_verified_referral(durable)
    assert durable.get("_verified_referral") == claim
