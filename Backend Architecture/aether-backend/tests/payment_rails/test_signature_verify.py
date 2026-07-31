"""Provider-native signature verification — golden vectors + failure modes.

Signatures are built here with the *documented* algorithm (raw ``hmac``), not the
module under test, so a parsing bug (like the old ``removeprefix('v1=')`` no-op on
a ``t=,v1=`` header) is actually caught.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.integrations.providers.payment_rails.signature_verify import (  # noqa: E402
    BODY_HEX,
    MOONPAY_COMPOUND,
    STRIPE_COMPOUND,
    TIMESTAMPED_HEX,
    verify_signature,
)

SECRET = "whsec_test_abc123"
PAYLOAD = b'{"id":"evt_1","type":"checkout.session.completed","amount":1000}'
NOW = 1_700_000_000


def _hmac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _stripe_header(secret: str, payload: bytes, t: int, tag: str = "v1") -> str:
    digest = _hmac(secret, f"{t}.".encode() + payload)
    return f"t={t},{tag}={digest}"


# ── Stripe compound ─────────────────────────────────────────────────────────
def test_stripe_valid():
    header = _stripe_header(SECRET, PAYLOAD, NOW)
    assert verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, header, now_epoch=NOW).ok


def test_stripe_wrong_secret():
    header = _stripe_header("whsec_other", PAYLOAD, NOW)
    r = verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, header, now_epoch=NOW)
    assert not r.ok and r.reason == "mismatch"


def test_stripe_body_tampered_one_byte():
    header = _stripe_header(SECRET, PAYLOAD, NOW)
    tampered = PAYLOAD[:-2] + b"9}"
    r = verify_signature(STRIPE_COMPOUND, [SECRET], tampered, header, now_epoch=NOW)
    assert not r.ok and r.reason == "mismatch"


def test_stripe_stale_timestamp():
    old = NOW - 10_000
    header = _stripe_header(SECRET, PAYLOAD, old)
    r = verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, header, now_epoch=NOW, tolerance_s=300)
    assert not r.ok and r.reason == "stale"


def test_stripe_missing_and_malformed():
    assert verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, None, now_epoch=NOW).reason == "no_signature"
    # a bare hex digest with no t=/v1= structure must not verify (the old bug)
    bare = _hmac(SECRET, PAYLOAD)
    r = verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, bare, now_epoch=NOW)
    assert not r.ok and r.reason in ("bad_format", "stale", "mismatch")


def test_stripe_multiple_v1_rotation():
    t = NOW
    good = _hmac(SECRET, f"{t}.".encode() + PAYLOAD)
    header = f"t={t},v1=deadbeef,v1={good}"  # first is wrong, second valid
    assert verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, header, now_epoch=NOW).ok


def test_stripe_previous_secret_in_overlap():
    header = _stripe_header("whsec_prev", PAYLOAD, NOW)
    # active first, previous second — signed with previous → still verifies
    assert verify_signature(STRIPE_COMPOUND, ["whsec_active", "whsec_prev"], PAYLOAD, header, now_epoch=NOW).ok
    # signed with a secret NOT in the set → rejected
    header2 = _stripe_header("whsec_expired", PAYLOAD, NOW)
    assert not verify_signature(STRIPE_COMPOUND, ["whsec_active", "whsec_prev"], PAYLOAD, header2, now_epoch=NOW).ok


def test_stripe_no_tolerance_when_now_none():
    header = _stripe_header(SECRET, PAYLOAD, NOW - 10_000)
    # now_epoch=None opts out of the freshness check
    assert verify_signature(STRIPE_COMPOUND, [SECRET], PAYLOAD, header, now_epoch=None).ok


# ── MoonPay compound (s= tag) ───────────────────────────────────────────────
def test_moonpay_compound_valid():
    header = _stripe_header(SECRET, PAYLOAD, NOW, tag="s")
    assert verify_signature(MOONPAY_COMPOUND, [SECRET], PAYLOAD, header, now_epoch=NOW).ok


# ── body_hex (Coinbase/Bridge) ──────────────────────────────────────────────
def test_body_hex_valid_and_invalid():
    sig = _hmac(SECRET, PAYLOAD)
    assert verify_signature(BODY_HEX, [SECRET], PAYLOAD, sig).ok
    assert not verify_signature(BODY_HEX, [SECRET], PAYLOAD + b"x", sig).ok
    # a Stripe-style compound header must NOT verify under body_hex
    assert not verify_signature(BODY_HEX, [SECRET], PAYLOAD, f"t={NOW},v1={sig}").ok


# ── timestamped_hex ─────────────────────────────────────────────────────────
def test_timestamped_hex_valid_and_missing_ts():
    ts = str(NOW)
    sig = _hmac(SECRET, f"{ts}.".encode() + PAYLOAD)
    assert verify_signature(TIMESTAMPED_HEX, [SECRET], PAYLOAD, sig, timestamp=ts).ok
    assert not verify_signature(TIMESTAMPED_HEX, [SECRET], PAYLOAD, sig, timestamp=None).ok


def test_no_secret_and_unknown_scheme():
    header = _stripe_header(SECRET, PAYLOAD, NOW)
    assert verify_signature(STRIPE_COMPOUND, [], PAYLOAD, header, now_epoch=NOW).reason == "no_secret"
    assert verify_signature("bogus", [SECRET], PAYLOAD, header, now_epoch=NOW).reason == "unknown_scheme"
