"""Temporal helpers for the substrate — a thin façade over ``shared/temporal``.

The Computation Substrate does NOT own time logic. It re-exports the Temporal
Integrity kernel's strict-parsing, zone-validation, and window helpers so
computation windows/watermarks are built with the same DST-safe, timezone-aware
primitives used everywhere else. There is deliberately no ad-hoc ``datetime``
math here.
"""

from __future__ import annotations

from enum import Enum

from shared.temporal import (  # re-export
    Clock,
    FixedClock,
    SYSTEM_CLOCK,
    SystemClock,
    ensure_aware_utc,
    is_valid_iana_zone,
    local_day_window_utc,
)


class WindowType(str, Enum):
    """The window shapes a computation definition may declare."""

    TUMBLING = "tumbling"
    SLIDING = "sliding"
    SESSION = "session"
    LIFETIME = "lifetime"
    CONTRACT_PERIOD = "contract_period"
    BILLING_PERIOD = "billing_period"
    ATTRIBUTION_WINDOW = "attribution_window"
    FORECAST_HORIZON = "forecast_horizon"
    OBSERVATION_WINDOW = "observation_window"


WINDOW_TYPES: tuple[str, ...] = tuple(w.value for w in WindowType)


__all__ = [
    "WindowType",
    "WINDOW_TYPES",
    "Clock",
    "FixedClock",
    "SystemClock",
    "SYSTEM_CLOCK",
    "ensure_aware_utc",
    "is_valid_iana_zone",
    "local_day_window_utc",
]
