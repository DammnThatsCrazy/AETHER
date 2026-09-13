"""Per-provider golden signature vectors — frozen, checked-in, adapter-wired.

Unlike ``test_signature_verify.py`` (which builds each signature at test time and
exercises the pure ``verify_signature`` surface), this module pins *frozen* known-
good vectors: every ``signature`` below is a literal string whose HMAC digest was
computed once, offline, and committed. A regression in HMAC construction, header
parsing, or the provider→scheme mapping breaks these vectors even if the same bug
were mirrored in a test-time helper. Each vector is verified through the **real
adapter's** ``native_signature_scheme()`` — so the provider→scheme wiring
(``base.native_signature_scheme``) is locked end to end, not just the raw token.

Confidence per provider (honest, not aspirational):

* ``confirmed`` — the native wire format is documented and implemented:
  - stripe   → ``stripe_compound``  (``Stripe-Signature: t=<ts>,v1=<hex>``)
  - moonpay  → ``moonpay_compound`` (``Moonpay-Signature-V2: t=<ts>,s=<hex>``)
  - coinbase → ``body_hex``         (``X-CC-Webhook-Signature: <hex over raw body>``)
* ``externally_blocked`` — the real provider header could NOT be confirmed against
  provider documentation, so the adapter's *declared* scheme is a placeholder and
  these vectors only lock the declared behaviour, NOT a claim of wire fidelity:
  - bridge — real header is ``X-Webhook-Signature: t=<ts>,v0=<sig>`` (plausibly a
    public-key signature, not a shared-secret HMAC); unconfirmed.
  - privy  — Privy delivers webhooks via Svix (``svix-signature: v1,<base64>`` over
    ``<id>.<ts>.<body>``), which is NOT the declared hex ``timestamped_hex``;
    unconfirmed.
  A follow-up slice must confirm these against provider docs (or a captured live
  delivery) before the pilot treats bridge/privy webhook auth as production-ready.

The ``externally_blocked`` markers here are the source of truth for that gap: a
guard test fails if a blocked provider is silently reclassified without updating
its vector, and another fails if a newly registered adapter has no golden entry.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional

os.environ.setdefault("AETHER_ENV", "local")

from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.signature_verify import (  # noqa: E402
    BODY_HEX,
    MOONPAY_COMPOUND,
    STRIPE_COMPOUND,
    TIMESTAMPED_HEX,
    verify_signature,
)

CONFIRMED = "confirmed"
EXTERNALLY_BLOCKED = "externally_blocked"

# The single frozen timestamp every compound vector was signed at. Compound
# schemes check freshness against ``now_epoch``; the vectors pass ``now_epoch=T``
# so the assertions are deterministic regardless of wall-clock time.
T = 1_700_000_000


@dataclass(frozen=True)
class GoldenVector:
    provider: str
    scheme: str
    confidence: str
    secret: str
    body: bytes
    signature: str            # exact wire value: compound header OR bare hex digest
    timestamp: Optional[str]  # out-of-band ts (timestamped_hex only); else None
    now_epoch: Optional[int]  # compound freshness anchor; None for the others
    note: str


# ── Frozen golden table ──────────────────────────────────────────────────────
# Digests below were precomputed offline as HMAC-SHA256 over the documented
# signed payload for each scheme. DO NOT recompute them from ``body``/``secret``
# in this file — the whole point is that the literal is the oracle.
GOLDEN: tuple[GoldenVector, ...] = (
    GoldenVector(
        provider="stripe",
        scheme=STRIPE_COMPOUND,
        confidence=CONFIRMED,
        secret="whsec_golden_stripe_2024",
        body=b'{"id":"evt_golden_stripe","type":"checkout.session.completed","data":{"object":{"amount_total":4200}}}',
        signature="t=1700000000,v1=2eb40592afe1e8f49d2f76343048f69e015faa6ec824a4d927e745bddb66912c",
        timestamp=None,
        now_epoch=T,
        note="Stripe-Signature compound header, HMAC-SHA256 over f'{t}.{body}'.",
    ),
    GoldenVector(
        provider="moonpay",
        scheme=MOONPAY_COMPOUND,
        confidence=CONFIRMED,
        secret="whsec_golden_moonpay_2024",
        body=b'{"type":"transaction_updated","data":{"id":"mp_tx_golden","status":"completed"}}',
        signature="t=1700000000,s=47b1539e1820cbfbf8853388eb011ff9eddad3356bdebba5c32728e59cd8139f",
        timestamp=None,
        now_epoch=T,
        note="Moonpay-Signature-V2 compound header with s= tag, same construction as Stripe.",
    ),
    GoldenVector(
        provider="coinbase",
        scheme=BODY_HEX,
        confidence=CONFIRMED,
        secret="whsec_golden_coinbase_2024",
        body=b'{"event":{"type":"charge:confirmed","data":{"id":"cb_charge_golden"}}}',
        signature="c22131c1524ba9deb65a6b05f6494d1b97c8c9807bc47cf50b21c88c6c6c1ae7",
        timestamp=None,
        now_epoch=None,
        note="X-CC-Webhook-Signature, bare hex HMAC-SHA256 over the raw body.",
    ),
    GoldenVector(
        provider="bridge",
        scheme=TIMESTAMPED_HEX,
        confidence=EXTERNALLY_BLOCKED,
        secret="whsec_declared_bridge_2024",
        body=b'{"event_type":"funds_received","data":{"id":"bridge_evt_golden"}}',
        signature="c84131fe5a01fe7da84dbfa41fe8842e690835b92512f0e10ee5f77b06a58a82",
        timestamp=str(T),
        now_epoch=None,
        note="DECLARED timestamped_hex only; real Bridge header (t=,v0=) unconfirmed.",
    ),
    GoldenVector(
        provider="privy",
        scheme=TIMESTAMPED_HEX,
        confidence=EXTERNALLY_BLOCKED,
        secret="whsec_declared_privy_2024",
        body=b'{"type":"funding.completed","data":{"id":"privy_evt_golden"}}',
        signature="bdcb980ef1de7f015fe140b3089214fd5b97892bd855181e67c8f5811751ea50",
        timestamp=str(T),
        now_epoch=None,
        note="DECLARED timestamped_hex only; real Privy delivery is Svix base64.",
    ),
)

_BY_PROVIDER = {v.provider: v for v in GOLDEN}


def _verify(v: GoldenVector, *, secret: Optional[str] = None, body: Optional[bytes] = None,
            signature: Optional[str] = None):
    return verify_signature(
        v.scheme,
        [secret if secret is not None else v.secret],
        body if body is not None else v.body,
        signature if signature is not None else v.signature,
        timestamp=v.timestamp,
        now_epoch=v.now_epoch,
    )


# ── Wiring: provider → native scheme (locks base.native_signature_scheme) ────
def test_adapter_native_scheme_matches_golden():
    """Every golden vector's scheme is exactly what the real adapter resolves."""
    for v in GOLDEN:
        adapter = ADAPTERS[v.provider]
        assert adapter.native_signature_scheme() == v.scheme, (
            f"{v.provider}: adapter resolves {adapter.native_signature_scheme()!r} "
            f"but golden vector pins {v.scheme!r}"
        )


def test_confirmed_scheme_shapes():
    """Confirmed providers resolve to their documented scheme families."""
    assert ADAPTERS["stripe"].native_signature_scheme() == STRIPE_COMPOUND
    assert ADAPTERS["moonpay"].native_signature_scheme() == MOONPAY_COMPOUND
    assert ADAPTERS["coinbase"].native_signature_scheme() == BODY_HEX


# ── Golden lock: each frozen vector verifies ─────────────────────────────────
def test_golden_vectors_verify():
    for v in GOLDEN:
        res = _verify(v)
        assert res.ok, f"{v.provider} golden vector failed to verify: {res.reason}"


# ── Tamper / wrong-secret: each frozen vector must reject the corruption ─────
def test_golden_body_tamper_rejected():
    for v in GOLDEN:
        tampered = v.body[:-2] + (b"0}" if not v.body.endswith(b"0}") else b"1}")
        res = _verify(v, body=tampered)
        assert not res.ok and res.reason == "mismatch", (
            f"{v.provider}: one-byte body tamper was NOT rejected ({res.reason})"
        )


def test_golden_wrong_secret_rejected():
    for v in GOLDEN:
        res = _verify(v, secret=v.secret + "_rotated_away")
        assert not res.ok and res.reason == "mismatch", (
            f"{v.provider}: wrong secret was NOT rejected ({res.reason})"
        )


# ── Scheme isolation: a header for one scheme must not verify under another ──
def test_cross_scheme_confusion_rejected():
    stripe = _BY_PROVIDER["stripe"]
    moonpay = _BY_PROVIDER["moonpay"]
    coinbase = _BY_PROVIDER["coinbase"]

    # A Stripe compound header must NOT verify under body_hex (the header string
    # is not a bare hex digest of the body).
    assert not verify_signature(
        BODY_HEX, [stripe.secret], stripe.body, stripe.signature
    ).ok
    # A MoonPay compound header (s= tag) must NOT verify under body_hex either.
    assert not verify_signature(
        BODY_HEX, [moonpay.secret], moonpay.body, moonpay.signature
    ).ok
    # A Coinbase bare-hex signature must NOT verify under stripe_compound: with
    # no ``t=`` the parsed timestamp is None and the signed payload differs.
    assert not verify_signature(
        STRIPE_COMPOUND, [coinbase.secret], coinbase.body, coinbase.signature,
        now_epoch=None,
    ).ok


# ── Honesty guards: blocked stays blocked, coverage stays complete ───────────
def test_externally_blocked_providers_are_flagged():
    """bridge/privy are declared-only; the vector must say so, and the adapter's
    declared scheme must still be the placeholder timestamped_hex. If a follow-up
    confirms the real wire format, it must update BOTH the vector and this guard.
    """
    for provider in ("bridge", "privy"):
        v = _BY_PROVIDER[provider]
        assert v.confidence == EXTERNALLY_BLOCKED, (
            f"{provider} was reclassified away from externally_blocked without a "
            "confirmed provider-native vector — update the golden vector, not this guard."
        )
        assert v.scheme == TIMESTAMPED_HEX
        assert ADAPTERS[provider].signature_scheme == TIMESTAMPED_HEX


def test_every_registered_provider_has_golden_coverage():
    """No adapter may ship without a golden entry (confirmed or externally_blocked)."""
    missing = set(ADAPTERS) - set(_BY_PROVIDER)
    assert not missing, f"providers with no golden signature vector: {sorted(missing)}"


def test_confirmed_providers_exist():
    """Sanity: the three confirmed providers are present and marked confirmed."""
    confirmed = {v.provider for v in GOLDEN if v.confidence == CONFIRMED}
    assert confirmed == {"stripe", "moonpay", "coinbase"}
