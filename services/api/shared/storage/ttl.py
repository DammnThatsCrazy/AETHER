"""TTL / retention helpers for the shared durable key-value stores.

``shared.store.DurableStore`` already supports per-key ``ttl_seconds`` on
``set()``; this module is the thin, policy-facing layer that turns a retention
window (days) into a store TTL and gives the payment-rail and other planes a
single canonical way to decide "should this record carry a TTL" and "has this
record aged past its retention window" — without each caller re-deriving day→
second math or timestamp parsing.

Design rules:
- Retention is OFF by default. ``retention_ttl_seconds(0)`` (and a missing /
  ``None`` window) returns ``0``, which the store treats as "no expiry" — so
  wiring a TTL helper into a store NEVER changes behavior until an operator
  opts in with an explicit retention window.
- ``is_expired`` is tolerance-safe: an unparseable timestamp is treated as
  NOT expired (a malformed ``created_at`` must not silently delete a record).
- This module is pure and offline — no settings import at module load. Callers
  pass the window explicitly (or read it from their settings lazily).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.temporal.instant import ensure_aware_utc

#: Seconds in one retention day. Exactly 86_400 (civil days; sub-day windows
#: are expressed in seconds directly by callers that need them).
SECONDS_PER_DAY = 86_400


def retention_ttl_seconds(retention_days: Optional[int]) -> int:
    """Store TTL (seconds) for a record kept ``retention_days``.

    ``0``/``None``/non-positive → ``0`` = no expiry (the store default). Any
    positive window is converted to whole seconds (``retention_days *
    86_400``). ``0`` is the store's canonical "no TTL" sentinel, so returning
    it keeps records forever exactly as an unwired store would.
    """
    if retention_days is None:
        return 0
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    return days * SECONDS_PER_DAY


def is_expired(
    created_at: Optional[str],
    *,
    retention_days: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    """True when a record created at ``created_at`` is past its retention window.

    Retention is OFF (never expired) when ``retention_days`` is falsy. An
    unparseable ``created_at`` is treated as NOT expired — failing open on a
    malformed timestamp avoids silently dropping records. ``now`` is injectable
    for deterministic tests; it defaults to ``datetime.now(timezone.utc)``.
    """
    ttl = retention_ttl_seconds(retention_days)
    if ttl <= 0 or not created_at:
        return False
    try:
        created = ensure_aware_utc(
            datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        )
    except (ValueError, TypeError):
        return False
    now = now or datetime.now(timezone.utc)
    now_utc = ensure_aware_utc(now)
    return (now_utc - created).total_seconds() > ttl


def set_with_retention(
    store: Any,
    key: str,
    record: dict[str, Any],
    *,
    retention_days: Optional[int],
) -> None:
    """Store ``record`` with a TTL derived from ``retention_days``.

    A falsy window calls ``store.set(key, record)`` with no TTL — byte-for-byte
    the unwired behavior. A positive window calls ``store.set(key, record,
    ttl_seconds=retention_ttl_seconds(retention_days))`` so the store expires
    the key automatically. Returns nothing (mirrors ``DurableStore.set``).
    """
    ttl = retention_ttl_seconds(retention_days)
    if ttl <= 0:
        return store.set(key, record)
    return store.set(key, record, ttl_seconds=ttl)


def record_key(prefix: str, *parts: Any) -> str:
    """Join a store-key prefix and parts with ``:`` (the shared store's key
    convention). Small helper so retention/replay code never hand-rolls keys."""
    return ":".join([str(prefix), *(str(p) for p in parts if p not in (None, ""))])


__all__ = [
    "SECONDS_PER_DAY",
    "retention_ttl_seconds",
    "is_expired",
    "set_with_retention",
    "record_key",
]
