"""Deterministic hashing for sensitive identity signals.

Rules:
- Raw email, phone, and private keys are NEVER stored.
- All hashes use HMAC-SHA256 with a tenant-scoped salt.
- Wallet addresses are normalized before hashing.
- Fingerprints are hashed before persistence.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Optional


# Fallback HMAC key used when no env var is set (test/local only).
_DEFAULT_HMAC_KEY = b"aether-identity-hash-key-default"

# Fallback key for verification proof secrets — a SEPARATE key domain from the
# identifier-hashing key so a proof secret's digest can never collide with an
# identifier hash even under the same raw input (test/local only).
_DEFAULT_VERIFICATION_KEY = b"aether-identity-verification-token-key-default"


def _hmac_key() -> bytes:
    raw = os.getenv("IDENTITY_HASH_KEY", "")
    if raw:
        return raw.encode()
    return _DEFAULT_HMAC_KEY


def _verification_hmac_key() -> bytes:
    raw = os.getenv("IDENTITY_VERIFICATION_TOKEN_KEY", "")
    return raw.encode() if raw else _DEFAULT_VERIFICATION_KEY


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
    return hmac.compare_digest(hash_verification_token(token, scope), expected_digest)


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
    """Hash a normalized wallet address with chain namespace."""
    normalized = normalize_wallet(address, chain_namespace)
    if not normalized:
        return ""
    return hash_value(normalized, scope=f"wallet:{chain_namespace}")


def normalize_wallet(address: str, chain_namespace: str = "eip155") -> str:
    """Normalize a wallet address for the given chain namespace."""
    if not address:
        return ""
    stripped = address.strip()
    # EVM addresses: lowercase the 0x-prefixed hex
    if chain_namespace in ("eip155", "evm") or stripped.startswith("0x"):
        return stripped.lower()
    # Solana / SVM: base58 is case-sensitive, preserve as-is
    if chain_namespace in ("solana", "svm"):
        return stripped
    # Default: strip and lowercase
    return stripped.lower()


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
