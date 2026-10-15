"""Deterministic hashing for sensitive identity signals.

Rules:
- Raw email, phone, and private keys are NEVER stored.
- All hashes use HMAC-SHA256 with a tenant-scoped salt.
- Wallet addresses are normalized before hashing.
- Fingerprints are hashed before persistence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# Fallback HMAC key used when no env var is set (test/local only).
_DEFAULT_HMAC_KEY = b"aether-identity-hash-key-default"

# Fallback key for verification proof secrets — a SEPARATE key domain from the
# identifier-hashing key so a proof secret's digest can never collide with an
# identifier hash even under the same raw input (test/local only).
_DEFAULT_VERIFICATION_KEY = b"aether-identity-verification-token-key-default"
_WALLET_SUBJECT_BINDING_CIPHERTEXT_VERSION = "v2"


def _hmac_key() -> bytes:
    raw = os.getenv("IDENTITY_HASH_KEY", "")
    if raw:
        return raw.encode()
    return _DEFAULT_HMAC_KEY


def _verification_hmac_key() -> bytes:
    raw = os.getenv("IDENTITY_VERIFICATION_TOKEN_KEY", "")
    return raw.encode() if raw else _DEFAULT_VERIFICATION_KEY


def _verification_hmac_keys() -> list[bytes]:
    keys = [_verification_hmac_key()]
    previous = os.getenv("IDENTITY_VERIFICATION_TOKEN_KEY_PREVIOUS", "")
    if previous:
        previous_key = previous.encode()
        if previous_key not in keys:
            keys.append(previous_key)
    return keys


def _derive_wallet_subject_binding_key(material: bytes, tenant_id: str) -> bytes:
    return hmac.new(
        material,
        f"wallet-proof-subject-binding:{tenant_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _wallet_subject_binding_keyring(tenant_id: str) -> tuple[str, dict[str, bytes]]:
    raw = os.getenv("IDENTITY_VERIFICATION_TOKEN_KEY", "")
    environment = os.getenv("AETHER_ENV", "local").strip().lower()
    if not raw and environment not in {"local", "test", "development"}:
        raise RuntimeError("IDENTITY_VERIFICATION_TOKEN_KEY is required")
    if not tenant_id:
        raise ValueError("tenant id is required for wallet subject binding")

    active_id = os.getenv("IDENTITY_VERIFICATION_TOKEN_KEY_ID", "current").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", active_id):
        raise ValueError("invalid IDENTITY_VERIFICATION_TOKEN_KEY_ID")
    active_material = raw.encode() if raw else _DEFAULT_VERIFICATION_KEY
    keys = {active_id: _derive_wallet_subject_binding_key(active_material, tenant_id)}

    previous_raw = os.getenv("IDENTITY_VERIFICATION_TOKEN_KEY_PREVIOUS", "")
    if previous_raw:
        previous_id = os.getenv(
            "IDENTITY_VERIFICATION_TOKEN_KEY_PREVIOUS_ID", "previous"
        ).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", previous_id):
            raise ValueError("invalid IDENTITY_VERIFICATION_TOKEN_KEY_PREVIOUS_ID")
        if previous_id == active_id:
            raise ValueError("active and previous wallet binding key IDs must differ")
        keys[previous_id] = _derive_wallet_subject_binding_key(
            previous_raw.encode(), tenant_id
        )
    return active_id, keys


def ensure_wallet_subject_binding_key(tenant_id: str) -> None:
    """Fail early if production cannot safely persist replay bindings."""
    _wallet_subject_binding_keyring(tenant_id)


def hash_value(value: str, scope: str = "") -> str:
    """Return a deterministic HMAC-SHA256 hex digest of ``value``.

    ``scope`` is mixed in so the same raw value produces different hashes
    under different tenant or type namespaces.
    """
    if not value:
        return ""
    msg = f"{scope}:{value}" if scope else value
    return hmac.new(_hmac_key(), msg.encode(), hashlib.sha256).hexdigest()


def hash_verification_token(token: str, scope: str = "") -> str:
    """HMAC-SHA256 digest of a verification OTP/magic-link secret, under a key
    domain SEPARATE from identifier hashing so proof secrets and identifier
    hashes can never collide."""
    if not token:
        return ""
    msg = f"{scope}:{token}" if scope else token
    return hmac.new(_verification_hmac_key(), msg.encode(), hashlib.sha256).hexdigest()


def verify_token_digest(token: str, expected_digest: str, scope: str = "") -> bool:
    """Constant-time comparison of a presented token against a stored digest."""
    if not token or not expected_digest:
        return False
    msg = f"{scope}:{token}" if scope else token
    matched = False
    for key in _verification_hmac_keys():
        digest = hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()
        matched |= hmac.compare_digest(digest, expected_digest)
    return matched


def encrypt_wallet_subject_binding(subject_id: str, tenant_id: str) -> str:
    """Encrypt a wallet proof's anonymous subject for durable replay recovery.

    The ciphertext is authenticated and tenant-bound. The verification secret
    key is used as key material so this recoverable value stays in a separate
    key domain from identity aliases and is never written to logs or API output.
    """
    if not subject_id or not tenant_id:
        return ""
    active_id, keyring = _wallet_subject_binding_keyring(tenant_id)
    nonce = os.urandom(12)
    encrypted = AESGCM(keyring[active_id]).encrypt(
        nonce, subject_id.encode("utf-8"), tenant_id.encode("utf-8")
    )
    payload = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
    return f"{_WALLET_SUBJECT_BINDING_CIPHERTEXT_VERSION}.{active_id}.{payload}"


def decrypt_wallet_subject_binding(ciphertext: str, tenant_id: str) -> str:
    """Recover a tenant-bound wallet proof subject from its stored ciphertext."""
    if not ciphertext or not tenant_id:
        return ""
    try:
        _, keyring = _wallet_subject_binding_keyring(tenant_id)
        if ciphertext.startswith(f"{_WALLET_SUBJECT_BINDING_CIPHERTEXT_VERSION}."):
            version, key_id, encoded_payload = ciphertext.split(".", 2)
            if version != _WALLET_SUBJECT_BINDING_CIPHERTEXT_VERSION:
                return ""
            key = keyring.get(key_id)
            if key is None:
                return ""
            packed = base64.b64decode(
                encoded_payload.encode("ascii"), altchars=b"-_", validate=True
            )
            keys = [key]
        else:
            # Pre-v2 records were unversioned and used only the then-active
            # key. Try the configured active and previous keys during a
            # rotation window so existing persisted evidence remains usable.
            packed = base64.b64decode(
                ciphertext.encode("ascii"), altchars=b"-_", validate=True
            )
            keys = list(dict.fromkeys(keyring.values()))
        if len(packed) <= 12:
            return ""
        for key in keys:
            try:
                return AESGCM(key).decrypt(
                    packed[:12], packed[12:], tenant_id.encode("utf-8")
                ).decode("utf-8")
            except InvalidTag:
                continue
    except (ValueError, UnicodeDecodeError, binascii.Error, InvalidTag, RuntimeError):
        return ""
    return ""


def hash_email(email: str, tenant_id: str) -> str:
    """Hash a normalized email address, scoped to tenant."""
    normalized = _normalize_email(email)
    if not normalized:
        return ""
    return hash_value(normalized, scope=f"email:{tenant_id}")


def hash_phone(phone: str, tenant_id: str) -> str:
    """Hash an E.164 phone number, scoped to tenant."""
    normalized = _normalize_phone(phone)
    if not normalized:
        return ""
    return hash_value(normalized, scope=f"phone:{tenant_id}")


def hash_fingerprint(fingerprint_id: str) -> str:
    """Hash a device fingerprint ID (support-only, no tenant scope)."""
    if not fingerprint_id:
        return ""
    return hash_value(fingerprint_id, scope="fingerprint")


def hash_external_id(external_id: str, tenant_id: str) -> str:
    """Hash a tenant-owned external customer/account ID."""
    if not external_id:
        return ""
    return hash_value(external_id, scope=f"external:{tenant_id}")


def hash_wallet(address: str, chain_namespace: str = "eip155") -> str:
    """Hash a normalized wallet address with VM and concrete chain scope."""
    normalized = normalize_wallet(address, chain_namespace)
    if not normalized:
        return ""
    namespace = (chain_namespace or "eip155").strip().lower()
    return hash_value(normalized, scope=f"wallet:{namespace}")


def normalize_wallet(address: str, chain_namespace: str = "eip155") -> str:
    """Normalize a wallet address for the given chain namespace."""
    if not address:
        return ""
    stripped = address.strip()
    family = (chain_namespace or "eip155").strip().lower().split(":", 1)[0]
    # These address families use hex identifiers whose casing is not
    # semantically significant. Keep this gated by family: Bitcoin Base58,
    # Substrate SS58, and other textual encodings are case-sensitive.
    if family in {"eip155", "evm"} or (
        family in {"sui", "aptos", "movevm", "starknet", "tvm"}
        and stripped.startswith("0x")
    ):
        return stripped.lower()
    # Bech32-based account identifiers are conventionally represented in
    # lowercase. Other formats remain untouched unless their format is known.
    if family in {"cosmos", "near", "hedera", "icp"}:
        return stripped.lower()
    # Solana, Bitcoin, Substrate, Stellar, Cardano, Algorand, and unknown
    # formats can contain case-sensitive base encodings.
    return stripped


def _normalize_email(email: str) -> str:
    if not email:
        return ""
    normalized = email.strip().lower()
    _EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    if not _EMAIL_RE.match(normalized):
        return ""
    return normalized


def _normalize_phone(phone: str) -> str:
    """Naive E.164 normalizer — strips non-digit chars, preserves leading +."""
    if not phone:
        return ""
    stripped = re.sub(r"[^\d+]", "", phone.strip())
    if not stripped:
        return ""
    if not stripped.startswith("+"):
        stripped = "+" + stripped
    if len(stripped) < 8 or len(stripped) > 16:
        return ""
    return stripped


def redact_display(value: str, signal_type: str) -> str:
    """Return a safe display-only redacted form of a sensitive value."""
    if not value:
        return ""
    if signal_type in ("email_hash", "phone_hash"):
        return f"[REDACTED:{signal_type}]"
    if signal_type == "wallet_address":
        # Show first 6 + last 4 chars of the address
        if len(value) > 10:
            return f"{value[:6]}...{value[-4:]}"
        return value
    if signal_type == "device_fingerprint":
        return "[REDACTED:fingerprint]"
    # For non-sensitive types, show a truncated version
    if len(value) > 12:
        return f"{value[:6]}...{value[-4:]}"
    return value
