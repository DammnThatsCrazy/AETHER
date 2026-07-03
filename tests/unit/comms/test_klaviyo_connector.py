"""Unit tests — Klaviyo connector webhook mapping and catalog sync (Phase 12)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _klaviyo_record(metric_name: str, event_props: dict | None = None) -> dict:
    return {
        "id": "kl-ev-1",
        "type": "event",
        "attributes": {
            "metric": {"name": metric_name},
            "datetime": "2026-07-01T00:00:00+00:00",
            "event_properties": event_props or {},
            "profile": {"email": "jane@example.com", "id": "prof-1"},
        },
    }


class TestWebhookMapping:
    @pytest.mark.parametrize("metric,expected", [
        ("Delivered Email", "email_delivered"),
        ("Received Email", "email_delivered"),
        ("Opened Email", "email_opened"),
        ("Clicked Email", "email_clicked"),
        ("Bounced Email", "email_bounced"),
        ("Dropped Email", "email_dropped"),
        ("Marked Email as Spam", "email_spam_complaint"),
        ("Unsubscribed", "unsubscribe_observed"),
        ("Unsubscribed from List", "unsubscribe_observed"),
        ("Replied to Email", "email_replied"),
        ("Sent Email", "email_sent"),
    ])
    def test_metric_mapping(self, metric, expected):
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        events = KlaviyoConnector().parse_webhook({"data": [_klaviyo_record(metric)]})
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "klaviyo"

    def test_unknown_metric_dropped(self):
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        events = KlaviyoConnector().parse_webhook(
            {"data": [_klaviyo_record("Viewed Product")]},
        )
        assert events == []

    def test_campaign_and_link_evidence_extracted(self):
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        events = KlaviyoConnector().parse_webhook({"data": [_klaviyo_record(
            "Clicked Email",
            {"$message": "msg-42", "$flow": "flow-7", "URL": "https://x.example/promo",
             "$variation": "var-b"},
        )]})
        props = events[0].properties
        assert props["external_message_id"] == "msg-42"
        assert props["external_flow_id"] == "flow-7"
        assert props["link_id"] == "https://x.example/promo"
        assert props["variant_id"] == "var-b"

    def test_hard_bounce_type(self):
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        events = KlaviyoConnector().parse_webhook({"data": [_klaviyo_record(
            "Bounced Email", {"Bounce Type": "HardBounce"},
        )]})
        assert events[0].properties["bounce_type"] == "hard"

    def test_unsubscribe_scope(self):
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        events = KlaviyoConnector().parse_webhook({"data": [_klaviyo_record(
            "Unsubscribed from List",
        )]})
        assert events[0].properties["unsubscribe_scope"] == "list"


class TestDescriptor:
    def test_supports_full_lifecycle(self):
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        c = KlaviyoConnector()
        assert c.supports_webhook and c.supports_pull
        assert c.supports_historical_backfill
        for t in ("email_delivered", "email_clicked", "email_bounced",
                  "email_spam_complaint", "unsubscribe_observed"):
            assert t in c.ingest_event_types

    def test_registry_serves_expanded_connector(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.klaviyo import KlaviyoConnector
        assert isinstance(get_connector("klaviyo"), KlaviyoConnector)


class TestIngestBridge:
    @pytest.mark.asyncio
    async def test_comm_events_ingest_to_bronze_pipeline(self):
        from services.comms.ingest import ingest_normalized_events
        counts = await ingest_normalized_events("tenant-k", [
            {"event_type": "email_delivered", "source": "klaviyo",
             "external_id": "e1", "occurred_at": "2026-07-01T00:00:00+00:00",
             "properties": {"provider": "klaviyo"}},
            {"event_type": "klaviyo.profile", "source": "klaviyo",
             "external_id": "p1", "properties": {}},
        ])
        assert counts["communications"] == 1
        assert counts["skipped"] == 1

    @pytest.mark.asyncio
    async def test_catalog_records_register_canonical_campaign(self):
        from services.comms.ingest import ingest_normalized_events
        counts = await ingest_normalized_events("tenant-k", [
            {"event_type": "klaviyo.campaign", "source": "klaviyo",
             "external_id": "camp-ext-1",
             "properties": {"external_campaign_id": "camp-ext-1",
                            "name": "Summer Launch", "channel": "email"}},
        ])
        assert counts["catalog"] == 1
