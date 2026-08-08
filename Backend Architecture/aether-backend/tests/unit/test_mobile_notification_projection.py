"""M1a unit tests — redacted mobile notification projection (decision-log D11).

Covers the projection service (`services/notification_intelligence/projection.py`)
and its wiring into the push adapters (`_notification_base` / `apns` / `fcm`):

  * redaction — no raw payload / PII / amounts leak into projection fields;
  * truncation limits on title / body / summary;
  * deep-link class correctness (continuation-plane surfaces, not new classes);
  * category routing;
  * fail-closed on a push with no projection AND no source content;
  * parity of the new snake_case fields (Python model ↔ TS contract shape);
  * a push built from the projection contains ONLY projected fields;
  * the canonical inbox record is populated with the projection at creation.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from config.settings import Environment
import config.settings as settings_mod

from services.delivery.adapters.apns import APNsAdapter
from services.delivery.adapters.fcm import FCMAdapter
from services.delivery.adapters.base import ConfigurationError
from services.notification_intelligence.models import IntelligenceNotificationEvent
from services.notification_intelligence.projection import (
    DEFAULT_DEEP_LINK_CLASS,
    DEFAULT_PUSH_BODY,
    DEFAULT_PUSH_TITLE,
    PUSH_BODY_MAX_CHARS,
    PUSH_SUMMARY_MAX_CHARS,
    PUSH_TITLE_MAX_CHARS,
    PROJECTION_FIELDS,
    MobileNotificationProjection,
    build_projection,
)


def _run(coro):
    return asyncio.run(coro)


def _set_env(monkeypatch, env: Environment):
    monkeypatch.setattr(settings_mod.settings, "env", env)


def _stub_transport(status, data):
    async def _t(method, url, headers, body):
        _t.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return status, dict(data)

    _t.calls = []
    return _t


# ── redaction ────────────────────────────────────────────────────────────────

def test_projection_redacts_pii_amounts_and_card_numbers():
    proj = build_projection(
        title="Payment from Alice for $1,234.56",
        body=(
            "Charged 4111111111111111, contact alice@example.com "
            "at +1 234 567 8900 — total 9,876.54 USD"
        ),
        summary="Total $9,876.54",
    )
    payload = proj.as_payload()
    joined = " ".join(str(v or "") for v in payload.values())
    for raw in (
        "$1,234.56",
        "4111111111111111",
        "alice@example.com",
        "+1 234 567 8900",
        "9,876.54",
    ):
        assert raw not in joined, f"raw value leaked into projection: {raw!r}"
    assert "[redacted]" in joined


def test_projection_redacts_ungrouped_and_large_amounts():
    """Ungrouped/large amounts the comma-form regex cannot see must not leak
    (M8 data-truth-2): '1234.56', '12000', '200000.0', '$12000.00'."""
    proj = build_projection(
        title="Total 1234.56",
        body="Balance 12000 — transfer 200000.0 — fee $12000.00",
        summary="Wire 12000.5",
    )
    payload = proj.as_payload()
    joined = " ".join(str(v or "") for v in payload.values())
    for raw in ("1234.56", "12000", "200000.0", "$12000.00", "12000.5"):
        assert raw not in joined, f"ungrouped amount leaked into projection: {raw!r}"
    assert "[redacted]" in joined


def test_projection_does_not_over_redact_bare_years():
    """The ungrouped-amount pass is deliberately conservative: a bare 4-digit
    run without a decimal part is a year, not an amount, and must survive."""
    proj = build_projection(
        title="fiscal year 2026",
        body="baseline for 2026 reporting",
    )
    joined = " ".join(str(v or "") for v in proj.as_payload().values())
    assert "2026" in joined


def test_projection_redacts_direct_record_payload():
    """A raw record dict (notification-shaped) yields a redacted projection."""
    proj = build_projection(
        {
            "title": "Withdrawal $50,000.00 for alice@example.com",
            "body": "wire +1 555 0100 9999 to account 1234567890",
            "notification_class": "alert",
            "severity": "P0",
            "deep_link": "/investigation/xyz",
        }
    )
    payload = proj.as_payload()
    joined = " ".join(str(v or "") for v in payload.values())
    assert "50,000.00" not in joined
    assert "alice@example.com" not in joined
    assert "1234567890" not in joined
    assert proj.push_deep_link_class == "investigation"
    assert proj.push_category == "alert"


def test_projection_never_includes_raw_payload_dict_fields():
    """operator_context / graph_propagation / routing_policy never surface."""
    proj = build_projection(
        {
            "title": "Anomaly",
            "body": "observed",
            "operator_context": {"investigation_case_id": "case-99", "actor": "kyber-ops"},
            "graph_propagation": {"entity_ids": ["ent_abc123"]},
            "routing_policy": {"channels": ["slack", "push"]},
            "slack_payload": {"blocks": [{"text": "RAW"}]},
        }
    )
    joined = " ".join(str(v or "") for v in proj.as_payload().values())
    for raw in ("case-99", "kyber-ops", "ent_abc123", "RAW"):
        assert raw not in joined, f"raw payload field leaked: {raw!r}"


# ── truncation ───────────────────────────────────────────────────────────────

def test_projection_truncates_long_content():
    long_title = "x" * (PUSH_TITLE_MAX_CHARS + 50)
    long_body = "y" * (PUSH_BODY_MAX_CHARS + 50)
    long_summary = "z" * (PUSH_SUMMARY_MAX_CHARS + 50)
    proj = build_projection(title=long_title, body=long_body, summary=long_summary)
    assert len(proj.push_title) <= PUSH_TITLE_MAX_CHARS
    assert len(proj.push_body) <= PUSH_BODY_MAX_CHARS
    assert len(proj.push_summary) <= PUSH_SUMMARY_MAX_CHARS
    assert proj.push_title.endswith("…")


def test_projection_fallback_defaults_on_empty_source():
    proj = build_projection(record={})
    assert proj.push_title == DEFAULT_PUSH_TITLE
    assert proj.push_body == DEFAULT_PUSH_BODY
    assert proj.push_deep_link_class == DEFAULT_DEEP_LINK_CLASS
    assert proj.push_category == "alert"


# ── deep-link class ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "deep_link, expected",
    [
        ("/mission", "mission"),
        ("/mission/something", "mission"),
        ("/exploration/abc", "exploration"),
        ("/investigation", "investigation"),
        ("/incident/42", "incident"),
        ("/notifications/inbox", "notifications"),
        ("/campaigns/q3", "campaign"),
        ("cont_abc123", DEFAULT_DEEP_LINK_CLASS),
        ("https://app.example.com/some/route", DEFAULT_DEEP_LINK_CLASS),
        ("/unknown/route", DEFAULT_DEEP_LINK_CLASS),
        (None, DEFAULT_DEEP_LINK_CLASS),
    ],
)
def test_deep_link_class_mapping(deep_link, expected):
    proj = build_projection(title="t", body="b", deep_link=deep_link)
    assert proj.push_deep_link_class == expected


def test_deep_link_class_is_validated_to_continuation_surface():
    # A bogus/invented class degrades to the default surface — never an invented one.
    proj = MobileNotificationProjection(push_deep_link_class="not-a-surface")
    assert proj.push_deep_link_class == DEFAULT_DEEP_LINK_CLASS


# ── category routing ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "category, notification_class, expected",
    [
        ("billing", None, "billing"),
        (None, "action-request", "action-request"),
        ("operational", "alert", "operational"),
        (None, None, "alert"),
        ("", None, "alert"),
    ],
)
def test_category_routing(category, notification_class, expected):
    proj = build_projection(
        title="t", body="b", category=category, notification_class=notification_class
    )
    assert proj.push_category == expected


# ── fail closed ──────────────────────────────────────────────────────────────

def test_push_projection_fails_closed_without_source_content():
    adapter = APNsAdapter()
    with pytest.raises(ConfigurationError, match="redacted projection"):
        adapter._push_projection({}, {})
    with pytest.raises(ConfigurationError, match="redacted projection"):
        adapter._push_alert({}, {})


def test_dispatch_fails_closed_without_projection(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"_headers": {"apns-id": "X"}})
    adapter = APNsAdapter(transport=transport)
    with pytest.raises(ConfigurationError, match="redacted projection"):
        _run(
            adapter.dispatch(
                {},
                {"device_token": "d", "bundle_id": "b"},
                credential="jwt",
            )
        )
    # The transport must never have been called with a raw payload.
    assert transport.calls == []


# ── parity of the new fields ─────────────────────────────────────────────────

def test_projection_field_contract_parity():
    assert set(MobileNotificationProjection.model_fields.keys()) == set(PROJECTION_FIELDS)
    # The canonical event carries the projection fields so a push needs no 2nd record.
    event_fields = set(IntelligenceNotificationEvent.model_fields.keys())
    assert set(PROJECTION_FIELDS) <= event_fields


def test_projection_model_forbids_extra_fields():
    with pytest.raises(Exception):
        MobileNotificationProjection(push_title="t", raw_payload="boom")  # noqa: E501


# ── a push built from the projection contains ONLY projected fields ──────────

def test_apns_push_contains_only_projected_fields(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"_headers": {"apns-id": "ABC-123"}})
    adapter = APNsAdapter(transport=transport)
    payload = {
        "push_title": "P1 alert",
        "push_body": "Suspicious activity on your account",
        "push_summary": "Review required",
        "push_deep_link_class": "investigation",
        "push_category": "action-request",
        # Raw payload must never travel even when present alongside the projection.
        "title": "RAW: Alice paid $1,234.56 to card 4111111111111111",
        "body": "RAW: contact alice@example.com at +1 234 567 8900",
        "deep_link_id": "cont_abc123",
    }
    _run(
        adapter.dispatch(
            payload,
            {"device_token": "devtok", "bundle_id": "com.aether.app", "environment": "sandbox"},
            credential="bearer-jwt",
        )
    )
    body = transport.calls[0]["body"]
    text = body.decode("utf-8")
    sent = json.loads(body)
    alert = sent["aps"]["alert"]
    assert alert["title"] == "P1 alert"
    assert alert["body"] == "Suspicious activity on your account"
    assert alert["subtitle"] == "Review required"
    assert sent["push_deep_link_class"] == "investigation"
    assert sent["push_category"] == "action-request"
    assert sent["deep_link_id"] == "cont_abc123"
    for raw in (
        "RAW",
        "Alice",
        "$1,234.56",
        "4111111111111111",
        "alice@example.com",
        "+1 234 567 8900",
    ):
        assert raw not in text, f"raw payload leaked into APNs push: {raw!r}"


def test_fcm_push_carries_projection_routing_fields(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"name": "projects/proj/messages/42"})
    adapter = FCMAdapter(transport=transport)
    payload = {
        "push_title": "Extraction cluster escalated",
        "push_body": "Review the flagged cluster",
        "push_summary": "P0 action required",
        "push_deep_link_class": "exploration",
        "push_category": "action-request",
        "title": "RAW: cluster 44 with entity ent_secret",
        "body": "RAW: $9,999.99 to alice@example.com",
    }
    _run(
        adapter.dispatch(
            payload,
            {"registration_token": "rt", "project_id": "proj"},
            credential="oauth-token",
        )
    )
    sent = json.loads(transport.calls[0]["body"])
    message = sent["message"]
    assert message["notification"]["title"] == "Extraction cluster escalated"
    assert message["notification"]["body"] == "Review the flagged cluster"
    assert message["data"]["push_summary"] == "P0 action required"
    assert message["data"]["push_deep_link_class"] == "exploration"
    assert message["data"]["push_category"] == "action-request"
    text = transport.calls[0]["body"].decode("utf-8")
    for raw in ("RAW", "ent_secret", "$9,999.99", "alice@example.com"):
        assert raw not in text, f"raw payload leaked into FCM push: {raw!r}"


def test_apns_derives_redacted_projection_from_source_content(monkeypatch):
    """No explicit projection → the boundary derives a redacted one (D11)."""
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"_headers": {"apns-id": "X"}})
    adapter = APNsAdapter(transport=transport)
    _run(
        adapter.dispatch(
            {"title": "Payment of $5,000 to alice@example.com", "body": "details"},
            {"device_token": "d", "bundle_id": "b"},
            credential="jwt",
        )
    )
    body = transport.calls[0]["body"]
    assert b"$5,000" not in body
    assert b"alice@example.com" not in body
    assert b"[redacted]" in body


# ── canonical inbox record carries the projection at creation ────────────────

def test_inbox_notification_populates_projection():
    from services.notification_intelligence.inbox import create_inbox_notification

    row = _run(
        create_inbox_notification(
            "tenant-1",
            category="alert",
            severity="P1",
            title="Escalation $5,000.00 for bob@example.com",
            body="Review immediately",
            link="/investigation/abc",
        )
    )
    assert set(PROJECTION_FIELDS) <= set(row.keys())
    joined = " ".join(str(row.get(f) or "") for f in PROJECTION_FIELDS)
    assert "$5,000.00" not in joined
    assert "bob@example.com" not in joined
    assert row["push_deep_link_class"] == "investigation"
    assert row["push_category"] == "alert"
