"""Regression: behavioral/expectations staleness must be a dynamic freshness SLA
computed against the current time, never a hardcoded calendar date."""

from __future__ import annotations

from datetime import timedelta

from shared.common.common import utc_now
from services.behavioral.engines import _is_source_stale as behavioral_is_stale
from services.expectations.engine import _is_source_stale as expectations_is_stale


def _iso(days_ago: int) -> str:
    return (utc_now() - timedelta(days=days_ago)).isoformat()


def test_recent_is_not_stale():
    for fn in (behavioral_is_stale, expectations_is_stale):
        assert fn(_iso(1)) is False
        assert fn(_iso(10)) is False


def test_old_is_stale_relative_to_now():
    for fn in (behavioral_is_stale, expectations_is_stale):
        assert fn(_iso(120)) is True


def test_absent_or_unparseable_is_unknown_not_stale():
    for fn in (behavioral_is_stale, expectations_is_stale):
        assert fn("") is None
        assert fn(None) is None
        assert fn("not-a-timestamp") is None


def test_not_anchored_to_hardcoded_2026_03_01():
    # A date after the old hardcoded "2026-03-01" threshold that is nonetheless
    # older than the SLA must be stale (the old code called it fresh).
    old_but_after_march = utc_now() - timedelta(days=90)
    for fn in (behavioral_is_stale, expectations_is_stale):
        assert fn(old_but_after_march.isoformat()) is True
