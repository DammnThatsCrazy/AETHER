"""Tenant-scoped rotating IP HMAC — the only permitted transform of a client IP.

Raw IPs must never persist (safety default ``AETHER_RAW_IP_PERSISTENCE_BLOCKED``).
Where short-term correlation/deduplication is legitimately needed (abuse
review, audit trails), persist this HMAC instead:

    token = HMAC-SHA256( derive(root_secret, tenant_id, window), normalized_ip )

Keys are DERIVED per (tenant, rotation window) from one root secret — no key
table, no per-request reads — so tokens are tenant-scoped (no cross-tenant
joins) and expire naturally when the window rotates. The token is one-way:
the raw IP is not recoverable and never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
from datetime import datetime
from typing import Optional

from shared.temporal.instant import ensure_aware_utc

_TOKEN_PREFIX = "iph1"  # versioned so a future scheme can coexist


def _root_secret() -> bytes:
    secret = os.environ.get("AETHER_IP_HMAC_SECRET") or os.environ.get("JWT_SECRET") or ""
    if not secret:
        # Local/test fallback — never used in hosted envs (JWT_SECRET is required there).
        secret = "aether-local-ip-hmac"
    return secret.encode()


def _normalize_ip(raw_ip: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(raw_ip.strip()))
    except ValueError:
        return None


def ip_hmac_token(
    raw_ip: Optional[str],
    tenant_id: str,
    at: datetime,
    *,
    rotation_hours: int = 24,
) -> Optional[str]:
    """Rotating, tenant-scoped, one-way token for an IP — or None for invalid input.

    Deterministic within a rotation window (dedup works), different across
    tenants and windows (no long-lived identifier).
    """
    if not raw_ip:
        return None
    normalized = _normalize_ip(raw_ip)
    if normalized is None:
        return None
    instant = ensure_aware_utc(at)
    window = int(instant.timestamp() // (max(1, rotation_hours) * 3600))
    key = hmac.new(
        _root_secret(), f"{tenant_id}:{window}".encode(), hashlib.sha256
    ).digest()
    digest = hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{_TOKEN_PREFIX}:{digest}"


def is_ip_hmac_token(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(f"{_TOKEN_PREFIX}:")


def audit_ip_token(raw_ip: Optional[str], tenant_id: str) -> Optional[str]:
    """Convenience for audit paths: rotating token at the current instant."""
    from datetime import datetime, timezone

    return ip_hmac_token(raw_ip, tenant_id, datetime.now(timezone.utc))


__all__ = ["ip_hmac_token", "is_ip_hmac_token"]
