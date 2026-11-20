"""Typed repositories bind ISO-8601 strings for ``*_at`` columns as aware datetimes."""

from datetime import datetime

from repositories.typed_repo import _instant


def test_iso_strings_for_timestamp_columns_become_aware_datetimes():
    for raw in ("2026-11-20T10:00:00+00:00", "2026-11-20T10:00:00Z"):
        value = _instant("executed_at", raw)
        assert isinstance(value, datetime) and value.tzinfo is not None


def test_other_columns_and_unparseable_values_pass_through():
    assert _instant("status", "2026-11-20T10:00:00Z") == "2026-11-20T10:00:00Z"
    assert _instant("executed_at", "not a time") == "not a time"
    assert _instant("executed_at", None) is None
    moment = datetime(2026, 11, 20)
    assert _instant("executed_at", moment) is moment
