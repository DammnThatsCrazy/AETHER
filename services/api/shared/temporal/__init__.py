"""Temporal Integrity kernel — the canonical owner of exact instants,
IANA zones, injectable clocks, DST-safe windows/recurrence, temporal
authorities, and temporal envelopes.

No other module may implement timezone parsing or calendar rules; legacy
helpers (``shared.common.common.parse_iso``) remain only as compatibility
call sites. TS twin vocabularies: ``packages/shared/temporal.ts``.
"""

from shared.temporal.authority import (
    TEMPORAL_AUTHORITIES,
    TemporalAuthority,
    classify_temporal_state,
    compute_clock_skew_ms,
    compute_delivery_lag_ms,
    elapsed_ms,
)
from shared.temporal.clock import SYSTEM_CLOCK, Clock, FixedClock, SteppingClock, SystemClock
from shared.temporal.envelope import (
    CLOCK_SOURCES,
    TEMPORAL_PRECISIONS,
    TEMPORAL_STATES,
    TIME_ZONE_SOURCES,
    ClockSource,
    EventTemporalEnvelope,
    TemporalEnvelope,
    TemporalPrecision,
    TemporalState,
    TimeZoneSource,
)
from shared.temporal.instant import (
    TEMPORAL_REASON_CODES,
    TemporalError,
    TemporalReasonCode,
    ensure_aware_utc,
    parse_instant_strict,
    to_iso_utc,
    try_parse_instant,
)
from shared.temporal.recurrence import (
    RECURRENCE_FREQUENCIES,
    RecurrenceFrequency,
    next_occurrence_utc,
)
from shared.temporal.windows import (
    GAP_POLICIES,
    OVERLAP_POLICIES,
    GapPolicy,
    OverlapPolicy,
    local_date_window_utc,
    local_day_window_utc,
    resolve_local_datetime,
)
from shared.temporal.zones import (
    is_valid_iana_zone,
    local_key,
    offset_minutes_at,
    require_valid_zone,
    require_zone_offset_consistent,
    tzdb_version,
    zone_offset_consistent,
)

__all__ = [
    # instant
    "TemporalError",
    "TemporalReasonCode",
    "TEMPORAL_REASON_CODES",
    "parse_instant_strict",
    "ensure_aware_utc",
    "to_iso_utc",
    "try_parse_instant",
    # zones
    "is_valid_iana_zone",
    "require_valid_zone",
    "offset_minutes_at",
    "zone_offset_consistent",
    "require_zone_offset_consistent",
    "tzdb_version",
    "local_key",
    # clock
    "Clock",
    "SystemClock",
    "FixedClock",
    "SteppingClock",
    "SYSTEM_CLOCK",
    # windows
    "GapPolicy",
    "OverlapPolicy",
    "GAP_POLICIES",
    "OVERLAP_POLICIES",
    "resolve_local_datetime",
    "local_date_window_utc",
    "local_day_window_utc",
    # recurrence
    "RecurrenceFrequency",
    "RECURRENCE_FREQUENCIES",
    "next_occurrence_utc",
    # envelope
    "TemporalState",
    "TEMPORAL_STATES",
    "TimeZoneSource",
    "TIME_ZONE_SOURCES",
    "ClockSource",
    "CLOCK_SOURCES",
    "TemporalPrecision",
    "TEMPORAL_PRECISIONS",
    "EventTemporalEnvelope",
    "TemporalEnvelope",
    # authority
    "TemporalAuthority",
    "TEMPORAL_AUTHORITIES",
    "elapsed_ms",
    "compute_clock_skew_ms",
    "compute_delivery_lag_ms",
    "classify_temporal_state",
]
