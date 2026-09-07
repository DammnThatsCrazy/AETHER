"""DB-free tests for the Data Exchange Plane M4 parquet serializer.

Covers the pyarrow serializer (:mod:`services.data_exchange.parquet`) and the
M4 serializer dispatcher (:func:`services.data_exchange.exporters.
produce_export_bytes`):

- rows → parquet bytes → pyarrow table round-trip equality;
- column allowlists project before serialization;
- the ExportSpecContract compression vocabulary (gzip / snappy / zstd) round
  trips, and unknown codes are rejected;
- ``produce_export_bytes`` routes ``csv``/``json``/``ndjson`` through the
  *canonical* ``serialize_rows`` (so CSV stays formula-safe) and ``parquet``
  through :mod:`services.data_exchange.parquet`.

No Postgres, no ObjectStore, no pyarrow-at-module-import assumption: pyarrow is
an optional M4 backend dependency, so the whole module import is skipped when it
is absent (matching the ``pytest.importorskip`` contract).
"""

from __future__ import annotations

from typing import Any

import pytest

pyarrow = pytest.importorskip("pyarrow")
pyarrow_parquet = pytest.importorskip("pyarrow.parquet")

from services.data_exchange.exporters import (  # noqa: E402
    produce_export_bytes,
)
from services.data_exchange.parquet import (  # noqa: E402
    PARQUET_COMPRESSIONS,
    PARQUET_CONTENT_TYPE,
    infer_columns,
    normalize_compression,
    parquet_rows_from_bytes,
    rows_to_parquet_bytes,
    rows_to_table,
)


def _rows() -> list[dict]:
    return [
        {"id": 1, "name": "alice", "score": 1.5, "active": True},
        {"id": 2, "name": "bob", "score": 2.5, "active": False},
        {"id": 3, "name": "=SUM(A1:A3)", "score": 0.0, "active": True},
    ]


# ── serializer round trips ──────────────────────────────────────────────────


def test_rows_to_parquet_bytes_round_trips() -> None:
    rows = _rows()
    content = rows_to_parquet_bytes(rows)
    assert isinstance(content, bytes) and len(content) > 0
    assert parquet_rows_from_bytes(content) == rows


def test_rows_to_parquet_bytes_honors_column_allowlist() -> None:
    rows = _rows()
    content = rows_to_parquet_bytes(rows, columns=["id", "name"])
    back = parquet_rows_from_bytes(content)
    assert back == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
        {"id": 3, "name": "=SUM(A1:A3)"},
    ]


def test_rows_to_table_empty_rows_keeps_declared_columns() -> None:
    content = rows_to_parquet_bytes([], columns=["id", "name"])
    table = pyarrow_parquet.read_table(__import__("io").BytesIO(content))
    assert table.num_rows == 0
    assert table.column_names == ["id", "name"]


def test_compression_codes_round_trip() -> None:
    rows = _rows()
    assert set(PARQUET_COMPRESSIONS) == {"gzip", "snappy", "zstd"}
    for code in PARQUET_COMPRESSIONS:
        content = rows_to_parquet_bytes(rows, compression=code)
        assert parquet_rows_from_bytes(content) == rows


def test_normalize_compression_rejects_unknown_codes() -> None:
    assert normalize_compression(None) is None
    assert normalize_compression("ZSTD") == "zstd"
    with pytest.raises(ValueError):
        normalize_compression("lz4")  # deliberately not in the envelope vocabulary


def test_infer_columns_preserves_first_seen_order() -> None:
    assert infer_columns([{"b": 1, "a": 2}, {"c": 3}]) == ["b", "a", "c"]


# ── produce_export_bytes dispatcher ─────────────────────────────────────────


def test_produce_export_bytes_parquet_via_parquet_module() -> None:
    rows = _rows()
    content, content_type, columns = produce_export_bytes(
        rows, format="parquet", columns=["id", "name"], compression="snappy"
    )
    assert content_type == PARQUET_CONTENT_TYPE
    assert columns == ["id", "name"]
    assert parquet_rows_from_bytes(content) == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
        {"id": 3, "name": "=SUM(A1:A3)"},
    ]


def test_canonical_serialize_rows_accepts_parquet_after_m4_delta() -> None:
    """The M4 coordinator delta taught the canonical serializer parquet, so the
    canonical ``export.generate`` path and the envelope dispatcher agree byte-
    for-byte on the same input."""
    from services.export.service import SUPPORTED_FORMATS, serialize_rows

    assert "parquet" in SUPPORTED_FORMATS
    rows = _rows()
    content, content_type, columns = serialize_rows(rows, "parquet", ["id", "name"])
    assert content_type == PARQUET_CONTENT_TYPE
    assert columns == ["id", "name"]
    # Identical bytes to the direct parquet-module serializer for the same input.
    assert content == rows_to_parquet_bytes(rows, columns=["id", "name"])
    assert parquet_rows_from_bytes(content) == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
        {"id": 3, "name": "=SUM(A1:A3)"},
    ]


def test_canonical_serialize_rows_parquet_keeps_formula_like_cells_verbatim() -> None:
    from services.export.service import serialize_rows

    # Parquet is typed binary — a leading '=' cell is data, never a spreadsheet
    # formula, so no CSV-style escaping applies on this path.
    rows = [{"name": "=SUM(A1)", "ok": "+plain", "n": 1}]
    content, content_type, _ = serialize_rows(rows, "parquet")
    assert content_type == PARQUET_CONTENT_TYPE
    assert parquet_rows_from_bytes(content) == rows


def test_produce_export_bytes_csv_is_formula_safe_via_canonical_serializer() -> None:
    rows = [{"name": "=SUM(A1)", "note": "+safe", "ok": "plain"}]
    content, content_type, columns = produce_export_bytes(rows, format="csv")
    assert content_type == "text/csv"
    text = content.decode("utf-8")
    assert "'=SUM(A1)" in text
    assert "'+safe" in text
    assert "plain" in text
    # The canonical csv serializer returned the sorted column names, not a
    # naive per-row projection of formula-ish cell values into columns.
    assert columns == ["name", "note", "ok"]


def test_produce_export_bytes_json_via_canonical_serializer() -> None:
    rows = [{"name": "=SUM(A1)", "n": 1}]
    content, content_type, columns = produce_export_bytes(rows, format="json")
    assert content_type == "application/json"
    decoded: Any = __import__("json").loads(content.decode("utf-8"))
    assert decoded == rows  # JSON path does not mutate cell values


def test_produce_export_bytes_ndjson_via_canonical_serializer() -> None:
    rows = [{"name": "=SUM(A1)"}, {"name": "alice"}]
    content, content_type, columns = produce_export_bytes(rows, format="ndjson")
    assert content_type == "application/x-ndjson"
    lines = [line for line in content.decode("utf-8").splitlines() if line]
    assert len(lines) == 2


def test_rows_to_parquet_bytes_requires_pyarrow_at_call_time() -> None:
    """Import failure surfaces at call time with a clear message."""
    import builtins

    real_import = builtins.__import__

    def _block_pyarrow(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("No module named 'pyarrow' (simulated)")
        return real_import(name, *args, **kwargs)

    from services.data_exchange import parquet as parquet_mod

    builtins.__import__ = _block_pyarrow  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="pyarrow is required"):
            parquet_mod.rows_to_parquet_bytes([{"a": 1}])
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]
