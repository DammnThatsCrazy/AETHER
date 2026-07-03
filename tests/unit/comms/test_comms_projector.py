"""Unit tests — CommsProjector facts, classification, privacy (Phase 4/6/14)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _event(event_type: str, props: dict | None = None, message_id: str = "m-1") -> dict:
    return {
        "type": event_type,
        "messageId": message_id,
        "userId": "user-9",
        "timestamp": "2026-07-01T09:00:00+00:00",
        "context": {"tenantId": "tenant-p", "orgId": "org-1"},
        "properties": {
            "provider": "klaviyo",
            "provider_account_id": "acct-9",
            "provider_event_id": "prov-1",
            "recipient_email": "jane.doe@example.com",
            **(props or {}),
        },
    }


class TestFactShape:
    def test_click_fact_fields(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_clicked", {
            "external_campaign_id": "camp-1", "external_message_id": "msg-1",
            "link_id": "link-1", "sequence_step": 2,
        }))
        row = result.rows[0]
        assert row["tenant_id"] == "tenant-p"
        assert row["channel"] == "email"
        assert row["direction"] == "outbound"
        assert row["communication_state"] == "clicked"
        assert row["journey_role"] == "active_step"
        assert row["external_message_id"] == "msg-1"
        assert row["sequence_step"] == 2
        assert row["provider_event_id"] == "prov-1"
        assert row["idempotency_key"]
        assert row["canonical_activity_key"]

    def test_bounce_normalizes_state(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_bounced", {"bounce_type": "hard"}))
        row = result.rows[0]
        assert row["communication_state"] == "bounced"
        assert row["bounce_type"] == "hard"
        assert row["journey_role"] == "state_only"

    def test_missing_message_id_skips(self):
        from services.comms.projector import CommsProjector
        event = _event("email_clicked")
        event.pop("messageId")
        result = CommsProjector().project(event)
        assert result.skipped and result.skip_reason == "missing_message_id"


class TestNoRawPII:
    """ADR-C10 — raw addresses are hashed; bodies/subjects never persist."""

    def test_raw_email_never_stored(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_delivered"))
        row = result.rows[0]
        flat = str(row)
        assert "jane.doe@example.com" not in flat
        assert row["recipient_alias_id"]
        assert row["recipient_display"].startswith("j***@")

    def test_payload_strips_content_fields(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_replied", {
            "subject": "Re: secret negotiation",
            "body": "full text",
            "headers": {"In-Reply-To": "<x>"},
        }))
        payload = result.rows[0]["payload"]
        assert "subject" not in payload
        assert "body" not in payload
        assert "headers" not in payload


class TestMachineClassification:
    """Phase 14 — deterministic separation of machine engagement."""

    def test_scanner_click_flagged_and_excluded_from_journey(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_clicked", {
            "user_agent": "Barracuda Sentinel LinkProtect",
        }))
        row = result.rows[0]
        assert row["suspected_machine_activity"] is True
        assert row["machine_activity_probability"] >= 0.9
        assert row["journey_role"] == "excluded"

    def test_proxy_open_weak_engagement(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_opened", {
            "user_agent": "Mozilla/5.0 (via GoogleImageProxy)",
        }))
        row = result.rows[0]
        assert row["suspected_machine_activity"] is True

    def test_human_click_probable(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_clicked", {
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        }))
        row = result.rows[0]
        assert row["suspected_machine_activity"] is False
        assert row["engagement_strength"] in ("probable", "strong")

    def test_authenticated_session_deterministic(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_clicked", {
            "has_authenticated_session": True,
        }))
        row = result.rows[0]
        assert row["engagement_strength"] == "deterministic"
        assert row["engagement_confidence"] == 1.0

    def test_delivery_events_carry_no_engagement(self):
        from services.comms.projector import CommsProjector
        result = CommsProjector().project(_event("email_delivered"))
        row = result.rows[0]
        assert row["engagement_type"] is None
        assert row["suspected_machine_activity"] is False


class TestActivityOwnership:
    """ADR-C4 — email_clicked → one comms fact, one touchpoint, one activity."""

    @pytest.mark.asyncio
    async def test_one_fact_one_touchpoint_one_activity(self):
        from services.silver.dispatcher import SilverDispatcher
        from services.measurement.silver_adapters import adapt_from_silver
        from services.comms.repository import reset_local_stores

        reset_local_stores()
        outcome = await SilverDispatcher().project_with_outcome(
            _event("email_clicked", {"external_message_id": "msg-1", "link_id": "l1"})
        )
        comms = [r for r in outcome.results if r.table == "silver_comms_facts"]
        touchpoints = [r for r in outcome.results if r.table == "silver_campaign_touchpoint_facts"]
        assert len(comms) == 1 and len(comms[0].rows) == 1
        assert len(touchpoints) == 1 and len(touchpoints[0].rows) == 1

        activity = adapt_from_silver("silver_comms_facts", comms[0].rows[0])
        assert activity is not None
        assert activity["activity_family"] == "campaign"  # marketing default
        assert activity["actor_type"] == "organization"   # outbound org send
        # Touchpoint carries lineage back to the comms fact
        tp = touchpoints[0].rows[0]
        assert tp["communication_fact_id"] == comms[0].rows[0]["idempotency_key"]

    def test_excluded_machine_activity_produces_no_activity(self):
        from services.comms.projector import CommsProjector
        from services.measurement.silver_adapters import adapt_from_silver
        result = CommsProjector().project(_event("email_clicked", {
            "user_agent": "python-requests/2.31",
        }))
        activity = adapt_from_silver("silver_comms_facts", result.rows[0])
        assert activity is None


class TestTouchpointGating:
    """Phase 7 — engagement policy on touchpoints."""

    @pytest.mark.asyncio
    async def test_machine_click_creates_no_touchpoint(self):
        from services.silver.dispatcher import SilverDispatcher
        outcome = await SilverDispatcher().project_with_outcome(
            _event("email_clicked", {"user_agent": "curl/8.0"})
        )
        tables = [r.table for r in outcome.results]
        assert "silver_comms_facts" in tables
        assert "silver_campaign_touchpoint_facts" not in tables

    @pytest.mark.asyncio
    async def test_bounce_creates_no_positive_touchpoint(self):
        from services.silver.dispatcher import SilverDispatcher
        outcome = await SilverDispatcher().project_with_outcome(_event("email_bounced"))
        tables = [r.table for r in outcome.results]
        assert "silver_campaign_touchpoint_facts" not in tables

    @pytest.mark.asyncio
    async def test_reply_creates_email_reply_touchpoint(self):
        from services.silver.dispatcher import SilverDispatcher
        outcome = await SilverDispatcher().project_with_outcome(_event("email_replied"))
        tp = next(r for r in outcome.results if r.table == "silver_campaign_touchpoint_facts")
        assert tp.rows[0]["touchpoint_type"] == "email_reply"
