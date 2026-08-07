"""Unit tests — Customer.io connector webhook mapping + signature (ADR-C11)."""

from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

SECRET = "whsec_cio_test"
# Connector verify_webhook_signature checks freshness against time.time(), so
# golden vectors must be signed in the current freshness window.
NOW = int(time.time())
PAYLOAD = b'{"event":"email_opened"}'


def _cio_record(event: str, **extra) -> dict:
    return {
        "event": event,
        "event_id": "cio-ev-1",
        "timestamp": NOW,
        "data": {"email_address": "jane@example.com", "campaign_id": "c1",
                 "delivery_id": "dl-1"},
        **extra,
    }


class TestWebhookMapping:
    @pytest.mark.parametrize("event,expected", [
        ("email_sent", "email_sent"),
        ("email_delivered", "email_delivered"),
        ("email_opened", "email_opened"),
        ("email_clicked", "email_clicked"),
        ("email_bounced", "email_bounced"),
        ("email_spammed", "email_spam_complaint"),
        ("email_dropped", "email_dropped"),
        ("unsubscribed", "unsubscribe_observed"),
    ])
    def test_event_mapping(self, event, expected):
        from services.integrations.connectors.customerio import CustomerIOConnector
        events = CustomerIOConnector().parse_webhook([_cio_record(event)])
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "customerio"

    def test_short_metric_name_mapping(self):
        from services.integrations.connectors.customerio import CustomerIOConnector
        events = CustomerIOConnector().parse_webhook([
            {**_cio_record("email_clicked"), "metric": "clicked"},
        ])
        assert events[0].event_type == "email_clicked"

    def test_unknown_event_dropped(self):
        from services.integrations.connectors.customerio import CustomerIOConnector
        assert CustomerIOConnector().parse_webhook(
            [_cio_record("email_converted")]
        ) == []

    def test_unix_timestamp_converted(self):
        from datetime import datetime, timezone
        from services.integrations.connectors.customerio import CustomerIOConnector
        events = CustomerIOConnector().parse_webhook([_cio_record("email_delivered")])
        assert events[0].occurred_at.startswith(
            datetime.fromtimestamp(NOW, tz=timezone.utc).isoformat().split("+")[0]
        )
        assert events[0].occurred_at.endswith("+00:00")

    def test_bounce_type(self):
        from services.integrations.connectors.customerio import CustomerIOConnector
        hard = CustomerIOConnector().parse_webhook([
            _cio_record("email_bounced", bounce_type="hard")
        ])[0]
        assert hard.properties["bounce_type"] == "hard"


class TestSignature:
    def _cio_sig(self, ts: int, payload: bytes) -> str:
        return hmac.new(
            SECRET.encode(), f"v0:{ts}:".encode() + payload, hashlib.sha256
        ).hexdigest()

    def test_verify_dispatches_native_hmac(self):
        from services.integrations.connectors.customerio import CustomerIOConnector
        sig = self._cio_sig(NOW, PAYLOAD)
        headers = {"X-CIO-Signature": sig, "X-CIO-Timestamp": str(NOW)}
        assert CustomerIOConnector.verify_webhook_signature(PAYLOAD, headers, SECRET)
        assert not CustomerIOConnector.verify_webhook_signature(
            PAYLOAD + b"x", headers, SECRET
        )
        assert not CustomerIOConnector.verify_webhook_signature(
            PAYLOAD, {}, SECRET
        )
        # the legacy ts.body construction must NOT verify — v0: is part of the
        # signed string
        legacy = hmac.new(
            SECRET.encode(), f"{NOW}.".encode() + PAYLOAD, hashlib.sha256
        ).hexdigest()
        assert not CustomerIOConnector.verify_webhook_signature(
            PAYLOAD, {"X-CIO-Signature": legacy, "X-CIO-Timestamp": str(NOW)}, SECRET
        )


class TestDescriptor:
    def test_honest_declaration(self):
        from services.integrations.connectors.customerio import CustomerIOConnector
        from shared.certification.readiness import to_readiness
        c = CustomerIOConnector()
        assert c.signature_scheme == "customerio_hmac_v0"
        assert c.required_credentials == ("webhook_signing_secret",)
        assert c.supports_pull is False
        assert to_readiness(c.implementation_status).value == "credential_waiting"
        assert "comms.click_events" in c.manifest_data_outputs

    def test_registry_serves_customerio(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.customerio import CustomerIOConnector
        assert isinstance(get_connector("customerio"), CustomerIOConnector)
