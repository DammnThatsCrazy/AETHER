"""Verified referral resolution stays inside the canonical Silver pipeline."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from unittest.mock import AsyncMock

import pytest

from services.comms.projector import COMMS_TABLE, CommsProjector
from services.ingestion.workers import _bus_payload_to_sdk_envelope
from services.silver import dispatcher as dispatcher_module
from services.silver.dispatcher import SilverDispatcher
from services.silver.projectors.base import ProjectionResult
from services.silver.projectors.outcome_projector import OutcomeProjector
from services.silver.projectors.touchpoint_projector import TouchpointProjector


async def _no_graph(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_verified_link_is_resolved_before_classification_and_activity(monkeypatch):
    token = "opaque-referral-token"
    campaign_id = "f113dca1-8b82-4d94-ac2a-c111a6e44c09"
    claim = {
        "verified_referral_link_id": "2f0ccedb-b630-4dc4-844d-6ff1fdd00701",
        "placement_id": "verified-placement",
        "agent_id": "verified-agent",
        "campaign_id": campaign_id,
        "ai_provider": "openai",
        "ai_product": "chatgpt",
        "referral_mediation_type": "owned_agent_referral",
        "actor_type": "agent",
        "journey_role": "handoff",
        "source": "openai",
    }
    projector = TouchpointProjector()
    emitted_rows: list[dict] = []
    order: list[str] = []

    async def resolve_campaign(rows, *, table):
        assert table == "silver_campaign_touchpoint_facts"
        assert rows[0]["_canonical_campaign_id_hint"] == campaign_id
        rows[0]["campaign_id"] = campaign_id
        rows[0]["campaign_resolution_status"] = "resolved"
        order.append("campaign")

    async def emit_activity(_table, rows):
        assert rows[0]["campaign_id"] == campaign_id
        assert "_canonical_campaign_id_hint" not in rows[0]
        emitted_rows.extend(deepcopy(rows))
        order.append("activity")

    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "page", [projector])
    monkeypatch.setattr(
        dispatcher_module._verified_referral_links,
        "resolve_token",
        AsyncMock(return_value=claim),
    )
    monkeypatch.setattr(dispatcher_module, "_resolve_campaign_rows", resolve_campaign)
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", _no_graph)
    monkeypatch.setattr(projector, "_emit_to_canonical_activity", emit_activity)

    event = {
        "type": "page",
        "messageId": "event-1",
        "userId": "profile-1",
        "timestamp": "2026-07-14T12:00:00Z",
        "context": {
            "tenantId": "tenant-a",
            "trafficSource": {
                "referralToken": token,
                "verifiedReferral": {"ai_provider": "forged-traffic-provider"},
            },
            "acquisitionEvidence": {
                "verifiedReferral": {"ai_provider": "forged-acquisition-provider"},
            },
            "verifiedReferral": {"ai_provider": "forged-context-provider"},
            "page": {
                "url": (
                    "https://example.test/landing"
                    f"?aether_ref={token}&utm_source=legacy"
                )
            },
        },
        "properties": {"placement_id": "unverified-placement"},
    }

    outcome = await SilverDispatcher().project_with_outcome(event)
    await asyncio.sleep(0)

    assert len(outcome.results) == 1
    row = outcome.results[0].rows[0]
    assert row["ai_provider"] == "openai"
    assert row["ai_product"] == "chatgpt"
    assert row["actor_type"] == "agent"
    assert row["referral_mediation_type"] == "owned_agent_referral"
    assert row["verification_level"] == "verified_referral_link"
    assert row["verified_referral_link_id"] == claim["verified_referral_link_id"]
    assert row["agent_id"] == "verified-agent"
    assert row["placement_id"] == "verified-placement"
    assert emitted_rows == [row]
    assert order == ["campaign", "activity"]
    assert token not in repr(row)
    assert token not in repr(event)
    assert "aether_ref" not in event["context"]["page"]["url"]
    dispatcher_module._verified_referral_links.resolve_token.assert_awaited_once_with(
        "tenant-a", token, source_event_id="event-1"
    )


@pytest.mark.asyncio
async def test_invalid_token_cannot_self_assert_verified_metadata(monkeypatch):
    projector = TouchpointProjector()
    activity = AsyncMock()
    resolver = AsyncMock(return_value=None)

    async def no_campaign(_rows, *, table):
        assert table == "silver_campaign_touchpoint_facts"

    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "page", [projector])
    monkeypatch.setattr(dispatcher_module._verified_referral_links, "resolve_token", resolver)
    monkeypatch.setattr(dispatcher_module, "_resolve_campaign_rows", no_campaign)
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", _no_graph)
    monkeypatch.setattr(projector, "_emit_to_canonical_activity", activity)

    event = {
        "type": "page",
        "messageId": "event-invalid",
        "timestamp": "2026-07-14T12:00:00Z",
        "context": {
            "tenantId": "tenant-a",
            "acquisitionEvidence": {
                "referralToken": "invalid-token",
                "verifiedReferral": {
                    "ai_provider": "forged-provider",
                    "verified_referral_link_id": "forged-link",
                },
            },
            "page": {"url": "https://example.test/landing?aether_ref=invalid-token"},
        },
    }

    outcome = await SilverDispatcher().project_with_outcome(event)
    await asyncio.sleep(0)

    row = outcome.results[0].rows[0]
    assert row["verification_level"] != "verified_referral_link"
    assert row["verified_referral_link_id"] is None
    assert row["ai_provider"] is None
    assert "verifiedReferral" not in event["context"]["acquisitionEvidence"]
    assert "invalid-token" not in repr(event)
    activity.assert_awaited_once()


@pytest.mark.asyncio
async def test_persisted_token_hash_replays_through_verified_resolution(monkeypatch):
    projector = TouchpointProjector()
    digest = hashlib.sha256(b"opaque-token").hexdigest()
    claim = {
        "verified_referral_link_id": "2f0ccedb-b630-4dc4-844d-6ff1fdd00701",
        "placement_id": "answer-footer",
        "agent_id": "agent-1",
        "campaign_id": None,
        "ai_provider": "openai",
        "ai_product": "chatgpt",
        "referral_mediation_type": "agent_mediated_referral",
        "actor_type": "agent",
        "journey_role": "handoff",
        "source": "openai",
    }
    resolve_hash = AsyncMock(return_value=claim)

    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "page", [projector])
    monkeypatch.setattr(
        dispatcher_module._verified_referral_links,
        "resolve_token_hash",
        resolve_hash,
    )
    monkeypatch.setattr(
        dispatcher_module, "_resolve_campaign_rows", AsyncMock()
    )
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", _no_graph)
    monkeypatch.setattr(projector, "_emit_to_canonical_activity", AsyncMock())

    event = {
        "type": "page",
        "messageId": "event-replay",
        "timestamp": "2026-07-14T12:00:00Z",
        "context": {
            "tenantId": "tenant-a",
            "referralTokenHash": digest,
            "page": {"url": "https://example.test/landing"},
        },
    }

    outcome = await SilverDispatcher().project_with_outcome(event)

    row = outcome.results[0].rows[0]
    assert row["verification_level"] == "verified_referral_link"
    assert row["ai_provider"] == "openai"
    assert "referralTokenHash" not in event["context"]
    resolve_hash.assert_awaited_once_with(
        "tenant-a", digest, source_event_id="event-replay"
    )


@pytest.mark.asyncio
async def test_authenticated_tenant_overwrites_spoofed_context_for_referral_projection(
    monkeypatch,
):
    projector = TouchpointProjector()
    resolve = AsyncMock(
        return_value={
            "verified_referral_link_id": "2f0ccedb-b630-4dc4-844d-6ff1fdd00701",
            "placement_id": "answer-footer",
            "agent_id": "agent-1",
            "campaign_id": None,
            "ai_provider": "openai",
            "ai_product": "chatgpt",
            "referral_mediation_type": "agent_mediated_referral",
            "actor_type": "agent",
            "journey_role": "handoff",
            "source": "openai",
        }
    )
    activity = AsyncMock()

    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "page", [projector])
    monkeypatch.setattr(
        dispatcher_module._verified_referral_links, "resolve_token", resolve
    )
    monkeypatch.setattr(
        dispatcher_module, "_resolve_campaign_rows", AsyncMock()
    )
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", _no_graph)
    monkeypatch.setattr(projector, "_emit_to_canonical_activity", activity)

    envelope = _bus_payload_to_sdk_envelope(
        {
            "tenant_id": "tenant-authenticated",
            "event_id": "event-tenant-authority",
            "event_type": "page",
            "timestamp": "2026-07-14T12:00:00Z",
            "context": {
                "tenantId": "tenant-spoofed",
                "trafficSource": {"referralToken": "opaque-token"},
            },
            "properties": {},
        }
    )

    outcome = await SilverDispatcher().project_with_outcome(envelope)

    row = outcome.results[0].rows[0]
    assert envelope["context"]["tenantId"] == "tenant-authenticated"
    assert row["tenant_id"] == "tenant-authenticated"
    resolve.assert_awaited_once_with(
        "tenant-authenticated",
        "opaque-token",
        source_event_id="event-tenant-authority",
    )
    activity.assert_awaited_once()


def test_legacy_property_click_id_is_classified_as_paid_traffic():
    result = TouchpointProjector().project(
        {
            "type": "page",
            "messageId": "event-paid-click",
            "timestamp": "2026-07-14T12:00:00Z",
            "context": {"tenantId": "tenant-a"},
            "properties": {"gclid": "paid-click-id"},
        }
    )

    assert result is not None
    row = result.rows[0]
    assert row["click_id"] == "paid-click-id"
    assert row["source"] == "google"
    assert row["medium"] == "cpc"
    # v3 intentionally replaces the blanket "paid" silver channel with the
    # canonical paid_search / paid_social / display split.
    assert row["channel"] == "paid_search"
    assert row["source_class"] == "paid_search"
    assert row["economic_class"] == "paid"
    assert row["channel_family"] == "search"
    assert row["entry_method"] == "paid_click_id"
    assert row["proof_level"] == "declared"
    assert row["verification_level"] == "verified_click_id"


@pytest.mark.asyncio
async def test_comms_remains_only_activity_owner(monkeypatch):
    comms = CommsProjector()
    touchpoint = TouchpointProjector()
    comms_activity = AsyncMock()
    touchpoint_activity = AsyncMock()

    monkeypatch.setattr(
        comms,
        "project",
        lambda _event: ProjectionResult(
            table=COMMS_TABLE,
            rows=[{"tenant_id": "tenant-a", "source_event_id": "event-comms"}],
        ),
    )
    monkeypatch.setattr(
        touchpoint,
        "project",
        lambda _event: ProjectionResult(
            table="silver_campaign_touchpoint_facts",
            rows=[{"tenant_id": "tenant-a", "source_event_id": "event-comms"}],
        ),
    )
    monkeypatch.setattr(comms, "_emit_to_canonical_activity", comms_activity)
    monkeypatch.setattr(touchpoint, "_emit_to_canonical_activity", touchpoint_activity)
    monkeypatch.setitem(
        dispatcher_module._TYPE_MAP, "email_delivered", [comms, touchpoint]
    )
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", _no_graph)
    monkeypatch.setattr(dispatcher_module, "_resolve_campaign_rows", AsyncMock())

    outcome = await SilverDispatcher().project_with_outcome(
        {
            "type": "email_delivered",
            "messageId": "event-comms",
            "timestamp": "2026-07-14T12:00:00Z",
            "context": {"tenantId": "tenant-a"},
        }
    )
    await asyncio.sleep(0)

    assert len(outcome.results) == 2
    comms_activity.assert_awaited_once()
    touchpoint_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_touchpoint_is_only_non_comms_activity_owner_when_projectors_overlap(
    monkeypatch,
):
    touchpoint = TouchpointProjector()
    outcome = OutcomeProjector()
    touchpoint_activity = AsyncMock()
    outcome_activity = AsyncMock()

    monkeypatch.setattr(
        touchpoint,
        "project",
        lambda _event: ProjectionResult(
            table="silver_campaign_touchpoint_facts",
            rows=[{"tenant_id": "tenant-a", "source_event_id": "event-overlap"}],
        ),
    )
    monkeypatch.setattr(
        outcome,
        "project",
        lambda _event: ProjectionResult(
            table="silver_outcome_facts",
            rows=[{"tenant_id": "tenant-a", "source_event_id": "event-overlap"}],
        ),
    )
    monkeypatch.setattr(touchpoint, "_emit_to_canonical_activity", touchpoint_activity)
    monkeypatch.setattr(outcome, "_emit_to_canonical_activity", outcome_activity)
    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "overlap_test", [touchpoint, outcome])
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", _no_graph)
    monkeypatch.setattr(dispatcher_module, "_resolve_campaign_rows", AsyncMock())

    result = await SilverDispatcher().project_with_outcome(
        {
            "type": "overlap_test",
            "messageId": "event-overlap",
            "timestamp": "2026-07-14T12:00:00Z",
            "context": {"tenantId": "tenant-a"},
        }
    )
    await asyncio.sleep(0)

    assert len(result.results) == 2
    touchpoint_activity.assert_awaited_once()
    outcome_activity.assert_not_awaited()
