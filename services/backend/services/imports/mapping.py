"""Mapping-level validation and template reconciliation for the Import Engine.

Where :mod:`services.imports.contracts` holds the per-field structural check
(:func:`validate_field_mapping`), this module reasons about a *whole* mapping:
duplicate targets, empty source columns, which file columns fall through to the
``unmapped_record`` primitive, and whether a previously saved template still
applies to a freshly uploaded file.

Every function here is a pure, deterministic, stdlib-only helper — no I/O, no
randomness, stable (sorted) output — so both the map/validate routes and the
template machinery can share the same logic.
"""

from __future__ import annotations

from .contracts import FieldMapping, validate_field_mapping

__all__ = [
    "validate_mapping_fields",
    "unmapped_columns",
    "match_template",
    "template_drift",
]

# The single (primitive, target_field) pair a mapping may legitimately reuse:
# every leftover column funnels into ``unmapped_record.raw``.
_UNMAPPED_TARGET: tuple[str, str] = ("unmapped_record", "raw")


def validate_mapping_fields(fields: list[FieldMapping]) -> list[str]:
    """Full-mapping structural validation.

    Returns a list of human-readable error strings (an empty list means the
    mapping is structurally valid). Checks:

    * each field via :func:`validate_field_mapping` (its error is collected);
    * no two fields map to the SAME ``(primitive, target_field)`` pair
      (duplicate target) unless that pair is ``unmapped_record.raw``;
    * at least one field is present (an empty mapping yields one error);
    * every ``source_column`` referenced is non-empty.

    The returned errors are de-duplicated and sorted for deterministic output.
    """
    if not fields:
        return ["mapping has no fields"]

    errors: list[str] = []
    seen_targets: set[tuple[str, str]] = set()

    for fm in fields:
        field_error = validate_field_mapping(fm)
        if field_error is not None:
            errors.append(field_error)

        if not fm.source_column.strip():
            errors.append(
                f"field mapping to {fm.primitive}.{fm.target_field} "
                "has an empty source_column"
            )

        target = (fm.primitive, fm.target_field)
        if target != _UNMAPPED_TARGET:
            if target in seen_targets:
                errors.append(
                    f"duplicate target {fm.primitive}.{fm.target_field}"
                )
            else:
                seen_targets.add(target)

    return sorted(set(errors))


def unmapped_columns(fields: list[FieldMapping], column_names: list[str]) -> list[str]:
    """Source columns present in the file but not referenced by any mapping field.

    These are the columns that would flow to the ``unmapped_record`` primitive.
    The result is de-duplicated and sorted.
    """
    referenced = {fm.source_column for fm in fields}
    return sorted({name for name in column_names if name not in referenced})


def match_template(header_signature: str, templates: list[dict]) -> dict | None:
    """Return the first template whose ``header_signature`` equals the argument.

    ``templates`` are raw dicts as stored (each carrying a ``header_signature``
    and ``fields``). Returns ``None`` when no template matches.
    """
    for template in templates:
        if template.get("header_signature") == header_signature:
            return template
    return None


def template_drift(template_fields: list[dict], column_names: list[str]) -> dict:
    """Compare a template's mapping fields to a new file's actual columns.

    Returns ``{'missing_columns': [...], 'new_columns': [...], 'applicable': bool}``:

    * ``missing_columns``: source columns the template maps that are ABSENT from
      ``column_names`` (sorted);
    * ``new_columns``: columns in ``column_names`` the template does not
      reference (sorted);
    * ``applicable``: ``True`` when ``missing_columns`` is empty — the template
      can be applied as-is and any ``new_columns`` are simply left unmapped.

    ``template_fields`` are raw dicts, each with a ``source_column`` key.
    """
    mapped = {
        field.get("source_column")
        for field in template_fields
        if field.get("source_column")
    }
    actual = set(column_names)
    missing = sorted(mapped - actual)
    new = sorted(actual - mapped)
    return {
        "missing_columns": missing,
        "new_columns": new,
        "applicable": not missing,
    }
