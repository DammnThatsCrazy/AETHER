"""Temporal envelopes plus skew/lag computation and state classification."""
from __future__ import annotations

import pytest

from shared.temporal.authority import (
    TEMPORAL_AUTHORITIES,
    classify_temporal_state,
    compute_clock_skew_ms,
    compute_delivery_lag_ms,
    elapsed_ms,
)
from shared.temporal.envelope import (
    CLOCK_SOURCES,
    TEMPORAL_STATES,
    TIME_ZONE_SOURCES,
    EventTemporalEnvelope,
    TemporalEnvelope,
)
from shared.temporal.instant import parse_instant_strict

T0 = parse_instant_strict("2026-07-01T12:00:00Z")
T0_PLUS_2S = parse_instant_strict("2026-07-01T12:00:02Z")


def test_elapsed_and_skew_lag_math():
    assert elapsed_ms(T0, T0_PLUS_2S) == 2000
    assert compute_clock_skew_ms(T0_PLUS_2S, T0) == 2000  # client clock ahead
    assert compute_clock_skew_ms(T0, T0_PLUS_2S) == -2000  # client behind
    assert compute_delivery_lag_ms(T0, T0_PLUS_2S) == 2000
    assert compute_delivery_lag_ms(T0_PLUS_2S, T0) == 0  # lag never negative


BOUNDS = dict(max_future_skew_ms=300_000, warn_skew_ms=30_000, max_lateness_ms=86_400_000)


def test_classify_valid():
    state, reasons = classify_temporal_state(
        clock_skew_ms=500, delivery_lag_ms=200, source_time_zone_known=True, **BOUNDS
    )
    assert state == "valid" and reasons == []


def test_classify_future_beyond_tolerance():
    state, reasons = classify_temporal_state(
        clock_skew_ms=600_000, delivery_lag_ms=0, source_time_zone_known=True, **BOUNDS
    )
    assert state == "future" and reasons == ["timestamp_future"]


def test_classify_late_beyond_lateness():
    state, reasons = classify_temporal_state(
        clock_skew_ms=-90_000_000, delivery_lag_ms=None, source_time_zone_known=True, **BOUNDS
    )
    assert state == "late" and "timestamp_too_old" in reasons


def test_classify_skew_warning_band():
    state, reasons = classify_temporal_state(
        clock_skew_ms=60_000, delivery_lag_ms=0, source_time_zone_known=True, **BOUNDS
    )
    assert state == "skewed" and reasons == ["clock_skew_warning"]


def test_classify_timezone_unknown_is_warn_only():
    state, reasons = classify_temporal_state(
        clock_skew_ms=0, delivery_lag_ms=0, source_time_zone_known=False, **BOUNDS
    )
    assert state == "timezone_unknown"
    assert reasons == ["temporal_provenance_missing"]


def test_event_envelope_bronze_dump_is_json_safe():
    envelope = EventTemporalEnvelope(
        occurred_at=T0,
        received_at=T0_PLUS_2S,
        source_time_zone="America/New_York",
        source_utc_offset_minutes=-240,
        time_zone_source="device",
        clock_source="device",
        clock_skew_ms=-2000,
        temporal_state="valid",
    )
    dumped = envelope.model_dump_bronze()
    assert dumped["occurred_at"].endswith("Z") or "+" in dumped["occurred_at"]
    assert "sent_at" not in dumped  # exclude_none
    assert dumped["temporal_state"] == "valid"


def test_event_envelope_rejects_unknown_fields_and_values():
    with pytest.raises(Exception):
        EventTemporalEnvelope(
            occurred_at=T0, received_at=T0, temporal_state="nonsense"
        )
    with pytest.raises(Exception):
        EventTemporalEnvelope(occurred_at=T0, received_at=T0, bogus_field=1)


def test_bitemporal_envelope_mirror_fields():
    envelope = TemporalEnvelope(
        event_time="2026-07-01T12:00:00Z",
        observed_time="2026-07-01T12:00:02Z",
        first_seen="2026-07-01T12:00:00Z",
        last_seen="2026-07-01T12:00:00Z",
        valid_from="2026-07-01T12:00:00Z",
        recorded_at="2026-07-01T12:00:02Z",
        lifecycle_state="active",
    )
    assert envelope.valid_to is None and envelope.superseded_at is None


def test_vocabularies_are_nonempty_and_unique():
    for vocab in (TEMPORAL_STATES, TIME_ZONE_SOURCES, CLOCK_SOURCES, TEMPORAL_AUTHORITIES):
        assert len(vocab) == len(set(vocab)) and len(vocab) > 0
