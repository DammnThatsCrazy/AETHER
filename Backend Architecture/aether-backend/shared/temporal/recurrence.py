"""DST-safe wall-clock recurrence.

Business schedules recur in LOCAL wall-clock time within an IANA zone ("every
day at 09:00 in America/New_York"), so each occurrence must be resolved
through the zone with explicit DST gap/overlap policies — never by adding a
fixed duration to the previous UTC instant (retries and timeouts use elapsed
``Duration`` math instead, via the monotonic clock).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal

from shared.temporal.instant import TemporalError, ensure_aware_utc
from shared.temporal.windows import GapPolicy, OverlapPolicy, resolve_local_datetime
from shared.temporal.zones import require_valid_zone

RecurrenceFrequency = Literal["daily", "weekly", "monthly"]

RECURRENCE_FREQUENCIES: tuple[str, ...] = ("daily", "weekly", "monthly")


def _advance_local_date(day: date, frequency: str) -> date:
    if frequency == "daily":
        return day + timedelta(days=1)
    if frequency == "weekly":
        return day + timedelta(days=7)
    if frequency == "monthly":
        year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
        # Clamp to the target month's last day (Jan 31 → Feb 28/29), keeping
        # calendar semantics instead of pretending a month is 30 days.
        for dom in (day.day, 30, 29, 28):
            try:
                return date(year, month, dom)
            except ValueError:
                continue
        raise AssertionError("unreachable: every month has a 28th")
    raise TemporalError("temporal_policy_violation", f"unknown recurrence frequency {frequency!r}")


def next_occurrence_utc(
    *,
    after: datetime,
    local_time_of_day: time,
    zone_id: str,
    frequency: RecurrenceFrequency = "daily",
    gap_policy: GapPolicy = "shift_forward",
    overlap_policy: OverlapPolicy = "earlier_offset",
    max_scan_days: int = 62,
) -> datetime:
    """The next scheduled UTC instant STRICTLY after ``after``.

    Walks local calendar days (so a 23-hour DST day still fires once) and
    resolves each candidate wall time through the zone with the given
    policies. ``gap_policy="reject"`` skips occurrences that fall in a DST
    gap rather than failing the schedule.
    """
    zone = require_valid_zone(zone_id)
    after_utc = ensure_aware_utc(after)
    local_cursor = after_utc.astimezone(zone).date()
    scanned = 0
    while scanned <= max_scan_days:
        candidate_local = datetime.combine(local_cursor, local_time_of_day)
        try:
            candidate = resolve_local_datetime(
                candidate_local,
                zone_id,
                gap_policy=gap_policy,
                overlap_policy=overlap_policy,
            )
        except TemporalError as exc:
            if exc.reason_code == "local_time_nonexistent":
                candidate = None  # skipped by policy
            else:
                raise
        if candidate is not None and candidate > after_utc:
            return candidate
        step = 1 if frequency == "daily" else 0
        if frequency == "daily":
            local_cursor = local_cursor + timedelta(days=step)
        else:
            local_cursor = _advance_local_date(local_cursor, frequency)
        scanned += 1 if frequency == "daily" else 31
    raise TemporalError(
        "temporal_policy_violation",
        f"no next occurrence within {max_scan_days} days for {frequency} schedule in {zone_id}",
    )


__all__ = [
    "RecurrenceFrequency",
    "RECURRENCE_FREQUENCIES",
    "next_occurrence_utc",
]
