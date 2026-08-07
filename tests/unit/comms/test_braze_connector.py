"""Unit tests — Braze connector webhook mapping and pull-with-durable-cursor.

The Braze adapter is pull-model-first (ADR-C11 follow-up): email lifecycle
events (hard bounces, unsubscribes) export through the REST email-list
endpoints, plus campaign/canvas catalog sync, and pushed message events map
through ``parse_webhook``. Cursor advancement happens in the service layer only
after durable acceptance — a failed pull never moves the cursor.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


@pytest.fixture(autouse=True)
def _clean():
    from repositories.repos import _IN_MEMORY_STORES
    _IN_MEMORY_STORES.clear()
    yield
    _IN_MEMORY_STORES.clear()


def _braze_message_event(event_type: str, extra: dict | None = None) -> dict:
    return {
        "id": "br-ev-1",
        "event_type": event_type,
        "time": 1750000000,
        "user": {"braze_id": "user-1", "email_address": "person@example.com",
                 "external_id": "ext-1"},
        "campaign_id": "camp-1",
        "dispatch_id": "disp-1",
        **(extra or {}),
    }


class TestWebhookMapping:
    @pytest.mark.parametrize("event_type,expected", [
        ("users.messages.email.Send", "email_sent"),
        ("users.messages.email.Delivered", "email_delivered"),
        ("users.messages.email.Open", "email_opened"),
        ("users.messages.email.Click", "email_clicked"),
        ("users.messages.email.Bounce", "email_bounced"),
        ("users.messages.email.SoftBounce", "email_bounced"),
        ("users.messages.email.DeliveryFailure", "email_dropped"),
        ("users.messages.email.Spam", "email_spam_complaint"),
        ("users.messages.email.Unsubscribe", "unsubscribe_observed"),
        # /users/track-recorded custom event names normalize to canonical types.
        ("email_unsubscribed", "unsubscribe_observed"),
        ("email_spam", "email_spam_complaint"),
        ("clicked email", "email_clicked"),
    ])
    def test_message_event_mapping(self, event_type, expected):
        from services.integrations.connectors.braze import BrazeConnector
        events = BrazeConnector().parse_webhook(
            {"items": [_braze_message_event(event_type)]},
        )
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "braze"
        assert events[0].source == "braze"

    def test_unknown_event_dropped(self):
        from services.integrations.connectors.braze import BrazeConnector
        events = BrazeConnector().parse_webhook(
            {"items": [_braze_message_event("users.messages.email.CustomTouch")]},
        )
        assert events == []

    def test_campaign_and_link_evidence_extracted(self):
        from services.integrations.connectors.braze import BrazeConnector
        events = BrazeConnector().parse_webhook({"items": [_braze_message_event(
            "users.messages.email.Click",
            {"link_url": "https://x.example/promo", "link_id": "link-1",
             "message_variation_id": "var-b", "canvas_id": "canvas-7",
             "canvas_step_id": "step-3", "template_id": "tpl-9",
             "device": {"user_agent": "Mozilla/5.0"},
             "canvas_variation_id": "var-a"},
        )]})
        props = events[0].properties
        assert props["external_campaign_id"] == "camp-1"
        assert props["external_flow_id"] == "canvas-7"
        assert props["external_message_id"] == "var-b"
        assert props["external_template_id"] == "tpl-9"
        assert props["variant_id"] == "var-a"
        assert props["link_id"] == "link-1"
        assert props["link_url_hash"]
        assert props["user_agent"] == "Mozilla/5.0"

    def test_hard_bounce_type(self):
        from services.integrations.connectors.braze import BrazeConnector
        events = BrazeConnector().parse_webhook(
            {"items": [_braze_message_event("users.messages.email.Bounce")]},
        )
        assert events[0].properties["bounce_type"] == "hard"

    def test_soft_bounce_stays_soft(self):
        """SoftBounce never becomes a hard-bounce suppression downstream."""
        from services.integrations.connectors.braze import BrazeConnector
        events = BrazeConnector().parse_webhook(
            {"items": [_braze_message_event("users.messages.email.SoftBounce")]},
        )
        assert events[0].properties["bounce_type"] == "soft"

    def test_unsubscribe_scope(self):
        from services.integrations.connectors.braze import BrazeConnector
        events = BrazeConnector().parse_webhook(
            {"items": [_braze_message_event("users.messages.email.Unsubscribe")]},
        )
        assert events[0].properties["unsubscribe_scope"] == "marketing_channel"


class TestEmailListExports:
    """REST email-list export entries (the pull surface) normalize to canonical
    events with suppression semantics for downstream suppression_authority."""

    def test_hard_bounce_entry(self):
        from services.integrations.connectors.braze import normalize_braze_event
        ev = normalize_braze_event(
            {"email": "a@example.com", "hard_bounced_at": "2026-07-01T00:00:00Z"},
        )
        assert ev is not None
        assert ev.event_type == "email_bounced"
        assert ev.properties["bounce_type"] == "hard"
        assert ev.properties["recipient_email"] == "a@example.com"

    def test_unsubscribe_entry(self):
        from services.integrations.connectors.braze import normalize_braze_event
        ev = normalize_braze_event(
            {"email": "b@example.com", "unsubscribed_at": "2026-07-01T00:00:00Z"},
        )
        assert ev is not None
        assert ev.event_type == "unsubscribe_observed"
        assert ev.properties["unsubscribe_scope"] == "marketing_channel"

    def test_list_export_events_carry_deterministic_ids(self):
        """Identifiers are derived deterministically (idempotent replay)."""
        from services.integrations.connectors.braze import normalize_braze_event
        record = {"email": "c@example.com", "hard_bounced_at": "2026-07-01T00:00:00Z"}
        ev1 = normalize_braze_event(record)
        ev2 = normalize_braze_event(record)
        assert ev1 is not None and ev2 is not None
        assert ev1.external_id == ev2.external_id
        assert ev1.external_id.startswith("br-")


class TestPull:
    @pytest.mark.asyncio
    async def test_pull_builds_list_and_catalog_events(self, monkeypatch):
        import services.integrations.connectors.braze as braze_mod
        from services.integrations.connectors.braze import BrazeConnector
        from services.integrations.connectors.base import ConnectorConfig

        async def fake_get(url, secret):
            assert secret == "rest-key"
            if "/email/hard_bounces" in url:
                assert "start_date=" in url and "end_date=" in url
                return 200, {"emails": [
                    {"email": "a@example.com",
                     "hard_bounced_at": "2026-07-01T00:00:00Z"},
                ]}
            if "/email/unsubscribes" in url:
                return 200, {"emails": [
                    {"email": "b@example.com",
                     "unsubscribed_at": "2026-07-01T00:00:00Z"},
                ]}
            if "/campaigns/list" in url:
                return 200, {"campaigns": [{"id": "c1", "name": "Launch",
                                            "is_api_campaign": True}]}
            if "/canvas/list" in url:
                return 200, {"canvases": [{"id": "f1", "name": "Onboard"}]}
            return 200, {}

        monkeypatch.setattr(braze_mod, "_get", fake_get)
        config = ConnectorConfig(connector_type="braze", tenant_id="t1")
        events = await BrazeConnector().pull(
            config, since="2026-07-01T00:00:00Z", secret="rest-key",
        )
        types = {e.event_type for e in events}
        assert {"email_bounced", "unsubscribe_observed",
                "braze.campaign", "braze.canvas"} <= types
        bounced = next(e for e in events if e.event_type == "email_bounced")
        assert bounced.properties["bounce_type"] == "hard"

    @pytest.mark.asyncio
    async def test_pull_rate_limit_leaves_no_events(self, monkeypatch):
        """A 429 aborts the list export with no events — the service layer then
        leaves the durable cursor put and the next run resumes from here."""
        import services.integrations.connectors.braze as braze_mod
        from services.integrations.connectors.braze import BrazeConnector
        from services.integrations.connectors.base import ConnectorConfig

        async def rate_limited(url, secret):
            return 429, {}

        monkeypatch.setattr(braze_mod, "_get", rate_limited)
        config = ConnectorConfig(connector_type="braze", tenant_id="t1")
        events = await BrazeConnector().pull(config, since="2026-07-01T00:00:00Z",
                                             secret="rest-key")
        assert events == []


class TestPullCursor:
    @pytest.mark.asyncio
    async def test_cursor_advances_only_after_durable_acceptance(self, monkeypatch):
        """Failed pull → sync raises and the cursor never moves; healthy pull →
        events persist AND the cursor advances (service-layer guarantee)."""
        from services.integrations.connectors.service import connector_service
        from services.integrations.connectors.braze import BrazeConnector
        from services.integrations.connectors.base import NormalizedEvent
        from repositories.delivery_repos import ConnectorCursorRepository

        async def failing_pull(self, config, since=None, secret=None):
            raise RuntimeError("upstream 500")

        monkeypatch.setattr(BrazeConnector, "pull", failing_pull)
        await connector_service.configure(
            "tenant-b", "braze", name="Braze", enabled=True,
            credential="rest-key", actor_id="user-1",
        )
        from services.delivery.adapters.base import ConnectorSyncError
        with pytest.raises(ConnectorSyncError):
            await connector_service.sync("tenant-b", "braze", actor_id="user-1")

        cursor = await ConnectorCursorRepository().get_cursor("tenant-b", "braze")
        assert cursor is None  # durable cursor never advanced on failure

        async def healthy_pull(self, config, since=None, secret=None):
            return [
                NormalizedEvent(event_type="email_bounced", source="braze",
                                external_id="b1",
                                properties={"provider": "braze",
                                            "bounce_type": "hard"}),
                NormalizedEvent(event_type="unsubscribe_observed", source="braze",
                                external_id="u1",
                                properties={"provider": "braze",
                                            "unsubscribe_scope": "marketing_channel"}),
            ]

        monkeypatch.setattr(BrazeConnector, "pull", healthy_pull)
        result = await connector_service.sync("tenant-b", "braze", actor_id="user-1")
        assert result.status == "healthy"

        cursor = await ConnectorCursorRepository().get_cursor("tenant-b", "braze")
        assert cursor is not None
        assert cursor["cursor_value"]  # advanced only after durable acceptance

    @pytest.mark.asyncio
    async def test_sync_records_durable_sync_run(self, monkeypatch):
        """The sync-run ledger records cursor_before → cursor_after honestly."""
        from services.integrations.connectors.service import connector_service
        from services.integrations.connectors.braze import BrazeConnector
        from services.integrations.connectors.base import NormalizedEvent

        async def fake_pull(self, config, since=None, secret=None):
            return [
                NormalizedEvent(event_type="email_delivered", source="braze",
                                external_id="e1", properties={"provider": "braze"}),
                NormalizedEvent(event_type="email_clicked", source="braze",
                                external_id="e2", properties={"provider": "braze"}),
            ]

        monkeypatch.setattr(BrazeConnector, "pull", fake_pull)
        await connector_service.configure(
            "tenant-x", "braze", name="Braze", enabled=True,
            credential="rest-key", actor_id="user-1",
        )
        result = await connector_service.sync("tenant-x", "braze", actor_id="user-1")
        assert result.status == "healthy"

        runs = await connector_service.list_sync_runs("tenant-x", "braze")
        assert len(runs) == 1
        run = runs[0]
        assert run["status"] == "completed"
        assert run["provider"] == "braze"
        assert run["records_received"] == 2
        assert run["cursor_after"] is not None


class TestDescriptor:
    def test_supports_pull_first_lifecycle(self):
        from services.integrations.connectors.braze import BrazeConnector
        c = BrazeConnector()
        assert c.supports_webhook and c.supports_pull
        assert c.supports_historical_backfill
        assert c.supports_reconciliation is False  # honest: no REST reconcile surface
        assert c.requires_secret
        assert c.required_credentials == ("api_key",)
        for t in ("email_sent", "email_delivered", "email_opened", "email_clicked",
                  "email_bounced", "email_dropped", "email_spam_complaint",
                  "unsubscribe_observed", "braze.campaign", "braze.canvas"):
            assert t in c.ingest_event_types

    def test_manifest_data_outputs_are_comms(self):
        from services.integrations.connectors.braze import BrazeConnector
        outputs = BrazeConnector().manifest_data_outputs
        assert outputs
        assert all(o.startswith("comms.") for o in outputs)

    def test_webhook_scheme_is_honest_generic_hmac(self):
        """Braze has no provider-native webhook HMAC; the generic timestamped
        HMAC is the honest fallback (pull-model-first)."""
        from services.integrations.connectors.braze import BrazeConnector
        assert BrazeConnector().signature_scheme == "hmac"

    def test_registry_serves_expanded_connector(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.braze import BrazeConnector
        assert isinstance(get_connector("braze"), BrazeConnector)


class TestIngestBridge:
    @pytest.mark.asyncio
    async def test_comm_events_ingest_to_bronze_pipeline(self):
        from services.comms.ingest import ingest_normalized_events
        counts = await ingest_normalized_events("tenant-b", [
            {"event_type": "email_delivered", "source": "braze",
             "external_id": "e1", "occurred_at": "2026-07-01T00:00:00+00:00",
             "properties": {"provider": "braze"}},
            {"event_type": "email_bounced", "source": "braze",
             "external_id": "e2", "occurred_at": "2026-07-01T00:00:00+00:00",
             "properties": {"provider": "braze", "bounce_type": "hard"}},
        ])
        assert counts["communications"] == 2

    @pytest.mark.asyncio
    async def test_catalog_records_register_canonical_campaign(self):
        from services.comms.ingest import ingest_normalized_events
        counts = await ingest_normalized_events("tenant-b", [
            {"event_type": "braze.campaign", "source": "braze",
             "external_id": "camp-ext-1",
             "properties": {"external_campaign_id": "camp-ext-1",
                            "name": "Summer Launch", "channel": "email"}},
        ])
        assert counts["catalog"] == 1
