"""Centralized security utilities for delivery pipeline.

Provides SSRF protection, timestamp tolerance, constant-time comparison,
idempotency key generation, and header sanitization helpers shared across
the delivery pipeline.

SSRF protection delegates to :mod:`shared.security.ssrf`, the single
resolver-level check for tenant-configured outbound destinations. It is
imported lazily so the other helpers stay importable without the ``shared``
package import chain.
"""

from __future__ import annotations

import hashlib
import hmac
import time


# ─── SSRF Protection ────────────────────────────────────────────────────────

def validate_webhook_url(url: str, allow_private: bool = False) -> None:
    """SSRF protection: every address the URL's host resolves to must be public.

    Args:
        url: The URL to validate.
        allow_private: If True, skip the check (local/test use only).
    """
    if allow_private:
        return

    from actions.delivery.adapters.base import SSRFBlockedError
    from shared.security.ssrf import UnsafeDestinationError, resolve_public_addresses

    try:
        resolve_public_addresses(url)
    except UnsafeDestinationError as exc:
        raise SSRFBlockedError(str(exc)) from exc


# ─── Constant-Time Comparison ────────────────────────────────────────────────

def constant_time_compare(a: str | bytes, b: str | bytes) -> bool:
    """Wrapper around hmac.compare_digest with encoding handling.

    Prevents timing-based signature oracle attacks.
    """
    if isinstance(a, str):
        a = a.encode()
    if isinstance(b, str):
        b = b.encode()
    return hmac.compare_digest(a, b)


# ─── Timestamp Tolerance ─────────────────────────────────────────────────────

def verify_timestamp_tolerance(timestamp_str: str, max_age_seconds: int = 300) -> bool:
    """Return True if timestamp is within max_age_seconds of now.

    Protects against replay attacks using stale signed requests.
    """
    try:
        ts = int(timestamp_str)
        return abs(time.time() - ts) <= max_age_seconds
    except (ValueError, TypeError):
        return False


# ─── Idempotency Key ─────────────────────────────────────────────────────────

def generate_idempotency_key(*parts: str) -> str:
    """Return SHA-256 hex digest of ':'.join(parts).

    Produces a deterministic, collision-resistant key for deduplication.
    """
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


# ─── Header Sanitization ─────────────────────────────────────────────────────

_SENSITIVE_HEADERS = frozenset({
    "authorization",
    "x-api-key",
    "x-bot-token",
    "x-auth-token",
    "x-secret",
    "cookie",
    "set-cookie",
    "proxy-authorization",
})


def sanitize_headers(headers: dict) -> dict:
    """Remove sensitive headers before persisting to WebhookInbox.headers_snapshot.

    Comparison is case-insensitive. Returns a new dict; does not mutate input.
    """
    return {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS}
