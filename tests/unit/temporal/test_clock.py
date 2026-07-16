"""Injectable clocks: no temporal test depends on the real wall clock."""
from __future__ import annotations

from datetime import timezone

import pytest

from shared.temporal.clock import Clock, FixedClock, SteppingClock, SystemClock
from shared.temporal.instant import TemporalError, parse_instant_strict

START = parse_instant_strict("2026-07-01T00:00:00Z")


def test_system_clock_is_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo == timezone.utc
    assert isinstance(SystemClock().monotonic(), float)


def test_fixed_clock_freezes_and_advances():
    clock = FixedClock(START)
    assert clock.now() == START
    assert clock.now() == START
    clock.advance(90)
    assert (clock.now() - START).total_seconds() == 90
    assert clock.monotonic() == 90


def test_stepping_clock_strictly_increases():
    clock = SteppingClock(START, step_seconds=2)
    first, second, third = clock.now(), clock.now(), clock.now()
    assert (second - first).total_seconds() == 2
    assert (third - second).total_seconds() == 2


def test_clocks_satisfy_protocol():
    for instance in (SystemClock(), FixedClock(START), SteppingClock(START)):
        assert isinstance(instance, Clock)


def test_fixed_clock_rejects_naive_start():
    from datetime import datetime

    with pytest.raises(TemporalError):
        FixedClock(datetime(2026, 7, 1))
