"""Wall-clock recurrence across DST: next occurrence is strictly later."""
from __future__ import annotations

from datetime import time

import pytest

# NOTE: all shared.temporal imports bind at collection time (one module
# generation) — some legacy suites pop shared.* from sys.modules mid-run, so a
# mid-test re-import would see a DIFFERENT TemporalError class identity.
from shared.temporal.instant import TemporalError, parse_instant_strict, to_iso_utc
from shared.temporal.recurrence import next_occurrence_utc

NY = "America/New_York"


def test_daily_occurrence_tracks_wall_clock_across_spring_forward():
    # 09:00 local daily: the UTC instant shifts by an hour across DST.
    before = parse_instant_strict("2026-03-07T15:00:00Z")  # Mar 7, 10:00 EST
    first = next_occurrence_utc(after=before, local_time_of_day=time(9, 0), zone_id=NY)
    assert to_iso_utc(first) == "2026-03-08T13:00:00Z"  # 09:00 EDT (gap day)
    second = next_occurrence_utc(after=first, local_time_of_day=time(9, 0), zone_id=NY)
    assert to_iso_utc(second) == "2026-03-09T13:00:00Z"


def test_occurrence_in_dst_gap_shifts_forward_by_default():
    before = parse_instant_strict("2026-03-08T00:00:00Z")
    occurrence = next_occurrence_utc(
        after=before, local_time_of_day=time(2, 30), zone_id=NY
    )
    # 02:30 does not exist on 2026-03-08; shift-forward resolves across the gap.
    assert to_iso_utc(occurrence) == "2026-03-08T07:30:00Z"


def test_occurrence_in_gap_skipped_when_rejected():
    before = parse_instant_strict("2026-03-08T00:00:00Z")
    occurrence = next_occurrence_utc(
        after=before, local_time_of_day=time(2, 30), zone_id=NY, gap_policy="reject"
    )
    # The gap-day occurrence is skipped; next valid day fires at 02:30 EDT.
    assert to_iso_utc(occurrence) == "2026-03-09T06:30:00Z"


def test_next_occurrence_strictly_after():
    at_nine = parse_instant_strict("2026-07-01T13:00:00Z")  # exactly 09:00 EDT
    occurrence = next_occurrence_utc(after=at_nine, local_time_of_day=time(9, 0), zone_id=NY)
    assert occurrence > at_nine
    assert to_iso_utc(occurrence) == "2026-07-02T13:00:00Z"


def test_monthly_clamps_to_short_months():
    jan31 = parse_instant_strict("2026-01-31T15:00:00Z")
    occurrence = next_occurrence_utc(
        after=jan31, local_time_of_day=time(9, 0), zone_id=NY, frequency="monthly"
    )
    # Next monthly slot after Jan 31 09:00 EST clamps into February.
    assert to_iso_utc(occurrence) == "2026-02-28T14:00:00Z"


def test_weekly_frequency():
    before = parse_instant_strict("2026-07-01T00:00:00Z")
    first = next_occurrence_utc(
        after=before, local_time_of_day=time(9, 0), zone_id=NY, frequency="weekly"
    )
    second = next_occurrence_utc(
        after=first, local_time_of_day=time(9, 0), zone_id=NY, frequency="weekly"
    )
    assert (second - first).days == 7


def test_invalid_zone_rejected():
    with pytest.raises(TemporalError):
        next_occurrence_utc(
            after=parse_instant_strict("2026-07-01T00:00:00Z"),
            local_time_of_day=time(9, 0),
            zone_id="EST",
        )
