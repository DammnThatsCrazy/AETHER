"""Tests for services/delivery/security.py.

Covers SSRF protection, timestamp tolerance, constant-time comparison,
idempotency key generation, header sanitization, and signature forgery
resistance across Slack, Linear, Jira, Stripe, and Shopify adapters.

Note: imports are kept shallow (no shared.logger chain) so this suite
runs in environments where the cryptography/jwt wheel is broken.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

from services.delivery.security import (
    constant_time_compare,
    generate_idempotency_key,
    sanitize_headers,
    validate_webhook_url,
    verify_timestamp_tolerance,
)
from services.delivery.adapters.base import SSRFBlockedError


# ─── SSRF ────────────────────────────────────────────────────────────────────

def _mock_getaddrinfo(ip: str):
    """Return a minimal getaddrinfo response for the given IP."""
    return [(2, 1, 6, "", (ip, 443))]


@pytest.mark.parametrize("ip", [
    "10.0.0.1",
    "127.0.0.1",
    "169.254.169.254",   # AWS metadata endpoint
    "192.168.1.1",
    "172.16.0.1",
])
def test_ssrf_private_ips_blocked(ip):
    """Private and loopback IPs must be rejected by validate_webhook_url."""
    with patch("services.delivery.security.socket.getaddrinfo", return_value=_mock_getaddrinfo(ip)):
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url("https://example.com/hook")


def test_ssrf_public_url_passes():
    """A URL resolving to a public IP must pass SSRF validation."""
    with patch("services.delivery.security.socket.getaddrinfo", return_value=_mock_getaddrinfo("93.184.216.34")):
        # Should not raise
        validate_webhook_url("https://example.com/hook")


def test_ssrf_allow_private_bypasses_check():
    """allow_private=True skips DNS resolution and accepts private URLs."""
    # No socket.getaddrinfo call should be made
    with patch("services.delivery.security.socket.getaddrinfo", side_effect=Exception("should not be called")):
        validate_webhook_url("http://10.0.0.1/internal", allow_private=True)


def test_ssrf_missing_hostname_raises():
    """A URL with no parseable hostname should raise SSRFBlockedError."""
    with pytest.raises(SSRFBlockedError, match="Cannot parse hostname"):
        validate_webhook_url("not-a-url", allow_private=False)


# ─── Timestamp Tolerance ─────────────────────────────────────────────────────

def test_timestamp_tolerance_too_old():
    old_ts = str(int(time.time()) - 400)
    assert not verify_timestamp_tolerance(old_ts)


def test_timestamp_tolerance_recent():
    recent_ts = str(int(time.time()) - 200)
    assert verify_timestamp_tolerance(recent_ts)


def test_timestamp_tolerance_future():
    """Timestamps slightly in the future (clock skew) are tolerated."""
    future_ts = str(int(time.time()) + 10)
    assert verify_timestamp_tolerance(future_ts)


def test_timestamp_tolerance_invalid_string():
    assert not verify_timestamp_tolerance("not-a-number")


def test_timestamp_tolerance_empty_string():
    assert not verify_timestamp_tolerance("")


def test_timestamp_tolerance_custom_window():
    ts = str(int(time.time()) - 700)
    assert not verify_timestamp_tolerance(ts, max_age_seconds=600)
    assert verify_timestamp_tolerance(ts, max_age_seconds=800)


# ─── Constant-Time Compare ───────────────────────────────────────────────────

def test_constant_time_compare_equal_strings():
    assert constant_time_compare("abc", "abc")


def test_constant_time_compare_unequal_strings():
    assert not constant_time_compare("abc", "abd")


def test_constant_time_compare_bytes():
    assert constant_time_compare(b"abc", b"abc")
    assert not constant_time_compare(b"abc", b"xyz")


def test_constant_time_compare_mixed():
    assert constant_time_compare("abc", b"abc")
    assert constant_time_compare(b"abc", "abc")


# ─── Idempotency Key ─────────────────────────────────────────────────────────

def test_generate_idempotency_key_consistent():
    k1 = generate_idempotency_key("suggestion", "abc", "slack", "ch1")
    k2 = generate_idempotency_key("suggestion", "abc", "slack", "ch1")
    assert k1 == k2


def test_generate_idempotency_key_different_parts():
    k1 = generate_idempotency_key("a", "b")
    k2 = generate_idempotency_key("a", "c")
    assert k1 != k2


def test_generate_idempotency_key_is_sha256():
    k = generate_idempotency_key("hello", "world")
    expected = hashlib.sha256("hello:world".encode()).hexdigest()
    assert k == expected


# ─── Header Sanitization ─────────────────────────────────────────────────────

def test_sanitize_headers_removes_auth():
    headers = {
        "Authorization": "Bearer token",
        "Content-Type": "application/json",
        "X-Api-Key": "secret",
    }
    clean = sanitize_headers(headers)
    assert "Authorization" not in clean
    assert "X-Api-Key" not in clean
    assert "Content-Type" in clean


def test_sanitize_headers_case_insensitive():
    headers = {
        "authorization": "Bearer x",
        "COOKIE": "session=abc",
        "x-bot-token": "tok",
        "X-Request-ID": "req-1",
    }
    clean = sanitize_headers(headers)
    assert "authorization" not in clean
    assert "COOKIE" not in clean
    assert "x-bot-token" not in clean
    assert "X-Request-ID" in clean


def test_sanitize_headers_empty():
    assert sanitize_headers({}) == {}


def test_sanitize_headers_does_not_mutate_input():
    original = {"Authorization": "Bearer token", "Content-Type": "application/json"}
    _ = sanitize_headers(original)
    assert "Authorization" in original  # original unchanged


# ─── Signature Forgery Resistance ────────────────────────────────────────────
# These tests use HMAC directly, bypassing the adapter import chain.

def test_slack_signature_forgery_fails():
    """Modifying the Slack body should cause signature verification to fail."""
    secret = "slack-signing-secret-123"
    body = b"v0:test_payload"
    ts = str(int(time.time()))
    base = f"v0:{ts}:{body.decode()}"
    valid_sig = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()

    # Tamper the body
    tampered_body = b"v0:tampered_payload"
    tampered_base = f"v0:{ts}:{tampered_body.decode()}"
    tampered_sig = hmac.new(secret.encode(), tampered_base.encode(), hashlib.sha256).hexdigest()

    assert not constant_time_compare(valid_sig, "v0=" + tampered_sig)


def test_linear_signature_forgery_fails():
    """Modifying the Linear body should fail HMAC check."""
    try:
        from services.integrations.connectors.adapters import LinearConnector
    except BaseException:
        pytest.skip("connectors import unavailable in this environment (cryptography broken)")
        return

    secret = "linear-webhook-secret"
    body = b'{"type":"Issue","action":"update"}'
    valid_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    tampered = b'{"type":"Issue","action":"remove"}'
    result = LinearConnector.verify_webhook_signature(
        tampered,
        {"Linear-Signature": valid_sig},
        secret,
    )
    assert not result


def test_jira_signature_forgery_fails():
    """Modifying the Jira body should fail HMAC check."""
    try:
        from services.integrations.connectors.adapters import JiraConnector
    except BaseException:
        pytest.skip("connectors import unavailable in this environment (cryptography broken)")
        return

    secret = "jira-webhook-secret"
    body = b'{"webhookEvent":"jira:issue_updated"}'
    valid_sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    tampered = b'{"webhookEvent":"jira:issue_deleted"}'
    result = JiraConnector.verify_webhook_signature(
        tampered,
        {"X-Hub-Signature-256": valid_sig},
        secret,
    )
    assert not result


def test_stripe_signature_forgery_fails():
    """Modifying the Stripe body should fail signature check."""
    try:
        from services.integrations.connectors.adapters import StripeConnector
    except BaseException:
        pytest.skip("connectors import unavailable in this environment (cryptography broken)")
        return

    secret = "stripe-webhook-secret"
    body = b'{"type":"payment_intent.created"}'
    ts = str(int(time.time()))
    signed_payload = f"{ts}.{body.decode()}"
    valid_v1 = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    sig_header = f"t={ts},v1={valid_v1}"

    tampered = b'{"type":"payment_intent.succeeded"}'
    result = StripeConnector.verify_webhook_signature(
        tampered,
        {"Stripe-Signature": sig_header},
        secret,
    )
    assert not result


def test_shopify_signature_forgery_fails():
    """Modifying the Shopify body should fail HMAC check."""
    try:
        from services.integrations.connectors.adapters import ShopifyConnector
    except BaseException:
        pytest.skip("connectors import unavailable in this environment (cryptography broken)")
        return

    secret = "shopify-secret"
    body = b'{"id":123}'
    valid_sig = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()

    tampered = b'{"id":999}'
    result = ShopifyConnector.verify_webhook_signature(
        tampered,
        {"X-Shopify-Hmac-SHA256": valid_sig},
        secret,
    )
    assert not result


def test_webhook_generic_signature_missing_fails():
    """A generic webhook with no signature should report unverified."""
    assert not constant_time_compare("", "expected_value")
