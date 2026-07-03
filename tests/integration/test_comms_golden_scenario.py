"""Golden end-to-end release scenario — "Customer Reactivation" (permanent CI fixture).

Exercises the complete Communications Intelligence vertical slice in local
mode (in-memory stores):

  campaign synchronized → message synchronized → recipient alias created →
  email sent → delivered → machine-generated open → human-qualified click →
  reply → communication state → funnel/message/link rollups → journey-role
  and attribution-eligibility assertions → aggregated graph relationship.

This fixture is the release gate for the vertical slice (mono-spec §32).
Do not delete or skip it; extend it when new lifecycle stages ship.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

TENANT = "tenant-golden"
RECIPIENT = "returning.customer@example.com"
PROVIDER = "klaviyo"
ACCOUNT = "acct-golden"
CAMPAIGN_EXT_ID = "reactivation-2026"
MESSAGE_EXT_ID = "msg-reactivation-1"
LINK_ID = "https://shop.example/reactivate"


def _provider_event(event_type: str, provider_event_id: str, props: dict | None = None) -> dict:
    return {
        "type": event_type,
        "messageId": f"golden-{provider_event_id}",
        "userId": "customer-77",
        "timestamp": props.pop("_ts", "2026-07-01T10:00:00+00:00") if props else "2026-07-01T10:00:00+00:00",
        "context": {"tenantId": TENANT, "orgId": "org-golden"},
        "properties": {
            "provider": PROVIDER,
            "provider_account_id": ACCOUNT,
            "provider_event_id": provider_event_id,
            "recipient_email": RECIPIENT,
            "external_campaign_id": CAMPAIGN_EXT_ID,
            "external_message_id": MESSAGE_EXT_ID,
            **(props or {}),
        },
    }


@pytest.fixture(autouse=True)
def _clean():
    from services.comms.repository import reset_local_stores
    from services.comms.graph_projection import reset_local_relationships
    from services.silver.writer import reset_local_tables
    reset_local_stores()
    reset_local_relationships()
    reset_local_tables()
    yield
    reset_local_stores()
    reset_local_relationships()
    reset_local_tables()


@pytest.fixture()
def _canonical_campaign(monkeypatch):
    """Deterministic campaign registry/resolver boundary.

    The real campaign repositories require Postgres by design (no in-memory
    fallback); this fixture substitutes only that boundary so the rest of
    the pipeline (projectors, writer, state, graph, funnel) runs for real.
    """
    from uuid import uuid5, NAMESPACE_URL
    from decimal import Decimal
    from services.campaign.registry import CampaignRegistryService
    from services.campaign.resolver import CampaignResolver, ResolutionResult

    campaign_uuid = uuid5(NAMESPACE_URL, f"{TENANT}:{PROVIDER}:{ACCOUNT}:{CAMPAIGN_EXT_ID}")

    async def fake_upsert(self, tenant_id, platform, external_account_id,
                          external_campaign_id, **kwargs):
        assert tenant_id == TENANT and platform == PROVIDER
        return {"campaign_id": campaign_uuid, "tenant_id": tenant_id,
                "name": kwargs.get("external_campaign_name"), "channel": "email"}

    async def fake_resolve_one(self, tenant_id, **evidence):
        if (evidence.get("external_campaign_id") == CAMPAIGN_EXT_ID
                or evidence.get("canonical_campaign_id") == str(campaign_uuid)):
            return ResolutionResult(
                status="resolved", campaign_id=campaign_uuid,
                method="external_ref", confidence=Decimal("1.0"),
            )
        return ResolutionResult(status="unresolved")

    monkeypatch.setattr(CampaignRegistryService, "upsert_external_campaign", fake_upsert)
    monkeypatch.setattr(CampaignResolver, "resolve_one", fake_resolve_one)
    return campaign_uuid


@pytest.mark.asyncio
async def test_customer_reactivation_golden_scenario(_canonical_campaign):
    from services.silver.dispatcher import SilverDispatcher
    from services.silver.writer import SilverFactWriter
    from services.comms.repository import (
        CampaignMessageRepository, CommsFactsRepository,
    )
    from services.comms.state import CommunicationStateService
    from services.comms.graph_projection import CommsGraphProjector, _local_relationships
    from services.comms.mailbox import build_email_alias
    from services.comms.click_token import issue_click_token, verify_click_token
    from services.comms.ingest import ingest_normalized_events
    from services.comms.attribution_policy import comms_touchpoint_eligibility
    from services.measurement.silver_adapters import adapt_from_silver

    dispatcher = SilverDispatcher()
    writer = SilverFactWriter()
    facts_repo = CommsFactsRepository()

    # ── 1-2. Campaign + message synchronized from the provider catalog ───────
    counts = await ingest_normalized_events(TENANT, [{
        "event_type": "klaviyo.campaign",
        "source": PROVIDER,
        "external_id": CAMPAIGN_EXT_ID,
        "properties": {
            "external_campaign_id": CAMPAIGN_EXT_ID,
            "provider_account_id": ACCOUNT,
            "name": "Customer Reactivation",
            "channel": "email",
            "messages": [{"id": MESSAGE_EXT_ID, "name": "Reactivation offer",
                          "sequence_step": 1}],
        },
    }])
    assert counts["catalog"] == 1

    from services.campaign.resolver import CampaignResolver
    resolution = await CampaignResolver().resolve_one(
        TENANT, platform=PROVIDER, external_account_id=ACCOUNT,
        external_campaign_id=CAMPAIGN_EXT_ID,
    )
    assert resolution.campaign_id is not None, "campaign must resolve to a canonical UUID"
    campaign_id = str(resolution.campaign_id)

    messages = await CampaignMessageRepository().list_for_campaign(TENANT, campaign_id)
    assert any(m["external_message_id"] == MESSAGE_EXT_ID for m in messages)

    # ── 3. Recipient alias (hashed, never raw) ───────────────────────────────
    alias = build_email_alias(RECIPIENT, TENANT)
    assert alias and not alias.is_shared_mailbox

    # ── 4-7. Lifecycle: sent → delivered → machine open → human click ───────
    events = [
        _provider_event("email_sent", "ev-sent", {"_ts": "2026-07-01T10:00:00+00:00"}),
        _provider_event("email_delivered", "ev-delivered", {"_ts": "2026-07-01T10:00:05+00:00"}),
        _provider_event("email_opened", "ev-open-machine", {
            "_ts": "2026-07-01T10:00:06+00:00",
            "user_agent": "GoogleImageProxy (via ggpht.com)",
        }),
        _provider_event("email_clicked", "ev-click-human", {
            "_ts": "2026-07-01T11:30:00+00:00",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "link_id": LINK_ID,
            "has_authenticated_session": True,
        }),
        _provider_event("email_replied", "ev-reply", {
            "_ts": "2026-07-01T12:00:00+00:00", "direction": "inbound",
        }),
    ]
    for event in events:
        outcome = await dispatcher.project_with_outcome(event)
        await writer.persist(outcome.results)
        assert not outcome.failed_projectors, outcome.projector_status
        # ── 13. Graph update (aggregated) ────────────────────────────────────
        for result in outcome.results:
            if result.table == "silver_comms_facts":
                for row in result.rows:
                    await CommsGraphProjector().project_fact(row)

    # Replay the click — no duplicates anywhere (replay safety)
    replay = await dispatcher.project_with_outcome(events[3])
    await writer.persist(replay.results)

    # ── Assertions ────────────────────────────────────────────────────────────
    rows, _ = await facts_repo.list_for_entity(TENANT, "customer-77", limit=100)
    by_type = {}
    for row in rows:
        by_type.setdefault(row["source_event_type"], []).append(row)

    # Click creates exactly one communication fact (replay-safe)
    assert len(by_type["email_clicked"]) == 1
    click = by_type["email_clicked"][0]

    # Campaign resolution attached the canonical UUID
    assert click["campaign_id"] == campaign_id
    assert click["campaign_resolution_status"] == "resolved"

    # Machine open excluded from human engagement; click human-qualified
    machine_open = by_type["email_opened"][0]
    assert machine_open["suspected_machine_activity"] is True
    assert machine_open["journey_role"] != "active_step"
    assert click["suspected_machine_activity"] is False
    assert click["engagement_strength"] == "deterministic"
    assert click["journey_role"] == "active_step"

    # One canonical activity for the click, correctly classified
    activity = adapt_from_silver("silver_comms_facts", click)
    assert activity is not None
    assert activity["activity_family"] == "campaign"
    assert activity["idempotency_key"].startswith("comms:")
    # Machine open never becomes an activity
    assert adapt_from_silver("silver_comms_facts", machine_open) is None

    # No raw recipient address anywhere in stored facts
    assert RECIPIENT not in str(rows)
    assert click["recipient_alias_id"] == alias.alias_hash

    # ── Profile360: communication state ───────────────────────────────────────
    state = await CommunicationStateService().rebuild_for_entity(TENANT, "customer-77")
    assert state["total_sent"] == 1
    assert state["total_delivered"] == 1
    assert state["total_reported_opens"] == 1
    assert state["total_human_clicks"] == 1
    assert state["total_replies"] == 1
    assert state["last_human_engagement_at"] is not None
    assert state["subscription_status"] == "subscribed"
    assert state["deliverability_status"] == "deliverable"

    # ── Campaign 360: funnel, messages, links reconcile ───────────────────────
    funnel = await facts_repo.campaign_funnel(TENANT, campaign_id)
    assert funnel["delivered"] == 1
    assert funnel["reported_opens"] == 1
    assert funnel["human_opens"] == 0       # the only open was machine
    assert funnel["human_clicks"] == 1
    assert funnel["replies"] == 1
    assert funnel["machine_events"] == 1

    message_stats = await facts_repo.message_stats(TENANT, campaign_id)
    msg_stat = next(s for s in message_stats
                    if s["external_message_id"] == MESSAGE_EXT_ID)
    assert msg_stat["human_clicks"] == 1

    link_stats = await facts_repo.link_stats(TENANT, campaign_id)
    assert any(l["link_id"] == LINK_ID and l["human_clicks"] == 1 for l in link_stats)

    # ── Attribution: click eligible, delivery/machine excluded ────────────────
    assert comms_touchpoint_eligibility({"touchpoint_type": "email_click"})[0]
    assert not comms_touchpoint_eligibility({"touchpoint_type": "email_delivery"})[0]
    assert not comms_touchpoint_eligibility(
        {"touchpoint_type": "email_click", "machine_activity_probability": 0.95}
    )[0]

    # ── Graph: bounded — aggregated relationships, no event-node explosion ───
    assert 0 < len(_local_relationships) <= 3
    outbound = next(
        (a for a in _local_relationships.values() if a["edge_type"] == "CONTACTED"), None,
    )
    assert outbound is not None
    assert outbound["sender_ref"] == "org:org-golden"  # never a global "system" node
    assert outbound["delivered_count"] == 1
    assert str(campaign_id) in outbound["campaign_ids"]

    # ── 8-9. Post-click correlation: signed token verifies ───────────────────
    token = issue_click_token(
        TENANT, campaign_id=campaign_id, external_message_id=MESSAGE_EXT_ID,
        recipient_alias_id=alias.alias_hash, link_id=LINK_ID,
    )
    verified = verify_click_token(token, TENANT)
    assert verified.valid and verified.claims.campaign_id == campaign_id
    assert not verify_click_token(token, "other-tenant").valid

    # ── Kyber: pipeline health reports the processed volume ───────────────────
    from services.comms.routes import _health_snapshot
    health = await _health_snapshot(TENANT)
    assert health["communication_facts"] == len(rows)
    assert health["campaign_resolution_rate"] > 0
