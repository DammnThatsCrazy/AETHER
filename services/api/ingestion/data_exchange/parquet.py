"""Data Exchange Plane — pyarrow parquet serializer (M4 egress).

M4 adds ``parquet`` to the egress structured formats by plugging pyarrow into
the canonical exporter serialization surface (see ``exporters.py``).  This
module is the *only* place the Data Exchange Plane talks to pyarrow; it stays a
pure serializer so the routes and the canonical exporter registry that do not
need parquet never import it.

Pyarrow availability policy:

- ``pyarrow`` is an optional backend dependency added by the coordinator at
  integration (see the M4 shared-surface delta — ``pyproject.toml`` backend
  extra).  It is therefore **never imported at module import time** here: every
  function that needs it imports lazily and fails with a clear ``RuntimeError``
  at *call* time when it is missing, so importing ``parquet.py`` (or a router
  that imports it) can never raise ``ImportError`` on a deployment that has not
  installed the extra.
- The ``DATA_EXCHANGE_PARQUET_ENABLED`` flag controls *surface availability*
  only; the serializer itself is inert until a caller asks for ``parquet``.

Parquet needs no spreadsheet-formula escaping: the canonical CSV path protects
``= + - @`` cell prefixes because a spreadsheet client executes them; parquet
is a typed columnar binary format that no spreadsheet cell-evaluator runs over,
so ``rows_to_parquet_bytes`` stores cell values verbatim.
"""

from __future__ import annotations

from typing import Any, Optional

# Registered in exporters.py as the stable content type for data-exchange
# ``parquet`` egress artifacts.  This is the media type the canonical artifact
# repository records and the download route serves.
PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"

# Pyarrow compression codes accepted by ``pyarrow.parquet.write_table``.
# M4 maps the ExportSpecContract compression vocabulary (gzip/snappy/zstd)
# directly onto these; pyarrow's own default when none is requested is snappy.
PARQUET_COMPRESSIONS: tuple[str, ...] = ("gzip", "snappy", "zstd")

# Since the M4 coordinator delta the canonical export engine's SUPPORTED_FORMATS
# includes parquet and canonical ``serialize_rows`` delegates here; this module
# owns the pyarrow half of the serializer surface.
PARQUET_FORMAT = "parquet"

_PYARROW_IMPORT_ERROR = (
    "pyarrow is required for parquet export (Data Exchange Plane M4). "
    "Install the backend parquet extra (pyarrow) and set "
    "DATA_EXCHANGE_PARQUET_ENABLED=true."
)


def _import_pyarrow() -> tuple[Any, Any]:
    """Lazily import ``pyarrow`` + ``pyarrow.parquet``; fail clearly if absent.

    Imported inside every function that serializes parquet so this module (and
    any module importing it) never raises at import time.
    """
    try:  # pragma: no cover - import path exercised per-interpreter
        import pyarrow as pa  # noqa: PLC0415 — lazy by design
        import pyarrow.parquet as pq  # noqa: PLC0415 — lazy by design
    except ImportError as exc:  # pragma: no cover - depends on install
        raise RuntimeError(_PYARROW_IMPORT_ERROR) from exc
    return pa, pq


def pyarrow_available() -> bool:
    """True when pyarrow can be imported; drives availability gating."""
    try:
        _import_pyarrow()
    except RuntimeError:
        return False
    return True


def normalize_compression(compression: Optional[str]) -> Optional[str]:
    """Coerce the Data Exchange compression vocabulary onto pyarrow codes.

    Accepts ``None`` (pyarrow default), ``gzip``, ``snappy`` and ``zstd``;
    anything else is rejected so a misspelled envelope value fails loudly
    instead of silently writing uncompressed files.
    """
    if compression is None:
        return None
    value = str(compression).strip().lower()
    if value not in PARQUET_COMPRESSIONS:
        raise ValueError(
            f"Unsupported parquet compression {compression!r} — expected one of "
            f"{', '.join(PARQUET_COMPRESSIONS)}"
        )
    return value


def infer_columns(rows: list[dict]) -> list[str]:
    """Union of keys across rows, first-seen order preserved.

    Used for the manifest ``columns`` and for schema construction when the
    caller did not supply an explicit column allowlist.
    """
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def rows_to_table(
    rows: list[dict],
    *,
    columns: Optional[list[str]] = None,
    schema: Optional[Any] = None,
) -> Any:
    """Build a ``pyarrow.Table`` from a list of dict rows.

    ``columns`` is an optional allowlist (order + inclusion); fields outside it
    are dropped before serialization.  ``schema`` (a ``pyarrow.Schema``) may be
    supplied for fully deterministic typing; when omitted the schema is inferred
    from the rows (pyarrow ``Table.from_pylist``), and an empty row set with an
    explicit ``columns`` allowlist still yields a zero-row typed table instead
    of a schema-less empty file.
    """
    pa, _pq = _import_pyarrow()
    allowed = columns or infer_columns(rows)
    if not rows:
        # Deterministic empty artifact: one column per allowlist entry, typed
        # null so a reader observes the declared shape with zero rows.
        if allowed:
            arrays: list[Any] = []
            fields: list[Any] = []
            for col in allowed:
                fields.append(pa.field(str(col), pa.null()))
                arrays.append(pa.array([], type=pa.null()))
            table = pa.Table.from_arrays(arrays, schema=pa.schema(fields))
            if schema is not None:
                table = table.cast(schema)
            return table
        return pa.table({})
    if schema is not None:
        projected: list[dict] = [
            {str(k): row[k] for k in allowed if k in row} for row in rows
        ]
        return pa.Table.from_pylist(projected, schema=schema)
    if allowed:
        projected = [{str(k): row[k] for k in allowed if k in row} for row in rows]
        return pa.Table.from_pylist(projected)
    return pa.Table.from_pylist(rows)


def table_to_parquet_bytes(table: Any, *, compression: Optional[str] = None) -> bytes:
    """Serialize a ``pyarrow.Table`` to parquet bytes (in-memory, no temp file)."""
    _pa, pq = _import_pyarrow()
    import io

    code = normalize_compression(compression)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression=code)
    return buf.getvalue()


def rows_to_parquet_bytes(
    rows: list[dict],
    *,
    schema: Optional[Any] = None,
    columns: Optional[list[str]] = None,
    compression: Optional[str] = None,
) -> bytes:
    """Serialize a list of dict rows to parquet bytes.

    The one public serializer the M4 exporter surface calls for
    ``format="parquet"``.  ``columns`` is an optional field allowlist; when both
    ``columns`` and ``schema`` are omitted, pyarrow infers the schema from the
    first row batch (column order = first-seen key order).
    """
    table = rows_to_table(rows, columns=columns, schema=schema)
    return table_to_parquet_bytes(table, compression=compression)


def parquet_rows_from_bytes(content: bytes) -> list[dict]:
    """Read parquet bytes back into Python dict rows (test/verify helper).

    Mirrors the canonical ``serialize_rows`` inverse used by the checksum
    verification path; pyarrow converts each column to Python objects, so
    round-tripped values are comparable to the source rows.
    """
    _pa, pq = _import_pyarrow()
    import io

    table = pq.read_table(io.BytesIO(bytes(content)))
    return table.to_pylist()
