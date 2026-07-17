"""Temporal authorities plus skew/lag/state classification.

Every calendar-based business rule names WHICH authority owns its clock and
calendar (viewer display never changes billing truth; a campaign cap never
follows a traveling user's device zone). The authority vocabulary is shared
with TS (parity-tested); resolution against tenant/campaign/contract settings
happens in the services that own those records.

Classification here is pure math over instants + policy bounds — no I/O, no
global clock — so ingestion enforcement behaves identically in shadow, warn,
and enforce modes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from shared.temporal.instant import ensure_aware_utc

TemporalAuthority = Literal[
    "viewer",
    "source",
    "tenant_business",
    "campaign",
    "contract",
    "provider",
    "market",
    "legal_policy",
    "investigation",
    "server",
    "utc",
]

TEMPORAL_AUTHORITIES: tuple[str, ...] = (
    "viewer",
    "source",
    "tenant_business",
    "campaign",
    "contract",
    "provider",
    "market",
    "legal_policy",
    "investigation",
    "server",
    "utc",
)


def elapsed_ms(earlier: datetime, later: datetime) -> int:
    """Signed milliseconds from ``earlier`` to ``later`` (negative if reversed)."""
    a = ensure_aware_utc(earlier)
    b = ensure_aware_utc(later)
    return round((b - a).total_seconds() * 1000)


def compute_clock_skew_ms(occurred_at: datetime, received_at: datetime) -> int:
    """Positive when the client clock reads ahead of server receipt time."""
    return elapsed_ms(received_at, occurred_at)


def compute_delivery_lag_ms(sent_at: datetime, received_at: datetime) -> int:
    """Positive transit/buffering delay between client send and server receipt."""
    return max(0, elapsed_ms(sent_at, received_at))


def classify_temporal_state(
    *,
    clock_skew_ms: int,
    delivery_lag_ms: Optional[int],
    max_future_skew_ms: int,
    warn_skew_ms: int,
    max_lateness_ms: int,
    source_time_zone_known: bool,
) -> tuple[str, list[str]]:
    """Classify one event's temporal state from measured skew/lag and bounds.

    Returns ``(temporal_state, reason_codes)`` using the canonical
    vocabularies. ``future`` (beyond tolerated forward skew) and ``late``
    (beyond allowed lateness) are policy-disposition states; ``skewed`` and
    lag warnings accept the event with evidence attached.
    """
    reasons: list[str] = []
    state = "valid"
    if clock_skew_ms > max_future_skew_ms:
        return "future", ["timestamp_future"]
    if -clock_skew_ms > max_lateness_ms:
        state = "late"
        reasons.append("timestamp_too_old")
    elif abs(clock_skew_ms) > warn_skew_ms:
        state = "skewed"
        reasons.append("clock_skew_warning")
    if delivery_lag_ms is not None and delivery_lag_ms > max_lateness_ms:
        if state == "valid":
            state = "late"
        reasons.append("delivery_lag_warning")
    if not source_time_zone_known:
        if state == "valid":
            state = "timezone_unknown"
        reasons.append("temporal_provenance_missing")
    return state, reasons


__all__ = [
    "TemporalAuthority",
    "TEMPORAL_AUTHORITIES",
    "elapsed_ms",
    "compute_clock_skew_ms",
    "compute_delivery_lag_ms",
    "classify_temporal_state",
]
