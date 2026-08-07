"""Unit tests — Iterable connector webhook mapping, signature, and pull (ADR-C11)."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

SECRET = "whsec_iterable_test"
# The connector checks freshness against time.time(), so golden vectors must be
# signed in the current freshness window.
NOW = int(time.time())
PAYLOAD = b'{"eventType":"emailOpen"}'


def _iterable_record(event_type: str, **extra) -> dict:
    return {
        "eventType": event_type,
        "email": "jane@example.com",
        "campaignId": 42,
        "templateId": 7,
        "messageId": "iter-ev-1",
        "createdAt": "2026-07-01T00:00:00.000Z",
        "projectId": 123,
        **extra,
    }


class TestWebhookMapping:
    @pytest.mark.parametrize("event,expected", [
        ("emailSend", "email_sent"),
        ("emailDelivered", "email_delivered"),
        ("emailOpen", "email_opened"),
        ("emailClick", "email_clicked"),
        ("emailBounce", "email_bounced"),
        ("emailComplaint", "email_spam_complaint"),
        ("emailUnsubscribe", "unsubscribe_observed"),
        ("emailUnSubscribe", "unsubscribe_observed"),  # camelCase variant
    ])
    def test_event_mapping(self, event, expected):
        from services.integrations.connectors.iterable import IterableConnector
        events = IterableConnector().parse_webhook(_iterable_record(event))
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "iterable"
        assert events[0].properties["external_campaign_id"] == 42
        assert events[0].properties["external_template_id"] == 7
        assert events[0].properties["external_message_id"] == "iter-ev-1"

    def test_list_webhook_payload(self):
        from services.integrations.connectors.iterable import IterableConnector
        events = IterableConnector().parse_webhook(
            {"items": [_iterable_record("emailOpen"), _iterable_record("emailClick")]}
        )
        assert [e.event_type for e in events] == ["email_opened", "email_clicked"]

    def test_subscribe_has_no_canonical_event(self):
        """A resubscription is not a communication lifecycle fact Aether observes
        today — the record is dropped (mirrors SendGrid's group_resubscribe)."""
        from services.integrations.connectors.iterable import IterableConnector
        assert IterableConnector().parse_webhook(
            _iterable_record("emailSubscribe")
        ) == []

    def test_unknown_event_dropped(self):
        from services.integrations.connectors.iterable import IterableConnector
        assert IterableConnector().parse_webhook(
            _iterable_record("smsReceived")
        ) == []

    def test_identify_routes_to_identity_evidence(self):
        """identify/profile payloads are identity evidence, never a communication fact."""
        from services.integrations.connectors.iterable import IterableConnector
        events = IterableConnector().parse_webhook(
            {"eventType": "identify", "userId": "u-1", "email": "jane@example.com"}
        )
        assert len(events) == 1
        assert events[0].event_type == "iterable.profile"
        assert events[0].properties["provider_profile_id"] == "u-1"

    def test_hard_bounce_type(self):
        from services.integrations.connectors.iterable import IterableConnector
        events = IterableConnector().parse_webhook(_iterable_record(
            "emailBounce", dataFields={"bounceType": "HardBounce"},
        ))
        assert events[0].properties["bounce_type"] == "hard"

    def test_soft_bounce_type(self):
        from services.integrations.connectors.iterable import IterableConnector
        events = IterableConnector().parse_webhook(_iterable_record(
            "emailBounce", bounceType="SoftBounce",
        ))
        assert events[0].properties["bounce_type"] == "soft"

    def test_unsubscribe_scope(self):
        from services.integrations.connectors.iterable import IterableConnector
        scoped = IterableConnector().parse_webhook(
            _iterable_record("emailUnsubscribe", listId=9)
        )[0]
        assert scoped.properties["unsubscribe_scope"] == "list"
        global_ = IterableConnector().parse_webhook(
            _iterable_record("emailUnsubscribe")
        )[0]
        assert global_.properties["unsubscribe_scope"] == "marketing_channel"

    def test_click_link_and_user_agent(self):
        from services.integrations.connectors.iterable import IterableConnector
        events = IterableConnector().parse_webhook(_iterable_record(
            "emailClick", url="https://x.example/promo", userAgent="Mozilla/5.0",
        ))
        assert events[0].properties["link_id"] == "https://x.example/promo"
        assert events[0].properties["user_agent"] == "Mozilla/5.0"


class TestSignature:
    def _iterable_sig(self, payload: bytes) -> str:
        return hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()

    def test_verify_dispatches_native_query_hmac(self):
        from services.integrations.connectors.iterable import IterableConnector
        sig = self._iterable_sig(PAYLOAD)
        # The generic comms route merges the webhook URL's query params into the
        # headers mapping the native verifier reads (signature/ts as query params).
        headers = {"signature": sig}
        assert IterableConnector.verify_webhook_signature(PAYLOAD, headers, SECRET)
        # Tampered body must not verify.
        assert not IterableConnector.verify_webhook_signature(
            PAYLOAD + b"x", headers, SECRET
        )
        # Missing signature must not verify.
        assert not IterableConnector.verify_webhook_signature(PAYLOAD, {}, SECRET)
        # Wrong secret must not verify.
        assert not IterableConnector.verify_webhook_signature(
            PAYLOAD, headers, SECRET + "x"
        )

    def test_ts_query_param_rejects_stale_replay(self):
        from services.integrations.connectors.iterable import IterableConnector
        sig = self._iterable_sig(PAYLOAD)
        stale = int(time.time()) - 600  # outside the ±300s window
        headers = {"signature": sig, "ts": str(stale)}
        assert not IterableConnector.verify_webhook_signature(PAYLOAD, headers, SECRET)
        fresh = int(time.time())
        assert IterableConnector.verify_webhook_signature(
            PAYLOAD, {"signature": sig, "ts": str(fresh)}, SECRET
        )


class TestPull:
    def test_pull_requires_credential(self):
        """Offline (no credential) pull returns [] honestly — never fake data."""
        import asyncio
        from services.integrations.connectors.base import ConnectorConfig
        from services.integrations.connectors.iterable import IterableConnector

        cfg = ConnectorConfig(tenant_id="t", connector_type="iterable", enabled=True)
        events = asyncio.run(IterableConnector().pull(cfg, secret=None))
        assert events == []

    def test_pull_builds_cursor_bounded_export_requests(self):
        """The pull cursor maps onto the Export API startDateTime/endDateTime range
        and parses NDJSON event lines as canonical events."""
        from services.integrations.connectors.iterable import _EMAIL_EXPORT_DATA_TYPES
        from services.integrations.connectors.iterable import IterableConnector

        captured: list[tuple[str, str]] = []

        async def fake_get_text(url: str, secret: str):
            captured.append((url, secret))
            if "emailClick" in url:
                return 200, json.dumps({
                    "email": "jane@example.com", "campaignId": 42,
                    "messageId": "m1", "url": "https://x",
                    "createdAt": "2026-07-01T00:00:00.000Z",
                })
            if "userNew" in url:
                return 200, json.dumps({"email": "jane@example.com", "userId": "u-1"})
            return 200, ""

        conn = IterableConnector()
        import services.integrations.connectors.iterable as mod
        original = mod._get_text
        mod._get_text = fake_get_text  # type: ignore[assignment]
        try:
            import asyncio
            from services.integrations.connectors.base import ConnectorConfig
            cfg = ConnectorConfig(tenant_id="t", connector_type="iterable", enabled=True)
            events = asyncio.run(conn.pull(cfg, since="2026-06-01T00:00:00Z", secret=SECRET))
        finally:
            mod._get_text = original  # type: ignore[assignment]

        types_requested = {url.split("dataTypeName=")[1].split("&")[0] for url, _ in captured}
        assert types_requested == set(_EMAIL_EXPORT_DATA_TYPES) | {"userNew", "userUpdate"}
        assert any("startDateTime=2026-06-01T00%3A00%3A00Z" in url for url, _ in captured)
        # The click export line + userNew profile line both normalized.
        types = [e.event_type for e in events]
        assert "email_clicked" in types
        assert "iterable.profile" in types
        # Secret never leaves the adapter in logs — passed to the transport only.
        assert all(s == SECRET for _, s in captured)


class TestDescriptor:
    def test_supports_full_lifecycle(self):
        from services.integrations.connectors.iterable import IterableConnector
        c = IterableConnector()
        assert c.supports_webhook and c.supports_pull
        assert c.supports_historical_backfill
        assert not c.supports_reconciliation  # honestly undeclared
        for t in ("email_sent", "email_delivered", "email_opened", "email_clicked",
                  "email_bounced", "email_spam_complaint", "unsubscribe_observed"):
            assert t in c.ingest_event_types
        assert any(o.startswith("comms.") for o in c.manifest_data_outputs)

    def test_honest_readiness_and_credentials(self):
        from services.integrations.connectors.iterable import IterableConnector
        from shared.certification.readiness import to_readiness
        c = IterableConnector()
        assert c.signature_scheme == "iterable_hmac_query"
        assert c.required_credentials == ("api_key", "webhook_signing_secret")
        assert to_readiness(c.implementation_status).value == "credential_waiting"

    def test_registry_serves_iterable(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.iterable import IterableConnector
        assert isinstance(get_connector("iterable"), IterableConnector)


class TestIngestBridge:
    @pytest.mark.asyncio
    async def test_comm_events_ingest_to_bronze_pipeline(self):
        from services.comms.ingest import ingest_normalized_events
        counts = await ingest_normalized_events("tenant-i", [
            {"event_type": "email_delivered", "source": "iterable",
             "external_id": "e1", "occurred_at": "2026-07-01T00:00:00+00:00",
             "properties": {"provider": "iterable"}},
            {"event_type": "iterable.profile", "source": "iterable",
             "external_id": "p1",
             "properties": {"provider": "iterable", "email": "jane@example.com",
                            "provider_profile_id": "prof-1"}},
        ])
        assert counts["communications"] == 1
        assert counts["identities"] == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_flows_to_suppression_authority(self):
        """emailUnsubscribe → unsubscribe_observed → canonical suppression with the
        provider recorded as generic metadata (no provider branching)."""
        from services.comms.ingest import ingest_normalized_events
        from services.comms.suppression_authority import SuppressionAuthorityService

        await ingest_normalized_events("tenant-i", [
            {"event_type": "unsubscribe_observed", "source": "iterable",
             "external_id": "u1", "occurred_at": "2026-07-01T00:00:00+00:00",
             "properties": {"provider": "iterable", "recipient_email": "jane@example.com",
                            "unsubscribe_scope": "marketing_channel"}},
        ])
        active = await SuppressionAuthorityService().list_for_tenant(
            "tenant-i", provider="iterable"
        )
        assert active and active[0]["reason"] == "unsubscribe"
        assert active[0]["provider"] == "iterable"
