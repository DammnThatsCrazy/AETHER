"""Signed agent events: proof of who reported an edge, not just that a deployment exists.

A deployment may register an Ed25519 public key. The agent then signs each event with
the private key, which Aether never holds, and an event whose signature verifies is
recorded as ``attested``. Without this, a deployment id only shows the id is valid,
because no ingest credential is bound to a deployment.

The signature covers the event's identity and a hash of its properties and lineage
context, so it cannot be reused for another event or edge. Twin: ``attestAgentEvent`` in ``packages/sdk/server/src/agent-telemetry.ts``.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from decimal import Decimal
from typing import Any, Mapping, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ATTESTATION_VERSION = "aether.agent-attestation.v1"
_PUBLIC_KEY_BYTES = 32
_SIGNATURE_BYTES = 64


def _decode(value: str, expected: int) -> Optional[bytes]:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None
    return raw if len(raw) == expected else None


def is_valid_public_key(value: str) -> bool:
    return _decode(value, _PUBLIC_KEY_BYTES) is not None


def _js_number(value: float | int) -> str:
    """ECMAScript Number::toString, which ``JSON.stringify`` uses.

    The SDK signs ``JSON.stringify`` output, so the backend must produce the same
    bytes for the same parsed number: ``0.000001`` (not ``1e-06``),
    ``1.2345678901234568e+20`` as ``123456789012345680000``, ``1e-7`` as
    ``1e-7``, integral floats without ``.0``, and ``null`` for non-finite values.
    """
    if isinstance(value, int) and abs(value) < 2**53:
        return str(value)
    try:
        number = float(value)
    except OverflowError:
        # JSON.parse reads an integer this large as Infinity, which
        # JSON.stringify writes as null; never let it abort a batch.
        return "null"
    if not math.isfinite(number):
        return "null"
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    # repr() yields the shortest round-tripping digits, as ECMAScript requires.
    digits_tuple, exponent = Decimal(repr(abs(number))).normalize().as_tuple()[1:]
    digits = "".join(str(d) for d in digits_tuple)
    k = len(digits)
    n = exponent + k  # value = 0.<digits> x 10**n
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mantissa = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        text = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + text


def _utf16_key(key: str) -> bytes:
    return key.encode("utf-16-be")  # JavaScript sorts object keys by UTF-16 code units


def _canonical_json(value: Any) -> str:
    """Byte-for-byte twin of ``canonicalJson`` in packages/sdk/server/src/agent-telemetry.ts."""
    if isinstance(value, Mapping):
        items = sorted(((str(k), v) for k, v in value.items()), key=lambda kv: _utf16_key(kv[0]))
        return "{" + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{_canonical_json(v)}" for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(v) for v in value) + "]"
    if value is None or value is True or value is False:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return _js_number(value)
    return json.dumps(value, ensure_ascii=False)


def _lineage_digest(properties: Mapping[str, Any], blocks: Mapping[str, Any]) -> str:
    """Hash of everything the projector can read lineage or effects from."""
    material = {"properties": dict(properties), **{k: v for k, v in blocks.items() if v}}
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def canonical_payload(
    *, deployment_id: str, agent_id: str, message_id: str, event_type: str, timestamp: Optional[str],
    properties: Mapping[str, Any], blocks: Optional[Mapping[str, Any]] = None,
) -> bytes:
    """Exact bytes that are signed. Any change here must change ``ATTESTATION_VERSION``.

    All properties and context blocks are hashed rather than a list of fields, so a field
    the projector starts reading later cannot be left unsigned. A value that does not
    survive the round trip fails verification, which leaves the event unattested.
    """
    return json.dumps([
        ATTESTATION_VERSION, deployment_id, agent_id, message_id, event_type, timestamp,
        _lineage_digest(properties, blocks or {}),
    ], separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_attestation(public_key: Optional[str], signature: Any, payload: bytes) -> bool:
    """True only for a well-formed signature that verifies. Never raises on bad input."""
    if not public_key or not isinstance(signature, str):
        return False
    key = _decode(public_key, _PUBLIC_KEY_BYTES)
    sig = _decode(signature, _SIGNATURE_BYTES)
    if key is None or sig is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(sig, payload)
    except (InvalidSignature, ValueError):
        return False
    return True
