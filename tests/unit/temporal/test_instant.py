"""Strict instant parsing: naive rejection, normalization, roundtrips."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.temporal.instant import (
    TEMPORAL_REASON_CODES,
    TemporalError,
    ensure_aware_utc,
    parse_instant_strict,
    to_iso_utc,
    try_parse_instant,
)


def test_parses_z_suffix_to_utc():
    dt = parse_instant_strict("2026-07-11T18:42:13.482731Z")
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2026 and dt.hour == 18 and dt.microsecond == 482731


def test_parses_explicit_offset_and_normalizes():
    dt = parse_instant_strict("2026-07-11T14:42:13.482-04:00")
    assert to_iso_utc(dt) == "2026-07-11T18:42:13.482000Z"


@pytest.mark.parametrize(
    "value",
    ["2026-07-11T14:42:13", "2026-07-11T14:42:13.482", "2026-07-11 14:42:13"],
)
def test_naive_timestamps_rejected(value):
    with pytest.raises(TemporalError) as exc:
        parse_instant_strict(value)
    assert exc.value.reason_code == "timestamp_naive"


@pytest.mark.parametrize("value", ["", "not-a-time", "2026-13-45T99:99:99Z", None, 12345])
def test_malformed_rejected(value):
    with pytest.raises(TemporalError) as exc:
        parse_instant_strict(value)  # type: ignore[arg-type]
    assert exc.value.reason_code == "timestamp_invalid"


def test_out_of_range_offset_rejected():
    with pytest.raises(TemporalError) as exc:
        parse_instant_strict("2026-07-11T14:42:13+15:00")
    assert exc.value.reason_code == "timezone_invalid"


def test_lowercase_z_accepted():
    assert to_iso_utc(parse_instant_strict("2026-07-11T18:00:00z")) == "2026-07-11T18:00:00Z"


def test_roundtrip_preserves_instant():
    original = "2026-01-01T00:00:00.000001Z"
    assert to_iso_utc(parse_instant_strict(original)) == "2026-01-01T00:00:00.000001Z"


def test_ensure_aware_utc_rejects_naive_datetime():
    with pytest.raises(TemporalError):
        ensure_aware_utc(datetime(2026, 1, 1))


def test_try_parse_returns_reason_code_instead_of_raising():
    instant, reason = try_parse_instant("2026-07-11T14:42:13")
    assert instant is None and reason == "timestamp_naive"
    instant, reason = try_parse_instant("2026-07-11T14:42:13Z")
    assert reason is None and instant is not None


def test_unknown_reason_code_rejected_by_error_type():
    with pytest.raises(ValueError):
        TemporalError("no_such_code", "boom")


def test_reason_code_vocabulary_is_stable():
    # Spec-stable codes must all be present (additions are fine, removals are not).
    for code in (
        "timestamp_invalid",
        "timestamp_naive",
        "timestamp_future",
        "timestamp_too_old",
        "timezone_invalid",
        "timezone_offset_mismatch",
        "local_time_ambiguous",
        "local_time_nonexistent",
        "temporal_authority_missing",
        "temporal_policy_violation",
    ):
        assert code in TEMPORAL_REASON_CODES
