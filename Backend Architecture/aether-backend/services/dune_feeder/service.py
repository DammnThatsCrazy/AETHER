"""
Aether Service — DuneFeederService

Governed ingestion of Dune Analytics query results into the Bronze data tier.

Key invariants:
- Dune data CANNOT directly mutate canonical graph state.
- All rows land in Bronze only.
- Silver promotion requires explicit operator action via promote_to_silver().
- Any graph candidate generation must go through a review queue (not this service).
- This module MUST NOT import anything from graph/neptune modules.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.common.common import BadRequestError, NotFoundError, parse_iso
from shared.logger.logger import get_logger, metrics

from services.dune_feeder.models import (
    DuneBronzeRecord,
    FeederHealthStatus,
    FeederIngestRequest,
    FeederIngestResponse,
    FreshnessResult,
    ProvenanceStep,
    QualityResult,
)

logger = get_logger("aether.service.dune_feeder")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_row(row: dict) -> str:
    """Deterministic SHA-256 of a row dict (sorted keys)."""
    serialised = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


# ── In-memory stores (dev/test mode) ─────────────────────────────────────────
# In production these would delegate to a lake repository.

_BRONZE_STORE: dict[str, DuneBronzeRecord] = {}   # record_id -> record
_SILVER_STORE: dict[str, DuneBronzeRecord] = {}   # record_id -> promoted copy
_GOLD_STORE: dict[str, dict] = {}                 # gold_id -> materialized aggregate

# Totals for health metrics
_TOTAL_SUBMITTED: int = 0
_TOTAL_REJECTED: int = 0
_LAST_INGEST_AT: Optional[str] = None
_LAST_INGEST_SOURCE_TAG: Optional[str] = None


def _reset_stores() -> None:
    """Reset all in-memory stores — used by tests."""
    global _TOTAL_SUBMITTED, _TOTAL_REJECTED, _LAST_INGEST_AT, _LAST_INGEST_SOURCE_TAG
    _BRONZE_STORE.clear()
    _SILVER_STORE.clear()
    _GOLD_STORE.clear()
    _TOTAL_SUBMITTED = 0
    _TOTAL_REJECTED = 0
    _LAST_INGEST_AT = None
    _LAST_INGEST_SOURCE_TAG = None


# ── Service ───────────────────────────────────────────────────────────────────

class DuneFeederService:
    """
    Governed feeder that lands Dune Analytics data in Bronze only.

    Design constraints:
    - No graph/Neptune imports or writes.
    - No Silver auto-promotion; operators must call promote_to_silver() explicitly.
    - Provenance is recorded per row at landing time.
    - Freshness and quality gates are enforced before any row touches storage.
    """

    # ── Freshness gate ────────────────────────────────────────────────────────

    def check_freshness(self, pulled_at: str, max_age_seconds: int) -> FreshnessResult:
        """
        Reject stale Dune results.

        Args:
            pulled_at: ISO-8601 timestamp from the Dune pull.
            max_age_seconds: Maximum acceptable age in seconds.

        Returns:
            FreshnessResult with passed=True if within max_age_seconds.
        """
        try:
            pull_dt = parse_iso(pulled_at)
        except BadRequestError:
            return FreshnessResult(
                passed=False,
                pulled_at=pulled_at,
                age_seconds=-1.0,
                max_age_seconds=max_age_seconds,
                reason=f"Cannot parse pulled_at timestamp: {pulled_at}",
            )

        now = datetime.now(timezone.utc)
        # Make pull_dt timezone-aware if naive
        if pull_dt.tzinfo is None:
            pull_dt = pull_dt.replace(tzinfo=timezone.utc)

        age_seconds = (now - pull_dt).total_seconds()

        # Reject clearly future-dated timestamps (allow up to 5 min clock skew)
        if age_seconds < -300:
            return FreshnessResult(
                passed=False,
                pulled_at=pulled_at,
                age_seconds=age_seconds,
                max_age_seconds=max_age_seconds,
                reason=(
                    f"pulled_at is {abs(age_seconds):.0f}s in the future; "
                    "clock skew tolerance is 300s"
                ),
            )

        if age_seconds > max_age_seconds:
            return FreshnessResult(
                passed=False,
                pulled_at=pulled_at,
                age_seconds=age_seconds,
                max_age_seconds=max_age_seconds,
                reason=(
                    f"Data is {age_seconds:.0f}s old; max allowed is {max_age_seconds}s"
                ),
            )

        return FreshnessResult(
            passed=True,
            pulled_at=pulled_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
        )

    # ── Quality gate ──────────────────────────────────────────────────────────

    def check_quality(
        self,
        row: dict,
        schema: Optional[dict[str, str]] = None,
        required_fields: Optional[list[str]] = None,
    ) -> QualityResult:
        """
        Validate a single row against an optional schema and required-field list.

        Args:
            row: A single result row (dict).
            schema: Optional {field_name: type_name} mapping.
            required_fields: Fields that must be present and non-None.

        Returns:
            QualityResult with a score in [0, 1].
        """
        missing_fields: list[str] = []
        type_errors: list[str] = []

        effective_required = required_fields or (list(schema.keys()) if schema else [])

        # Required field presence check
        for field_name in effective_required:
            if field_name not in row or row[field_name] is None:
                missing_fields.append(field_name)

        # Type check (best-effort)
        if schema:
            # "number" accepts both int and float — integer JSON values are valid
            # numeric values and would otherwise be rejected by isinstance(1, float).
            _TYPE_MAP: dict[str, type | tuple] = {
                "str": str, "string": str,
                "int": int, "integer": int,
                "float": float, "number": (int, float),
                "bool": bool, "boolean": bool,
                "list": list, "dict": dict,
            }
            for field_name, expected_type_name in schema.items():
                if field_name in row and row[field_name] is not None:
                    expected_type = _TYPE_MAP.get(expected_type_name.lower())
                    if expected_type and not isinstance(row[field_name], expected_type):
                        type_errors.append(
                            f"{field_name}: expected {expected_type_name}, "
                            f"got {type(row[field_name]).__name__}"
                        )

        total_checks = len(effective_required) + len(type_errors)
        failed = len(missing_fields) + len(type_errors)

        if total_checks == 0:
            score = 1.0
        else:
            score = max(0.0, 1.0 - (failed / total_checks))

        passed = len(missing_fields) == 0 and len(type_errors) == 0

        reason: Optional[str] = None
        if missing_fields:
            reason = f"Missing required fields: {missing_fields}"
        elif type_errors:
            reason = f"Type errors: {type_errors}"

        return QualityResult(
            passed=passed,
            score=score,
            missing_fields=missing_fields,
            type_errors=type_errors,
            reason=reason,
        )

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest(self, payload: FeederIngestRequest) -> FeederIngestResponse:
        """
        Accept a Dune query result, run freshness + quality gates, land in Bronze.

        Silver promotion is NOT automatic. Operators must call promote_to_silver().
        Graph state is NEVER touched here.

        Args:
            payload: FeederIngestRequest with DuneQueryResult + gate configuration.

        Returns:
            FeederIngestResponse with per-batch statistics.
        """
        global _TOTAL_SUBMITTED, _TOTAL_REJECTED, _LAST_INGEST_AT, _LAST_INGEST_SOURCE_TAG

        qr = payload.query_result

        # ── Freshness gate (batch-level) ──────────────────────────────────────
        freshness = self.check_freshness(qr.pulled_at, payload.max_age_seconds)
        if not freshness.passed:
            logger.warning(
                "Dune ingest rejected: freshness gate failed",
                extra={
                    "source_tag": payload.source_tag,
                    "query_id": qr.query_id,
                    "reason": freshness.reason,
                },
            )
            raise BadRequestError(
                f"Freshness gate failed: {freshness.reason}",
                details={
                    "pulled_at": qr.pulled_at,
                    "age_seconds": freshness.age_seconds,
                    "max_age_seconds": payload.max_age_seconds,
                },
            )

        now_iso = _utc_now_iso()
        rows_accepted = 0
        rows_rejected = 0
        rejected_reasons: list[str] = []

        _TOTAL_SUBMITTED += len(qr.rows)

        for idx, row in enumerate(qr.rows):
            # ── Quality gate (per-row) ────────────────────────────────────────
            quality = self.check_quality(
                row,
                schema=payload.schema,
                required_fields=payload.required_fields,
            )

            if not quality.passed or quality.score < payload.quality_threshold:
                rows_rejected += 1
                _TOTAL_REJECTED += 1
                reason = quality.reason or f"Quality score {quality.score:.2f} below threshold {payload.quality_threshold}"
                rejected_reasons.append(f"row[{idx}]: {reason}")
                metrics.increment(
                    "dune_feeder_row_rejected",
                    labels={"domain": payload.domain, "query_id": qr.query_id},
                )
                continue

            # ── Build provenance chain ────────────────────────────────────────
            provenance = [
                ProvenanceStep(
                    step="dune_pull",
                    actor="dune_analytics",
                    timestamp=qr.pulled_at,
                    notes=f"execution_id={qr.execution_id}",
                ),
                ProvenanceStep(
                    step="freshness_gate",
                    actor="dune_feeder_service",
                    timestamp=now_iso,
                    notes=f"age={freshness.age_seconds:.0f}s / max={payload.max_age_seconds}s PASS",
                ),
                ProvenanceStep(
                    step="quality_gate",
                    actor="dune_feeder_service",
                    timestamp=now_iso,
                    notes=f"score={quality.score:.3f} threshold={payload.quality_threshold} PASS",
                ),
                ProvenanceStep(
                    step="bronze_land",
                    actor="dune_feeder_service",
                    timestamp=now_iso,
                    notes=f"source_tag={payload.source_tag} domain={payload.domain}",
                ),
            ]

            row_hash = _hash_row(row)
            record_id = str(uuid.uuid4())

            bronze_record = DuneBronzeRecord(
                record_id=record_id,
                provider="dune",
                query_id=qr.query_id,
                query_name=qr.query_name,
                query_version=qr.query_version,
                execution_id=qr.execution_id,
                source_tag=payload.source_tag,
                domain=payload.domain,
                tenant_scope=payload.tenant_scope,
                pulled_at=qr.pulled_at,
                landed_at=now_iso,
                row_index=idx,
                row_data=row,
                row_hash=row_hash,
                freshness_timestamp=qr.pulled_at,
                quality_score=quality.score,
                promotion_status="bronze",
                provenance_chain=provenance,
            )

            _BRONZE_STORE[record_id] = bronze_record
            rows_accepted += 1
            metrics.increment(
                "dune_feeder_row_accepted",
                labels={"domain": payload.domain, "query_id": qr.query_id},
            )

        _LAST_INGEST_AT = now_iso
        _LAST_INGEST_SOURCE_TAG = payload.source_tag

        logger.info(
            "Dune ingest complete",
            extra={
                "source_tag": payload.source_tag,
                "query_id": qr.query_id,
                "domain": payload.domain,
                "rows_submitted": len(qr.rows),
                "rows_accepted": rows_accepted,
                "rows_rejected": rows_rejected,
            },
        )
        metrics.increment(
            "dune_feeder_ingest",
            labels={"domain": payload.domain, "status": "ok"},
        )

        return FeederIngestResponse(
            source_tag=payload.source_tag,
            domain=payload.domain,
            query_id=qr.query_id,
            execution_id=qr.execution_id,
            rows_submitted=len(qr.rows),
            rows_accepted=rows_accepted,
            rows_rejected=rows_rejected,
            freshness_passed=True,
            freshness_age_seconds=freshness.age_seconds,
            rejected_reasons=rejected_reasons,
        )

    # ── Silver promotion ──────────────────────────────────────────────────────

    def promote_to_silver(self, source_tag: str, tenant_scope: Optional[str] = None) -> int:
        """
        Promote all valid Bronze rows with matching source_tag to Silver.

        Only rows with promotion_status='bronze' and quality_score >= 0.8 are
        eligible.  Rows marked 'rejected' stay rejected.

        Args:
            source_tag: Batch identifier to promote.
            tenant_scope: When provided, only promote rows belonging to this tenant.

        Returns:
            Number of rows promoted.
        """
        promoted = 0
        for record_id, record in list(_BRONZE_STORE.items()):
            if record.source_tag != source_tag:
                continue
            if tenant_scope is not None and record.tenant_scope != tenant_scope:
                continue
            if record.promotion_status != "bronze":
                continue
            if record.quality_score < 0.8:
                continue

            # Mutate status in-place and copy to Silver store
            updated = record.model_copy(
                update={
                    "promotion_status": "silver",
                    "provenance_chain": record.provenance_chain + [
                        ProvenanceStep(
                            step="silver_promotion",
                            actor="dune_feeder_service",
                            timestamp=_utc_now_iso(),
                            notes=f"operator-approved promotion source_tag={source_tag}",
                        )
                    ],
                }
            )
            _BRONZE_STORE[record_id] = updated
            _SILVER_STORE[record_id] = updated
            promoted += 1

        logger.info(
            "Dune rows promoted to Silver",
            extra={"source_tag": source_tag, "promoted": promoted},
        )
        metrics.increment(
            "dune_feeder_promote",
            labels={"source_tag": source_tag},
        )
        return promoted

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback(self, source_tag: str, tenant_scope: Optional[str] = None) -> int:
        """
        Remove all Bronze and Silver records with matching source_tag.

        Args:
            source_tag: Batch identifier to roll back.
            tenant_scope: When provided, only delete records belonging to this tenant.
                          Prevents cross-tenant tag collisions from deleting unowned rows.

        Returns:
            Total number of records deleted.
        """
        bronze_ids = [
            rid for rid, r in _BRONZE_STORE.items()
            if r.source_tag == source_tag
            and (tenant_scope is None or r.tenant_scope == tenant_scope)
        ]
        silver_ids = [
            rid for rid, r in _SILVER_STORE.items()
            if r.source_tag == source_tag
            and (tenant_scope is None or r.tenant_scope == tenant_scope)
        ]
        gold_ids = [
            gid for gid, g in _GOLD_STORE.items()
            if g.get("source_tag") == source_tag
            and (tenant_scope is None or g.get("tenant_scope") == tenant_scope)
        ]

        for rid in bronze_ids:
            del _BRONZE_STORE[rid]
        for rid in silver_ids:
            del _SILVER_STORE[rid]
        for gid in gold_ids:
            del _GOLD_STORE[gid]

        total = len(bronze_ids) + len(silver_ids) + len(gold_ids)
        logger.info(
            "Dune rollback complete",
            extra={
                "source_tag": source_tag,
                "bronze_deleted": len(bronze_ids),
                "silver_deleted": len(silver_ids),
                "gold_deleted": len(gold_ids),
            },
        )
        metrics.increment("dune_feeder_rollback", labels={"source_tag": source_tag})
        return total

    # ── Audit ─────────────────────────────────────────────────────────────────

    def audit(self, source_tag: str, tenant_scope: Optional[str] = None) -> list[dict]:
        """
        Return all Bronze records for a source_tag (audit trail).

        Args:
            source_tag: Batch identifier to audit.
            tenant_scope: When provided, only return records for this tenant.

        Returns:
            List of record dicts (serialised DuneBronzeRecord).
        """
        records = [
            r.model_dump() for r in _BRONZE_STORE.values()
            if r.source_tag == source_tag
            and (tenant_scope is None or r.tenant_scope == tenant_scope)
        ]
        records.sort(key=lambda r: r["row_index"])
        return records

    # ── Health ────────────────────────────────────────────────────────────────

    def get_health(self) -> FeederHealthStatus:
        """
        Return feeder health metrics.

        Returns:
            FeederHealthStatus with current store counts and rejection rate.
        """
        unique_tags = {r.source_tag for r in _BRONZE_STORE.values()}
        total_bronze = len(_BRONZE_STORE)
        total_silver = len(_SILVER_STORE)

        rejection_rate = (
            _TOTAL_REJECTED / _TOTAL_SUBMITTED
            if _TOTAL_SUBMITTED > 0
            else 0.0
        )

        overall = "ok"
        if rejection_rate > 0.5:
            overall = "degraded"

        return FeederHealthStatus(
            status=overall,
            total_bronze_records=total_bronze,
            total_silver_records=total_silver,
            total_gold_records=len(_GOLD_STORE),
            unique_source_tags=len(unique_tags),
            rejection_rate=rejection_rate,
            last_ingest_at=_LAST_INGEST_AT,
            last_ingest_source_tag=_LAST_INGEST_SOURCE_TAG,
            graph_isolation_enforced=True,
        )

    # ── Gold materialization ──────────────────────────────────────────────────

    def promote_to_gold(self, source_tag: str, tenant_scope: Optional[str] = None) -> int:
        """
        Materialize Gold aggregates from Silver rows with matching source_tag.

        Gold records are domain-level aggregates keyed by (source_tag, domain,
        query_id, tenant_scope) — the tenant_scope is always part of the key so
        rows from different tenants that share a tag are never merged.

        Silver rows that have already contributed to a Gold record are stamped
        and skipped on re-calls (idempotent).

        Returns:
            Number of new Gold records created.
        """
        from collections import defaultdict

        eligible: list[DuneBronzeRecord] = [
            r for r in _SILVER_STORE.values()
            if r.source_tag == source_tag
            and r.promotion_status == "silver"
            and (tenant_scope is None or r.tenant_scope == tenant_scope)
            and not (r.provenance_chain and r.provenance_chain[-1].notes
                     and r.provenance_chain[-1].notes.startswith("gold_materialized"))
        ]

        if not eligible:
            return 0

        # Key includes tenant_scope to prevent cross-tenant row merging (P1 fix)
        groups: dict[tuple, list[DuneBronzeRecord]] = defaultdict(list)
        for rec in eligible:
            groups[(rec.domain, rec.query_id, rec.tenant_scope)].append(rec)

        now_iso = _utc_now_iso()
        created = 0

        for (domain, query_id, rec_tenant), rows in groups.items():
            gold_id = str(uuid.uuid4())
            avg_quality = round(sum(r.quality_score for r in rows) / len(rows), 4)
            sorted_rows = sorted(rows, key=lambda r: r.row_index)

            gold_record: dict = {
                "gold_id": gold_id,
                "provider": "dune",
                "source_tag": source_tag,
                "domain": domain,
                "query_id": query_id,
                "query_name": rows[0].query_name,
                "execution_id": rows[0].execution_id,
                "tenant_scope": rec_tenant,
                "materialized_at": now_iso,
                "row_count": len(rows),
                "avg_quality_score": avg_quality,
                "data": [r.row_data for r in sorted_rows],
                "provenance": {
                    "source_record_ids": [r.record_id for r in rows],
                    "materialization_step": "gold_materialization",
                    "actor": "dune_feeder_service",
                },
            }
            _GOLD_STORE[gold_id] = gold_record
            created += 1

            for rec in rows:
                updated = rec.model_copy(
                    update={
                        "provenance_chain": rec.provenance_chain + [
                            ProvenanceStep(
                                step="gold_materialization",
                                actor="dune_feeder_service",
                                timestamp=now_iso,
                                notes=f"gold_materialized gold_id={gold_id}",
                            )
                        ],
                    }
                )
                _SILVER_STORE[rec.record_id] = updated
                _BRONZE_STORE[rec.record_id] = updated

        logger.info(
            "Dune rows materialized to Gold",
            extra={"source_tag": source_tag, "gold_records_created": created},
        )
        metrics.increment("dune_feeder_promote_gold", labels={"source_tag": source_tag})
        return created

    def get_gold_records(self, source_tag: Optional[str] = None, tenant_scope: Optional[str] = None) -> list[dict]:
        """Return Gold records filtered by source_tag and/or tenant_scope."""
        records = list(_GOLD_STORE.values())
        if source_tag is not None:
            records = [r for r in records if r.get("source_tag") == source_tag]
        if tenant_scope is not None:
            records = [r for r in records if r.get("tenant_scope") == tenant_scope]
        records.sort(key=lambda r: r.get("materialized_at", ""), reverse=True)
        return records


# Module-level singleton (mirrors pattern in other services)
dune_feeder_service = DuneFeederService()
