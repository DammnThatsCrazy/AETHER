"""Unit tests for the shared event-time parser (audit finding H, TASK H).

``shared.common.common.parse_event_time`` centralizes the ISO-8601 event-time
parsing that used to be duplicated (with the same rules) across
``services/measurement/engine/attribution_engine.py`` and
``services/attribution/resolver.py``. It mirrors the accept/reject rule
enforced by ``BaseEvent.validate_timestamp`` (services/ingestion/batch.py):
same ``datetime.fromisoformat(value.replace("Z", "+00:00"))`` call, no
additional accepted formats invented.
"""

from __future__ import annotations

import os

from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.ingestion.batch import BaseEvent  # noqa: E402
from shared.common.common import parse_event_time  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Required cases (valid string / datetime input / empty / None / garbage / naive)
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_iso_string_with_z_returns_aware_utc_datetime():
    result = parse_event_time("2026-01-01T12:00:00Z")
    assert result == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_datetime_instance_input_is_normalized():
    # Already tz-aware: returned as-is (offset preserved, not forced to UTC).
    aware = datetime(2026, 3, 15, 8, 30, 0, tzinfo=timezone(timedelta(hours=5)))
    result = parse_event_time(aware)
    assert result == aware
    assert result.tzinfo == aware.tzinfo


def test_empty_string_returns_none():
    assert parse_event_time("") is None


def test_none_returns_none():
    assert parse_event_time(None) is None


def test_unparseable_string_returns_none():
    assert parse_event_time("not-a-date") is None


def test_naive_iso_string_without_tz_normalizes_to_utc():
    # No offset / no "Z" — datetime.fromisoformat still accepts this (it is
    # NOT rejected), and the canonical rule assumes UTC rather than an
    # inferred local zone, matching _parse_ts / _event_reference_time.
    result = parse_event_time("2026-01-01T12:00:00")
    assert result == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_naive_datetime_instance_is_stamped_utc():
    naive = datetime(2026, 6, 1, 9, 0, 0)
    result = parse_event_time(naive)
    assert result == datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Additional coverage
# ─────────────────────────────────────────────────────────────────────────────

def test_iso_string_with_explicit_offset_is_preserved_not_forced_to_utc():
    result = parse_event_time("2026-01-01T12:00:00+05:00")
    assert result.utcoffset() == timedelta(hours=5)
    # Still the correct instant when compared against an equivalent UTC value.
    assert result == datetime(2026, 1, 1, 7, 0, 0, tzinfo=timezone.utc)


def test_non_string_non_datetime_unparseable_value_returns_none():
    assert parse_event_time(["2026-01-01T12:00:00Z"]) is None
    assert parse_event_time({"iso": "2026-01-01T12:00:00Z"}) is None


# ─────────────────────────────────────────────────────────────────────────────
# Canonical-rule cross-check: parse_event_time must accept/reject exactly what
# BaseEvent.validate_timestamp (services/ingestion/batch.py) accepts/rejects.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    [
        "2026-01-01T12:00:00Z",
        "2026-01-01T12:00:00+05:00",
        "2026-01-01T12:00:00",
        "2026-01-01",
        "not-a-date",
        "",
    ],
)
def test_matches_base_event_validate_timestamp_accept_reject(value):
    try:
        BaseEvent.validate_timestamp(value)
        accepted_by_canonical_rule = True
    except ValueError:
        accepted_by_canonical_rule = False

    parsed = parse_event_time(value)
    assert (parsed is not None) == accepted_by_canonical_rule, (
        f"parse_event_time({value!r}) disagreed with BaseEvent.validate_timestamp: "
        f"parsed={parsed!r} canonical_accepts={accepted_by_canonical_rule}"
    )
