"""Centralized security utilities for delivery pipeline.

Provides SSRF protection, timestamp tolerance, constant-time comparison,
idempotency key generation, and header sanitization helpers shared across
the delivery pipeline.

SSRF protection is implemented directly here (stdlib only) so this module
can be imported without pulling in the full adapter dependency chain.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
import time
from urllib.parse import urlparse

# Private / loopback / link-local ranges that must never be reachable outbound.
# Mirrors the list in adapters/webhook.py — keep in sync if ranges change.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),     # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),    # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
    ipaddress.ip_network("0.0.0.0/8"),         # unspecified
]


# ─── SSRF Protection ────────────────────────────────────────────────────────

def validate_webhook_url(url: str, allow_private: bool = False) -> None:
    """SSRF protection. Resolves hostname DNS, checks all IPs against RFC 1918 blocklist.

    Args:
        url: The URL to validate.
        allow_private: If True, skip private-range checks (local/test use only).
    """
    if allow_private:
        return

    from services.delivery.adapters.base import SSRFBlockedError

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError(f"Cannot parse hostname from URL: {url!r}")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS resolution failed for {hostname!r}: {exc}")

    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                raise SSRFBlockedError(
                    f"Webhook URL {url!r} resolves to blocked address {addr_str!r} "
                    f"(matches {network}). SSRF protection active."
                )


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
