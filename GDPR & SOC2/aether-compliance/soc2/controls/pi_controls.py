"""
PI-2.1 — Processing Integrity Controls Documentation
Formal documentation of all processing integrity controls implemented in Aether.

Maps each technical control to its SOC 2 PI criterion, evidence source,
test procedure, and owner. Satisfies the documentation requirement for PI 1.1-1.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PIControl:
    """A single documented processing integrity control."""
    control_id: str
    criterion: str
    title: str
    description: str
    implementation: str
    evidence_sources: list
    test_procedure: str
    owner: str
    frequency: str    # continuous | daily | per-request | on-change


PI_CONTROLS: list[PIControl] = [
    PIControl(
        control_id="PI-INPUT-001",
        criterion="PI 1.1",
        title="API Input Validation — Pydantic Schema Enforcement",
        description=(
            "All API endpoints enforce strict input schema validation using Pydantic v2 models. "
            "Invalid requests are rejected with HTTP 422 before reaching business logic."
        ),
        implementation=(
            "FastAPI + Pydantic: every request body, path parameter, and query string is "
            "validated against a typed model. Strict mode enabled — no coercion of "
            "incompatible types. Validation errors return structured 422 responses."
        ),
        evidence_sources=[
            "Backend API route models (services/*/routes.py)",
            "Pydantic model definitions across all service modules",
            "CI test suite: tests/unit/test_api_contracts.py",
        ],
        test_procedure=(
            "1. Submit malformed payloads to each endpoint. Verify HTTP 422 returned. "
            "2. Submit payloads with extra fields. Verify extra fields stripped. "
            "3. Run API contract tests in CI. Verify 100% pass rate."
        ),
        owner="Engineering",
        frequency="per-request",
    ),
    PIControl(
        control_id="PI-INPUT-002",
        criterion="PI 1.1",
        title="Event Schema Validation — Data Ingestion Layer",
        description=(
            "All ingested SDK events are validated against versioned event schemas before "
            "persisting to the data lake. Invalid or malformed events are quarantined."
        ),
        implementation=(
            "Data Ingestion Layer validates event_type, required fields, and data types. "
            "Invalid events routed to dead-letter queue (DLQ) with error metadata. "
            "Schema versions tracked in schema_version.ts."
        ),
        evidence_sources=[
            "Data Ingestion Layer/src/ — validation middleware",
            "packages/shared/schema-version.ts",
            "DLQ metrics in CloudWatch",
        ],
        test_procedure=(
            "1. Send events with missing required fields. Verify DLQ routing. "
            "2. Send events with invalid types. Verify rejection. "
            "3. Check DLQ error rate in CloudWatch: must be < 0.1% of valid traffic."
        ),
        owner="Engineering",
        frequency="per-request",
    ),
    PIControl(
        control_id="PI-IDEM-001",
        criterion="PI 1.2",
        title="Idempotency — Redis SETNX Deduplication",
        description=(
            "All write operations carry an idempotency key. Duplicate requests within the "
            "deduplication window (24h) are rejected with HTTP 409, preventing duplicate records."
        ),
        implementation=(
            "Ingestion middleware: Redis SETNX on idempotency_key with 24h TTL. "
            "If key exists, return cached response. If new, process and cache result. "
            "Idempotency keys must be UUIDs supplied by the caller."
        ),
        evidence_sources=[
            "Backend Architecture/aether-backend/services/x402/idempotency.py",
            "Ingestion service middleware config",
            "Redis SETNX pattern documented in SUBSYSTEM-CACHE.md",
        ],
        test_procedure=(
            "1. Submit identical event twice with same idempotency key. "
            "2. Verify database has exactly 1 record. "
            "3. Verify second call returns HTTP 409 with original response body."
        ),
        owner="Engineering",
        frequency="per-request",
    ),
    PIControl(
        control_id="PI-AUDIT-001",
        criterion="PI 1.3",
        title="Event Sourcing — Immutable Audit Log",
        description=(
            "All data mutations are captured in an append-only event log. "
            "The event store serves as the system of record; projections are derived. "
            "No UPDATE or DELETE on the event store — only INSERT."
        ),
        implementation=(
            "TimescaleDB hypertable (append-only) + S3 data lake (Parquet, immutable). "
            "Behavioral events, consent changes, DSR actions, and agent decisions all "
            "written as immutable log entries. Audit engine provides 5 trail types."
        ),
        evidence_sources=[
            "GDPR & SOC2/aether-compliance/audit/trails/audit_engine.py",
            "TimescaleDB hypertable DDL (append-only constraint)",
            "S3 data lake Parquet files (write-once policy via S3 Object Lock)",
        ],
        test_procedure=(
            "1. Perform data mutation. Verify event log entry created with correct actor/action. "
            "2. Attempt to DELETE from audit table. Verify permission denied. "
            "3. Verify S3 Object Lock prevents overwrite of Parquet files."
        ),
        owner="Engineering / Security",
        frequency="continuous",
    ),
    PIControl(
        control_id="PI-QUALITY-001",
        criterion="PI 1.4",
        title="Data Quality Scoring — ML Pipeline Validation",
        description=(
            "ML features are scored for completeness, freshness, and anomaly indicators "
            "before being used in model training or inference. Low-quality features are flagged."
        ),
        implementation=(
            "Data quality pipeline: schema completeness scoring, field null-rate checks, "
            "statistical anomaly detection (z-score > 3σ flagged), freshness validation "
            "(features stale if > configured TTL). Quality score attached to every feature batch."
        ),
        evidence_sources=[
            "Backend Architecture/aether-backend/services/lake/drift_monitor.py",
            "ML Models/ — feature validation pipeline",
            "CloudWatch metric: DataQualityScore (target > 95%)",
        ],
        test_procedure=(
            "1. Inject batch with 20% null fields. Verify quality score < threshold. "
            "2. Inject stale features. Verify freshness flag set. "
            "3. Verify quality score metric in CloudWatch is > 95% over trailing 7 days."
        ),
        owner="Engineering / Data Science",
        frequency="per-batch",
    ),
]


class PIControlsDocument:
    """Manages and presents the processing integrity controls documentation."""

    def __init__(self):
        self.controls = PI_CONTROLS

    def generate_evidence(self) -> dict:
        by_criterion: dict = {}
        for c in self.controls:
            by_criterion.setdefault(c.criterion, []).append(c.control_id)

        return {
            "control": "PI-2.1",
            "artifact": "Processing Integrity Controls Documentation",
            "total_controls": len(self.controls),
            "criteria_covered": list(by_criterion.keys()),
            "owners": list({c.owner for c in self.controls}),
            "status": "IMPLEMENTED",
            "evidence_type": "controls_document",
        }

    def print_document(self) -> None:
        print(f"\n  Processing Integrity Controls — {len(self.controls)} controls documented\n")
        for c in self.controls:
            print(f"  [{c.control_id}] {c.title}")
            print(f"    Criterion: {c.criterion}  |  Frequency: {c.frequency}  |  Owner: {c.owner}")
            print(f"    {c.description[:90]}...")
            print(f"    Evidence: {c.evidence_sources[0]}")
