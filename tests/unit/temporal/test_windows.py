"""DST-safe local-date windows: half-open, gap/overlap policies, partitioning."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from shared.temporal.instant import TemporalError, to_iso_utc
from shared.temporal.windows import (
    local_date_window_utc,
    local_day_window_utc,
    resolve_local_datetime,
)

NY = "America/New_York"


def test_ny_july_month_window_matches_spec_example():
    start, end = local_date_window_utc(date(2026, 7, 1), date(2026, 8, 1), NY)
    assert to_iso_utc(start) == "2026-07-01T04:00:00Z"
    assert to_iso_utc(end) == "2026-08-01T04:00:00Z"


def test_spring_forward_day_is_23_hours():
    # US DST starts 2026-03-08 (02:00 → 03:00 local).
    start, end = local_day_window_utc(date(2026, 3, 8), NY)
    assert (end - start) == timedelta(hours=23)


def test_fall_back_day_is_25_hours():
    # US DST ends 2026-11-01 (02:00 → 01:00 local).
    start, end = local_day_window_utc(date(2026, 11, 1), NY)
    assert (end - start) == timedelta(hours=25)


def test_adjacent_ranges_partition_without_gap_or_overlap():
    cursor = date(2026, 3, 6)
    previous_end = None
    for _ in range(6):  # crosses the spring-forward transition
        start, end = local_day_window_utc(cursor, NY)
        assert start < end
        if previous_end is not None:
            assert start == previous_end  # half-open: no gap, no overlap
        previous_end = end
        cursor += timedelta(days=1)


def test_gap_policy_reject_raises_nonexistent():
    # 02:30 does not exist on the US spring-forward day.
    with pytest.raises(TemporalError) as exc:
        resolve_local_datetime(
            datetime(2026, 3, 8, 2, 30), NY, gap_policy="reject"
        )
    assert exc.value.reason_code == "local_time_nonexistent"


def test_gap_policy_shift_forward_produces_valid_instant():
    resolved = resolve_local_datetime(datetime(2026, 3, 8, 2, 30), NY)
    # Shifted across the gap: 02:30 EST-claimed → 07:30Z (03:30 EDT).
    assert to_iso_utc(resolved) == "2026-03-08T07:30:00Z"


def test_overlap_policies_pick_each_occurrence():
    ambiguous = datetime(2026, 11, 1, 1, 30)  # occurs twice on fall-back day
    earlier = resolve_local_datetime(ambiguous, NY, overlap_policy="earlier_offset")
    later = resolve_local_datetime(ambiguous, NY, overlap_policy="later_offset")
    assert to_iso_utc(earlier) == "2026-11-01T05:30:00Z"  # EDT occurrence
    assert to_iso_utc(later) == "2026-11-01T06:30:00Z"    # EST occurrence
    with pytest.raises(TemporalError) as exc:
        resolve_local_datetime(ambiguous, NY, overlap_policy="reject")
    assert exc.value.reason_code == "local_time_ambiguous"


def test_rejects_aware_input_and_reversed_range():
    from datetime import timezone

    with pytest.raises(TemporalError):
        resolve_local_datetime(datetime(2026, 1, 1, tzinfo=timezone.utc), NY)
    with pytest.raises(TemporalError):
        local_date_window_utc(date(2026, 2, 1), date(2026, 1, 1), NY)


def test_custom_day_start_boundary():
    start, _ = local_date_window_utc(
        date(2026, 7, 1), date(2026, 7, 2), NY, day_start=time(9, 0)
    )
    assert to_iso_utc(start) == "2026-07-01T13:00:00Z"


def test_lord_howe_half_hour_dst():
    # Australia/Lord_Howe shifts by 30 minutes; a transition day is 23.5h.
    start, end = local_day_window_utc(date(2026, 10, 4), "Australia/Lord_Howe")
    assert (end - start) == timedelta(hours=23, minutes=30)
