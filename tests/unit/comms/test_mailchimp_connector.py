"""Unit tests — Mailchimp connector webhook mapping + auth model (ADR-C11)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _mc_form(type_: str, **data) -> dict:
    """A Mailchimp form-encoded payload as the service layer flattens it."""
    return {"type": type_, **{f"data[{k}]": v for k, v in data.items()}}


class TestWebhookMapping:
    def test_unsubscribe_maps_to_observed_list_unsubscribe(self):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        events = MailchimpConnector().parse_webhook(_mc_form(
            "unsubscribe", email="u@example.com", id="mc-1", list_id="L1",
            reason="clicked unsubscribe",
        ))
        assert len(events) == 1
        ev = events[0]
        assert ev.event_type == "unsubscribe_observed"
        assert ev.properties["unsubscribe_scope"] == "list"
        assert ev.properties["recipient_email"] == "u@example.com"
        assert ev.properties["external_list_id"] == "L1"
        assert ev.external_id == "mc-1"
        # Mailchimp sends no timestamp — the normalizer is a pure function of
        # the input (empty occurrence sentinel, stamped at ingest).
        assert ev.occurred_at == ""

    def test_cleaned_maps_to_suppression_with_reason(self):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        hard = MailchimpConnector().parse_webhook(
            _mc_form("cleaned", email="a@example.com", action="hard")
        )[0]
        assert hard.event_type == "email_suppressed"
        assert hard.properties["suppression_reason"] == "hard_bounce"
        abuse = MailchimpConnector().parse_webhook(
            _mc_form("cleaned", email="b@example.com", action="abuse")
        )[0]
        assert abuse.properties["suppression_reason"] == "abuse_complaint"

    @pytest.mark.parametrize("type_", ["subscribe", "upemail", "profile", "campaign"])
    def test_identity_campaign_events_dropped(self, type_):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        assert MailchimpConnector().parse_webhook(
            _mc_form(type_, email="x@example.com")
        ) == []

    def test_nested_json_payload_shape(self):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        events = MailchimpConnector().parse_webhook({
            "type": "unsubscribe",
            "data": {"email": "n@example.com", "id": "mc-2", "list_id": "L2"},
        })
        assert events[0].properties["recipient_email"] == "n@example.com"


class TestAuthModel:
    def test_endpoint_secret_verified_by_possession(self):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        # No body signature — possession of the durable endpoint id is the auth.
        assert MailchimpConnector.verify_webhook_signature(b"{}", {}, "")

    def test_supports_get_validation_probe(self):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        assert MailchimpConnector().supports_get_validation is True


class TestDescriptor:
    def test_honest_declaration(self):
        from services.integrations.connectors.mailchimp import MailchimpConnector
        from shared.certification.readiness import to_readiness
        c = MailchimpConnector()
        assert c.signature_scheme == "endpoint_secret"
        assert c.required_credentials == ()
        assert c.requires_secret is False  # endpoint id is the credential
        assert c.supports_pull is False
        assert to_readiness(c.implementation_status).value == "credential_waiting"
        assert "comms.suppressions" in c.manifest_data_outputs

    def test_registry_serves_mailchimp(self):
        from services.integrations.connectors.registry import get_connector
        from services.integrations.connectors.mailchimp import MailchimpConnector
        assert isinstance(get_connector("mailchimp"), MailchimpConnector)
