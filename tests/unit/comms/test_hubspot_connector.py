"""Unit tests — HubSpot Marketing Hub comms connector (ADR-C11 follow-up).

Covers the HubSpot Marketing Email event webhook mapping → canonical
communication events, the existing ``hubspot_signature_v3`` webhook
verification, suppression mapping, the credential-gated connection test, and
the marketing-email campaign pull. The pre-existing CRM surface
(``hubspot.contact`` / ``hubspot.company`` / ``hubspot.deal``) is asserted to
remain untouched.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

PAYLOAD = b'{"events":[{"eventType":"CLICK"}]}'


def _hubspot_record(event_type: str, **extra) -> dict:
    return {
        "eventType": event_type,
        "id": "hs-ev-1",
        "email": "jane@example.com",
        "recipient": "jane@example.com",
        "campaignId": 7,
        "portalId": 62515,
        "created": 1750000000,
        **extra,
    }


def _hubspot_v3_signature(secret: str, payload: bytes) -> str:
    """Mirror the adapter's in-process verification: base64(HMAC-SHA256(secret, body))."""
    return base64.b64encode(
        hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    ).decode()


class TestWebhookMapping:
    @pytest.mark.parametrize("event_type,expected", [
        ("SENT", "email_sent"),
        ("PROCESSED", "email_processed"),
        ("DEFERRED", "email_deferred"),
        ("DELIVERED", "email_delivered"),
        ("OPEN", "email_opened"),
        ("OPENED", "email_opened"),
        ("CLICK", "email_clicked"),
        ("CLICKED", "email_clicked"),
        ("BOUNCE", "email_bounced"),
        ("DROPPED", "email_dropped"),
        ("SPAMREPORT", "email_spam_complaint"),
        ("SPAM", "email_spam_complaint"),
        ("UNSUBSCRIBE", "unsubscribe_observed"),
        ("UNSUBSCRIBED", "unsubscribe_observed"),
    ])
    def test_event_mapping(self, event_type, expected):
        from services.integrations.connectors.adapters import HubSpotConnector
        events = HubSpotConnector().parse_webhook({"events": [_hubspot_record(event_type)]})
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "hubspot"

    def test_unknown_event_dropped(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        assert HubSpotConnector().parse_webhook(
            {"events": [_hubspot_record("STATUSCHANGE")]}
        ) == []

    def test_generic_wrapped_array(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        events = HubSpotConnector().parse_webhook(
            {"items": [_hubspot_record("OPEN")]}
        )
        assert events[0].event_type == "email_opened"

    def test_single_record_dict(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        events = HubSpotConnector().parse_webhook(_hubspot_record("CLICK"))
        assert events[0].event_type == "email_clicked"

    def test_millisecond_epoch_normalized(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        events = HubSpotConnector().parse_webhook(
            {"events": [_hubspot_record("DELIVERED", created=1750000000000)]}
        )
        assert events[0].occurred_at.startswith("2025-06-15T")

    def test_bounce_type_from_subtype(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        hard = HubSpotConnector().parse_webhook(
            {"events": [_hubspot_record("BOUNCE", bounceSubType="PERMANENT")]}
        )[0]
        soft = HubSpotConnector().parse_webhook(
            {"events": [_hubspot_record("BOUNCE", bounceSubType="TEMPORARY")]}
        )[0]
        assert hard.properties["bounce_type"] == "hard"
        assert soft.properties["bounce_type"] == "soft"

    def test_unsubscribe_scope(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        props = HubSpotConnector().parse_webhook(
            {"events": [_hubspot_record("UNSUBSCRIBE")]}
        )[0].properties
        assert props["unsubscribe_scope"] == "marketing_channel"

    def test_click_evidence_extracted(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        props = HubSpotConnector().parse_webhook(
            {"events": [_hubspot_record("CLICK", url="https://x.example/promo")]}
        )[0].properties
        assert props["link_id"] == "https://x.example/promo"
        assert props["external_campaign_id"] == 7

    def test_crm_webhook_preserved(self):
        """CRM webhook payloads carry no ``eventType`` and keep the pre-comms
        base mapping exactly (no crash, no marketing rewrite)."""
        from services.integrations.connectors.adapters import HubSpotConnector
        crm = {"items": [
            {"subscriptionType": "contact.creation", "eventId": 1, "portalId": 1},
        ]}
        events = HubSpotConnector().parse_webhook(crm)
        assert len(events) == 1
        assert events[0].event_type == "hubspot.event"
        assert events[0].source == "hubspot"


class TestSignature:
    def test_verify_hubspot_signature_v3(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        headers = {"X-HubSpot-Signature-v3": _hubspot_v3_signature("whsec_x", PAYLOAD)}
        assert HubSpotConnector.verify_webhook_signature(PAYLOAD, headers, "whsec_x")
        # tampered body / missing header / wrong secret must all be rejected
        assert not HubSpotConnector.verify_webhook_signature(
            PAYLOAD + b"x", headers, "whsec_x"
        )
        assert not HubSpotConnector.verify_webhook_signature(PAYLOAD, {}, "whsec_x")
        assert not HubSpotConnector.verify_webhook_signature(PAYLOAD, headers, "wrong")

    def test_lowercased_header_accepted(self):
        """HTTP middleware lowercases header names; the all-lowercase form must
        still verify (this is the shape a framework delivers)."""
        from services.integrations.connectors.adapters import HubSpotConnector
        headers = {"x-hubspot-signature-v3": _hubspot_v3_signature("whsec_x", PAYLOAD)}
        assert HubSpotConnector.verify_webhook_signature(PAYLOAD, headers, "whsec_x")

    def test_legacy_signature_header_accepted(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        headers = {"X-HubSpot-Signature": _hubspot_v3_signature("whsec_x", PAYLOAD)}
        assert HubSpotConnector.verify_webhook_signature(PAYLOAD, headers, "whsec_x")


class TestDescriptor:
    def test_honest_declaration(self):
        from shared.certification.readiness import to_readiness
        from services.integrations.connectors.adapters import HubSpotConnector
        c = HubSpotConnector()
        assert c.signature_scheme == "hubspot_signature_v3"
        assert set(c.required_credentials) == {"api_key", "webhook_signing_secret"}
        assert c.supports_webhook and c.supports_pull
        assert to_readiness(c.implementation_status).value == "credential_waiting"
        assert "comms.delivery_events" in c.manifest_data_outputs
        assert "comms.campaigns" in c.manifest_data_outputs
        assert "send" not in c.ingest_event_types  # observe-only (ADR-C1)
        # existing CRM surface untouched
        assert c.category == "crm"
        for t in ("hubspot.contact", "hubspot.company", "hubspot.deal"):
            assert t in c.ingest_event_types

    def test_registry_serves_hubspot(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        from services.integrations.connectors.registry import get_connector
        assert isinstance(get_connector("hubspot"), HubSpotConnector)


class TestSuppressionMapping:
    @pytest.mark.asyncio
    async def test_unsubscribe_flows_to_authority(self):
        from services.comms.suppression_authority import SuppressionAuthorityService
        rec = await SuppressionAuthorityService().record_from_event("t", {
            "event_type": "unsubscribe_observed",
            "external_id": "hs-ev-1",
            "properties": {"provider": "hubspot", "recipient_email": "u@example.com",
                           "unsubscribe_scope": "marketing_channel"},
        })
        assert rec is not None
        assert rec["reason"] == "unsubscribe"
        assert rec["provider"] == "hubspot"

    @pytest.mark.asyncio
    async def test_hard_bounce_suppresses_soft_does_not(self):
        from services.comms.suppression_authority import SuppressionAuthorityService
        service = SuppressionAuthorityService()
        hard = await service.record_from_event("t", {
            "event_type": "email_bounced",
            "properties": {"provider": "hubspot", "recipient_email": "u@example.com",
                           "bounce_type": "hard"},
        })
        assert hard is not None and hard["reason"] == "hard_bounce"
        soft = await service.record_from_event("t", {
            "event_type": "email_bounced",
            "properties": {"provider": "hubspot", "recipient_email": "u@example.com",
                           "bounce_type": "soft"},
        })
        assert soft is None


class TestConnection:
    @pytest.mark.asyncio
    async def test_offline_credential_gated(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        from services.integrations.connectors.base import ConnectorConfig
        conn = HubSpotConnector()
        cfg = ConnectorConfig(tenant_id="t", connector_type="hubspot",
                              enabled=True, secret_configured=False)
        res = await conn.test_connection(cfg, secret=None)
        assert res.ok is False
        assert res.status == "not_configured"


class TestPull:
    @pytest.mark.asyncio
    async def test_pull_offline_returns_empty(self):
        from services.integrations.connectors.adapters import HubSpotConnector
        from services.integrations.connectors.base import ConnectorConfig
        cfg = ConnectorConfig(tenant_id="t", connector_type="hubspot")
        assert await HubSpotConnector().pull(cfg, secret=None) == []

    @pytest.mark.asyncio
    async def test_pull_syncs_marketing_email_campaigns(self, monkeypatch):
        import services.integrations.connectors.adapters as adapters
        from services.integrations.connectors.adapters import HubSpotConnector
        from services.integrations.connectors.base import ConnectorConfig

        async def fake_get(url: str, headers: dict) -> tuple[int, dict]:
            if "/marketing/v3/emails" in url:
                assert "createdAt=" in url  # durable cursor threaded through
                return 200, {"results": [
                    {"id": "email-1", "name": "Summer Launch", "state": "PUBLISHED",
                     "createdAt": "2026-07-01T00:00:00+00:00",
                     "updatedAt": "2026-07-02T00:00:00+00:00"},
                ]}
            return 200, {"results": [
                {"id": "c-1", "updatedAt": "2026-07-01T00:00:00+00:00",
                 "properties": {"email": "a@example.com"}},
            ]}

        monkeypatch.setattr(adapters, "_http_get", fake_get)
        cfg = ConnectorConfig(tenant_id="t", connector_type="hubspot")
        events = await HubSpotConnector().pull(
            cfg, since="2026-07-01T00:00:00+00:00", secret="tok"
        )
        campaigns = [e for e in events if e.event_type == "hubspot.campaign"]
        assert len(campaigns) == 1
        assert campaigns[0].properties["external_campaign_id"] == "email-1"
        assert campaigns[0].properties["channel"] == "email"
        contacts = [e for e in events if e.event_type == "hubspot.contact"]
        assert len(contacts) == 1  # existing CRM pull preserved
