from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import json

import pytest

from services.imports import analyzer
from services.imports.analyzer import (
    SUPPORTED_FORMATS,
    analyze_bytes,
    detect_format,
    header_signature,
    infer_column_type,
    infer_sensitivity,
    read_rows,
)
from services.imports.contracts import SchemaProfile
from shared.common.common import BadRequestError

WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40
UUID_1 = "550e8400-e29b-41d4-a716-446655440000"
UUID_2 = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


# ── format detection ────────────────────────────────────────────────────────


def test_supported_formats_constant():
    assert SUPPORTED_FORMATS == {"csv", "json", "jsonl"}


def test_detect_csv_by_extension_and_content_type():
    content = b"a,b\n1,2\n"
    assert detect_format("data.csv", "text/csv", content) == "csv"


def test_detect_json_array_vs_single_object():
    array = b'[{"a": 1}, {"a": 2}]'
    single = b'{"a": 1, "b": 2}'
    assert detect_format("d.json", "application/json", array) == "json"
    # No extension -> content sniff still resolves a single object to json.
    assert detect_format("mystery", "", single) == "json"


def test_detect_jsonl_by_content_sniff_without_extension():
    jsonl = b'{"x": 1}\n{"x": 2}\n{"x": 3}\n'
    assert detect_format("stream", "", jsonl) == "jsonl"
    assert detect_format("stream.jsonl", "", jsonl) == "jsonl"


def test_detect_format_rejects_xlsx_by_extension():
    with pytest.raises(BadRequestError):
        detect_format("book.xlsx", "application/octet-stream", b"PK\x03\x04\x14\x00")


def test_detect_format_rejects_zip_magic_regardless_of_name():
    # PK zip magic (also the xlsx container) must be rejected even with a .bin name.
    with pytest.raises(BadRequestError):
        detect_format("mystery.bin", "", b"PK\x03\x04\x14\x00\x08\x00")


def test_detect_format_rejects_parquet_magic():
    with pytest.raises(BadRequestError):
        detect_format("data.bin", "", b"PAR1\x15\x00\x00\x00")


def test_detect_format_rejects_parquet_extension():
    with pytest.raises(BadRequestError):
        detect_format("data.parquet", "", b"anything")


def test_detect_format_rejects_zip_extension():
    with pytest.raises(BadRequestError):
        detect_format("bundle.zip", "", b"PK\x03\x04")


def test_detect_format_rejects_gzip_magic():
    with pytest.raises(BadRequestError):
        detect_format("data.bin", "", b"\x1f\x8b\x08\x00")


# ── read_rows ───────────────────────────────────────────────────────────────


def test_read_rows_csv_sniffs_comma_delimiter_and_header():
    content = b"name,age,email\nAlice,30,alice@example.com\nBob,25,bob@example.com\n"
    rows, meta = read_rows(content, "csv")
    assert meta["delimiter"] == ","
    assert meta["has_header"] is True
    assert rows == [
        {"name": "Alice", "age": "30", "email": "alice@example.com"},
        {"name": "Bob", "age": "25", "email": "bob@example.com"},
    ]


def test_read_rows_csv_sniffs_semicolon_delimiter():
    content = b"name;score;active\nAlice;9.5;true\nBob;7;false\n"
    rows, meta = read_rows(content, "csv")
    assert meta["delimiter"] == ";"
    assert rows[0] == {"name": "Alice", "score": "9.5", "active": "true"}


def test_read_rows_json_array_stringifies_and_nests():
    content = json.dumps(
        [{"id": 1, "tags": ["x", "y"], "meta": {"k": "v"}}, {"id": 2, "tags": []}]
    ).encode()
    rows, meta = read_rows(content, "json")
    assert meta == {"delimiter": None, "has_header": None}
    assert rows[0]["id"] == "1"
    assert rows[0]["tags"] == json.dumps(["x", "y"], sort_keys=True)
    assert rows[0]["meta"] == json.dumps({"k": "v"}, sort_keys=True)


def test_read_rows_json_single_object_is_one_row():
    rows, _ = read_rows(b'{"a": 1, "b": 2}', "json")
    assert rows == [{"a": "1", "b": "2"}]


def test_read_rows_jsonl_one_object_per_line():
    content = b'{"x": 1}\n\n{"x": 2}\n{"x": 3}\n'
    rows, meta = read_rows(content, "jsonl")
    assert meta == {"delimiter": None, "has_header": None}
    assert rows == [{"x": "1"}, {"x": "2"}, {"x": "3"}]


def test_read_rows_json_invalid_raises_bad_request():
    with pytest.raises(BadRequestError):
        read_rows(b"{not valid json", "json")


def test_read_rows_jsonl_invalid_line_raises_bad_request():
    with pytest.raises(BadRequestError):
        read_rows(b'{"x": 1}\n{bad}\n', "jsonl")


# ── type inference ──────────────────────────────────────────────────────────


def test_infer_type_empty():
    assert infer_column_type([]) == "empty"
    assert infer_column_type(["", "   ", ""]) == "empty"


def test_infer_type_integer():
    assert infer_column_type(["1", "2", "-3", "42"]) == "integer"


def test_infer_type_float_requires_a_non_int():
    assert infer_column_type(["1.5", "2", "3.25"]) == "float"
    # All integers must not be misread as float.
    assert infer_column_type(["1", "2", "3"]) == "integer"


def test_infer_type_boolean_is_conservative():
    assert infer_column_type(["true", "false", "TRUE"]) == "boolean"
    assert infer_column_type(["yes", "no"]) == "boolean"
    # 0/1 alone stays integer, not boolean.
    assert infer_column_type(["0", "1", "1"]) == "integer"


def test_infer_type_email():
    assert infer_column_type(["a@b.com", "c.d@e.org"]) == "email"


def test_infer_type_wallet_address():
    assert infer_column_type([WALLET_A, WALLET_B]) == "wallet_address"


def test_infer_type_uuid():
    assert infer_column_type([UUID_1, UUID_2]) == "uuid"


def test_infer_type_datetime_and_date():
    assert infer_column_type(["2024-01-15T10:30:00Z", "2024-02-20T08:00:00"]) == "datetime"
    assert infer_column_type(["2024-01-15", "2024-02-20"]) == "date"


def test_infer_type_string_and_mixed():
    assert infer_column_type(["alice", "bob", "charlie"]) == "string"
    assert infer_column_type(["10", "hello"]) == "mixed"


def test_infer_type_json_and_phone():
    assert infer_column_type(['{"a": 1}', "[1, 2, 3]"]) == "json"
    assert infer_column_type(["+1-555-123-4567", "+1 (555) 987 6543"]) == "phone"


# ── sensitivity inference ───────────────────────────────────────────────────


def test_sensitivity_email_is_identifier():
    assert infer_sensitivity("email", "email", ["a@b.com"]) == "identifier"


def test_sensitivity_ssn_is_pii():
    assert infer_sensitivity("ssn", "phone", ["123-45-6789"]) == "pii"
    assert infer_sensitivity("date_of_birth", "date", ["1990-01-01"]) == "pii"


def test_sensitivity_password_and_api_key_are_secret():
    assert infer_sensitivity("password", "string", ["hunter2xx"]) == "secret"
    assert infer_sensitivity("api_key", "string", ["abc123"]) == "secret"


def test_sensitivity_secret_by_value_prefix():
    assert infer_sensitivity("field", "string", ["sk_live_abcdef", "sk_live_ghijkl"]) == "secret"


def test_sensitivity_consent_is_governance():
    assert infer_sensitivity("consent", "boolean", ["true", "false"]) == "governance"
    assert infer_sensitivity("gdpr_opt_in", "boolean", ["yes"]) == "governance"


def test_sensitivity_plain_column_is_none():
    assert infer_sensitivity("notes", "string", ["hello world"]) == "none"


# ── header signature ────────────────────────────────────────────────────────


def test_header_signature_is_order_and_case_insensitive():
    sig_a = header_signature(["Name", "AGE", "Email"])
    sig_b = header_signature([" email ", "name", "age"])
    assert sig_a == sig_b


def test_header_signature_is_deterministic_and_distinguishes():
    assert header_signature(["a", "b"]) == header_signature(["b", "a"])
    assert header_signature(["a", "b"]) != header_signature(["a", "c"])
    assert len(header_signature(["a"])) == 64  # sha256 hex


# ── end-to-end analyze_bytes ────────────────────────────────────────────────


def test_analyze_bytes_csv_full_profile():
    content = (
        b"user_id,email,amount,signup\n"
        b"1,alice@example.com,9.50,2024-01-01\n"
        b"2,bob@example.com,,2024-02-01\n"
        b"3,carol@example.com,3.25,2024-03-01\n"
    )
    profile = analyze_bytes("file-1", content, "customers.csv", "text/csv")
    assert isinstance(profile, SchemaProfile)
    assert profile.format == "csv"
    assert profile.row_count == 3
    assert profile.sampled_rows == 3
    assert profile.delimiter == ","

    by_name = {c.name: c for c in profile.columns}
    assert by_name["user_id"].sensitivity == "identifier"
    assert by_name["email"].inferred_type == "email"
    assert by_name["email"].sensitivity == "identifier"
    assert by_name["amount"].inferred_type == "float"
    assert by_name["amount"].null_count == 1
    assert by_name["amount"].nullable is True
    assert by_name["signup"].inferred_type == "date"


def test_analyze_bytes_respects_sample_size():
    rows = "\n".join(f"{i},name{i}" for i in range(1, 11))
    content = ("id,label\n" + rows + "\n").encode()
    profile = analyze_bytes("f", content, "big.csv", "text/csv", sample_size=4)
    assert profile.row_count == 10
    assert profile.sampled_rows == 4


def test_analyze_bytes_jsonl_profile():
    content = b'{"id": 1, "wallet": "%s"}\n{"id": 2, "wallet": "%s"}\n' % (
        WALLET_A.encode(),
        WALLET_B.encode(),
    )
    profile = analyze_bytes("f2", content, "events.jsonl", "application/x-ndjson")
    assert profile.format == "jsonl"
    by_name = {c.name: c for c in profile.columns}
    assert by_name["wallet"].inferred_type == "wallet_address"
    assert by_name["wallet"].sensitivity == "identifier"


def test_analyze_bytes_rejects_binary_upload():
    with pytest.raises(BadRequestError):
        analyze_bytes("f3", b"PK\x03\x04\x14\x00", "sheet.xlsx", "application/octet-stream")


def test_analyzer_module_exposes_public_api():
    for fn in ("detect_format", "read_rows", "analyze_bytes", "header_signature"):
        assert fn in analyzer.__all__
