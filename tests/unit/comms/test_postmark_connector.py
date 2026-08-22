"""Unit tests — Postmark connector webhook mapping + auth model (ADR-C11)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _pm_record(record_type: str, **extra) -> dict:
    return {"RecordType": record_type, "MessageID": "pm-1", **extra}


class TestWebhookMapping:
    @pytest.mark.parametrize("record_type,expected", [
        ("Delivery", "email_delivered"),
        ("Open", "email_opened"),
        ("Click", "email_clicked"),
        ("Bounce", "email_bounced"),
        ("SpamComplaint", "email_spam_complaint"),
    ])
    def test_record_type_mapping(self, record_type, expected):
        from services.integrations.connectors.postmark import PostmarkConnector
        events = PostmarkConnector().parse_webhook(
            [_pm_record(record_type, Recipient="jane@example.com",
                        ReceivedAt="2026-07-01T10:00:00Z")]
        )
        assert len(events) == 1
        assert events[0].event_type == expected
        assert events[0].properties["provider"] == "postmark"

    def test_transient_bounce_maps_to_deferred(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        events = PostmarkConnector().parse_webhook([
            _pm_record("Bounce", Type="Transient", BouncedAt="2026-07-01T10:00:00Z")
        ])
        assert events[0].event_type == "email_deferred"

    def test_unsubscribe_bounce_maps_to_unsubscribe(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        events = PostmarkConnector().parse_webhook([
            _pm_record("Bounce", Type="Unsubscribe", Recipient="u@example.com")
        ])
        assert events[0].event_type == "unsubscribe_observed"
        assert events[0].properties["unsubscribe_scope"] == "marketing_channel"

    def test_hard_bounce_classification(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        hard = PostmarkConnector().parse_webhook([
            _pm_record("Bounce", Type="HardBounce")
        ])[0]
        assert hard.properties["bounce_type"] == "hard"
        soft = PostmarkConnector().parse_webhook([
            _pm_record("Bounce", Type="Transient")
        ])[0]
        assert soft.event_type == "email_deferred"

    def test_subscription_change_suppression(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        events = PostmarkConnector().parse_webhook([
            _pm_record("SubscriptionChange", SuppressSending=True,
                       Recipient="u@example.com", ChangeType="Complaint")
        ])
        assert events[0].event_type == "email_suppressed"
        assert events[0].properties["suppression_reason"] == "recipient_suppression_request"

    def test_reactivation_dropped(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        assert PostmarkConnector().parse_webhook([
            _pm_record("SubscriptionChange", SuppressSending=False)
        ]) == []

    def test_unknown_record_type_dropped(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        assert PostmarkConnector().parse_webhook([_pm_record("Inbound")]) == []

    def test_transactional_message_category(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        events = PostmarkConnector().parse_webhook([
            _pm_record("Delivery", MessageStream="transactional")
        ])
        assert events[0].properties["message_category"] == "transactional"

    def test_timestamp_normalized(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        events = PostmarkConnector().parse_webhook([
            _pm_record("Open", OpenedAt="2026-07-01T10:00:00.0000000Z")
        ])
        assert events[0].occurred_at == "2026-07-01T10:00:00.0000000+00:00"


class TestAuthModel:
    def test_endpoint_secret_verified_by_possession(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        # No body signature — possession of the durable endpoint id is the auth.
        assert PostmarkConnector.verify_webhook_signature(b"{}", {}, "")


class TestDescriptor:
    def test_honest_declaration(self):
        from services.integrations.connectors.postmark import PostmarkConnector
        from shared.certification.readiness import to_readiness
        c = PostmarkConnector()
        assert c.signature_scheme == "endpoint_secret"
        assert c.required_credentials == ()
        assert c.requires_secret is False  # endpoint id is the credential
        assert c.supports_pull is False
        assert to_readiness(c.implementation_status).value == "credential_waiting"
        assert "comms.delivery_events" in c.manifest_data_outputs

    def test_registry_serves_postmark(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.postmark import PostmarkConnector
        assert isinstance(get_connector("postmark"), PostmarkConnector)
