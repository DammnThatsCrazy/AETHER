"""Temporal segmentation for IncentiveContext (§32) + DST-safe window conversion.

Segment-boundary assumptions (RECORDED decision — the blueprint treats boundary
choice as an explicit, documented decision; external spec §§30-33 govern the
segment vocabulary):

1. Every interval is HALF-OPEN ``[start, end)`` so adjacent segments never
   overlap and never gap. An activity at exactly ``exposure_started_at`` is
   INCENTIVE_WINDOW; an activity at exactly ``exposure_ended_at`` is
   POST_INCENTIVE.
2. The incentive window segment is the anchor: ``[exposure_started_at,
   exposure_ended_at)`` — the campaign/reward exposure window the context
   resolves against.
3. PRE_INCENTIVE / POST_INCENTIVE outer bounds are EVIDENCE-BOUNDED by default:
   the pre segment starts at the earliest supplied activity strictly before the
   window; the post segment ends at the latest supplied activity at/after the
   window end. No magic look-back/look-forward constant is invented. When no
   activity exists on a side, that segment is NOT emitted (a "persistence of
   zero" is never manufactured from an unobserved horizon).
4. A caller MAY supply an explicit ``pre_start`` / ``post_end`` (e.g. the
   campaign's registration horizon). When an explicit outer bound is supplied,
   the segment IS emitted and its ``interaction_count`` is the true count over
   the supplied timeline within those bounds (0 is a real measurement then).
5. ``interaction_count`` is measured over the timeline observations supplied to
   the resolver — never extrapolated to un-supplied activity. If the count is
   not derivable it stays ``None`` (unknown, not 0).
6. Boundary conversion: an aware UTC datetime is used as-is. A naive datetime
   without ``zone_id`` is read as UTC (the repo stores UTC instants). A naive
   local datetime (or local date) WITH ``zone_id`` is resolved DST-safely
   through ``shared.temporal.windows.py`` (gap → shift_forward, overlap →
   earlier_offset by default).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Optional

from shared.temporal.instant import coerce_utc_lenient
from shared.temporal.windows import (
    local_date_window_utc,
    resolve_local_datetime,
)

from .canonical import (
    INCENTIVE_WINDOW,
    POST_INCENTIVE,
    PRE_INCENTIVE,
    SEGMENT_BOUNDARY_POLICY,
)
from .models import TemporalSegment

__all__ = [
    "SEGMENT_BOUNDARY_POLICY",
    "campaign_window_utc",
    "parse_boundary",
    "segment_timeline",
]

_UTC = timezone.utc


def parse_boundary(value: object) -> Optional[datetime]:
    """Parse ``None`` / ISO str / datetime into an aware UTC datetime.

    Naive datetimes are read as UTC (recorded assumption 6); strings with a
    trailing ``Z`` are accepted. Returns ``None`` for ``None`` input so callers
    can keep optional boundaries optional.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        # A bare date is a whole local/UTC calendar day; without a zone we read
        # it as UTC midnight (an instant, so day boundaries are exact).
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"not an ISO datetime: {value!r}") from exc
    else:
        raise TypeError(
            f"expected datetime/date/ISO string, got {type(value).__name__}"
        )
    if dt.tzinfo is None:
        # The "naive wall-clock reads as UTC" policy lives in the temporal
        # kernel (the only module permitted to attach a timezone).
        dt = coerce_utc_lenient(dt)
    return dt.astimezone(_UTC)


def campaign_window_utc(
    start: object,
    end: object,
    *,
    zone_id: Optional[str] = None,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Resolve a campaign exposure window to a half-open UTC pair.

    DST-safe when the campaign declares LOCAL boundaries (a naive local
    datetime, or a start/end local date pair) plus ``zone_id`` — delegation to
    ``shared.temporal.windows.local_date_window_utc`` /
    ``resolve_local_datetime`` (gap → shift_forward, overlap → earlier_offset).
    An aware boundary is used as-is. ``end`` is exclusive (half-open).
    """
    if zone_id is not None and isinstance(start, date) and isinstance(end, date) \
            and not isinstance(start, datetime) and not isinstance(end, datetime):
        # Local calendar-date window [start, end) resolved DST-safely.
        lo, hi = local_date_window_utc(start, end, zone_id)
        return lo, hi
    start_utc = parse_boundary(start)
    end_utc = parse_boundary(end)
    if zone_id is not None and isinstance(start, datetime) and start.tzinfo is None:
        start_utc = resolve_local_datetime(
            start, zone_id, gap_policy="shift_forward", overlap_policy="earlier_offset"
        )
    if zone_id is not None and isinstance(end, datetime) and end.tzinfo is None:
        end_utc = resolve_local_datetime(
            end, zone_id, gap_policy="shift_forward", overlap_policy="earlier_offset"
        )
    return start_utc, end_utc


def _as_utc(dt: datetime) -> datetime:
    """Read a naive wall-clock as UTC (policy lives in the temporal kernel)."""
    if dt.tzinfo is not None:
        return dt
    aware = coerce_utc_lenient(dt)
    if aware is None:  # pragma: no cover -- a datetime input always coerces
        raise TypeError(f"uncoercible datetime: {dt!r}")
    return aware


def segment_timeline(
    exposure_started_at: datetime,
    exposure_ended_at: Optional[datetime],
    timeline: Iterable[datetime],
    *,
    pre_start: Optional[object] = None,
    post_end: Optional[object] = None,
    pre_note: Optional[str] = None,
    post_note: Optional[str] = None,
) -> list[TemporalSegment]:
    """Segment a timeline into PRE_INCENTIVE / INCENTIVE_WINDOW / POST_INCENTIVE.

    ``exposure_started_at`` is required (the anchor). ``exposure_ended_at`` may
    be ``None`` (an open-ended/active window) — then there is no INCENTIVE →
    POST boundary and only a PRE segment can be produced. Boundary assumptions
    are recorded in each segment's ``notes`` (see module docstring).

    Returns segments in canonical order (PRE, INCENTIVE, POST).
    """
    start = _as_utc(exposure_started_at).astimezone(_UTC)
    if exposure_ended_at is None:
        end: Optional[datetime] = None
    else:
        end = _as_utc(exposure_ended_at).astimezone(_UTC)
    times = sorted(_as_utc(t).astimezone(_UTC) for t in timeline if t is not None)

    if end is not None and end <= start:
        raise ValueError(
            "exposure_ended_at must be strictly after exposure_started_at "
            "(half-open [start, end) requires start < end)"
        )

    segments: list[TemporalSegment] = []

    # ---- PRE_INCENTIVE [lo, start) ----------------------------------------
    pre_lo = None
    if pre_start is not None:
        pre_lo = parse_boundary(pre_start)
        if pre_lo is not None and pre_lo.astimezone(_UTC) >= start:
            raise ValueError("pre_start must be strictly before exposure_started_at")
    pre_observations = [t for t in times if t < start]
    if pre_lo is not None or pre_observations:
        lo = pre_lo or (min(pre_observations) if pre_observations else None)
        if lo is not None:
            note = pre_note or (
                "PRE_INCENTIVE outer bound supplied by caller"
                if pre_lo is not None
                else "PRE_INCENTIVE outer bound evidence-bounded to earliest "
                     "observed activity before the window"
            )
            note = f"{note}; {SEGMENT_BOUNDARY_POLICY}"
            segments.append(
                TemporalSegment(
                    segment=PRE_INCENTIVE,
                    started_at=lo.astimezone(_UTC),
                    ended_at=start,
                    interaction_count=sum(1 for t in pre_observations if lo <= t < start),
                    notes=note,
                )
            )

    # ---- INCENTIVE_WINDOW [start, end) -------------------------------------
    if end is None:
        window_obs = [t for t in times if t >= start]
        window_note = (
            "INCENTIVE_WINDOW is open-ended (no exposure_ended_at recorded); "
            "ended_at reflects the latest observed activity within it "
            f"(not a claimed campaign end); {SEGMENT_BOUNDARY_POLICY}"
        )
        # An open window with no observed activity has no honest ended_at; do
        # not fabricate a zero-width or guessed segment.
        if not window_obs:
            window_obs = None
    else:
        window_obs = [t for t in times if start <= t < end]
        window_note = f"anchor segment [exposure_start, exposure_end); {SEGMENT_BOUNDARY_POLICY}"
    if window_obs is not None:
        window_end = end if end is not None else window_obs[-1]
        segments.append(
            TemporalSegment(
                segment=INCENTIVE_WINDOW,
                started_at=start,
                ended_at=window_end,
                interaction_count=len(window_obs),
                notes=window_note,
            )
        )

    # ---- POST_INCENTIVE [end, hi) -------------------------------------------
    if end is not None:
        post_hi = None
        if post_end is not None:
            post_hi = parse_boundary(post_end)
            if post_hi is not None and post_hi.astimezone(_UTC) <= end:
                raise ValueError("post_end must be strictly after exposure_ended_at")
        post_observations = [t for t in times if t >= end]
        if post_hi is not None or post_observations:
            hi = post_hi or max(post_observations)
            note = post_note or (
                "POST_INCENTIVE outer bound supplied by caller"
                if post_hi is not None
                else "POST_INCENTIVE outer bound evidence-bounded to latest "
                     "observed activity at/after window end"
            )
            note = f"{note}; {SEGMENT_BOUNDARY_POLICY}"
            segments.append(
                TemporalSegment(
                    segment=POST_INCENTIVE,
                    started_at=end,
                    ended_at=hi.astimezone(_UTC),
                    interaction_count=sum(1 for t in post_observations if end <= t <= hi),
                    notes=note,
                )
            )
    return segments


def timeline_overlaps_window(
    activity_occurred_at: object,
    exposure_started_at: object,
    exposure_ended_at: object,
) -> str:
    """Classify one instant against a half-open exposure window.

    Returns ``in`` / ``out`` / ``unknown``. ``out`` is only returned when the
    window bounds are known AND the instant is known to fall outside them;
    missing information yields ``unknown`` (never a guess).
    """
    activity = parse_boundary(activity_occurred_at)
    start = parse_boundary(exposure_started_at)
    end = parse_boundary(exposure_ended_at)
    if activity is None:
        return "unknown"
    if start is not None and activity < start:
        return "out"
    if end is not None and activity >= end:
        return "out"
    if start is not None or end is not None:
        return "in"
    return "unknown"
