"""Apple App Attest attestation verification.

Implements Apple's "Validating apps that connect to your server" checks for an
attestation object produced by ``DCAppAttestService.attestKey``:

1. ``fmt`` is ``apple-appattest``; ``x5c`` chains credential cert ->
   intermediate -> the pinned Apple App Attestation Root CA, all valid now.
2. ``nonce = SHA256(authData || SHA256(challenge))`` equals the value in the
   credential certificate's extension 1.2.840.113635.100.8.2.
3. ``SHA256(credential public key)`` equals the key identifier.
4. ``authData.rpIdHash`` equals ``SHA256(<TEAM_ID>.<bundle id>)`` for a
   configured app ID.
5. ``signCount`` is 0; ``aaguid`` matches the configured environment;
   ``credentialId`` equals the key identifier.

Everything is offline: the only trust anchor is the pinned root certificate.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ingestion.device_integrity import cbor

ROOT_CA_PATH = Path(__file__).with_name("apple_app_attestation_root_ca.pem")
#: SHA-256 fingerprint of the pinned root (checked on load).
ROOT_CA_SHA256 = "1cb9823ba28ba6ad2d33a006941de2ae4f513ef1d4e831b9f7e0fa7b6242c932"
NONCE_OID = x509.ObjectIdentifier("1.2.840.113635.100.8.2")
AAGUID_PRODUCTION = b"appattest" + b"\x00" * 7
AAGUID_DEVELOPMENT = b"appattestdevelop"


class AppAttestError(ValueError):
    """The attestation is invalid. ``reason`` is a stable, content-free code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AppAttestResult:
    app_id: str
    environment: str
    key_id: str


@lru_cache(maxsize=1)
def pinned_root() -> x509.Certificate:
    cert = x509.load_pem_x509_certificate(ROOT_CA_PATH.read_bytes())
    if cert.fingerprint(hashes.SHA256()).hex() != ROOT_CA_SHA256:
        raise RuntimeError("pinned Apple App Attestation root does not match its fingerprint")
    return cert


def _b64(value: str) -> bytes:
    value = value.strip()
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_" if ("-" in value or "_" in value) else None, validate=False)
    except (ValueError, TypeError) as exc:
        raise AppAttestError("bad_base64") from exc


def _check_chain(chain: list[x509.Certificate], root: x509.Certificate, now: datetime) -> None:
    certs = [*chain, root]
    for cert in certs:
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise AppAttestError("certificate_not_valid_now")
    try:
        for child, issuer in zip(certs, certs[1:]):
            child.verify_directly_issued_by(issuer)
    except Exception as exc:  # InvalidSignature, ValueError, TypeError
        raise AppAttestError("certificate_chain_invalid") from exc


def _nonce_from_extension(cert: x509.Certificate) -> bytes:
    try:
        ext = cert.extensions.get_extension_for_oid(NONCE_OID)
    except x509.ExtensionNotFound as exc:
        raise AppAttestError("nonce_extension_missing") from exc
    der = ext.value.value  # UnrecognizedExtension: raw DER
    # SEQUENCE { [1] EXPLICIT OCTET STRING (32 bytes) }
    prefix = bytes.fromhex("3024a1220420")
    if len(der) != len(prefix) + 32 or not der.startswith(prefix):
        raise AppAttestError("nonce_extension_malformed")
    return der[len(prefix):]


def verify_attestation(
    *,
    key_id_b64: str,
    attestation_object_b64: str,
    challenge: str,
    app_ids: Iterable[str],
    environment: str = "production",
    root: Optional[x509.Certificate] = None,
    now: Optional[datetime] = None,
) -> AppAttestResult:
    """Verify one App Attest attestation. Raises ``AppAttestError`` on any failure."""
    now = now or datetime.now(timezone.utc)
    root = root or pinned_root()
    key_id = _b64(key_id_b64)
    try:
        obj = cbor.decode(_b64(attestation_object_b64))
    except cbor.CBORError as exc:
        raise AppAttestError("attestation_not_cbor") from exc
    if not isinstance(obj, dict) or obj.get("fmt") != "apple-appattest":
        raise AppAttestError("wrong_format")
    stmt = obj.get("attStmt")
    auth_data = obj.get("authData")
    if not isinstance(stmt, dict) or not isinstance(auth_data, bytes):
        raise AppAttestError("attestation_incomplete")
    x5c = stmt.get("x5c")
    if not isinstance(x5c, list) or len(x5c) < 2 or not all(isinstance(c, bytes) for c in x5c):
        raise AppAttestError("certificate_chain_missing")
    try:
        chain = [x509.load_der_x509_certificate(c) for c in x5c]
    except ValueError as exc:
        raise AppAttestError("certificate_unparseable") from exc
    _check_chain(chain, root, now)
    cred_cert = chain[0]

    client_data_hash = hashlib.sha256(challenge.encode("utf-8")).digest()
    expected_nonce = hashlib.sha256(auth_data + client_data_hash).digest()
    if _nonce_from_extension(cred_cert) != expected_nonce:
        raise AppAttestError("nonce_mismatch")

    public_key = cred_cert.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise AppAttestError("unexpected_key_type")
    point = public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    if hashlib.sha256(point).digest() != key_id:
        raise AppAttestError("key_id_mismatch")

    # authData: rpIdHash(32) flags(1) signCount(4) aaguid(16) credIdLen(2) credId(...)
    if len(auth_data) < 55:
        raise AppAttestError("auth_data_truncated")
    rp_id_hash = auth_data[0:32]
    sign_count = int.from_bytes(auth_data[33:37], "big")
    aaguid = auth_data[37:53]
    cred_len = int.from_bytes(auth_data[53:55], "big")
    cred_id = auth_data[55:55 + cred_len]

    matched = next((a for a in app_ids if hashlib.sha256(a.encode("utf-8")).digest() == rp_id_hash), None)
    if matched is None:
        raise AppAttestError("app_id_not_allowed")
    if sign_count != 0:
        raise AppAttestError("counter_not_zero")
    expected_aaguid = AAGUID_DEVELOPMENT if environment == "development" else AAGUID_PRODUCTION
    if aaguid != expected_aaguid:
        raise AppAttestError("environment_mismatch")
    if cred_id != key_id:
        raise AppAttestError("credential_id_mismatch")
    return AppAttestResult(app_id=matched, environment=environment, key_id=key_id_b64)


__all__ = ["AppAttestError", "AppAttestResult", "pinned_root", "verify_attestation"]
