"""IANA zone validation, offset facts, and zone/offset consistency."""
from __future__ import annotations

import pytest

from shared.temporal.instant import TemporalError, parse_instant_strict
from shared.temporal.zones import (
    is_valid_iana_zone,
    local_key,
    offset_minutes_at,
    require_valid_zone,
    require_zone_offset_consistent,
    tzdb_version,
    zone_offset_consistent,
)

JAN = parse_instant_strict("2026-01-15T12:00:00Z")
JUL = parse_instant_strict("2026-07-15T12:00:00Z")


@pytest.mark.parametrize(
    "zone",
    ["UTC", "America/New_York", "Asia/Kolkata", "Australia/Lord_Howe", "Pacific/Chatham"],
)
def test_valid_iana_zones(zone):
    assert is_valid_iana_zone(zone)
    assert require_valid_zone(zone) is not None


@pytest.mark.parametrize("zone", ["EST", "CST", "PST", "IST", "US/Fake", "", "utc "])
def test_invalid_zones_rejected(zone):
    # Abbreviations are not persistent calendar authorities.
    if is_valid_iana_zone(zone):
        pytest.skip(f"{zone} exists in this tzdb build")
    with pytest.raises(TemporalError) as exc:
        require_valid_zone(zone)
    assert exc.value.reason_code == "timezone_invalid"


def test_offsets_track_dst():
    assert offset_minutes_at("America/New_York", JAN) == -300  # EST
    assert offset_minutes_at("America/New_York", JUL) == -240  # EDT


def test_half_hour_and_odd_offsets():
    assert offset_minutes_at("Asia/Kolkata", JUL) == 330       # +05:30
    assert offset_minutes_at("Asia/Kathmandu", JUL) == 345     # +05:45
    assert offset_minutes_at("Australia/Lord_Howe", JAN) == 660  # +11:00 (their DST)


def test_zone_offset_consistency():
    assert zone_offset_consistent("America/New_York", JUL, -240)
    assert not zone_offset_consistent("America/New_York", JUL, -300)
    require_zone_offset_consistent("America/New_York", JUL, -240)
    with pytest.raises(TemporalError) as exc:
        require_zone_offset_consistent("America/New_York", JUL, -300)
    assert exc.value.reason_code == "timezone_offset_mismatch"


def test_tzdb_version_reports_something():
    version = tzdb_version()
    assert isinstance(version, str) and version


def test_local_key_fallback():
    assert local_key("America/New_York") == "America/New_York"
    assert local_key(None) == "utc"
    assert local_key("EST") == "utc"
