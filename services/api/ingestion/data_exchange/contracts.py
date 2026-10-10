"""Canonical Data Exchange Plane contract (Python mirror of
``packages/shared/data-exchange.ts``).

The Data Exchange Plane is Aether's governed, tenant-facing import/export
layer.  Its doctrine is *many ways in — one canonical graph — many ways out —
one governed portability layer*.  This module owns the vocabulary every
ingress and egress artifact speaks (direction, status, format,
classification, source type) plus the five canonical exchange contracts
defined by the Data Exchange blueprint:

- ``DataArtifactContract``  — one artifact, either direction, bound to a
  tenant + object key.  ``object_key`` is the durable byte locator; Postgres
  never stores artifact payload bytes.
- ``ImportSourceContract``  — an ingress source (day-one: ``file``).
- ``ImportMappingContract`` — a mapping of source columns onto canonical
  Aether primitives.
- ``ExportSpecContract``    — an egress request (structured formats only).
- ``ReportSpecContract``    — a human-readable report request (PDF), which is
  an *artifact* but never a structured export format.

The TS twin and this module are kept in lockstep by
``tests/contracts/test_data_exchange_parity.py`` (const-array equality on
directions, artifact statuses, ingress/egress formats, source types, and
classifications, plus the barrel export).

Milestone status (M0): this is the declared-but-dark contract skeleton.  No
route mounts, no table, no job references these yet.  The term-to-canonical
mapping onto the existing import engine's ``ImportSessionState`` FSM and the
export engine's artifact repository lands in M3/M4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ── direction ───────────────────────────────────────────────────────────────

DataExchangeDirection = Literal["ingress", "egress"]

DATA_EXCHANGE_DIRECTIONS: tuple[str, ...] = ("ingress", "egress")


# ── artifact lifecycle ──────────────────────────────────────────────────────
# One status vocabulary for every artifact, regardless of direction.  A status
# is explicit — never inferred from the existence of bytes.

DataArtifactStatus = Literal[
    "created",
    "upload_pending",
    "uploading",
    "uploaded",
    "scanning",
    "analyzing",
    "ready",
    "processing",
    "committed",
    "partially_committed",
    "generating",
    "available",
    "failed",
    "expired",
    "deleted",
    "revoked",
]

DATA_ARTIFACT_STATUSES: tuple[str, ...] = (
    "created",
    "upload_pending",
    "uploading",
    "uploaded",
    "scanning",
    "analyzing",
    "ready",
    "processing",
    "committed",
    "partially_committed",
    "generating",
    "available",
    "failed",
    "expired",
    "deleted",
    "revoked",
)

# ``available``/``committed`` require durable bytes *and* a verified checksum.
DATA_ARTIFACT_TERMINAL_STATUSES: tuple[str, ...] = (
    "committed",
    "partially_committed",
    "available",
    "failed",
    "expired",
    "deleted",
    "revoked",
)


# ── formats ─────────────────────────────────────────────────────────────────
# Deliberately split: the import engine speaks ``jsonl``; the export engine
# speaks ``ndjson``.  Both share csv/json/parquet.  PDF is *never* a
# structured format — it is a ReportSpecContract artifact.

IngressFormat = Literal["csv", "json", "jsonl", "parquet"]
DATA_EXCHANGE_INGRESS_FORMATS: tuple[str, ...] = ("csv", "json", "jsonl", "parquet")

EgressFormat = Literal["csv", "json", "ndjson", "parquet"]
DATA_EXCHANGE_EGRESS_FORMATS: tuple[str, ...] = ("csv", "json", "ndjson", "parquet")


# ── source types ────────────────────────────────────────────────────────────
# Day-one tenant UI exposes ``file``; the contract already carries the future
# s3 / api / connector / warehouse sources so no schema redesign is needed.

DataExchangeSourceType = Literal["file", "s3", "api", "connector", "warehouse"]
DATA_EXCHANGE_SOURCE_TYPES: tuple[str, ...] = ("file", "s3", "api", "connector", "warehouse")


# ── content classification ──────────────────────────────────────────────────
# Artifact and field content sensitivity.  This is the Data Exchange
# classification vocabulary; the existing import engine's column-level
# sensitivity set (``none | pii | identifier | secret | governance``) and the
# shared privacy ``DataClassification`` remain canonical *downstream* — policy
# maps these labels onto them (see ``policy.py``).

DataExchangeClassification = Literal[
    "none",
    "identifier",
    "pii",
    "secret",
    "credential",
    "governance",
    "financial",
    "location",
    "temporal",
]

DATA_EXCHANGE_CLASSIFICATIONS: tuple[str, ...] = (
    "none",
    "identifier",
    "pii",
    "secret",
    "credential",
    "governance",
    "financial",
    "location",
    "temporal",
)

# Classifications that are blocked from graph commit by default unless an
# elevated tenant policy explicitly permits them.
DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS: tuple[str, ...] = ("secret", "credential")


# ── canonical exchange contracts ────────────────────────────────────────────

class DataArtifactContract(BaseModel):
    """One data-exchange artifact, either direction.

    ``object_key`` is the durable byte locator inside the shared ObjectStore.
    Every artifact is tenant-scoped, carries a sha256, an explicit status, and
    a persisted content classification.  Metadata may survive payload expiry
    as a tombstone where policy requires.
    """

    artifact_id: str
    tenant_id: str = Field(..., min_length=1)
    direction: DataExchangeDirection
    artifact_type: str
    job_id: Optional[str] = None
    source_or_destination: dict[str, Any] = Field(default_factory=dict)
    object_key: str = Field(..., min_length=1)
    filename: str
    format: str
    content_type: str
    size_bytes: int = Field(..., ge=0)
    sha256: str = Field(..., min_length=1)
    schema_version: Optional[str] = None
    classification: DataExchangeClassification
    encryption: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    status: DataArtifactStatus
    created_by: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class ImportSourceContract(BaseModel):
    """An ingress source session.  Day-one source type is ``file``; future S3 /
    warehouse sources ride the same contract."""

    import_id: str
    tenant_id: str = Field(..., min_length=1)
    source_type: DataExchangeSourceType
    artifact_id: str
    format: IngressFormat
    schema_version: Optional[str] = None
    declared_timezone: Optional[str] = None
    declared_currency: Optional[str] = None
    ownership: Literal["tenant_owned", "licensed", "unknown"] = "unknown"
    terms_status: str = "accepted"
    provenance: dict[str, Any] = Field(default_factory=dict)


class ImportMappingContract(BaseModel):
    """A mapping of source fields onto canonical Aether primitives.

    Field-level mapping details are owned by the import engine's existing
    ``FieldMapping`` model; this contract is the Data Exchange envelope that
    adds identity / temporal / currency / geographic / consent policy plus the
    unknown-field handling rule and version pinning."""

    import_id: str
    tenant_id: str = Field(..., min_length=1)
    version: int = Field(..., ge=1)
    fields: list[dict[str, Any]] = Field(default_factory=list)
    identity_policy: dict[str, Any] = Field(default_factory=dict)
    temporal_policy: dict[str, Any] = Field(default_factory=dict)
    currency_policy: dict[str, Any] = Field(default_factory=dict)
    geographic_policy: dict[str, Any] = Field(default_factory=dict)
    consent_policy: dict[str, Any] = Field(default_factory=dict)
    unknown_field_policy: Literal["error", "ignore"] = "error"
    created_by: Optional[str] = None
    created_at: datetime


class ExportSpecContract(BaseModel):
    """An egress request for structured data.  PDF is intentionally absent —
    it is expressed as a ReportSpecContract instead."""

    export_id: str
    tenant_id: str = Field(..., min_length=1)
    resource: str
    scope: dict[str, Any] = Field(default_factory=dict)
    fields: Optional[list[str]] = None
    include_relationships: bool = False
    include_identifiers: bool = False
    include_provenance: bool = False
    include_raw_events: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    temporal: dict[str, Any] = Field(default_factory=dict)
    display_timezone: str = "UTC"
    format: EgressFormat
    compression: Optional[Literal["gzip", "snappy", "zstd"]] = None
    destination: dict[str, Any] = Field(default_factory=dict)
    requested_by: Optional[str] = None


class ReportSpecContract(BaseModel):
    """A request for a human-readable report (PDF) artifact.

    The report engine produces a PDF through the same DataArtifactContract,
    but PDF is not a structured export format and never enters
    EgressFormat."""

    report_id: str
    tenant_id: str = Field(..., min_length=1)
    resource: str
    scope: dict[str, Any] = Field(default_factory=dict)
    temporal: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    display_timezone: str = "UTC"
    template: str
    include_methodology: bool = True
    include_provenance_summary: bool = True
    requested_by: Optional[str] = None
