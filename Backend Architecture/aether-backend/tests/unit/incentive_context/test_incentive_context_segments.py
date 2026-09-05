"""Temporal segmentation + DST-safe boundary resolution (M5 §32).

These tests pin the RECORDED segment-boundary decisions (see the module
docstring of ``services/incentive_context/segments.py``): half-open intervals,
evidence-bounded PRE/POST outer bounds by default, explicit outer bounds emit a
real zero count, naive-without-zone reads as UTC, and local boundaries resolve
DST-safely through ``shared/temporal/windows.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from services.incentive_context.canonical import (  # noqa: E402
    INCENTIVE_WINDOW,
    POST_INCENTIVE,
    PRE_INCENTIVE,
    SEGMENT_BOUNDARY_POLICY,
)
from services.incentive_context.segments import (  # noqa: E402
    campaign_window_utc,
    parse_boundary,
    segment_timeline,
    timeline_overlaps_window,
)

UTC = timezone.utc


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_half_open_segments_boundaries_are_explicit() -> None:
    """An activity exactly at exposure_start is IN; exactly at exposure_end POST."""
    start = _dt("2026-04-01T00:00:00Z")
    end = _dt("2026-06-01T00:00:00Z")
    timeline = [
        _dt("2026-03-01T00:00:00Z"),  # PRE
        start,                          # WINDOW (half-open lower bound inclusive)
        _dt("2026-05-01T00:00:00Z"),  # WINDOW
        end,                            # POST (half-open upper bound exclusive)
        _dt("2026-07-01T00:00:00Z"),  # POST
    ]
    segments = segment_timeline(start, end, timeline)
    assert [s.segment for s in segments] == [
        PRE_INCENTIVE, INCENTIVE_WINDOW, POST_INCENTIVE,
    ]
    pre, inc, post = segments
    assert pre.interaction_count == 1
    assert inc.interaction_count == 2
    assert post.interaction_count == 2
    assert pre.ended_at == inc.started_at == start
    assert inc.ended_at == post.started_at == end
    assert all(SEGMENT_BOUNDARY_POLICY in (s.notes or "") for s in segments)


def test_segments_are_adjacent_and_do_not_overlap() -> None:
    start, end = _dt("2026-04-01T00:00:00Z"), _dt("2026-06-01T00:00:00Z")
    segments = segment_timeline(
        start, end,
        [_dt("2026-03-01T00:00:00Z"), _dt("2026-04-15T00:00:00Z"),
         _dt("2026-06-15T00:00:00Z")],
    )
    bounds = []
    for s in segments:
        assert s.started_at < s.ended_at
        bounds.append((s.started_at, s.ended_at))
    assert bounds[0][1] == bounds[1][0]  # PRE end == WINDOW start
    assert bounds[1][1] == bounds[2][0]  # WINDOW end == POST start


def test_evidence_bounded_outer_bounds_omit_unobserved_sides() -> None:
    """No pre activity and no post activity => only the window segment."""
    start, end = _dt("2026-04-01T00:00:00Z"), _dt("2026-06-01T00:00:00Z")
    segments = segment_timeline(
        start, end, [_dt("2026-04-15T00:00:00Z"), _dt("2026-05-15T00:00:00Z")]
    )
    assert [s.segment for s in segments] == [INCENTIVE_WINDOW]
    # A persistence zero is never manufactured from an unobserved horizon.
    assert segments[0].interaction_count == 2


def test_explicit_outer_bounds_emit_real_zero_counts() -> None:
    """A caller-supplied pre_start / post_end bounds the segment even at zero."""
    start, end = _dt("2026-04-01T00:00:00Z"), _dt("2026-06-01T00:00:00Z")
    segments = segment_timeline(
        start,
        end,
        [_dt("2026-05-01T00:00:00Z")],
        pre_start=_dt("2026-01-01T00:00:00Z"),
        post_end=_dt("2026-08-01T00:00:00Z"),
    )
    assert [s.segment for s in segments] == [
        PRE_INCENTIVE, INCENTIVE_WINDOW, POST_INCENTIVE,
    ]
    assert segments[0].interaction_count == 0
    assert segments[1].interaction_count == 1
    assert segments[2].interaction_count == 0


def test_open_window_without_observed_activity_has_no_segment() -> None:
    """No exposure_ended_at and no window activity => no fabricated window."""
    start = _dt("2026-04-01T00:00:00Z")
    # Nothing observed at all -> nothing to segment; no degenerate zero-width
    # INCENTIVE segment is invented for an unbounded window.
    assert segment_timeline(start, None, []) == []
    # Only a pre-window observation -> only an honest PRE segment (the window
    # has no end to bound INCENTIVE/POST).
    segments = segment_timeline(start, None, [_dt("2026-03-01T00:00:00Z")])
    assert [s.segment for s in segments] == [PRE_INCENTIVE]


def test_open_window_with_observed_activity_closes_at_latest_observed() -> None:
    start = _dt("2026-04-01T00:00:00Z")
    obs = [_dt("2026-04-05T00:00:00Z"), _dt("2026-05-10T00:00:00Z")]
    segments = segment_timeline(start, None, obs)
    assert len(segments) == 1
    assert segments[0].segment == INCENTIVE_WINDOW
    assert segments[0].ended_at == obs[-1]
    assert "open-ended" in (segments[0].notes or "")


def test_local_dst_boundary_is_dst_safe() -> None:
    """America/New_York local dates resolve to correct UTC across spring-forward."""
    # 2026-03-08 is US spring-forward day (02:00 -> 03:00 EST->EDT).
    start, end = campaign_window_utc(
        date(2026, 3, 8), date(2026, 4, 1), zone_id="America/New_York"
    )
    # Midnight local 03-08 is EST (-05) => 05:00Z; midnight 04-01 is EDT (-04)
    # => 04:00Z. local_date_window_utc yields [start, end_exclusive).
    assert start == datetime(2026, 3, 8, 5, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 4, 1, 4, 0, 0, tzinfo=UTC)


def test_naive_boundary_without_zone_reads_as_utc() -> None:
    naive_start = datetime(2026, 4, 1, 0, 0, 0)
    start, end = campaign_window_utc(naive_start, datetime(2026, 6, 1, 0, 0, 0))
    assert start == datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def test_aware_boundary_passthrough_utc() -> None:
    aware = _dt("2026-04-01T00:00:00+02:00")
    start, end = campaign_window_utc(aware, None)
    assert end is None
    assert start == datetime(2026, 3, 31, 22, 0, 0, tzinfo=UTC)


def test_invalid_window_rejected() -> None:
    with pytest.raises(ValueError):
        segment_timeline(_dt("2026-06-01T00:00:00Z"), _dt("2026-04-01T00:00:00Z"), [])


def test_timeline_overlap_classification() -> None:
    start, end = _dt("2026-04-01T00:00:00Z"), _dt("2026-06-01T00:00:00Z")
    assert timeline_overlaps_window("2026-03-01T00:00:00Z", start, end) == "out"
    assert timeline_overlaps_window("2026-05-01T00:00:00Z", start, end) == "in"
    assert timeline_overlaps_window("2026-06-01T00:00:00Z", start, end) == "out"
    assert timeline_overlaps_window(None, start, end) == "unknown"


def test_parse_boundary_accepts_iso_and_z() -> None:
    parsed = parse_boundary("2026-04-01T00:00:00Z")
    assert parsed == datetime(2026, 4, 1, tzinfo=UTC)
    assert parse_boundary(None) is None
