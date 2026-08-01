"""Unit tests for the C3 mobile/notification provider adapters.

Covers, for APNs / FCM / Web Push / email:
  * the provider-shaped local fake (local/dev env → non-simulated receipt);
  * the production guard (integration/staging/production + no credential →
    ConfigurationError; a fake can never be a production sender);
  * the real path's request construction + response mapping, exercised through an
    injected transport (live provider sends are externally blocked);
  * receipt honesty (external_id never empty, never ``sim-``-prefixed).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from config.settings import Environment
import config.settings as settings_mod

from services.delivery.adapters.apns import APNsAdapter
from services.delivery.adapters.email import EmailAdapter
from services.delivery.adapters.fcm import FCMAdapter
from services.delivery.adapters.web_push import WebPushAdapter
from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapterRegistry,
    ProviderError,
    RetryableProviderError,
)


def _run(coro):
    return asyncio.run(coro)


def _set_env(monkeypatch, env: Environment):
    monkeypatch.setattr(settings_mod.settings, "env", env)


def _stub_transport(status, data):
    async def _t(method, url, headers, body):
        # Record the call for assertions.
        _t.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return status, dict(data)

    _t.calls = []
    return _t


# ── registration ────────────────────────────────────────────────────────────

def test_registry_registers_notification_providers():
    names = ProviderAdapterRegistry.default().list_names()
    for name in ("apns", "fcm", "web_push", "email"):
        assert name in names


# ── local fake path ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "adapter_cls, cfg",
    [
        (APNsAdapter, {"device_token": "dt", "bundle_id": "com.aether.app"}),
        (FCMAdapter, {"registration_token": "rt", "project_id": "proj"}),
        (WebPushAdapter, {"endpoint": "https://push.example/abc"}),
        (EmailAdapter, {"to": "u@example.com", "sender": "no-reply@aether.app"}),
    ],
)
def test_fake_accepts_in_local_env(monkeypatch, adapter_cls, cfg):
    _set_env(monkeypatch, Environment.LOCAL)
    adapter = adapter_cls()
    receipt = _run(adapter.dispatch({"title": "Hi", "body": "secret"}, cfg))
    assert isinstance(receipt, AdapterReceipt)
    assert receipt.external_id  # non-empty
    assert not receipt.external_id.startswith("sim-")
    assert receipt.raw_response.get("fake") is True
    assert receipt.http_status == 202


@pytest.mark.parametrize("env", [Environment.INTEGRATION, Environment.STAGING, Environment.PRODUCTION])
def test_fake_forbidden_outside_local_dev(monkeypatch, env):
    _set_env(monkeypatch, env)
    adapter = APNsAdapter()
    with pytest.raises(ConfigurationError, match="forbidden in env"):
        _run(adapter.dispatch({"title": "Hi"}, {"device_token": "dt", "bundle_id": "b"}))


def test_missing_recipient_is_configuration_error(monkeypatch):
    _set_env(monkeypatch, Environment.LOCAL)
    with pytest.raises(ConfigurationError, match="recipient/device token"):
        _run(APNsAdapter().dispatch({"title": "Hi"}, {}))


# ── APNs real path (injected transport) ─────────────────────────────────────

def test_apns_real_path_builds_request_and_maps_apns_id(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"_headers": {"apns-id": "ABC-123"}})
    adapter = APNsAdapter(transport=transport)
    receipt = _run(
        adapter.dispatch(
            {"title": "Alert", "body": "sensitive"},
            {"device_token": "devtok", "bundle_id": "com.aether.app", "environment": "sandbox"},
            credential="bearer-jwt",
            idempotency_key="idem-1",
        )
    )
    call = transport.calls[0]
    assert call["url"] == "https://api.sandbox.push.apple.com/3/device/devtok"
    assert call["headers"]["authorization"] == "bearer bearer-jwt"
    assert call["headers"]["apns-topic"] == "com.aether.app"
    # Push body is redacted by default — the sensitive body must not appear.
    assert b"sensitive" not in call["body"]
    sent = json.loads(call["body"])
    assert sent["aps"]["alert"]["title"] == "Alert"
    assert receipt.external_id == "apns:ABC-123"


def test_apns_full_content_opt_in(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"_headers": {"apns-id": "X"}})
    adapter = APNsAdapter(transport=transport)
    _run(
        adapter.dispatch(
            {"title": "Alert", "body": "full-body"},
            {"device_token": "d", "bundle_id": "b", "allow_full_content": True},
            credential="jwt",
        )
    )
    assert b"full-body" in transport.calls[0]["body"]


def test_apns_missing_apns_id_is_provider_error(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"_headers": {}})
    adapter = APNsAdapter(transport=transport)
    with pytest.raises(ProviderError, match="apns-id"):
        _run(adapter.dispatch({"title": "A"}, {"device_token": "d", "bundle_id": "b"}, credential="jwt"))


@pytest.mark.parametrize(
    "status, exc",
    [(429, RetryableProviderError), (503, RetryableProviderError), (400, ProviderError)],
)
def test_apns_status_mapping(monkeypatch, status, exc):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(status, {"reason": "BadDeviceToken"})
    adapter = APNsAdapter(transport=transport)
    with pytest.raises(exc):
        _run(adapter.dispatch({"title": "A"}, {"device_token": "d", "bundle_id": "b"}, credential="jwt"))


# ── FCM real path ───────────────────────────────────────────────────────────

def test_fcm_real_path_maps_message_name(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"name": "projects/proj/messages/42"})
    adapter = FCMAdapter(transport=transport)
    receipt = _run(
        adapter.dispatch(
            {"title": "N", "deep_link_id": "cont_1"},
            {"registration_token": "rt", "project_id": "proj"},
            credential="oauth-token",
        )
    )
    call = transport.calls[0]
    assert call["url"] == "https://fcm.googleapis.com/v1/projects/proj/messages:send"
    assert call["headers"]["authorization"] == "Bearer oauth-token"
    sent = json.loads(call["body"])
    assert sent["message"]["token"] == "rt"
    assert sent["message"]["data"]["deep_link_id"] == "cont_1"
    assert receipt.external_id == "projects/proj/messages/42"


def test_fcm_requires_project_id(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    adapter = FCMAdapter(transport=_stub_transport(200, {}))
    with pytest.raises(ConfigurationError, match="project_id"):
        _run(adapter.dispatch({"title": "N"}, {"registration_token": "rt"}, credential="tok"))


# ── Web Push real path ──────────────────────────────────────────────────────

def test_web_push_maps_location_header(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(201, {"_headers": {"location": "https://push/msg/9"}})
    adapter = WebPushAdapter(transport=transport)
    receipt = _run(
        adapter.dispatch(
            {"title": "N"},
            {"endpoint": "https://push.example/sub1", "encrypted_body": b"\x00\x01"},
            credential="vapid t=jwt, k=pub",
        )
    )
    call = transport.calls[0]
    assert call["url"] == "https://push.example/sub1"
    assert call["headers"]["content-encoding"] == "aes128gcm"
    assert receipt.external_id == "webpush:https://push/msg/9"


def test_web_push_without_location_still_real_id(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(201, {"_headers": {}})
    adapter = WebPushAdapter(transport=transport)
    receipt = _run(
        adapter.dispatch(
            {"title": "N"},
            {"endpoint": "https://push.example/sub1"},
            credential="vapid t=jwt",
        )
    )
    assert receipt.external_id.startswith("webpush:accepted:")
    assert not receipt.external_id.startswith("sim-")


# ── Email real path ─────────────────────────────────────────────────────────

def test_email_maps_message_id(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    transport = _stub_transport(200, {"MessageId": "0000-ses-id"})
    adapter = EmailAdapter(transport=transport)
    receipt = _run(
        adapter.dispatch(
            {"title": "Subject", "body": "Hello"},
            {"to": "u@example.com", "sender": "no-reply@aether.app", "region": "us-west-2"},
            credential="sigv4",
        )
    )
    call = transport.calls[0]
    assert call["url"] == "https://email.us-west-2.amazonaws.com/"
    assert b"SendEmail" in call["body"]
    assert receipt.external_id == "ses:0000-ses-id"


def test_email_requires_sender(monkeypatch):
    _set_env(monkeypatch, Environment.PRODUCTION)
    adapter = EmailAdapter(transport=_stub_transport(200, {}))
    with pytest.raises(ConfigurationError, match="sender"):
        _run(adapter.dispatch({"title": "S"}, {"to": "u@example.com"}, credential="sigv4"))
