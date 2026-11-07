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


def _lineage_digest(properties: Mapping[str, Any], blocks: Mapping[str, Any]) -> str:
    """Hash of everything the projector can read lineage or effects from."""
    material = {"properties": dict(properties), **{k: v for k, v in blocks.items() if v}}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
