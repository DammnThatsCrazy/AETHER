"""Focused tests for durable, tenant-scoped verified referral links."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from fastapi import HTTPException

from services.traffic import referral_links as referral_module
from services.traffic.referral_links import VerifiedReferralLinkRepository
from shared.auth.auth import Role, TenantContext


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(referral_module, "_pool", no_pool)
    referral_module.reset_verified_referral_links_for_tests()
    yield
    referral_module.reset_verified_referral_links_for_tests()


@pytest.mark.asyncio
async def test_create_persists_only_hash_and_list_never_discloses_secret():
    repo = VerifiedReferralLinkRepository()
    link, token = await repo.create(
        "tenant-a",
        agent_id="agent-1",
        placement_id="answer-footer",
        ai_provider="openai",
        ai_product="chatgpt",
        referral_mediation_type="owned_agent_referral",
    )

    stored = next(iter(referral_module._LOCAL_VERIFIED_REFERRAL_LINKS.values()))
    assert token
    assert token != stored["token_hash"]
    assert token not in repr(stored)
    assert "token_hash" not in link

    listed = await repo.list("tenant-a")
    assert len(listed) == 1
    assert "token_hash" not in listed[0]
    assert token not in repr(listed)


@pytest.mark.asyncio
async def test_resolve_is_tenant_scoped_and_returns_strict_server_claim():
    repo = VerifiedReferralLinkRepository()
    campaign_id = "f113dca1-8b82-4d94-ac2a-c111a6e44c09"
    link, token = await repo.create(
        "tenant-a",
        agent_id="agent-1",
        placement_id="answer-footer",
        campaign_id=campaign_id,
        ai_provider="anthropic",
        ai_product="claude",
    )

    assert await repo.resolve_token("tenant-b", token) is None
    claim = await repo.resolve_token("tenant-a", token)

    assert claim == {
        "verified_referral_link_id": str(link["verified_referral_link_id"]),
        "placement_id": "answer-footer",
        "agent_id": "agent-1",
        "campaign_id": campaign_id,
        "ai_provider": "anthropic",
        "ai_product": "claude",
        "referral_mediation_type": "agent_mediated_referral",
        "actor_type": "agent",
        "journey_role": "handoff",
        "source": "anthropic",
    }
    refreshed = await repo.get("tenant-a", link["verified_referral_link_id"])
    assert refreshed is not None
    assert refreshed["use_count"] == 1
    assert refreshed["first_used_at"] is not None


@pytest.mark.asyncio
async def test_ingestion_digest_can_resolve_without_persisting_plaintext():
    repo = VerifiedReferralLinkRepository()
    link, token = await repo.create("tenant-a", agent_id="agent-1")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

    claim = await repo.resolve_token_hash("tenant-a", digest)

    assert claim is not None
    assert claim["verified_referral_link_id"] == str(
        link["verified_referral_link_id"]
    )
    assert await repo.resolve_token_hash("tenant-a", "not-a-digest") is None


@pytest.mark.asyncio
async def test_replayed_source_event_does_not_inflate_verified_link_usage():
    repo = VerifiedReferralLinkRepository()
    link, token = await repo.create("tenant-a", agent_id="agent-1")

    first = await repo.resolve_token(
        "tenant-a", token, source_event_id="event-1"
    )
    replay = await repo.resolve_token(
        "tenant-a", token, source_event_id="event-1"
    )

    assert first == replay
    refreshed = await repo.get("tenant-a", link["verified_referral_link_id"])
    assert refreshed is not None
    assert refreshed["use_count"] == 1


@pytest.mark.asyncio
async def test_expired_and_revoked_tokens_are_rejected_without_oracle_detail():
    repo = VerifiedReferralLinkRepository()
    active_link, token = await repo.create(
        "tenant-a",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    stored = referral_module._LOCAL_VERIFIED_REFERRAL_LINKS[
        str(active_link["verified_referral_link_id"])
    ]
    stored["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await repo.resolve_token("tenant-a", token) is None

    other_link, other_token = await repo.create("tenant-a")
    revoked = await repo.revoke(
        "tenant-a", other_link["verified_referral_link_id"], reason="placement retired"
    )
    assert revoked is not None
    assert revoked["status"] == "revoked"
    assert await repo.resolve_token("tenant-a", other_token) is None
    assert await repo.revoke("tenant-b", other_link["verified_referral_link_id"]) is None


@pytest.mark.asyncio
async def test_create_rejects_invalid_expiry_and_mediation():
    repo = VerifiedReferralLinkRepository()
    with pytest.raises(ValueError, match="future"):
        await repo.create(
            "tenant-a", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    with pytest.raises(ValueError, match="unsupported"):
        await repo.create("tenant-a", referral_mediation_type="crawler_discovery")
    with pytest.raises(ValueError, match="canonical campaign UUID"):
        await repo.create("tenant-a", campaign_id="not-a-campaign-uuid")


@pytest.mark.asyncio
async def test_routes_use_authenticated_tenant_for_create_list_and_revoke(monkeypatch):
    from services.traffic import routes

    repo = VerifiedReferralLinkRepository()
    monkeypatch.setattr(routes, "_verified_referral_links", repo)
    tenant_a = TenantContext(tenant_id="tenant-a", user_id="user-a")
    tenant_b = TenantContext(tenant_id="tenant-b", user_id="user-b")

    created = await routes.create_verified_referral_link(
        routes.VerifiedReferralLinkCreate(agent_id="agent-a"), tenant=tenant_a
    )
    link_id = created["link"]["verified_referral_link_id"]
    assert created["referral_token"]
    assert "token_hash" not in created["link"]

    listed = await routes.list_verified_referral_links(
        status=None, limit=100, offset=0, tenant=tenant_a
    )
    other_tenant = await routes.list_verified_referral_links(
        status=None, limit=100, offset=0, tenant=tenant_b
    )
    assert [link["verified_referral_link_id"] for link in listed["links"]] == [link_id]
    assert other_tenant["links"] == []

    with pytest.raises(HTTPException) as exc_info:
        await routes.revoke_verified_referral_link(
            str(link_id), routes.VerifiedReferralLinkRevoke(), tenant=tenant_b
        )
    assert exc_info.value.status_code == 404

    revoked = await routes.revoke_verified_referral_link(
        str(link_id), routes.VerifiedReferralLinkRevoke(reason="retired"), tenant=tenant_a
    )
    assert revoked["link"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_referral_link_control_plane_rejects_unprivileged_browser_keys():
    from services.traffic import routes

    browser = TenantContext(tenant_id="tenant-a", role=Role.VIEWER)
    with pytest.raises(HTTPException) as read_error:
        await routes._require_referral_link_read(browser)
    assert read_error.value.status_code == 403

    with pytest.raises(HTTPException) as write_error:
        await routes._require_referral_link_write(browser)
    assert write_error.value.status_code == 403

    editor = TenantContext(tenant_id="tenant-a", role=Role.EDITOR)
    assert await routes._require_referral_link_read(editor) is editor
    assert await routes._require_referral_link_write(editor) is editor
