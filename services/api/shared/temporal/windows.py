"""DST-safe conversion of local calendar ranges to exact UTC intervals.

A local date is NOT an instant: ``2026-07-01`` only becomes a window once an
IANA zone (and boundary policy) is applied. All intervals are half-open
``[start, end_exclusive)`` so adjacent windows never overlap and never gap.

DST policies (spec vocabulary):
- gap (spring-forward, local time does not exist): ``shift_forward`` | ``reject``
- overlap (fall-back, local time occurs twice): ``earlier_offset`` |
  ``later_offset`` | ``reject``
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

from shared.temporal.instant import TemporalError
from shared.temporal.zones import require_valid_zone

GapPolicy = Literal["shift_forward", "reject"]
OverlapPolicy = Literal["earlier_offset", "later_offset", "reject"]

GAP_POLICIES: tuple[str, ...] = ("shift_forward", "reject")
OVERLAP_POLICIES: tuple[str, ...] = ("earlier_offset", "later_offset", "reject")


def _classify_local(dt_fold0: datetime) -> str:
    """Classify a wall-clock time in its zone: ``unique`` | ``gap`` | ``overlap``.

    Uses PEP 495: for ambiguous times fold=0/fold=1 map to different offsets;
    for nonexistent times the round-trip through UTC does not reproduce the
    wall time.
    """
    # Gap first: a nonexistent wall time never survives the UTC roundtrip.
    # (In BOTH gaps and folds the fold-0/fold-1 offsets differ, so the offset
    # comparison alone cannot distinguish them.)
    roundtrip = dt_fold0.astimezone(timezone.utc).astimezone(dt_fold0.tzinfo)
    if (roundtrip.hour, roundtrip.minute, roundtrip.second) != (
        dt_fold0.hour,
        dt_fold0.minute,
        dt_fold0.second,
    ):
        return "gap"
    if dt_fold0.utcoffset() != dt_fold0.replace(fold=1).utcoffset():
        return "overlap"
    return "unique"


def resolve_local_datetime(
    local: datetime,
    zone_id: str,
    *,
    gap_policy: GapPolicy = "shift_forward",
    overlap_policy: OverlapPolicy = "earlier_offset",
) -> datetime:
    """Resolve a naive local wall-clock datetime in ``zone_id`` to a UTC instant.

    ``local`` must be naive (it is a wall-clock reading, not an instant).
    """
    if local.tzinfo is not None:
        raise TemporalError(
            "timestamp_invalid", "resolve_local_datetime expects a naive wall-clock value"
        )
    zone = require_valid_zone(zone_id)
    candidate = local.replace(tzinfo=zone, fold=0)
    kind = _classify_local(candidate)
    if kind == "gap":
        if gap_policy == "reject":
            raise TemporalError(
                "local_time_nonexistent",
                f"{local.isoformat()} does not exist in {zone_id} (DST gap)",
            )
        # PEP 495 fold=0 maps a nonexistent wall time forward across the gap.
        return candidate.astimezone(timezone.utc)
    if kind == "overlap":
        if overlap_policy == "reject":
            raise TemporalError(
                "local_time_ambiguous",
                f"{local.isoformat()} occurs twice in {zone_id} (DST overlap)",
            )
        fold = 0 if overlap_policy == "earlier_offset" else 1
        return candidate.replace(fold=fold).astimezone(timezone.utc)
    return candidate.astimezone(timezone.utc)


def local_date_window_utc(
    start_date: date,
    end_date_exclusive: date,
    zone_id: str,
    *,
    day_start: Optional[time] = None,
    gap_policy: GapPolicy = "shift_forward",
    overlap_policy: OverlapPolicy = "earlier_offset",
) -> tuple[datetime, datetime]:
    """Convert a half-open local-date range to a half-open UTC instant interval.

    Example: ``2026-07-01 .. 2026-08-01`` in ``America/New_York`` →
    ``[2026-07-01T04:00Z, 2026-08-01T04:00Z)``.
    """
    if end_date_exclusive <= start_date:
        raise TemporalError(
            "timestamp_invalid",
            f"end_date_exclusive {end_date_exclusive} must be after start_date {start_date}",
        )
    boundary = day_start or time(0, 0, 0)
    start = resolve_local_datetime(
        datetime.combine(start_date, boundary),
        zone_id,
        gap_policy=gap_policy,
        overlap_policy=overlap_policy,
    )
    end = resolve_local_datetime(
        datetime.combine(end_date_exclusive, boundary),
        zone_id,
        gap_policy=gap_policy,
        overlap_policy=overlap_policy,
    )
    return start, end


def local_day_window_utc(
    day: date,
    zone_id: str,
    *,
    gap_policy: GapPolicy = "shift_forward",
    overlap_policy: OverlapPolicy = "earlier_offset",
) -> tuple[datetime, datetime]:
    """One local calendar day as a half-open UTC interval (23h/24h/25h on DST days)."""
    return local_date_window_utc(
        day,
        day + timedelta(days=1),
        zone_id,
        gap_policy=gap_policy,
        overlap_policy=overlap_policy,
    )


__all__ = [
    "GapPolicy",
    "OverlapPolicy",
    "GAP_POLICIES",
    "OVERLAP_POLICIES",
    "resolve_local_datetime",
    "local_date_window_utc",
    "local_day_window_utc",
]
