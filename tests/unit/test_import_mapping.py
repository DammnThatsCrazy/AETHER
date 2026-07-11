"""Unit tests for the Import Engine mapping helpers.

Covers full-mapping structural validation, unmapped-column detection, template
lookup by header signature, and template-vs-file drift computation. All pure and
synchronous — no asyncio, no I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.imports.contracts import FieldMapping  # noqa: E402
from services.imports.mapping import (  # noqa: E402
    match_template,
    template_drift,
    unmapped_columns,
    validate_mapping_fields,
)


def _valid_fields() -> list[FieldMapping]:
    return [
        FieldMapping(
            source_column="wallet",
            primitive="identifier",
            target_field="value",
        ),
        FieldMapping(
            source_column="name",
            primitive="entity",
            target_field="display_name",
        ),
    ]


# ── validate_mapping_fields ──────────────────────────────────────────────────


def test_valid_mapping_returns_empty() -> None:
    assert validate_mapping_fields(_valid_fields()) == []


def test_empty_mapping_returns_error() -> None:
    errors = validate_mapping_fields([])
    assert errors  # non-empty
    assert errors == ["mapping has no fields"]


def test_duplicate_target_is_flagged() -> None:
    fields = [
        FieldMapping(source_column="a", primitive="entity", target_field="display_name"),
        FieldMapping(source_column="b", primitive="entity", target_field="display_name"),
    ]
    errors = validate_mapping_fields(fields)
    assert any("duplicate target" in e and "entity.display_name" in e for e in errors)


def test_unmapped_record_raw_may_repeat() -> None:
    # Two columns both funnelling into unmapped_record.raw must NOT be a duplicate.
    fields = [
        FieldMapping(source_column="x", primitive="unmapped_record", target_field="raw"),
        FieldMapping(source_column="y", primitive="unmapped_record", target_field="raw"),
    ]
    assert validate_mapping_fields(fields) == []


def test_unknown_target_field_surfaces_field_error() -> None:
    bad = [
        FieldMapping(source_column="a", primitive="entity", target_field="not_a_field"),
    ]
    errors = validate_mapping_fields(bad)
    # The exact string comes straight from contracts.validate_field_mapping.
    from services.imports.contracts import validate_field_mapping

    expected = validate_field_mapping(bad[0])
    assert expected is not None
    assert expected in errors


def test_empty_source_column_is_flagged() -> None:
    fields = [
        FieldMapping(source_column="   ", primitive="entity", target_field="display_name"),
    ]
    errors = validate_mapping_fields(fields)
    assert any("empty source_column" in e for e in errors)


def test_errors_are_sorted_and_deterministic() -> None:
    fields = [
        FieldMapping(source_column="a", primitive="entity", target_field="display_name"),
        FieldMapping(source_column="b", primitive="entity", target_field="display_name"),
        FieldMapping(source_column="", primitive="entity", target_field="external_id"),
    ]
    errors = validate_mapping_fields(fields)
    assert errors == sorted(errors)


# ── unmapped_columns ─────────────────────────────────────────────────────────


def test_unmapped_columns_returns_leftovers() -> None:
    fields = _valid_fields()  # references "wallet" and "name"
    columns = ["wallet", "name", "created_at", "amount"]
    assert unmapped_columns(fields, columns) == ["amount", "created_at"]


def test_unmapped_columns_empty_when_all_referenced() -> None:
    fields = _valid_fields()
    assert unmapped_columns(fields, ["wallet", "name"]) == []


# ── match_template ───────────────────────────────────────────────────────────


def test_match_template_finds_by_signature() -> None:
    templates = [
        {"header_signature": "sig-a", "fields": []},
        {"header_signature": "sig-b", "fields": [{"source_column": "x"}]},
    ]
    found = match_template("sig-b", templates)
    assert found is not None
    assert found["header_signature"] == "sig-b"


def test_match_template_returns_none_when_absent() -> None:
    templates = [{"header_signature": "sig-a", "fields": []}]
    assert match_template("nope", templates) is None


def test_match_template_returns_first_on_multiple() -> None:
    templates = [
        {"header_signature": "dup", "fields": [{"source_column": "first"}]},
        {"header_signature": "dup", "fields": [{"source_column": "second"}]},
    ]
    found = match_template("dup", templates)
    assert found is not None
    assert found["fields"][0]["source_column"] == "first"


# ── template_drift ───────────────────────────────────────────────────────────


def test_template_drift_exact_match_is_applicable() -> None:
    template_fields = [
        {"source_column": "wallet"},
        {"source_column": "name"},
    ]
    drift = template_drift(template_fields, ["wallet", "name"])
    assert drift == {"missing_columns": [], "new_columns": [], "applicable": True}


def test_template_drift_new_columns_still_applicable() -> None:
    template_fields = [{"source_column": "wallet"}]
    drift = template_drift(template_fields, ["wallet", "extra"])
    assert drift["missing_columns"] == []
    assert drift["new_columns"] == ["extra"]
    assert drift["applicable"] is True


def test_template_drift_missing_column_not_applicable() -> None:
    template_fields = [
        {"source_column": "wallet"},
        {"source_column": "name"},
    ]
    drift = template_drift(template_fields, ["wallet"])  # "name" is gone
    assert drift["missing_columns"] == ["name"]
    assert drift["applicable"] is False


def test_template_drift_lists_are_sorted() -> None:
    template_fields = [
        {"source_column": "zeta"},
        {"source_column": "alpha"},
    ]
    drift = template_drift(template_fields, ["mid", "beta"])
    assert drift["missing_columns"] == ["alpha", "zeta"]
    assert drift["new_columns"] == ["beta", "mid"]
    assert drift["applicable"] is False
