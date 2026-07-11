"""Unit tests for the Tenant Import Engine dry-run mapping validator.

These exercise :func:`apply_transform` (each transform, happy path + failure)
and :func:`validate_mapping` (clean pass, missing column, missing required
field, transform failure, structural error, error cap, governance gating).
Everything here is synchronous and deterministic — no asyncio marks, no
wall-clock or randomness.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.imports.contracts import (  # noqa: E402
    ColumnProfile,
    FieldMapping,
)
from services.imports.validation import (  # noqa: E402
    apply_transform,
    validate_mapping,
)


# ── apply_transform: happy paths ────────────────────────────────────────────


def test_transform_none_passes_value_through():
    assert apply_transform("Value", "none") == "Value"


def test_transform_trim_strips_whitespace():
    assert apply_transform("  hello  ", "trim") == "hello"


def test_transform_lowercase_and_uppercase():
    assert apply_transform("MixEd", "lowercase") == "mixed"
    assert apply_transform("MixEd", "uppercase") == "MIXED"


def test_transform_to_timestamp_iso_string_normalizes_to_utc():
    assert apply_transform("2021-01-01T00:00:00Z", "to_timestamp") == (
        "2021-01-01T00:00:00+00:00"
    )


def test_transform_to_timestamp_naive_string_assumed_utc():
    assert apply_transform("2021-01-01T00:00:00", "to_timestamp") == (
        "2021-01-01T00:00:00+00:00"
    )


def test_transform_to_timestamp_epoch_seconds():
    # 1609459200 == 2021-01-01T00:00:00Z
    assert apply_transform("1609459200", "to_timestamp") == (
        "2021-01-01T00:00:00+00:00"
    )


def test_transform_to_timestamp_epoch_millis():
    # 1609459200000 ms == 2021-01-01T00:00:00Z; the larger magnitude selects ms.
    assert apply_transform("1609459200000", "to_timestamp") == (
        "2021-01-01T00:00:00+00:00"
    )


def test_transform_to_timestamp_is_deterministic():
    first = apply_transform("1609459200", "to_timestamp")
    second = apply_transform("1609459200", "to_timestamp")
    assert first == second


def test_transform_to_number_parses_float():
    assert apply_transform("3.14", "to_number") == pytest.approx(3.14)
    assert apply_transform("42", "to_number") == pytest.approx(42.0)


def test_transform_to_boolean_truthy_and_falsy():
    for truthy in ("true", "TRUE", "1", "Yes"):
        assert apply_transform(truthy, "to_boolean") is True
    for falsy in ("false", "FALSE", "0", "No"):
        assert apply_transform(falsy, "to_boolean") is False


def test_transform_hash_sha256_matches_hashlib():
    expected = hashlib.sha256("secret@example.com".encode("utf-8")).hexdigest()
    assert apply_transform("secret@example.com", "hash_sha256") == expected


def test_transform_json_parse_returns_object():
    assert apply_transform('{"a": 1, "b": [2, 3]}', "json_parse") == {
        "a": 1,
        "b": [2, 3],
    }


def test_transform_coalesce_empty_null():
    assert apply_transform("", "coalesce_empty_null") is None
    assert apply_transform("   ", "coalesce_empty_null") is None
    assert apply_transform("x", "coalesce_empty_null") == "x"


# ── apply_transform: failures raise ValueError ──────────────────────────────


def test_transform_to_timestamp_unparseable_raises():
    with pytest.raises(ValueError):
        apply_transform("not-a-date", "to_timestamp")


def test_transform_to_number_non_numeric_raises():
    with pytest.raises(ValueError):
        apply_transform("abc", "to_number")


def test_transform_to_boolean_unknown_raises():
    with pytest.raises(ValueError):
        apply_transform("maybe", "to_boolean")


def test_transform_json_parse_bad_json_raises():
    with pytest.raises(ValueError):
        apply_transform("{not json}", "json_parse")


def test_transform_unknown_name_raises():
    with pytest.raises(ValueError):
        apply_transform("x", "does_not_exist")


# ── fixtures / builders ─────────────────────────────────────────────────────


def _clean_fields() -> list[FieldMapping]:
    return [
        FieldMapping(
            source_column="email",
            primitive="entity",
            target_field="external_id",
            transform="trim",
            required=True,
        ),
        FieldMapping(
            source_column="name",
            primitive="entity",
            target_field="display_name",
            transform="none",
            required=False,
        ),
    ]


def _clean_columns() -> list[ColumnProfile]:
    return [
        ColumnProfile(name="email", sensitivity="none"),
        ColumnProfile(name="name", sensitivity="none"),
    ]


# ── validate_mapping ────────────────────────────────────────────────────────


def test_validate_all_rows_clean_ok_true():
    rows = [
        {"email": " a@x.com ", "name": "Ann"},
        {"email": "b@x.com", "name": "Bob"},
    ]
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=_clean_fields(),
        rows=rows,
        columns=_clean_columns(),
    )
    assert result.ok is True
    assert result.rows_total == 2
    assert result.rows_valid == 2
    assert result.rows_invalid == 0
    assert result.errors == []
    assert result.errors_truncated is False
    assert result.governance_review_required is False
    assert result.governance_reasons == []


def test_validate_required_field_empty():
    rows = [{"email": "   ", "name": "Ann"}]  # trims to '', required
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=_clean_fields(),
        rows=rows,
        columns=_clean_columns(),
    )
    assert result.ok is False
    assert result.rows_valid == 0
    assert result.rows_invalid == 1
    codes = [e.code for e in result.errors]
    assert codes == ["required_field_empty"]
    assert result.errors[0].row == 0
    assert result.errors[0].source_column == "email"


def test_validate_missing_source_column():
    rows = [{"name": "Ann"}]  # 'email' absent entirely
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=_clean_fields(),
        rows=rows,
        columns=_clean_columns(),
    )
    assert result.ok is False
    assert result.rows_invalid == 1
    assert [e.code for e in result.errors] == ["missing_column"]
    assert result.errors[0].source_column == "email"


def test_validate_transform_failed():
    fields = [
        FieldMapping(
            source_column="score",
            primitive="metric",
            target_field="value",
            transform="to_number",
            required=True,
        )
    ]
    columns = [ColumnProfile(name="score", sensitivity="none")]
    rows = [{"score": "not-a-number"}]
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=fields,
        rows=rows,
        columns=columns,
    )
    assert result.ok is False
    assert result.rows_invalid == 1
    assert [e.code for e in result.errors] == ["transform_failed"]


def test_validate_structural_error_invalid_mapping_short_circuits():
    fields = [
        FieldMapping(
            source_column="email",
            primitive="entity",
            target_field="not_a_real_field",  # unknown for 'entity'
            transform="none",
            required=False,
        )
    ]
    columns = [ColumnProfile(name="email", sensitivity="none")]
    rows = [{"email": "a@x.com"}, {"email": "b@x.com"}]
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=fields,
        rows=rows,
        columns=columns,
    )
    assert result.ok is False
    assert result.rows_total == 2
    assert result.rows_valid == 0  # short-circuited before row validation
    assert [e.code for e in result.errors] == ["invalid_mapping"]
    assert result.errors[0].row == -1


def test_validate_error_cap_and_truncation():
    fields = [
        FieldMapping(
            source_column="score",
            primitive="metric",
            target_field="value",
            transform="to_number",
            required=True,
        )
    ]
    columns = [ColumnProfile(name="score", sensitivity="none")]
    rows = [{"score": "bad"} for _ in range(10)]  # 10 failing rows
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=fields,
        rows=rows,
        columns=columns,
        max_errors=3,
    )
    assert result.ok is False
    assert result.rows_invalid == 10  # counts are not capped
    assert len(result.errors) == 3  # stored errors are capped
    assert result.errors_truncated is True


def test_validate_governance_required_for_identifier_primitive():
    fields = [
        FieldMapping(
            source_column="wallet",
            primitive="identifier",
            target_field="value",
            transform="none",
            required=True,
        )
    ]
    columns = [ColumnProfile(name="wallet", sensitivity="none")]
    rows = [{"wallet": "0xabc"}]
    result = validate_mapping(
        import_id="imp-1",
        mapping_version=1,
        fields=fields,
        rows=rows,
        columns=columns,
    )
    assert result.ok is True  # data is valid...
    assert result.governance_review_required is True  # ...but review is gated
    assert any("identifier" in reason for reason in result.governance_reasons)
