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


# ── Service ───────────────────────────────────────────────────────────────────

class DuneFeederService:
    """
    Governed feeder that lands Dune Analytics data in Bronze only.

    Design constraints:
    - No graph/Neptune imports or writes.
    - No Silver auto-promotion; operators must call promote_to_silver() explicitly.
    - Provenance is recorded per row at landing time.
    - Freshness and quality gates are enforced before any row touches storage.
    - Storage is repository-backed (dune_bronze_records / dune_silver_records /
      dune_gold_records tables) so records survive service restarts.
    """

    def __init__(self) -> None:
        from repositories.repos import (
            DuneBronzeRepository,
            DuneSilverRepository,
            DuneGoldRepository,
            DuneFeederStatsRepository,
        )
        self._bronze = DuneBronzeRepository()
        self._silver = DuneSilverRepository()
        self._gold = DuneGoldRepository()
        self._stats = DuneFeederStatsRepository()

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
        if pull_dt.tzinfo is None:
            pull_dt = pull_dt.replace(tzinfo=timezone.utc)

        age_seconds = (now - pull_dt).total_seconds()

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

        for field_name in effective_required:
            if field_name not in row or row[field_name] is None:
                missing_fields.append(field_name)

        if schema:
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

    async def ingest(self, payload: FeederIngestRequest) -> FeederIngestResponse:
        """
        Accept a Dune query result, run freshness + quality gates, land in Bronze.

        Silver promotion is NOT automatic. Operators must call promote_to_silver().
        Graph state is NEVER touched here.
        """
        qr = payload.query_result

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

        for idx, row in enumerate(qr.rows):
            quality = self.check_quality(
                row,
                schema=payload.schema,
                required_fields=payload.required_fields,
            )

            if not quality.passed or quality.score < payload.quality_threshold:
                rows_rejected += 1
                reason = quality.reason or f"Quality score {quality.score:.2f} below threshold {payload.quality_threshold}"
                rejected_reasons.append(f"row[{idx}]: {reason}")
                metrics.increment(
                    "dune_feeder_row_rejected",
                    labels={"domain": payload.domain, "query_id": qr.query_id},
                )
                continue

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
            # Deterministic key: same (source_tag, execution_id, row_index) always
            # maps to the same record_id so retried ingest requests are idempotent.
            record_id = f"dune:{payload.source_tag}:{qr.execution_id}:{idx}"

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

            await self._bronze.insert(record_id, bronze_record.model_dump())
            rows_accepted += 1
            metrics.increment(
                "dune_feeder_row_accepted",
                labels={"domain": payload.domain, "query_id": qr.query_id},
            )

        # Persist cumulative stats so health metrics survive restarts.
        await self._stats.increment(
            submitted=len(qr.rows),
            rejected=rows_rejected,
            last_ingest_at=now_iso,
            last_ingest_source_tag=payload.source_tag,
        )

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

    async def promote_to_silver(self, source_tag: str, tenant_scope: Optional[str] = None) -> int:
        """
        Promote all valid Bronze rows with matching source_tag to Silver.

        Only rows with promotion_status='bronze' and quality_score >= 0.8 are
        eligible. Rows marked 'rejected' stay rejected.
        """
        bronze_rows = await self._bronze.find_by_source_tag(source_tag, tenant_scope=tenant_scope)
        promoted = 0

        for raw in bronze_rows:
            if raw.get("promotion_status") != "bronze":
                continue
            if (raw.get("quality_score") or 0.0) < 0.8:
                continue

            provenance = list(raw.get("provenance_chain") or [])
            provenance.append(ProvenanceStep(
                step="silver_promotion",
                actor="dune_feeder_service",
                timestamp=_utc_now_iso(),
                notes=f"operator-approved promotion source_tag={source_tag}",
            ).model_dump())

            updated = {**raw, "promotion_status": "silver", "provenance_chain": provenance}
            record_id = raw["record_id"]
            await self._bronze.insert(record_id, updated)
            await self._silver.insert(record_id, updated)
            promoted += 1

        logger.info(
            "Dune rows promoted to Silver",
            extra={"source_tag": source_tag, "promoted": promoted},
        )
        metrics.increment("dune_feeder_promote", labels={"source_tag": source_tag})
        return promoted

    # ── Rollback ──────────────────────────────────────────────────────────────

    async def rollback(self, source_tag: str, tenant_scope: Optional[str] = None) -> int:
        """Remove all Bronze, Silver, and Gold records matching source_tag."""
        bronze_deleted = await self._bronze.delete_by_source_tag(source_tag, tenant_scope=tenant_scope)
        silver_deleted = await self._silver.delete_by_source_tag(source_tag, tenant_scope=tenant_scope)
        gold_deleted = await self._gold.delete_by_source_tag(source_tag, tenant_scope=tenant_scope)

        total = bronze_deleted + silver_deleted + gold_deleted
        logger.info(
            "Dune rollback complete",
            extra={
                "source_tag": source_tag,
                "bronze_deleted": bronze_deleted,
                "silver_deleted": silver_deleted,
                "gold_deleted": gold_deleted,
            },
        )
        metrics.increment("dune_feeder_rollback", labels={"source_tag": source_tag})
        return total

    # ── Audit ─────────────────────────────────────────────────────────────────

    async def audit(self, source_tag: str, tenant_scope: Optional[str] = None) -> list[dict]:
        """Return all Bronze records for a source_tag (audit trail)."""
        return await self._bronze.find_by_source_tag(source_tag, tenant_scope=tenant_scope)

    # ── Health ────────────────────────────────────────────────────────────────

    async def get_health(self, tenant_scope: Optional[str] = None) -> FeederHealthStatus:
        """Return feeder health metrics, scoped to tenant_scope for non-platform callers."""
        tier_filters = {"tenant_scope": tenant_scope} if tenant_scope else None

        # Use count() to avoid the 10k row cap on tier totals.
        total_bronze = await self._bronze.count(tier_filters)
        total_silver = await self._silver.count(tier_filters)
        total_gold = await self._gold.count(tier_filters)

        # Unique source tags: bounded by distinct Dune queries, not row count.
        tag_rows = await self._bronze.find_many(filters=tier_filters, limit=10000)
        unique_tags = {r.get("source_tag") for r in tag_rows if r.get("source_tag")}

        # Load persisted stats for restart-safe rejection rate and last-ingest fields.
        stats = await self._stats.load()
        total_submitted = stats.get("total_submitted", 0)
        total_rejected = stats.get("total_rejected", 0)
        rejection_rate = total_rejected / total_submitted if total_submitted > 0 else 0.0

        return FeederHealthStatus(
            status="degraded" if rejection_rate > 0.5 else "ok",
            total_bronze_records=total_bronze,
            total_silver_records=total_silver,
            total_gold_records=total_gold,
            unique_source_tags=len(unique_tags),
            rejection_rate=rejection_rate,
            last_ingest_at=stats.get("last_ingest_at"),
            last_ingest_source_tag=stats.get("last_ingest_source_tag"),
            graph_isolation_enforced=True,
        )

    # ── Gold materialization ──────────────────────────────────────────────────

    async def promote_to_gold(self, source_tag: str, tenant_scope: Optional[str] = None) -> int:
        """Materialize Gold aggregates from Silver rows with matching source_tag."""
        from collections import defaultdict

        silver_rows = await self._silver.find_by_source_tag(source_tag, tenant_scope=tenant_scope)
        eligible = [
            r for r in silver_rows
            if r.get("promotion_status") == "silver"
            and not any(
                p.get("notes", "").startswith("gold_materialized")
                for p in (r.get("provenance_chain") or [])
            )
        ]

        if not eligible:
            return 0

        groups: dict[tuple, list[dict]] = defaultdict(list)
        for rec in eligible:
            groups[(rec.get("domain"), rec.get("query_id"), rec.get("tenant_scope"))].append(rec)

        now_iso = _utc_now_iso()
        created = 0

        for (domain, query_id, rec_tenant), rows in groups.items():
            gold_id = str(uuid.uuid4())
            avg_quality = round(sum(r.get("quality_score", 0.0) for r in rows) / len(rows), 4)
            sorted_rows = sorted(rows, key=lambda r: r.get("row_index", 0))

            gold_record: dict = {
                "gold_id": gold_id,
                "provider": "dune",
                "source_tag": source_tag,
                "domain": domain,
                "query_id": query_id,
                "query_name": rows[0].get("query_name"),
                "execution_id": rows[0].get("execution_id"),
                "tenant_scope": rec_tenant,
                "materialized_at": now_iso,
                "row_count": len(rows),
                "avg_quality_score": avg_quality,
                "data": [r.get("row_data") for r in sorted_rows],
                "provenance": {
                    "source_record_ids": [r["record_id"] for r in rows],
                    "materialization_step": "gold_materialization",
                    "actor": "dune_feeder_service",
                },
            }
            await self._gold.insert(gold_id, gold_record)
            created += 1

            for rec in rows:
                provenance = list(rec.get("provenance_chain") or [])
                provenance.append(ProvenanceStep(
                    step="gold_materialization",
                    actor="dune_feeder_service",
                    timestamp=now_iso,
                    notes=f"gold_materialized gold_id={gold_id}",
                ).model_dump())
                updated = {**rec, "provenance_chain": provenance}
                await self._silver.insert(rec["record_id"], updated)
                await self._bronze.insert(rec["record_id"], updated)

        logger.info(
            "Dune rows materialized to Gold",
            extra={"source_tag": source_tag, "gold_records_created": created},
        )
        metrics.increment("dune_feeder_promote_gold", labels={"source_tag": source_tag})
        return created

    async def get_gold_records(
        self, source_tag: Optional[str] = None, tenant_scope: Optional[str] = None
    ) -> list[dict]:
        """Return Gold records filtered by source_tag and/or tenant_scope."""
        return await self._gold.find_filtered(source_tag=source_tag, tenant_scope=tenant_scope)


# Module-level singleton (mirrors pattern in other services)
dune_feeder_service = DuneFeederService()
