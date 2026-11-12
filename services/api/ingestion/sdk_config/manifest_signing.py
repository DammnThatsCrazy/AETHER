"""SDK manifest signing — canonical JSON + ECDSA P-256 (ES256, raw r||s).

Normative spec: docs/reference/sdks/manifest-signing.md. Every client SDK
(web, iOS, Android) re-implements ``canonical_json`` and ``verify`` and is tested
against the shared vectors in tests/fixtures/sdk/manifest-signing-vectors.json,
so this module is the reference those vectors are generated from.

Why asymmetric: the platform secret (``SDK_CONFIG_SECRET``) stays on the server.
The signing key is derived from it deterministically, so no new secret has to be
provisioned, and clients only ever need the public key.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SIGNATURE_ALG = "ecdsa-p256-sha256"
_KDF_INFO = b"aether.sdk-manifest.signing.v1"
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_MAX_SAFE_INT = 2**53 - 1
_SIGNATURE_RE = re.compile(r"[A-Za-z0-9_-]{86}")  # unpadded base64url of 64 bytes


class ManifestSigningError(ValueError):
    """The manifest cannot be represented in the canonical signing form."""


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted ASCII keys, no whitespace, integers only.

    Floats are rejected on purpose: number formatting is the one place JSON
    implementations disagree, and no manifest field needs a fractional value.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INT:
            raise ManifestSigningError(f"integer outside the safe range: {value}")
        return str(value)
    if isinstance(value, float):
        raise ManifestSigningError(f"floating point numbers cannot be signed: {value!r}")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str) or not key.isascii():
                raise ManifestSigningError(f"object keys must be ASCII strings: {key!r}")
        return "{" + ",".join(
            json.dumps(k, ensure_ascii=False) + ":" + canonical_json(value[k]) for k in sorted(value)
        ) + "}"
    raise ManifestSigningError(f"unsupported value type: {type(value).__name__}")


def signing_payload(manifest: dict[str, Any]) -> bytes:
    """Canonical bytes that are signed: every field except ``signature``."""
    if manifest.get("signature_alg") != SIGNATURE_ALG:
        raise ManifestSigningError(f"signature_alg must be {SIGNATURE_ALG!r}")
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return canonical_json(body).encode("utf-8")


def derive_private_key(secret: str) -> ec.EllipticCurvePrivateKey:
    """Deterministically derive the P-256 signing key from the platform secret."""
    okm = HKDF(algorithm=hashes.SHA256(), length=48, salt=None, info=_KDF_INFO).derive(secret.encode("utf-8"))
    scalar = int.from_bytes(okm, "big") % (_P256_ORDER - 1) + 1
    return ec.derive_private_key(scalar, ec.SECP256R1())


def public_key_spki_b64url(private_key: ec.EllipticCurvePrivateKey) -> str:
    """The public key clients are configured with: base64url DER SubjectPublicKeyInfo."""
    der = private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return b64url_encode(der)


def sign(private_key: ec.EllipticCurvePrivateKey, manifest: dict[str, Any]) -> str:
    """Sign a manifest dict; returns base64url of the 64-byte raw r||s signature."""
    der = private_key.sign(signing_payload(manifest), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def verify(public_key_spki: str, manifest: dict[str, Any]) -> bool:
    """Reference verifier (fails closed on anything malformed)."""
    try:
        signature = manifest.get("signature")
        if not isinstance(signature, str) or not _SIGNATURE_RE.fullmatch(signature):
            return False
        raw = b64url_decode(signature)
        public_key = serialization.load_der_public_key(b64url_decode(public_key_spki))
        if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
            public_key.curve, ec.SECP256R1
        ):
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        public_key.verify(der, signing_payload(manifest), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ManifestSigningError, ValueError, TypeError):
        return False
