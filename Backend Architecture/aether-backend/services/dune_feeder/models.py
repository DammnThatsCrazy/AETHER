"""
Aether Service — Dune Analytics Feeder Models

Data models for the governed Dune feeder service.
Dune data lands in Bronze only; Silver promotion requires explicit operator action.
Graph state is NEVER mutated directly by this service.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ─── Raw inbound from Dune API ────────────────────────────────────────────────

class DuneQueryResult(BaseModel):
    """Raw result pulled from the Dune Analytics API."""
    query_id: str = Field(..., description="Dune query ID (numeric string)")
    execution_id: str = Field(..., description="Dune execution/run ID")
    query_name: str = Field(..., description="Human-readable query name")
    query_version: Optional[str] = Field(None, description="Optional semver or hash for query versioning")
    rows: list[dict[str, Any]] = Field(..., description="Raw result rows from Dune")
    pulled_at: str = Field(..., description="ISO-8601 timestamp when the pull was executed")


# ─── Provenance ───────────────────────────────────────────────────────────────

class ProvenanceStep(BaseModel):
    """A single step in the provenance chain for a Bronze record."""
    step: str = Field(..., description="e.g. 'dune_pull', 'freshness_gate', 'quality_gate', 'bronze_land'")
    actor: str = Field(..., description="Service or operator that performed this step")
    timestamp: str = Field(..., description="ISO-8601 timestamp")
    notes: Optional[str] = None


class ProvenanceEnvelope(BaseModel):
    """Per-row provenance chain recorded at Bronze landing time."""
    provider: str = "dune"
    query_id: str
    execution_id: str
    source_tag: str
    pulled_at: str
    row_hash: str
    steps: list[ProvenanceStep] = Field(default_factory=list)


# ─── Bronze record ────────────────────────────────────────────────────────────

class DuneBronzeRecord(BaseModel):
    """A single row landed in the Bronze data tier with full provenance."""
    record_id: str = Field(..., description="UUID for this Bronze record")
    provider: str = "dune"
    query_id: str
    query_name: str
    query_version: Optional[str] = None
    execution_id: str
    source_tag: str = Field(..., description="User-provided batch identifier used for rollback")
    domain: str = Field(..., description="Data domain: onchain, governance, market, etc.")
    tenant_scope: Optional[str] = Field(None, description="Optional tenant restriction")
    pulled_at: str = Field(..., description="ISO-8601 timestamp from Dune")
    landed_at: str = Field(..., description="ISO-8601 timestamp when this record hit Bronze")
    row_index: int = Field(..., description="Position of this row within the original result set")
    row_data: dict[str, Any] = Field(..., description="Raw row contents")
    row_hash: str = Field(..., description="SHA-256 hex of the serialised row_data")
    freshness_timestamp: str = Field(..., description="Timestamp used for the freshness gate check")
    quality_score: float = Field(..., ge=0.0, le=1.0, description="Quality gate score 0.0–1.0")
    promotion_status: str = Field(
        default="bronze",
        description="Lifecycle stage: bronze | silver | rejected",
    )
    rejection_reason: Optional[str] = None
    provenance_chain: list[ProvenanceStep] = Field(default_factory=list)


# ─── Gate results ─────────────────────────────────────────────────────────────

class FreshnessResult(BaseModel):
    """Result of a freshness gate check."""
    passed: bool
    pulled_at: str
    age_seconds: float
    max_age_seconds: int
    reason: Optional[str] = None


class QualityResult(BaseModel):
    """Result of a quality gate check for a single row."""
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    type_errors: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


# ─── API request / response ───────────────────────────────────────────────────

class FeederIngestRequest(BaseModel):
    """Admin API request body for ingesting a Dune query result into Bronze."""
    query_result: DuneQueryResult
    source_tag: str = Field(..., description="Unique batch/run identifier for auditability and rollback")
    domain: str = Field(..., description="Data domain: onchain, governance, market, social, identity, tradfi")
    tenant_scope: Optional[str] = Field(None, description="Optional tenant restriction")
    schema: Optional[dict[str, str]] = Field(
        None,
        description="Optional expected schema: {field_name: type_name}. Used for quality gate.",
    )
    required_fields: Optional[list[str]] = Field(
        None,
        description="Required field names for quality gate. Defaults to all schema keys.",
    )
    max_age_seconds: int = Field(
        default=3600,
        description="Maximum acceptable age of the Dune pull in seconds (freshness gate)",
    )
    quality_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum quality score for a row to be accepted into Bronze",
    )


class FeederIngestResponse(BaseModel):
    """API response after a Dune ingest operation."""
    source_tag: str
    domain: str
    query_id: str
    execution_id: str
    rows_submitted: int
    rows_accepted: int
    rows_rejected: int
    freshness_passed: bool
    freshness_age_seconds: float
    rejected_reasons: list[str] = Field(default_factory=list)


class FeederRollbackRequest(BaseModel):
    """Admin API request body for rolling back records by source_tag."""
    source_tag: str = Field(..., description="Batch identifier to roll back (removes from bronze and silver)")
    tenant_scope: Optional[str] = Field(
        None,
        description=(
            "Restrict rollback to records ingested under this tenant scope. "
            "When set, only records whose tenant_scope matches are deleted."
        ),
    )


class FeederHealthStatus(BaseModel):
    """Health and operational metrics for the Dune feeder service."""
    status: str = Field(..., description="overall: ok | degraded | down")
    total_bronze_records: int
    total_silver_records: int
    total_gold_records: int = Field(default=0, description="Number of materialized Gold aggregate records")
    unique_source_tags: int
    rejection_rate: float = Field(..., description="Fraction of rows rejected across all ingests")
    last_ingest_at: Optional[str] = None
    last_ingest_source_tag: Optional[str] = None
    graph_isolation_enforced: bool = Field(
        default=True,
        description="Invariant: Dune data never writes directly to the graph",
    )


class FeederGoldMaterializeRequest(BaseModel):
    """Admin API request body for materializing Gold aggregates from Silver rows."""
    source_tag: str = Field(..., description="Batch identifier to materialize to Gold")
    tenant_scope: Optional[str] = Field(
        None,
        description="Restrict materialization to records ingested under this tenant scope.",
    )
