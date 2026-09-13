"""Pure, dependency-free schema analyzer for the Tenant Import Engine.

A tenant uploads a file (CSV / JSON / JSONL); this module sniffs its format,
parses it into row dicts, and profiles each column — inferred type, nullability,
distinct count, a few sample values, and a coarse data-sensitivity classification
(none / pii / identifier / secret / governance). The output is a
:class:`~services.imports.contracts.SchemaProfile` the service layer persists and
the tenant maps onto Aether's canonical primitives.

Stdlib only (``csv``, ``io``, ``json``, ``re``, ``hashlib``) — no third-party
parsers, so there is no zip-bomb / xlsx-macro surface: archive and binary
tabular formats are rejected up front.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re

from shared.common.common import BadRequestError

from .contracts import ColumnProfile, SchemaProfile

# ── public surface ──────────────────────────────────────────────────────────

SUPPORTED_FORMATS: set[str] = {"csv", "json", "jsonl"}

__all__ = [
    "SUPPORTED_FORMATS",
    "detect_format",
    "read_rows",
    "analyze_bytes",
    "header_signature",
]

# ── compiled patterns ───────────────────────────────────────────────────────

_RE_INT = re.compile(r"^-?\d+$")
_RE_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)
_RE_EVM = re.compile(r"^0x[a-fA-F0-9]{40}$")
_RE_BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_RE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
_RE_PHONE = re.compile(r"^\+?[0-9][0-9\-\s().]{6,}$")
_RE_SECRETISH = re.compile(r"^[A-Za-z0-9+/=_-]+$")

_BOOL_TOKENS = frozenset({"true", "false", "yes", "no"})

# ── name-based sensitivity vocabularies (already normalized to underscores) ──

_PII_NAME_TOKENS = frozenset(
    {"ssn", "social_security", "passport", "dob", "date_of_birth", "national_id"}
)
_GOVERNANCE_NAME_TOKENS = frozenset(
    {"consent", "opt_in", "opt_out", "gdpr", "ccpa", "legal_basis", "policy"}
)
_SECRET_NAME_TOKENS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "private_key",
        "access_key",
    }
)
_IDENTIFIER_NAME_TOKENS = frozenset(
    {"email", "phone", "wallet", "address", "user_id", "customer_id"}
)

# Reuse the shared server-SDK scrubber vocabulary as a *supplemental* signal for
# credential/secret column names when it is importable (it is stdlib-only, but
# its package __init__ pulls optional deps, so guard the import). PII and
# governance names are classified first, so their tokens never fall through to
# the secret bucket even though the scrubber set mixes categories.
try:  # pragma: no cover - import guard
    from shared.server_sdk.scrubber import _SENSITIVE_PATTERNS as _SCRUBBER_TOKENS
except Exception:  # pragma: no cover - fallback keeps analyzer dependency-free
    _SCRUBBER_TOKENS = frozenset(
        {
            "password",
            "passwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "access_key",
            "credential",
            "private_key",
            "client_secret",
            "webhook_secret",
        }
    )


def _normalize_name(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


# ── format detection ────────────────────────────────────────────────────────

_REJECT_EXTENSIONS: dict[str, str] = {
    "xlsx": "excel workbook",
    "xls": "excel workbook",
    "xlsm": "excel workbook",
    "xlsb": "excel workbook",
    "parquet": "parquet",
    "zip": "archive",
    "gz": "archive",
    "gzip": "archive",
    "tar": "archive",
    "tgz": "archive",
    "7z": "archive",
    "rar": "archive",
}


def _decode(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _extension(filename: str) -> str:
    name = (filename or "").lower().strip()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def _json_or_jsonl(text: str) -> str:
    """A single JSON array/object -> ``json``; newline-delimited objects -> ``jsonl``."""
    stripped = text.strip()
    if not stripped:
        raise BadRequestError("unsupported_format: empty content")
    try:
        json.loads(stripped)
        return "json"
    except Exception:
        pass
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) >= 2 and all(_is_json_value(ln) for ln in lines):
        return "jsonl"
    # A single unparseable-as-whole blob that also is not multi-line JSONL:
    # treat as JSON and let read_rows surface a precise parse error.
    return "json"


def _is_json_value(line: str) -> bool:
    try:
        json.loads(line)
        return True
    except Exception:
        return False


def detect_format(filename: str, content_type: str, content: bytes) -> str:
    """Return ``'csv'`` | ``'json'`` | ``'jsonl'``.

    Rejects everything else with ``BadRequestError('unsupported_format: ...')`` —
    explicitly xlsx/xls (PK zip magic or extension), parquet (PAR1 magic), and
    zip/gzip archives. Decides by extension first, then sniffs content.
    """
    ext = _extension(filename)
    if ext in _REJECT_EXTENSIONS:
        raise BadRequestError(
            f"unsupported_format: {_REJECT_EXTENSIONS[ext]} (.{ext}) not accepted"
        )

    head = content[:8] if content else b""
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        raise BadRequestError(
            "unsupported_format: zip/xlsx archive (PK magic) not accepted"
        )
    if head[:4] == b"PAR1":
        raise BadRequestError("unsupported_format: parquet (PAR1 magic) not accepted")
    if head[:2] == b"\x1f\x8b":
        raise BadRequestError("unsupported_format: gzip archive not accepted")

    if ext == "csv":
        return "csv"
    if ext in ("jsonl", "ndjson"):
        return "jsonl"

    text = _decode(content)
    if not text.strip():
        raise BadRequestError("unsupported_format: empty content")

    if ext == "json":
        return _json_or_jsonl(text)

    # No decisive extension — sniff content, then fall back to content-type hints.
    lead = text.lstrip()
    first = lead[0]
    if first == "[":
        return "json"
    if first == "{":
        return _json_or_jsonl(text)

    ct = (content_type or "").lower()
    if "ndjson" in ct or "jsonl" in ct:
        return "jsonl"
    if "json" in ct:
        return _json_or_jsonl(text)
    if "csv" in ct or "excel" in ct:
        return "csv"

    # Default for plain delimited text.
    return "csv"


# ── row reading ─────────────────────────────────────────────────────────────


def _stringify(value: object) -> str:
    """Coerce any cell value to a stable string. Nested structures -> JSON."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row_from_object(obj: object) -> dict[str, str]:
    if isinstance(obj, dict):
        return {str(k): _stringify(v) for k, v in obj.items()}
    # A bare scalar/array row is wrapped under a synthetic column.
    return {"value": _stringify(obj)}


def _read_csv(content: bytes) -> tuple[list[dict[str, str]], dict]:
    text = _decode(content).lstrip("﻿")
    if not text.strip():
        return [], {"delimiter": None, "has_header": None}

    sample = text[:8192]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        dialect = csv.excel

    has_header = True
    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = True

    reader = csv.reader(io.StringIO(text), dialect)
    try:
        rows_raw = [row for row in reader]
    except csv.Error as exc:
        raise BadRequestError(f"invalid_csv: {exc}") from exc

    rows_raw = [r for r in rows_raw if any(cell.strip() for cell in r)]
    if not rows_raw:
        return [], {"delimiter": delimiter, "has_header": has_header}

    # Spec: the first row is always the header.
    header = [h.strip() for h in rows_raw[0]]
    header = [h if h else f"column_{i + 1}" for i, h in enumerate(header)]
    data = rows_raw[1:]

    rows: list[dict[str, str]] = []
    for raw in data:
        record: dict[str, str] = {}
        for i, col in enumerate(header):
            record[col] = raw[i] if i < len(raw) else ""
        rows.append(record)
    return rows, {"delimiter": delimiter, "has_header": has_header}


def _read_json(content: bytes) -> tuple[list[dict[str, str]], dict]:
    text = _decode(content).strip()
    try:
        data = json.loads(text)
    except Exception as exc:
        raise BadRequestError(f"invalid_json: {exc}") from exc

    if isinstance(data, list):
        rows = [_row_from_object(item) for item in data]
    elif isinstance(data, dict):
        rows = [_row_from_object(data)]
    else:
        rows = [_row_from_object(data)]
    return rows, {"delimiter": None, "has_header": None}


def _read_jsonl(content: bytes) -> tuple[list[dict[str, str]], dict]:
    text = _decode(content)
    rows: list[dict[str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception as exc:
            raise BadRequestError(f"invalid_jsonl: line {lineno}: {exc}") from exc
        rows.append(_row_from_object(obj))
    return rows, {"delimiter": None, "has_header": None}


def read_rows(content: bytes, fmt: str) -> tuple[list[dict[str, str]], dict]:
    """Parse ``content`` into row dicts plus a ``{'delimiter', 'has_header'}`` meta."""
    if fmt == "csv":
        return _read_csv(content)
    if fmt == "json":
        return _read_json(content)
    if fmt == "jsonl":
        return _read_jsonl(content)
    raise BadRequestError(f"unsupported_format: {fmt!r}")


# ── type inference ──────────────────────────────────────────────────────────


def _is_wallet(value: str) -> bool:
    return bool(_RE_EVM.match(value) or _RE_BASE58.match(value))


def _is_phone(value: str) -> bool:
    if not _RE_PHONE.match(value):
        return False
    return sum(c.isdigit() for c in value) >= 7


def _is_json_struct(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _leaf_category(value: str) -> str:
    """Coarse per-value category used to distinguish ``string`` from ``mixed``."""
    if _RE_NUMERIC.match(value):
        return "number"
    if value.lower() in _BOOL_TOKENS:
        return "boolean"
    if _RE_EMAIL.match(value):
        return "email"
    if _RE_URL.match(value):
        return "url"
    if _is_wallet(value):
        return "wallet"
    if _RE_UUID.match(value):
        return "uuid"
    if _RE_DATETIME.match(value) or _RE_DATE.match(value):
        return "datetime"
    if _is_json_struct(value):
        return "json"
    return "string"


def infer_column_type(values: list[str]) -> str:
    """Infer one of ``IMPORT_COLUMN_TYPES`` over sampled non-empty cell values."""
    vals = [v.strip() for v in values if v.strip() != ""]
    if not vals:
        return "empty"

    lowered = {v.lower() for v in vals}
    if lowered <= _BOOL_TOKENS:
        return "boolean"
    if all(_RE_INT.match(v) for v in vals):
        return "integer"
    if all(_RE_NUMERIC.match(v) for v in vals) and any(
        not _RE_INT.match(v) for v in vals
    ):
        return "float"
    if all(_RE_EMAIL.match(v) for v in vals):
        return "email"
    if all(_RE_URL.match(v) for v in vals):
        return "url"
    if all(_is_wallet(v) for v in vals):
        return "wallet_address"
    if all(_RE_UUID.match(v) for v in vals):
        return "uuid"
    if all(_RE_DATETIME.match(v) or _RE_DATE.match(v) for v in vals):
        return "datetime" if any(_RE_DATETIME.match(v) for v in vals) else "date"
    if all(_is_phone(v) for v in vals):
        return "phone"
    if all(_is_json_struct(v) for v in vals):
        return "json"

    if len({_leaf_category(v) for v in vals}) > 1:
        return "mixed"
    return "string"


# ── sensitivity inference ───────────────────────────────────────────────────


def _value_looks_secret(value: str) -> bool:
    if _is_wallet(value) or _RE_UUID.match(value):
        return False
    if value.startswith("sk_") or value.startswith("AKIA"):
        return True
    if len(value) >= 32 and _RE_SECRETISH.match(value):
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        has_digit = any(c.isdigit() for c in value)
        return has_upper and has_lower and has_digit
    return False


def infer_sensitivity(name: str, inferred_type: str, values: list[str]) -> str:
    """Classify a column as none/pii/identifier/secret/governance.

    Precedence: pii > governance > secret > identifier. PII and governance names
    are matched first so the (uncategorized) reused scrubber vocabulary can only
    ever broaden the *secret* bucket, never mislabel a PII column.
    """
    n = _normalize_name(name)
    vals = [v for v in values if v.strip() != ""]

    if any(tok in n for tok in _PII_NAME_TOKENS):
        return "pii"
    if any(tok in n for tok in _GOVERNANCE_NAME_TOKENS):
        return "governance"
    if any(tok in n for tok in _SECRET_NAME_TOKENS) or any(
        tok in n for tok in _SCRUBBER_TOKENS
    ):
        return "secret"
    if (
        inferred_type in ("string", "mixed")
        and vals
        and all(_value_looks_secret(v) for v in vals)
    ):
        return "secret"
    if inferred_type in ("email", "phone", "wallet_address") or any(
        tok in n for tok in _IDENTIFIER_NAME_TOKENS
    ):
        return "identifier"
    return "none"


# ── full analysis ───────────────────────────────────────────────────────────


def _column_order(rows: list[dict[str, str]]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                order.append(key)
    return order


def analyze_bytes(
    file_id: str,
    content: bytes,
    filename: str,
    content_type: str,
    *,
    sample_size: int = 200,
) -> SchemaProfile:
    """Detect the format, parse rows, and profile each column into a SchemaProfile."""
    fmt = detect_format(filename, content_type, content)
    rows, meta = read_rows(content, fmt)

    row_count = len(rows)
    sampled = rows[: max(sample_size, 0)]
    sampled_rows = len(sampled)

    columns: list[ColumnProfile] = []
    for col in _column_order(rows):
        raw = [row.get(col, "") for row in sampled]
        non_empty = [v for v in raw if v is not None and str(v).strip() != ""]
        null_count = sampled_rows - len(non_empty)

        inferred = infer_column_type(non_empty)

        samples: list[str] = []
        for v in non_empty:
            if v not in samples:
                samples.append(v)
            if len(samples) >= 5:
                break

        columns.append(
            ColumnProfile(
                name=col,
                inferred_type=inferred,
                nullable=null_count > 0,
                null_count=null_count,
                distinct_count=len(set(non_empty)),
                sample_values=samples,
                sensitivity=infer_sensitivity(col, inferred, non_empty),
            )
        )

    return SchemaProfile(
        file_id=file_id,
        format=fmt,
        row_count=row_count,
        sampled_rows=sampled_rows,
        columns=columns,
        delimiter=meta.get("delimiter"),
        has_header=meta.get("has_header"),
    )


# ── template matching ───────────────────────────────────────────────────────


def header_signature(column_names: list[str]) -> str:
    """Deterministic sha256 hex of sorted, lowercased, stripped column names."""
    normalized = sorted(c.strip().lower() for c in column_names)
    joined = "|".join(normalized)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
