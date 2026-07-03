"""Unit tests — communication-state reducer (Phase 8, ADR-C7)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _fact(event_type: str, occurred_at: str, **extra) -> dict:
    return {"source_event_type": event_type, "occurred_at": occurred_at, **extra}


class TestReducer:
    def test_reduces_engagement_counters(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("email_sent", "2026-07-01T00:00:00+00:00"),
            _fact("email_delivered", "2026-07-01T00:01:00+00:00"),
            _fact("email_opened", "2026-07-01T01:00:00+00:00"),
            _fact("email_clicked", "2026-07-01T01:05:00+00:00"),
            _fact("email_replied", "2026-07-01T02:00:00+00:00"),
        ]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["total_sent"] == 1
        assert state["total_delivered"] == 1
        assert state["total_reported_opens"] == 1
        assert state["total_human_clicks"] == 1
        assert state["total_replies"] == 1
        assert state["subscription_status"] == "subscribed"
        assert state["deliverability_status"] == "deliverable"
        assert state["last_reply_at"] == "2026-07-01T02:00:00+00:00"

    def test_machine_engagement_never_counts_as_human(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("email_delivered", "2026-07-01T00:00:00+00:00"),
            _fact("email_opened", "2026-07-01T00:01:00+00:00", suspected_machine_activity=True),
            _fact("email_clicked", "2026-07-01T00:02:00+00:00", suspected_machine_activity=True),
        ]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["total_reported_opens"] == 1  # reported, not human
        assert state["total_human_clicks"] == 0
        assert state["last_human_engagement_at"] is None

    def test_automated_replies_excluded(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("email_replied", "2026-07-01T00:00:00+00:00",
                  automated_response_kind="out_of_office"),
        ]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["total_replies"] == 0

    def test_hard_bounce_sets_deliverability(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("email_delivered", "2026-07-01T00:00:00+00:00"),
            _fact("email_bounced", "2026-07-02T00:00:00+00:00", bounce_type="hard"),
        ]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["deliverability_status"] == "hard_bounced"
        assert state["hard_bounce_count"] == 1

    def test_idempotent_rebuild(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("email_delivered", "2026-07-01T00:00:00+00:00"),
            _fact("email_clicked", "2026-07-01T00:05:00+00:00"),
        ]
        a = reduce_facts(facts, tenant_id="t", entity_id="e")
        b = reduce_facts(facts, tenant_id="t", entity_id="e")
        a.pop("computed_at")
        b.pop("computed_at")
        assert a == b


class TestSuppressionScopes:
    """ADR-C7 — unsubscribes are scoped, never one global boolean."""

    def test_unsubscribe_scope_recorded(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("unsubscribe_observed", "2026-07-01T00:00:00+00:00",
                  unsubscribe_scope="list"),
        ]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["subscription_status"] == "unsubscribed"
        assert state["unsubscribe_scope"] == "list"

    def test_complaint_overrides_subscribed(self):
        from services.comms.state import reduce_facts
        facts = [
            _fact("email_delivered", "2026-07-01T00:00:00+00:00"),
            _fact("email_spam_complaint", "2026-07-02T00:00:00+00:00"),
        ]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["subscription_status"] == "complained"
        assert state["complaint_count"] == 1

    def test_suppression_scope_defaults_fail_closed(self):
        from services.comms.state import reduce_facts
        facts = [_fact("email_suppressed", "2026-07-01T00:00:00+00:00")]
        state = reduce_facts(facts, tenant_id="t", entity_id="e")
        assert state["subscription_status"] == "suppressed"
        assert state["suppression_scope"] == "provider_account"

    def test_scope_enum_covers_required_scopes(self):
        from services.comms.contracts import SuppressionScope
        assert {s.value for s in SuppressionScope} == {
            "message", "campaign", "list", "segment", "provider_account",
            "marketing_channel", "tenant_wide", "alias_wide",
        }


class TestStateService:
    @pytest.mark.asyncio
    async def test_rebuild_and_get_roundtrip(self):
        from services.comms.repository import CommsFactsRepository, reset_local_stores
        from services.comms.state import CommunicationStateService

        reset_local_stores()
        repo = CommsFactsRepository()
        await repo.upsert({
            "tenant_id": "t-s", "profile_id": "ent-1", "channel": "email",
            "source_event_type": "email_clicked",
            "occurred_at": "2026-07-01T00:00:00+00:00",
            "idempotency_key": "k1", "source_event_id": "s1",
        })
        service = CommunicationStateService()
        state = await service.rebuild_for_entity("t-s", "ent-1")
        assert state["total_human_clicks"] == 1
        fetched = await service.get("t-s", "ent-1")
        assert fetched is not None
        assert fetched["total_human_clicks"] == 1
