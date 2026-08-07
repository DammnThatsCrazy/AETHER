"""Unit tests — SendGrid (Twilio) connector webhook mapping + signature (ADR-C11)."""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

# Connector verify_webhook_signature checks freshness against time.time(), so
# golden vectors must be signed in the current freshness window.
NOW = int(time.time())
PAYLOAD = b'{"items":[{"event":"bounce"}]}'


def _sendgrid_record(event: str, **extra) -> dict:
    return {
        "event": event,
        "sg_event_id": "sg-ev-1",
        "email": "jane@example.com",
        "timestamp": NOW,
        **extra,
    }


class TestWebhookMapping:
    @pytest.mark.parametrize("event,expected", [
        ("processed", "email_processed"),
        ("deferred", "email_deferred"),
        ("delivered", "email_delivered"),
        ("open", "email_opened"),
        ("click", "email_clicked"),
        ("bounce", "email_bounced"),
        ("dropped", "email_dropped"),
        ("spamreport", "email_spam_complaint"),
        ("unsubscribe", "unsubscribe_observed"),
        ("group_unsubscribe", "unsubscribe_observed"),
    ])
    def test_event_mapping(self, event, expected):
        from services.integrations.connectors.sendgrid import SendGridConnector
        events = SendGridConnector().parse_webhook({"items": [_sendgrid_record(event)]})
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "sendgrid"

    def test_unknown_event_dropped(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        assert SendGridConnector().parse_webhook(
            {"items": [_sendgrid_record("group_resubscribe")]}
        ) == []

    def test_single_record_dict(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        events = SendGridConnector().parse_webhook(_sendgrid_record("open"))
        assert events[0].event_type == "email_opened"

    def test_bounce_type_from_smtp_status(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        hard = SendGridConnector().parse_webhook(
            {"items": [_sendgrid_record("bounce", status="5.1.1", reason="User unknown")]}
        )[0]
        soft = SendGridConnector().parse_webhook(
            {"items": [_sendgrid_record("bounce", status="4.2.2")]}
        )[0]
        assert hard.properties["bounce_type"] == "hard"
        assert soft.properties["bounce_type"] == "soft"

    def test_unsubscribe_scope(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        assert SendGridConnector().parse_webhook(
            {"items": [_sendgrid_record("unsubscribe")]}
        )[0].properties["unsubscribe_scope"] == "marketing_channel"
        assert SendGridConnector().parse_webhook(
            {"items": [_sendgrid_record("group_unsubscribe")]}
        )[0].properties["unsubscribe_scope"] == "list"

    def test_click_evidence_extracted(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        props = SendGridConnector().parse_webhook(
            {"items": [_sendgrid_record("click", url="https://x.example/promo",
                                        useragent="Mozilla/5.0")]}
        )[0].properties
        assert props["link_id"] == "https://x.example/promo"
        assert props["user_agent"] == "Mozilla/5.0"


class TestSignature:
    def _ec_public_key(self) -> tuple[object, str]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        private = ec.generate_private_key(ec.SECP256R1())
        public_der = private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return private, base64.b64encode(public_der).decode()

    def _ecdsa_sig(self, private, ts: int, payload: bytes) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        sig = private.sign(f"{ts}".encode() + payload, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(sig).decode()

    def test_verify_dispatches_native_ecdsa(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        private, public_b64 = self._ec_public_key()
        sig = self._ecdsa_sig(private, NOW, PAYLOAD)
        headers = {
            "X-Twilio-Email-Event-Webhook-Signature": sig,
            "X-Twilio-Email-Event-Webhook-Timestamp": str(NOW),
        }
        assert SendGridConnector.verify_webhook_signature(PAYLOAD, headers, public_b64)
        assert not SendGridConnector.verify_webhook_signature(
            PAYLOAD + b"x", headers, public_b64
        )
        assert not SendGridConnector.verify_webhook_signature(
            PAYLOAD, {}, public_b64
        )


class TestDescriptor:
    def test_honest_declaration(self):
        from services.integrations.connectors.sendgrid import SendGridConnector
        from shared.certification.readiness import to_readiness
        c = SendGridConnector()
        assert c.signature_scheme == "sendgrid_ecdsa"
        assert c.required_credentials == ("webhook_signing_secret",)
        assert c.supports_pull is False
        assert to_readiness(c.implementation_status).value == "credential_waiting"
        assert "comms.delivery_events" in c.manifest_data_outputs
        assert "send" not in c.ingest_event_types  # observe-only (ADR-C1)

    def test_registry_serves_sendgrid(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.sendgrid import SendGridConnector
        assert isinstance(get_connector("sendgrid"), SendGridConnector)
