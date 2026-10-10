"""Injectable clocks.

Services take a :class:`Clock` instead of calling ``datetime.now()`` so that
expiration, cooldown, retry, scheduling, and freshness logic is testable
without depending on the real wall clock. Wall time is always tz-aware UTC;
elapsed time uses the monotonic clock, never wall-clock subtraction.
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from shared.temporal.instant import ensure_aware_utc


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, tz-aware UTC."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds for elapsed-time measurement."""
        ...


class SystemClock:
    """The real clock (production default)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return _time.monotonic()


class FixedClock:
    """A frozen clock for tests; ``advance()`` moves it explicitly."""

    def __init__(self, instant: datetime) -> None:
        self._now = ensure_aware_utc(instant)
        self._mono = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
        self._mono += seconds


class SteppingClock:
    """Advances by a fixed step on every ``now()`` call (ordering tests)."""

    def __init__(self, start: datetime, step_seconds: float = 1.0) -> None:
        self._next = ensure_aware_utc(start)
        self._step = timedelta(seconds=step_seconds)
        self._mono = 0.0
        self._step_seconds = step_seconds

    def now(self) -> datetime:
        current = self._next
        self._next = self._next + self._step
        self._mono += self._step_seconds
        return current

    def monotonic(self) -> float:
        return self._mono


SYSTEM_CLOCK = SystemClock()

__all__ = ["Clock", "SystemClock", "FixedClock", "SteppingClock", "SYSTEM_CLOCK"]
