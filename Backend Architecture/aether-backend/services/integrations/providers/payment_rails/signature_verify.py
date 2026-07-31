"""Provider-native webhook signature verification.

The previous generic verifier treated every provider as ``HMAC(secret, payload)``
or ``HMAC(secret, f"{ts}.{payload}")`` and stripped a ``v1=`` prefix — which can
NEVER verify a real Stripe signature, whose header is a compound
``t=<ts>,v1=<hex>[,v1=<hex>...]`` value (the ``removeprefix("v1=")`` was a no-op
because the header starts with ``t=``). This module implements each provider's
documented scheme explicitly, in a small pure surface that is golden-vector
testable (no dependence on the same helper that produced the signature).

Schemes (each provider adapter declares ``signature_scheme``):

* ``stripe_compound`` — Stripe. Header ``Stripe-Signature: t=<unix>,v1=<hexmac>``
  (possibly several ``v1`` values during a secret rotation). Signed payload is
  ``f"{t}.{raw_body}"``; ``t`` inside the header is the timestamp (no separate
  header). Tolerance is checked against ``t``.
* ``moonpay_compound`` — MoonPay ``Moonpay-Signature-V2: t=<unix>,s=<hexmac>``.
  Same construction as Stripe with an ``s`` tag instead of ``v1``.
* ``body_hex`` — Coinbase Commerce ``X-CC-Webhook-Signature`` (and Bridge):
  hex ``HMAC-SHA256(secret, raw_body)``; no timestamp.
* ``timestamped_hex`` — a generic ``HMAC-SHA256(secret, f"{ts}.{raw_body}")`` with
  the timestamp supplied out-of-band (used by adapters whose exact native header
  is not yet confirmed; see each adapter's source-of-truth note).

All comparisons are constant-time. Secrets, expected digests, and supplied
digests are never logged. Current + previous secrets are tried (rotation
overlap); a match on any returns success.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Iterable, Optional

# Canonical scheme tokens.
STRIPE_COMPOUND = "stripe_compound"
MOONPAY_COMPOUND = "moonpay_compound"
BODY_HEX = "body_hex"
TIMESTAMPED_HEX = "timestamped_hex"

DEFAULT_TOLERANCE_S = 300


@dataclass(frozen=True)
class VerificationResult:
    """Typed result with a safe (secret-free) reason code."""

    ok: bool
    reason: str  # verified | no_signature | no_secret | bad_format | mismatch | stale | unknown_scheme

    @classmethod
    def verified(cls) -> "VerificationResult":
        return cls(True, "verified")


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _parse_compound(header: str) -> tuple[Optional[str], list[str], str]:
    """Parse ``t=<ts>,<tag>=<hex>[,<tag>=<hex>]`` → (t, [digests], tag).

    Accepts either ``v1`` (Stripe) or ``s`` (MoonPay) digest tags; returns the
    timestamp, every digest under the digest tag, and which tag was seen.
    """
    t: Optional[str] = None
    v1: list[str] = []
    s: list[str] = []
    for part in header.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key == "t":
            t = value
        elif key == "v1":
            v1.append(value)
        elif key == "s":
            s.append(value)
    if v1:
        return t, v1, "v1"
    return t, s, "s"


def _timestamp_fresh(t: Optional[str], now_epoch: Optional[int], tolerance_s: int) -> bool:
    if now_epoch is None:
        return True  # caller opted out of tolerance checking
    if not t:
        return False
    try:
        ts = int(float(t))
    except (ValueError, TypeError):
        return False
    return abs(now_epoch - ts) <= tolerance_s


def _verify_one_compound(
    secret: str,
    payload: bytes,
    header: str,
    *,
    now_epoch: Optional[int],
    tolerance_s: int,
) -> VerificationResult:
    t, digests, _tag = _parse_compound(header)
    if not digests:
        return VerificationResult(False, "bad_format")
    if not _timestamp_fresh(t, now_epoch, tolerance_s):
        return VerificationResult(False, "stale")
    signed = f"{t}.".encode("utf-8") + payload
    expected = _hmac_hex(secret, signed)
    for provided in digests:
        if hmac.compare_digest(expected, provided.strip().lower()):
            return VerificationResult.verified()
    return VerificationResult(False, "mismatch")


def _verify_one_body_hex(secret: str, payload: bytes, signature: str) -> VerificationResult:
    provided = signature.strip()
    for prefix in ("sha256=", "v1=", "s="):
        provided = provided[len(prefix):] if provided.startswith(prefix) else provided
    expected = _hmac_hex(secret, payload)
    if hmac.compare_digest(expected, provided.lower()):
        return VerificationResult.verified()
    return VerificationResult(False, "mismatch")


def _verify_one_timestamped_hex(
    secret: str, payload: bytes, signature: str, timestamp: Optional[str]
) -> VerificationResult:
    if not timestamp:
        return VerificationResult(False, "bad_format")
    signed = f"{timestamp}.".encode("utf-8") + payload
    expected = _hmac_hex(secret, signed)
    provided = signature.strip()
    for prefix in ("v1=", "s=", "sha256="):
        provided = provided[len(prefix):] if provided.startswith(prefix) else provided
    if hmac.compare_digest(expected, provided.lower()):
        return VerificationResult.verified()
    return VerificationResult(False, "mismatch")


def verify_signature(
    scheme: str,
    secrets: Iterable[str],
    payload: bytes,
    signature: Optional[str],
    *,
    timestamp: Optional[str] = None,
    now_epoch: Optional[int] = None,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> VerificationResult:
    """Verify ``signature`` over exact ``payload`` bytes under ``scheme``.

    ``secrets`` is the ordered set of acceptable secrets (active first, then a
    valid previous secret during a rotation overlap). Any match succeeds.
    """
    secrets = [s for s in secrets if s]
    if not signature:
        return VerificationResult(False, "no_signature")
    if not secrets:
        return VerificationResult(False, "no_secret")

    last = VerificationResult(False, "mismatch")
    for secret in secrets:
        if scheme == STRIPE_COMPOUND or scheme == MOONPAY_COMPOUND:
            res = _verify_one_compound(
                secret, payload, signature, now_epoch=now_epoch, tolerance_s=tolerance_s
            )
        elif scheme == BODY_HEX:
            res = _verify_one_body_hex(secret, payload, signature)
        elif scheme == TIMESTAMPED_HEX:
            res = _verify_one_timestamped_hex(secret, payload, signature, timestamp)
        else:
            return VerificationResult(False, "unknown_scheme")
        if res.ok:
            return res
        last = res
    return last


__all__ = [
    "STRIPE_COMPOUND",
    "MOONPAY_COMPOUND",
    "BODY_HEX",
    "TIMESTAMPED_HEX",
    "DEFAULT_TOLERANCE_S",
    "VerificationResult",
    "verify_signature",
]
