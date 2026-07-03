"""Unit tests — reply correlation and automated-response detection (Phase 13)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


class TestAutomatedResponseDetection:
    def test_out_of_office_subject(self):
        from services.comms.classification import detect_automated_response
        assert detect_automated_response(subject="Out of Office: back Monday") == "out_of_office"
        assert detect_automated_response(subject="Automatic reply: vacation") == "auto_response"

    def test_dsn_from_mailer_daemon(self):
        from services.comms.classification import detect_automated_response
        assert detect_automated_response(
            from_address_local="mailer-daemon",
        ) == "delivery_status_notification"

    def test_auto_submitted_header(self):
        from services.comms.classification import detect_automated_response
        assert detect_automated_response(
            headers={"Auto-Submitted": "auto-replied"},
        ) == "auto_response"

    def test_delivery_failure_subject(self):
        from services.comms.classification import detect_automated_response
        assert detect_automated_response(
            subject="Mail delivery failed: returning message to sender",
        ) == "delivery_status_notification"

    def test_human_reply_not_flagged(self):
        from services.comms.classification import detect_automated_response
        assert detect_automated_response(
            subject="Re: your proposal", headers={}, from_address_local="jane",
        ) is None


class TestCorrelation:
    def test_in_reply_to_wins(self):
        from services.comms.replies import correlate_reply
        result = correlate_reply(
            in_reply_to="<msg-1@provider>",
            references=["<older@provider>"],
            provider_thread_id="th-9",
        )
        assert result["method"] == "in_reply_to"
        assert result["external_message_id"] == "msg-1@provider"

    def test_references_fallback(self):
        from services.comms.replies import correlate_reply
        result = correlate_reply(references=["<a@p>", "<b@p>"])
        assert result["method"] == "references"
        assert result["external_message_id"] == "b@p"

    def test_thread_then_message_then_token(self):
        from services.comms.replies import correlate_reply
        assert correlate_reply(provider_thread_id="th-1")["method"] == "provider_thread"
        assert correlate_reply(external_message_id="m-1")["method"] == "external_message_id"
        assert correlate_reply(reply_token="tok12345")["method"] == "reply_token"
        assert correlate_reply()["method"] is None

    def test_reply_token_extraction(self):
        from services.comms.replies import extract_reply_token
        assert extract_reply_token("replies+AbC123xyz9@in.example.com") == "AbC123xyz9"
        assert extract_reply_token("plain@example.com") is None


class TestNormalization:
    def test_normalizes_human_reply(self):
        from services.comms.replies import normalize_inbound_reply
        event = normalize_inbound_reply("t1", {
            "from": "jane@example.com",
            "subject": "Re: offer",
            "in_reply_to": "<msg-77@klaviyo>",
            "received_at": "2026-07-01T10:00:00+00:00",
        })
        assert event["event_type"] == "email_replied"
        props = event["properties"]
        assert props["direction"] == "inbound"
        assert props["external_message_id"] == "msg-77@klaviyo"
        assert props["recipient_alias_id"]
        assert "automated_response_kind" not in props
        # no raw address, no subject retained
        assert "jane@example.com" not in str(event)
        assert "offer" not in str(event)

    def test_flags_out_of_office(self):
        from services.comms.replies import normalize_inbound_reply
        event = normalize_inbound_reply("t1", {
            "from": "jane@example.com",
            "subject": "Out of office until July 10",
            "in_reply_to": "<m@p>",
        })
        assert event["properties"]["automated_response_kind"] == "out_of_office"

    def test_rejects_missing_sender(self):
        from services.comms.replies import normalize_inbound_reply
        assert normalize_inbound_reply("t1", {"subject": "hi"}) is None
