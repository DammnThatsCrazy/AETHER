"""Inbound notification webhook verification — fail-closed adversarial tests.

Pins two closures:

1. The public Slack interactive callback used to SKIP signature verification
   entirely when ``SLACK_SIGNING_SECRET`` was unset. Outside local it now
   rejects instead.

2. Linear / Jira / generic-webhook inbox rows never carry a stored secret
   (that would persist plaintext at rest), so the inbox processor's
   verification could never succeed — every row stayed ``verified: False``
   forever. The processor now falls back to configured delivery secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import dataclasses

import pytest


def _set_delivery(monkeypatch, **overrides):
    from config.settings import settings

    monkeypatch.setattr(
        settings, "delivery", dataclasses.replace(settings.delivery, **overrides)
    )


def _processor():
    from services.delivery.outcome_processor import WebhookInboxProcessor

    return WebhookInboxProcessor(inbox_repo=None, outcome_repo=None, link_repo=None)


# ── Slack callback fail-closed ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slack_callback_rejects_without_secret_outside_local(monkeypatch):
    from starlette.requests import Request as StarletteRequest

    from shared.common.common import ForbiddenError
    from services.notification_intelligence.routes import slack_interactive_callback

    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    monkeypatch.setenv("AETHER_ENV", "production")

    async def receive():
        return {"type": "http.request", "body": b"payload=%7B%7D", "more_body": False}

    request = StarletteRequest(
        {"type": "http", "method": "POST", "path": "/slack/callback", "headers": []},
        receive,
    )
    with pytest.raises(ForbiddenError):
        await slack_interactive_callback(request)


@pytest.mark.asyncio
async def test_slack_callback_still_verifies_bad_signature(monkeypatch):
    from starlette.requests import Request as StarletteRequest

    from shared.common.common import ForbiddenError
    from services.notification_intelligence.routes import slack_interactive_callback

    monkeypatch.setenv("SLACK_SIGNING_SECRET", "configured-secret")
    monkeypatch.setenv("AETHER_ENV", "production")

    async def receive():
        return {"type": "http.request", "body": b"payload=%7B%7D", "more_body": False}

    request = StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "path": "/slack/callback",
            "headers": [
                (b"x-slack-request-timestamp", b"1700000000"),
                (b"x-slack-signature", b"v0=forged"),
            ],
        },
        receive,
    )
    with pytest.raises(ForbiddenError):
        await slack_interactive_callback(request)


# ── Inbox processor secret resolution ─────────────────────────────────────


@pytest.mark.asyncio
async def test_linear_inbox_row_verifies_via_configured_secret(monkeypatch):
    secret = "linear-inbound-secret"
    _set_delivery(monkeypatch, linear_webhook_secret=secret)
    body = b'{"action":"update","type":"Issue"}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    inbox = {
        "id": "in-1",
        "provider": "linear",
        "headers": {"Linear-Signature": signature},
        "raw_body": body.decode(),
        # NOTE: no webhook_secret on the row — the writer never persists one.
    }
    assert await _processor()._verify_signature(inbox) is True


@pytest.mark.asyncio
async def test_linear_forged_signature_fails(monkeypatch):
    _set_delivery(monkeypatch, linear_webhook_secret="linear-inbound-secret")
    inbox = {
        "id": "in-2",
        "provider": "linear",
        "headers": {"Linear-Signature": "0" * 64},
        "raw_body": '{"action":"update"}',
    }
    assert await _processor()._verify_signature(inbox) is False


@pytest.mark.asyncio
async def test_linear_without_any_secret_stays_unverified(monkeypatch):
    _set_delivery(monkeypatch, linear_webhook_secret="")
    inbox = {
        "id": "in-3",
        "provider": "linear",
        "headers": {"Linear-Signature": "0" * 64},
        "raw_body": "{}",
    }
    assert await _processor()._verify_signature(inbox) is False


@pytest.mark.asyncio
async def test_jira_inbox_row_verifies_via_configured_secret(monkeypatch):
    secret = "jira-inbound-secret"
    _set_delivery(monkeypatch, jira_webhook_secret=secret)
    body = b'{"webhookEvent":"jira:issue_updated"}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    inbox = {
        "id": "in-4",
        "provider": "jira",
        "headers": {"X-Hub-Signature-256": signature},
        "raw_body": body.decode(),
    }
    assert await _processor()._verify_signature(inbox) is True


@pytest.mark.asyncio
async def test_generic_webhook_verifies_via_configured_secret(monkeypatch):
    import time

    secret = "generic-callback-secret"
    _set_delivery(monkeypatch, webhook_signing_secret=secret)
    ts = str(int(time.time()))
    body = '{"outcome":"delivered"}'
    signature = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()

    inbox = {
        "id": "in-5",
        "provider": "webhook",
        "headers": {"X-Aether-Signature": f"sha256={signature}", "X-Aether-Timestamp": ts},
        "raw_body": body,
    }
    assert await _processor()._verify_signature(inbox) is True
