"""Aether correlation tokens: a deterministic join an agent carries for us.

Aether issues a token when an agent registers a task (for example through the
Aether MCP tool bridge). The agent writes it wherever the downstream system
lets it attach free text or metadata: a payment's metadata, an order note, a
pull request body. When a system-of-record stream later delivers that object,
the token turns a timing guess into an exact join between the agent's task
and the provider's effect.

Tokens leave Aether and are visible to third parties, so they carry no tenant,
agent, or principal identifier. The payload holds only an opaque task
reference, a key ID, and issue/expiry times. The tenant is bound through the
MAC instead: a token verifies only against the tenant of the connection that
observed it, so a token copied into another tenant's data never links.

This module does not read secrets from the environment. Callers pass key
material from their credential custody and may rotate by key ID.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Mapping, Optional


TOKEN_PREFIX = "aet1"
MAX_TOKEN_LENGTH = 256
MIN_KEY_BYTES = 32
DEFAULT_TTL = timedelta(days=7)
MAX_TTL = timedelta(days=30)
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_TOKENS_PER_TEXT = 8

_MAC_DOMAIN = b"aether-correlation-token:v1\x00"
_KEY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_TASK_REF_RE = re.compile(r"^ctk_[A-Za-z0-9_-]{16,64}$")
_B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOKEN_IN_TEXT_RE = re.compile(r"(?<![A-Za-z0-9_.-])aet1\.[A-Za-z0-9_-]{8,256}\.[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")

TokenRejection = Literal[
    "malformed",
    "unknown_key",
    "bad_signature",
    "expired",
    "not_yet_valid",
]


@dataclass(frozen=True)
class IssuedCorrelationToken:
    token: str
    task_ref: str
    key_id: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class CorrelationTokenVerification:
    valid: bool
    task_ref: Optional[str] = None
    key_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    rejection: Optional[TokenRejection] = None


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    if not _B64_RE.fullmatch(text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _require_tenant(tenant_id: str) -> bytes:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    return tenant_id.encode("utf-8")


def _validate_key(key_id: str, secret: bytes) -> None:
    if not _KEY_ID_RE.fullmatch(key_id):
        raise ValueError("key_id must be a short lowercase token")
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_KEY_BYTES:
        raise ValueError(f"correlation token keys need at least {MIN_KEY_BYTES} bytes")


def _mac(secret: bytes, tenant: bytes, payload_b64: str) -> str:
    message = _MAC_DOMAIN + tenant + b"\x00" + payload_b64.encode("ascii")
    return _b64encode(hmac.new(bytes(secret), message, hashlib.sha256).digest())


def _now(now: Optional[datetime]) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def new_task_ref() -> str:
    """An opaque task reference with no embedded identity."""
    return "ctk_" + secrets.token_urlsafe(16)


def issue_correlation_token(
    *,
    tenant_id: str,
    key_id: str,
    secret: bytes,
    task_ref: Optional[str] = None,
    ttl: timedelta = DEFAULT_TTL,
    now: Optional[datetime] = None,
) -> IssuedCorrelationToken:
    """Issue a tenant-bound token for one agent task."""
    tenant = _require_tenant(tenant_id)
    _validate_key(key_id, secret)
    if ttl <= timedelta(0) or ttl > MAX_TTL:
        raise ValueError(f"ttl must be positive and at most {MAX_TTL}")
    ref = task_ref or new_task_ref()
    if not _TASK_REF_RE.fullmatch(ref):
        raise ValueError("task_ref must be an opaque ctk_ reference")
    issued = _now(now).replace(microsecond=0)
    expires = issued + ttl
    payload = {"e": int(expires.timestamp()), "i": int(issued.timestamp()), "k": key_id, "t": ref, "v": 1}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii"))
    token = f"{TOKEN_PREFIX}.{payload_b64}.{_mac(secret, tenant, payload_b64)}"
    if len(token) > MAX_TOKEN_LENGTH:  # pragma: no cover - bounded by the ref/key regexes
        raise ValueError("token exceeds the maximum length")
    return IssuedCorrelationToken(token=token, task_ref=ref, key_id=key_id, issued_at=issued, expires_at=expires)


def verify_correlation_token(
    token: str,
    *,
    tenant_id: str,
    keys: Mapping[str, bytes],
    now: Optional[datetime] = None,
) -> CorrelationTokenVerification:
    """Verify ``token`` for the tenant whose connection observed it.

    Fails closed: any parse error, unknown key, wrong tenant, or time-window
    violation returns ``valid=False`` with a reason and no task reference.
    """
    tenant = _require_tenant(tenant_id)
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        return CorrelationTokenVerification(valid=False, rejection="malformed")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return CorrelationTokenVerification(valid=False, rejection="malformed")
    _, payload_b64, signature = parts
    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, UnicodeDecodeError):
        return CorrelationTokenVerification(valid=False, rejection="malformed")
    if not isinstance(payload, dict) or set(payload) != {"e", "i", "k", "t", "v"} or payload["v"] != 1:
        return CorrelationTokenVerification(valid=False, rejection="malformed")
    key_id, ref, iat, exp = payload["k"], payload["t"], payload["i"], payload["e"]
    if (
        not isinstance(key_id, str)
        or not isinstance(ref, str)
        or not _TASK_REF_RE.fullmatch(ref)
        or type(iat) is not int
        or type(exp) is not int
        or exp <= iat
        or exp - iat > int(MAX_TTL.total_seconds())
    ):
        return CorrelationTokenVerification(valid=False, rejection="malformed")
    secret = keys.get(key_id)
    if secret is None:
        return CorrelationTokenVerification(valid=False, rejection="unknown_key")
    _validate_key(key_id, secret)
    if not hmac.compare_digest(_mac(secret, tenant, payload_b64), signature):
        return CorrelationTokenVerification(valid=False, rejection="bad_signature")
    instant = _now(now)
    issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    if issued_at - MAX_CLOCK_SKEW > instant:
        return CorrelationTokenVerification(valid=False, rejection="not_yet_valid")
    if instant >= expires_at:
        return CorrelationTokenVerification(valid=False, rejection="expired")
    return CorrelationTokenVerification(valid=True, task_ref=ref, key_id=key_id, expires_at=expires_at)


def extract_correlation_tokens(text: str) -> tuple[str, ...]:
    """Candidate tokens embedded in free text (a note, a PR body, metadata).

    Returns distinct candidates in order of appearance, bounded so hostile text
    cannot force unbounded verification work. Candidates are unverified.
    """
    if not isinstance(text, str) or not text:
        return ()
    found: list[str] = []
    for match in _TOKEN_IN_TEXT_RE.finditer(text):
        candidate = match.group(0)
        if candidate not in found:
            found.append(candidate)
        if len(found) >= MAX_TOKENS_PER_TEXT:
            break
    return tuple(found)


TokenVerifier = Callable[[str, str], Optional[str]]


def token_verifier(keys: Mapping[str, bytes], *, now: Optional[datetime] = None) -> TokenVerifier:
    """Adapt verification to ``(token, tenant_id) -> task_ref | None``."""
    frozen = dict(keys)

    def _verify(token: str, tenant_id: str) -> Optional[str]:
        result = verify_correlation_token(token, tenant_id=tenant_id, keys=frozen, now=now)
        return result.task_ref if result.valid else None

    return _verify


__all__ = [
    "CorrelationTokenVerification",
    "DEFAULT_TTL",
    "IssuedCorrelationToken",
    "MAX_TOKEN_LENGTH",
    "MAX_TTL",
    "TOKEN_PREFIX",
    "TokenRejection",
    "TokenVerifier",
    "extract_correlation_tokens",
    "issue_correlation_token",
    "new_task_ref",
    "token_verifier",
    "verify_correlation_token",
]
