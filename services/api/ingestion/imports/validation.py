"""Dry-run mapping validation for the Tenant Import Engine.

A tenant maps source columns onto Aether's canonical primitives; before any
rows are staged we replay the mapping over a sample of materialized rows and
report — deterministically — whether every transform applies cleanly and every
required field is populated. Nothing is committed until this passes.

This module is pure stdlib and side-effect free: given the same inputs it
always produces the same :class:`ValidationResult`. The single time-dependent
operation, epoch → ISO conversion in ``to_timestamp``, is deterministic in its
input (no wall-clock reads).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from .contracts import (
    IMPORT_PRIMITIVES,
    IMPORT_TRANSFORMS,
    ColumnProfile,
    FieldMapping,
    ValidationError,
    ValidationResult,
    mapping_requires_review,
    validate_field_mapping,
)

# Digit strings at/above this magnitude are read as unix epoch milliseconds;
# below it, as seconds. 1e11 seconds is year 5138, so anything larger is far
# more plausibly a millisecond timestamp than a second one.
_EPOCH_MILLIS_THRESHOLD = 100_000_000_000

_EPOCH_RE = re.compile(r"-?\d+")


def _to_timestamp(value: str) -> str:
    """Parse an ISO-8601 string or a unix epoch (seconds/millis, as digits)
    into an ISO-8601 UTC string. Raise ``ValueError`` when unparseable."""
    text = value.strip()
    if text == "":
        raise ValueError("empty timestamp")

    if _EPOCH_RE.fullmatch(text):
        num = int(text)
        seconds = num / 1000.0 if abs(num) >= _EPOCH_MILLIS_THRESHOLD else float(num)
        try:
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(f"epoch out of range: {value!r}") from exc
        return dt.isoformat()

    iso = text
    if iso[-1:] in ("Z", "z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(f"unparseable timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _to_number(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def _to_boolean(value: str) -> bool:
    text = value.strip().lower() if isinstance(value, str) else value
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _json_parse(value: str):
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:  # JSONDecodeError subclasses ValueError
        raise ValueError(f"invalid json: {value!r}") from exc


def _coalesce_empty_null(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def apply_transform(value, transform: str):
    """Apply one deterministic transform to a single (string) cell value.

    Raises ``ValueError`` (with a short reason) on failure so the validator can
    turn it into a ``transform_failed`` row error.
    """
    if transform not in IMPORT_TRANSFORMS:
        raise ValueError(f"unknown transform {transform!r}")
    if transform == "none":
        return value
    if transform == "trim":
        return value.strip()
    if transform == "lowercase":
        return value.lower()
    if transform == "uppercase":
        return value.upper()
    if transform == "to_timestamp":
        return _to_timestamp(value)
    if transform == "to_number":
        return _to_number(value)
    if transform == "to_boolean":
        return _to_boolean(value)
    if transform == "hash_sha256":
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    if transform == "json_parse":
        return _json_parse(value)
    if transform == "coalesce_empty_null":
        return _coalesce_empty_null(value)
    # Unreachable: every IMPORT_TRANSFORMS member is handled above.
    raise ValueError(f"unhandled transform {transform!r}")  # pragma: no cover


def _is_empty(value) -> bool:
    """A post-transform value counts as empty when it is ``None`` or ``''``."""
    return value is None or value == ""


def validate_mapping(
    *,
    import_id: str,
    mapping_version: int,
    fields: list[FieldMapping],
    rows: list[dict],
    columns: list[ColumnProfile],
    max_errors: int = 500,
) -> ValidationResult:
    """Dry-run validate a mapping against materialized rows.

    Each row is replayed field-by-field: a missing source column yields
    ``missing_column``, a transform that raises ``ValueError`` yields
    ``transform_failed``, and a required field left empty post-transform yields
    ``required_field_empty``. Any of these makes the row invalid.

    Before touching rows the mapping itself is checked once via
    :func:`validate_field_mapping`; a structural problem (unknown primitive or
    target field) is reported as a ``row=-1`` ``invalid_mapping`` error, forces
    ``ok=False``, and short-circuits before row validation.

    Governance gating is delegated to :func:`mapping_requires_review`.
    """
    errors: list[ValidationError] = []
    errors_truncated = False

    def _record(err: ValidationError) -> None:
        nonlocal errors_truncated
        if len(errors) < max_errors:
            errors.append(err)
        else:
            errors_truncated = True

    governance_required, governance_reasons = mapping_requires_review(fields, columns)
    rows_total = len(rows)

    # ── structural check (once, up front) ───────────────────────────────────
    structural_msgs = [
        (fm, msg)
        for fm in fields
        if (msg := validate_field_mapping(fm)) is not None
    ]
    if structural_msgs:
        for fm, msg in structural_msgs:
            primitive = fm.primitive if fm.primitive in IMPORT_PRIMITIVES else None
            _record(
                ValidationError(
                    row=-1,
                    source_column=fm.source_column,
                    primitive=primitive,
                    code="invalid_mapping",
                    message=msg,
                )
            )
        return ValidationResult(
            import_id=import_id,
            mapping_version=mapping_version,
            ok=False,
            rows_total=rows_total,
            rows_valid=0,
            rows_invalid=0,
            errors=errors,
            errors_truncated=errors_truncated,
            governance_review_required=governance_required,
            governance_reasons=governance_reasons,
        )

    # ── per-row validation ──────────────────────────────────────────────────
    rows_valid = 0
    rows_invalid = 0
    for index, row in enumerate(rows):
        row_ok = True
        for fm in fields:
            if fm.source_column not in row:
                _record(
                    ValidationError(
                        row=index,
                        source_column=fm.source_column,
                        primitive=fm.primitive,
                        code="missing_column",
                        message=f"row is missing source column {fm.source_column!r}",
                    )
                )
                row_ok = False
                continue

            raw = row[fm.source_column]
            try:
                transformed = apply_transform(raw, fm.transform)
            except ValueError as exc:
                _record(
                    ValidationError(
                        row=index,
                        source_column=fm.source_column,
                        primitive=fm.primitive,
                        code="transform_failed",
                        message=f"transform {fm.transform!r} failed: {exc}",
                    )
                )
                row_ok = False
                continue

            if fm.required and _is_empty(transformed):
                _record(
                    ValidationError(
                        row=index,
                        source_column=fm.source_column,
                        primitive=fm.primitive,
                        code="required_field_empty",
                        message=(
                            f"required field {fm.target_field!r} is empty "
                            f"after transform {fm.transform!r}"
                        ),
                    )
                )
                row_ok = False

        if row_ok:
            rows_valid += 1
        else:
            rows_invalid += 1

    return ValidationResult(
        import_id=import_id,
        mapping_version=mapping_version,
        ok=rows_invalid == 0,
        rows_total=rows_total,
        rows_valid=rows_valid,
        rows_invalid=rows_invalid,
        errors=errors,
        errors_truncated=errors_truncated,
        governance_review_required=governance_required,
        governance_reasons=governance_reasons,
    )


__all__ = ["apply_transform", "validate_mapping"]
