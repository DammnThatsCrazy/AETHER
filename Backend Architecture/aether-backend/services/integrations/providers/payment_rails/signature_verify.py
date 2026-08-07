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
* ``body_hex`` — Coinbase Commerce ``X-CC-Webhook-Signature``: hex
  ``HMAC-SHA256(secret, raw_body)``; no timestamp. (Bridge's real header —
  ``X-Webhook-Signature: t=,v0=`` — is unconfirmed and NOT this scheme; the
  adapter declares a placeholder ``timestamped_hex`` until it is confirmed.)
* ``timestamped_hex`` — a generic ``HMAC-SHA256(secret, f"{ts}.{raw_body}")`` with
  the timestamp supplied out-of-band (used by adapters whose exact native header
  is not yet confirmed; see each adapter's source-of-truth note).
* ``sendgrid_ecdsa`` — SendGrid (Twilio) Event Webhook signing.
  ``X-Twilio-Email-Event-Webhook-Signature`` is a base64 DER-encoded ECDSA
  signature over SHA-256 of ``timestamp + raw_body``; the private key stays with
  Twilio and the stored credential is the account's **public key** (base64, or
  PEM-wrapped). Replay protection is the ``X-Twilio-Email-Event-Webhook-Timestamp``
  freshness window.
* ``customerio_hmac_v0`` — Customer.io reporting webhook
  (``X-CIO-Signature`` + ``X-CIO-Timestamp``): hex
  ``HMAC-SHA256(secret, "v0:{ts}:" + raw_body)``. The ``v0:`` version prefix and
  colon separators are part of the signed string; replay protection is the
  ``X-CIO-Timestamp`` freshness window.
* ``iterable_hmac_query`` — Iterable webhook signing. Iterable signs webhook
  requests with an HMAC-SHA256 built from the webhook signing secret; the
  signature (``signature``) and optional signing timestamp (``ts``) travel in the
  webhook URL's **query params**, not a header (the generic comms route merges
  the request's query params into the headers mapping a native verifier reads).
  The signed string is the raw request body (hex digest, no prefix). Replay
  protection is the ``ts`` query-param freshness window when Iterable includes
  one; otherwise the ``silver_comms_idem`` dedupe carries replay safety.
* ``endpoint_secret`` — no cryptographic signature. Mailchimp (Marketing)
  authenticates with a ``secret`` query parameter in the webhook URL and Postmark
  with URL/Basic-Auth credentials; neither HMACs its body. Both are covered by
  Aether's high-entropy durable ``whe_`` endpoint id, which the route resolves
  server-side before any of this code runs — possession of the endpoint id is the
  authentication. Replay safety relies on the idempotency dedupe downstream,
  never a signature.

All comparisons are constant-time. Secrets, expected digests, and supplied
digests are never logged. Current + previous secrets are tried (rotation
overlap); a match on any returns success.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Iterable, Optional

# Canonical scheme tokens.
STRIPE_COMPOUND = "stripe_compound"
MOONPAY_COMPOUND = "moonpay_compound"
BODY_HEX = "body_hex"
TIMESTAMPED_HEX = "timestamped_hex"
# Comms provider-native schemes (named so manifests state the provider's scheme).
SENDGRID_ECDSA = "sendgrid_ecdsa"
CUSTOMERIO_HMAC_V0 = "customerio_hmac_v0"
ITERABLE_HMAC_QUERY = "iterable_hmac_query"
# Mailchimp (Marketing) and Postmark send no cryptographic signature; the durable
# server-controlled endpoint id in the webhook URL is the credential.
ENDPOINT_SECRET = "endpoint_secret"

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


def _load_ec_public_key(material: str):
    """Load a SendGrid ECDSA public key from base64 DER or PEM-wrapped material."""
    from cryptography.hazmat.primitives.serialization import (
        load_der_public_key,
        load_pem_public_key,
    )

    if material.startswith("-----BEGIN"):
        return load_pem_public_key(material.encode("utf-8"))
    return load_der_public_key(base64.b64decode(material, validate=True))


def _verify_one_sendgrid_ecdsa(
    public_key_b64: str,
    payload: bytes,
    signature: str,
    timestamp: Optional[str],
    *,
    now_epoch: Optional[int],
    tolerance_s: int,
) -> VerificationResult:
    """SendGrid Event Webhook signed-payload verification (ECDSA, not HMAC).

    The stored credential is SendGrid's *public* key (the private key never
    leaves Twilio), so a leaked "secret" does not enable forgery — the public key
    can only verify. Signature bytes are base64 DER; the digest is
    SHA-256(``timestamp`` + raw body). Any decode/verify failure is ``mismatch``
    (never raised), so a malformed header is simply a denial.
    """
    if not timestamp:
        return VerificationResult(False, "bad_format")
    if not _timestamp_fresh(timestamp, now_epoch, tolerance_s):
        return VerificationResult(False, "stale")
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        sig_bytes = base64.b64decode(signature.strip(), validate=True)
        key = _load_ec_public_key(public_key_b64.strip())
        key.verify(
            sig_bytes,
            timestamp.encode("utf-8") + payload,
            ec.ECDSA(hashes.SHA256()),
        )
        return VerificationResult.verified()
    except Exception:
        return VerificationResult(False, "mismatch")


def _verify_one_customerio_v0(
    secret: str,
    payload: bytes,
    signature: str,
    timestamp: Optional[str],
    *,
    now_epoch: Optional[int],
    tolerance_s: int,
) -> VerificationResult:
    """Customer.io reporting webhook — ``X-CIO-Signature``.

    The signed string is ``v0:{X-CIO-Timestamp}:{raw_body}`` — the ``v0:`` prefix
    and colon separators are part of the payload, not a header prefix to strip.
    Replay protection is the ``X-CIO-Timestamp`` freshness window.
    """
    if not timestamp:
        return VerificationResult(False, "bad_format")
    if not _timestamp_fresh(timestamp, now_epoch, tolerance_s):
        return VerificationResult(False, "stale")
    signed = f"v0:{timestamp}:".encode("utf-8") + payload
    expected = _hmac_hex(secret, signed)
    provided = signature.strip()
    for prefix in ("v1=", "s=", "sha256="):
        provided = provided[len(prefix):] if provided.startswith(prefix) else provided
    if hmac.compare_digest(expected, provided.lower()):
        return VerificationResult.verified()
    return VerificationResult(False, "mismatch")


def _verify_one_iterable_query(
    secret: str,
    payload: bytes,
    signature: str,
    *,
    timestamp: Optional[str] = None,
    now_epoch: Optional[int] = None,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> VerificationResult:
    """Iterable webhook signing — ``iterable_hmac_query``.

    Iterable signs webhook requests with an HMAC-SHA256 built from the webhook
    signing secret; the signature (``signature``) and optional signing timestamp
    (``ts``) travel in the webhook URL's query params, not a header. The signed
    string is the raw request body (hex digest, no ``sha256=``/``v1=`` prefix).
    When Iterable includes a ``ts`` query param it is enforced as a replay
    freshness window; otherwise replay safety is the ``silver_comms_idem``
    dedupe downstream.
    """
    provided = signature.strip()
    for prefix in ("sha256=", "v1=", "s="):
        provided = provided[len(prefix):] if provided.startswith(prefix) else provided
    if not provided:
        return VerificationResult(False, "bad_format")
    if timestamp is not None and not _timestamp_fresh(timestamp, now_epoch, tolerance_s):
        return VerificationResult(False, "stale")
    expected = _hmac_hex(secret, payload)
    if hmac.compare_digest(expected, provided.lower()):
        return VerificationResult.verified()
    return VerificationResult(False, "mismatch")


def _verify_one_endpoint_secret() -> VerificationResult:
    """No cryptographic signature — possession of the durable endpoint id.

    Mailchimp (Marketing) authenticates with a ``secret`` query parameter in the
    webhook URL and Postmark with URL/Basic-Auth credentials; neither HMACs its
    body. Aether's high-entropy, revocable ``whe_`` endpoint id is the same
    mechanism, and the route already resolved it server-side before this runs.
    There is nothing to compare — a request that reached this point possessed the
    endpoint id. Replay safety is the idempotency dedupe downstream, never a
    signature.
    """
    return VerificationResult.verified()


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
    # endpoint_secret carries no signature — the durable endpoint id (resolved
    # server-side by the route) is the authentication, so there is nothing to
    # compare and no secret to consult.
    if scheme == ENDPOINT_SECRET:
        return _verify_one_endpoint_secret()
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
        elif scheme == SENDGRID_ECDSA:
            res = _verify_one_sendgrid_ecdsa(
                secret, payload, signature, timestamp,
                now_epoch=now_epoch, tolerance_s=tolerance_s,
            )
        elif scheme == CUSTOMERIO_HMAC_V0:
            res = _verify_one_customerio_v0(
                secret, payload, signature, timestamp,
                now_epoch=now_epoch, tolerance_s=tolerance_s,
            )
        elif scheme == ITERABLE_HMAC_QUERY:
            res = _verify_one_iterable_query(
                secret, payload, signature, timestamp=timestamp,
                now_epoch=now_epoch, tolerance_s=tolerance_s,
            )
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
    "SENDGRID_ECDSA",
    "CUSTOMERIO_HMAC_V0",
    "ITERABLE_HMAC_QUERY",
    "ENDPOINT_SECRET",
    "DEFAULT_TOLERANCE_S",
    "VerificationResult",
    "verify_signature",
]
