"""Canonical Tenant Import Engine contract (Python mirror of
``packages/shared/imports.ts``).

A tenant uploads a file (CSV / JSON / JSONL), Aether analyzes its schema, the
tenant maps source columns onto Aether's canonical primitives, a dry-run
validates the mapping, and — only after that — a commit stages the rows into
Bronze → Silver → the graph with full lineage.

The TS twin and this module are kept in lockstep by
``tests/contracts/test_imports_parity.py`` (const-array set equality on
statuses, primitives, transforms, and column types, plus the barrel export).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ── lifecycle ───────────────────────────────────────────────────────────────

ImportStatus = Literal[
    "created",
    "files_pending",
    "uploaded",
    "analyzing",
    "analyzed",
    "mapping",
    "mapped",
    "validating",
    "validated",
    "review_required",
    "approved",
    "committing",
    "committed",
    "partially_committed",
    "failed",
    "cancelled",
    "rolled_back",
]

IMPORT_STATUSES: tuple[str, ...] = (
    "created",
    "files_pending",
    "uploaded",
    "analyzing",
    "analyzed",
    "mapping",
    "mapped",
    "validating",
    "validated",
    "review_required",
    "approved",
    "committing",
    "committed",
    "partially_committed",
    "failed",
    "cancelled",
    "rolled_back",
)

# A session in one of these accepts no further transitions.
IMPORT_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"committed", "partially_committed", "failed", "cancelled", "rolled_back"}
)

# ── primitives ──────────────────────────────────────────────────────────────

ImportPrimitive = Literal[
    "entity",
    "identifier",
    "action",
    "relationship",
    "resource",
    "evidence",
    "metric",
    "governance_fact",
    "unmapped_record",
]

IMPORT_PRIMITIVES: tuple[str, ...] = (
    "entity",
    "identifier",
    "action",
    "relationship",
    "resource",
    "evidence",
    "metric",
    "governance_fact",
    "unmapped_record",
)

# Canonical target fields per primitive. A mapping targeting a field not listed
# here is rejected at map time (mirrors ``importPrimitiveFields`` in the TS twin).
IMPORT_PRIMITIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "entity": ("entity_type", "external_id", "display_name", "attributes"),
    "identifier": ("identifier_type", "value", "entity_ref", "confidence"),
    "action": ("action_type", "occurred_at", "entity_ref", "resource_ref", "properties"),
    "relationship": ("relationship_type", "from_ref", "to_ref", "weight", "properties"),
    "resource": ("resource_type", "external_id", "name", "attributes"),
    "evidence": ("evidence_type", "subject_ref", "source", "observed_at", "payload"),
    "metric": ("metric_name", "entity_ref", "value", "unit", "observed_at"),
    "governance_fact": (
        "fact_type",
        "subject_ref",
        "basis",
        "granted_at",
        "expires_at",
        "scope",
    ),
    "unmapped_record": ("raw",),
}

# Primitives whose presence in a mapping forces a governance review before commit.
GOVERNANCE_SENSITIVE_PRIMITIVES: frozenset[str] = frozenset(
    {"identifier", "governance_fact"}
)

# ── transforms ──────────────────────────────────────────────────────────────

ImportTransform = Literal[
    "none",
    "trim",
    "lowercase",
    "uppercase",
    "to_timestamp",
    "to_number",
    "to_boolean",
    "hash_sha256",
    "json_parse",
    "coalesce_empty_null",
]

IMPORT_TRANSFORMS: tuple[str, ...] = (
    "none",
    "trim",
    "lowercase",
    "uppercase",
    "to_timestamp",
    "to_number",
    "to_boolean",
    "hash_sha256",
    "json_parse",
    "coalesce_empty_null",
)

# ── column types & sensitivity ──────────────────────────────────────────────

ImportColumnType = Literal[
    "string",
    "integer",
    "float",
    "boolean",
    "datetime",
    "date",
    "json",
    "email",
    "url",
    "wallet_address",
    "phone",
    "uuid",
    "empty",
    "mixed",
]

IMPORT_COLUMN_TYPES: tuple[str, ...] = (
    "string",
    "integer",
    "float",
    "boolean",
    "datetime",
    "date",
    "json",
    "email",
    "url",
    "wallet_address",
    "phone",
    "uuid",
    "empty",
    "mixed",
)

ImportSensitivity = Literal["none", "pii", "identifier", "secret", "governance"]

IMPORT_SENSITIVITIES: tuple[str, ...] = (
    "none",
    "pii",
    "identifier",
    "secret",
    "governance",
)

# ── shapes ──────────────────────────────────────────────────────────────────


class ColumnProfile(BaseModel):
    """Per-column profile from schema analysis."""

    name: str
    inferred_type: ImportColumnType = "string"
    nullable: bool = True
    null_count: int = 0
    distinct_count: int = 0
    sample_values: list[str] = Field(default_factory=list)
    sensitivity: ImportSensitivity = "none"


class SchemaProfile(BaseModel):
    """The analyzed schema of a single uploaded file."""

    file_id: str
    format: str
    row_count: int = 0
    sampled_rows: int = 0
    columns: list[ColumnProfile] = Field(default_factory=list)
    delimiter: Optional[str] = None
    has_header: Optional[bool] = None


class FieldMapping(BaseModel):
    """One source-column → primitive-field mapping rule."""

    source_column: str
    primitive: ImportPrimitive
    target_field: str
    transform: ImportTransform = "none"
    required: bool = False


class ImportMapping(BaseModel):
    id: str
    import_id: str
    version: int = 1
    fields: list[FieldMapping] = Field(default_factory=list)
    created_at: Optional[str] = None


class ValidationError(BaseModel):
    row: int
    source_column: Optional[str] = None
    primitive: Optional[ImportPrimitive] = None
    code: str
    message: str


class ValidationResult(BaseModel):
    import_id: str
    mapping_version: int = 1
    ok: bool = False
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    errors: list[ValidationError] = Field(default_factory=list)
    errors_truncated: bool = False
    governance_review_required: bool = False
    governance_reasons: list[str] = Field(default_factory=list)


class ImportTemplate(BaseModel):
    id: str
    tenant_id: str
    name: str
    header_signature: str
    fields: list[FieldMapping] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── helpers ─────────────────────────────────────────────────────────────────


def is_terminal_status(status: str) -> bool:
    """True when a session is in a terminal state."""
    return status in IMPORT_TERMINAL_STATUSES


def primitive_fields(primitive: str) -> tuple[str, ...]:
    """Canonical target fields for a primitive (empty tuple for an unknown one)."""
    return IMPORT_PRIMITIVE_FIELDS.get(primitive, ())


def validate_field_mapping(mapping: FieldMapping) -> Optional[str]:
    """Return an error string if the mapping targets an unknown primitive/field,
    else ``None``. Kept pure so both the map route and the validator use it."""
    if mapping.primitive not in IMPORT_PRIMITIVE_FIELDS:
        return f"unknown primitive {mapping.primitive!r}"
    allowed = IMPORT_PRIMITIVE_FIELDS[mapping.primitive]
    if mapping.target_field not in allowed:
        return (
            f"field {mapping.target_field!r} is not valid for primitive "
            f"{mapping.primitive!r} (allowed: {', '.join(allowed)})"
        )
    if mapping.transform not in IMPORT_TRANSFORMS:
        return f"unknown transform {mapping.transform!r}"
    return None


def mapping_requires_review(fields: list[FieldMapping], columns: list[ColumnProfile]) -> tuple[bool, list[str]]:
    """Decide whether a mapping needs a governance review before commit.

    Triggers when any mapped primitive is governance-sensitive
    (identifier / governance_fact) or any mapped source column was profiled as
    pii / identifier / secret / governance. Returns ``(required, reasons)``.
    """
    reasons: list[str] = []
    sensitive_by_col = {c.name: c.sensitivity for c in columns}
    for fm in fields:
        if fm.primitive in GOVERNANCE_SENSITIVE_PRIMITIVES:
            reasons.append(f"maps to governance-sensitive primitive {fm.primitive!r}")
        sensitivity = sensitive_by_col.get(fm.source_column, "none")
        if sensitivity in {"pii", "identifier", "secret", "governance"}:
            reasons.append(
                f"source column {fm.source_column!r} is {sensitivity}"
            )
    return (len(reasons) > 0, sorted(set(reasons)))


__all__ = [
    "ImportStatus",
    "IMPORT_STATUSES",
    "IMPORT_TERMINAL_STATUSES",
    "ImportPrimitive",
    "IMPORT_PRIMITIVES",
    "IMPORT_PRIMITIVE_FIELDS",
    "GOVERNANCE_SENSITIVE_PRIMITIVES",
    "ImportTransform",
    "IMPORT_TRANSFORMS",
    "ImportColumnType",
    "IMPORT_COLUMN_TYPES",
    "ImportSensitivity",
    "IMPORT_SENSITIVITIES",
    "ColumnProfile",
    "SchemaProfile",
    "FieldMapping",
    "ImportMapping",
    "ValidationError",
    "ValidationResult",
    "ImportTemplate",
    "is_terminal_status",
    "primitive_fields",
    "validate_field_mapping",
    "mapping_requires_review",
]

# Silence unused-import complaints for re-exported typing helpers.
_ = (Any,)
