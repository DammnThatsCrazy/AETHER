"""Comms provider-native webhook signature schemes — golden vectors.

Signatures are built with the *documented* provider algorithm (raw ``hmac`` /
raw ECDSA signing), not the module under test, so a parsing mistake is actually
caught.

Provider facts verified against primary docs 2026-08-06:

* SendGrid (Twilio) Event Webhook signing is **ECDSA**, not HMAC — the
  ``X-Twilio-Email-Event-Webhook-Signature`` header is a base64 DER signature
  over SHA-256(``timestamp`` + raw body), verified with the account's public key
  (Twilio keeps the private key).
* Customer.io reporting webhooks sign ``HMAC-SHA256("v0:{timestamp}:{raw_body}")``
  as hex in ``X-CIO-Signature`` with the timestamp in ``X-CIO-Timestamp``.
* Mailchimp (Marketing) and Postmark send **no** cryptographic signature —
  authentication is the secret embedded in the webhook URL, which Aether covers
  with the server-controlled durable ``whe_`` endpoint id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.integrations.providers.payment_rails.signature_verify import (  # noqa: E402
    CUSTOMERIO_HMAC_V0,
    ENDPOINT_SECRET,
    SENDGRID_ECDSA,
    verify_signature,
)

SECRET = "whsec_test_abc123"
PAYLOAD = b'{"type":"event_received","id":"evt_9"}'
NOW = 1_700_000_000


def _hmac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


# ── sendgrid_ecdsa (X-Twilio-Email-Event-Webhook-Signature, ECDSA) ────────────
def _ec_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    public_der = private.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, base64.b64encode(public_der).decode()


def _ecdsa_sig(private, ts: int, payload: bytes) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    # SendGrid signs SHA-256(``timestamp`` + raw body) — concatenated, no separator
    sig = private.sign(f"{ts}".encode() + payload, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()


def test_sendgrid_ecdsa_valid():
    private, public_b64 = _ec_keypair()
    sig = _ecdsa_sig(private, NOW, PAYLOAD)
    r = verify_signature(
        SENDGRID_ECDSA, [public_b64], PAYLOAD, sig,
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    )
    assert r.ok


def test_sendgrid_ecdsa_tampered_stale_and_wrong_key():
    private, public_b64 = _ec_keypair()
    sig = _ecdsa_sig(private, NOW, PAYLOAD)
    # tampered body
    assert not verify_signature(
        SENDGRID_ECDSA, [public_b64], PAYLOAD + b"x", sig,
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    ).ok
    # stale timestamp (sig over a different ts; freshness rejects regardless)
    old = _ecdsa_sig(private, NOW - 10_000, PAYLOAD)
    assert not verify_signature(
        SENDGRID_ECDSA, [public_b64], PAYLOAD, old,
        timestamp=str(NOW - 10_000), now_epoch=NOW, tolerance_s=300,
    ).ok
    # wrong public key cannot verify
    _, other_public = _ec_keypair()
    assert not verify_signature(
        SENDGRID_ECDSA, [other_public], PAYLOAD, sig,
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    ).ok
    # malformed base64 signature is a denial, never a raise
    assert not verify_signature(
        SENDGRID_ECDSA, [public_b64], PAYLOAD, "!!!not-base64!!!",
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    ).ok
    # missing timestamp header is a denial
    assert not verify_signature(
        SENDGRID_ECDSA, [public_b64], PAYLOAD, sig, timestamp=None
    ).ok


# ── customerio_hmac_v0 (X-CIO-Signature / X-CIO-Timestamp) ────────────────────
def _cio_sig(secret: str, payload: bytes, ts: int) -> str:
    return _hmac(secret, f"v0:{ts}:".encode() + payload)


def test_customerio_v0_valid():
    sig = _cio_sig(SECRET, PAYLOAD, NOW)
    assert verify_signature(
        CUSTOMERIO_HMAC_V0, [SECRET], PAYLOAD, sig,
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    ).ok


def test_customerio_v0_tampered_stale_and_missing_ts():
    sig = _cio_sig(SECRET, PAYLOAD, NOW)
    assert not verify_signature(
        CUSTOMERIO_HMAC_V0, [SECRET], PAYLOAD + b"x", sig,
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    ).ok
    old = _cio_sig(SECRET, PAYLOAD, NOW - 10_000)
    assert not verify_signature(
        CUSTOMERIO_HMAC_V0, [SECRET], PAYLOAD, old,
        timestamp=str(NOW - 10_000), now_epoch=NOW, tolerance_s=300,
    ).ok
    assert not verify_signature(
        CUSTOMERIO_HMAC_V0, [SECRET], PAYLOAD, sig, timestamp=None
    ).ok
    # the legacy ts.body construction must NOT verify — v0: prefix and colons
    # are part of the signed string
    legacy = _hmac(SECRET, f"{NOW}.".encode() + PAYLOAD)
    assert not verify_signature(
        CUSTOMERIO_HMAC_V0, [SECRET], PAYLOAD, legacy,
        timestamp=str(NOW), now_epoch=NOW, tolerance_s=300,
    ).ok


# ── endpoint_secret (Mailchimp Marketing / Postmark — no signature) ───────────
def test_endpoint_secret_verifies_with_no_signature():
    # possession of the durable endpoint id (resolved server-side by the route)
    # is the authentication; there is no header to compare
    assert verify_signature(ENDPOINT_SECRET, [SECRET], PAYLOAD, None).ok
    assert verify_signature(ENDPOINT_SECRET, [], PAYLOAD, "").ok


def test_unknown_scheme_fails_closed():
    assert verify_signature("nonsense_scheme", [SECRET], PAYLOAD, "x").reason == "unknown_scheme"
    # the old (incorrect) comms scheme names no longer verify as aliases
    assert verify_signature("sendgrid_timestamped_hex", [SECRET], PAYLOAD, "x").reason == "unknown_scheme"
    assert verify_signature("postmark_token", [SECRET], PAYLOAD, SECRET).reason == "unknown_scheme"
