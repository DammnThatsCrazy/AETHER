"""Governed Dune feeder — Bronze ingestion + Bronze→Silver promotion pipeline.

The feeder is read-only with respect to Dune: it pulls query results, writes
them to Bronze with full provenance, then promotes rows to Silver only after
freshness and quality gates pass. No direct graph mutation occurs here.

Provenance model:
  Each Bronze row carries:
    source="dune"
    provider_record_id="{query_id}:{execution_id}:{row_index}"
    payload.query_id, payload.execution_id, payload.row_index
    ingested_at (ISO timestamp)
  Each Silver row additionally carries:
    bronze_id → back-reference to source Bronze record
    promotion_status="promoted" | "rejected"
    promotion_checked_at
    quality_score (0.0–1.0)
    quality_checks (list of {"check": str, "passed": bool, "detail": str})
    freshness_status="fresh" | "stale" | "expired"

Quality gates (all must pass for promotion):
  1. freshness — ingested_at within max_age_hours of now
  2. entity_id_present — row must have entity_id or a resolvable entity field
  3. null_rate — fraction of None values across row fields must be < threshold
  4. required_fields — all required_fields from feeder config present in row
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.logger.logger import get_logger, metrics
from shared.rights_authority.pep import rights_mode
from services.ingestion.rights import authorize_derivation, rights_context_from_result

logger = get_logger("aether.feeder.dune")

_DEFAULT_MAX_AGE_HOURS = 24
_DEFAULT_NULL_RATE_THRESHOLD = 0.3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


# ---------------------------------------------------------------------------
# Feeder config repository
# ---------------------------------------------------------------------------

class FeederConfigRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("dune_feeder_configs")


_feeder_configs = FeederConfigRepository()


def _feeder_key(tenant_id: str, feeder_id: str) -> str:
    return f"{tenant_id}:{feeder_id}"


# ---------------------------------------------------------------------------
# Quality gate evaluation
# ---------------------------------------------------------------------------

def _check_freshness(ingested_at: str, max_age_hours: float) -> dict[str, Any]:
    try:
        ingested = datetime.fromisoformat(ingested_at)
        age_hours = (_utc_now() - ingested).total_seconds() / 3600
        if age_hours <= max_age_hours:
            return {"check": "freshness", "passed": True, "detail": f"age={age_hours:.1f}h <= {max_age_hours}h"}
        return {"check": "freshness", "passed": False, "detail": f"age={age_hours:.1f}h > {max_age_hours}h (stale)"}
    except Exception as exc:
        return {"check": "freshness", "passed": False, "detail": f"invalid ingested_at: {exc}"}


def _check_null_rate(row: dict, threshold: float) -> dict[str, Any]:
    if not row:
        return {"check": "null_rate", "passed": False, "detail": "empty row"}
    null_count = sum(1 for v in row.values() if v is None)
    rate = null_count / len(row)
    passed = rate <= threshold
    return {
        "check": "null_rate",
        "passed": passed,
        "detail": f"null_rate={rate:.2f} ({'ok' if passed else f'exceeds {threshold}'})",
    }


def _check_required_fields(row: dict, required_fields: list[str]) -> dict[str, Any]:
    if not required_fields:
        return {"check": "required_fields", "passed": True, "detail": "no required fields configured"}
    missing = [f for f in required_fields if f not in row or row[f] is None]
    if missing:
        return {"check": "required_fields", "passed": False, "detail": f"missing: {missing}"}
    return {"check": "required_fields", "passed": True, "detail": "all required fields present"}


def _check_entity_id(row: dict, entity_id_field: str) -> dict[str, Any]:
    val = row.get(entity_id_field)
    if val:
        return {"check": "entity_id_present", "passed": True, "detail": f"{entity_id_field}={val}"}
    return {"check": "entity_id_present", "passed": False, "detail": f"no value for entity_id_field={entity_id_field!r}"}


def _quality_score(checks: list[dict]) -> float:
    if not checks:
        return 0.0
    return sum(1 for c in checks if c["passed"]) / len(checks)


# ---------------------------------------------------------------------------
# PromotionService
# ---------------------------------------------------------------------------

class PromotionService:
    """Promote Bronze Dune rows to Silver after freshness + quality gates pass.

    This is the governed path: every Silver row is traceable to a Bronze row,
    and every rejection is recorded so operators can query why rows were blocked.
    """

    async def promote_batch(
        self,
        bronze_repo,
        silver_repo,
        source_tag: str,
        tenant_id: str,
        entity_type: str = "dune_row",
        entity_id_field: str = "id",
        required_fields: Optional[list[str]] = None,
        max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
        null_rate_threshold: float = _DEFAULT_NULL_RATE_THRESHOLD,
    ) -> dict[str, Any]:
        """Promote all pending Bronze rows for a source_tag to Silver.

        Returns a summary: promoted_count, rejected_count, rejection_reasons.
        """
        bronze_rows = await bronze_repo.query_by_source_tag(source_tag, limit=10000)
        promoted = 0
        rejected = 0
        rejection_reasons: list[dict] = []

        for bronze_row in bronze_rows:
            if bronze_row.get("source") != "dune":
                continue

            payload = bronze_row.get("payload", {})
            row_data = payload.get("row", payload)  # Dune rows carry their data under "row"
            ingested_at = bronze_row.get("ingested_at", _iso_now())

            checks: list[dict] = [
                _check_freshness(ingested_at, max_age_hours),
                _check_null_rate(row_data, null_rate_threshold),
                _check_required_fields(row_data, required_fields or []),
                _check_entity_id(row_data, entity_id_field),
            ]
            score = _quality_score(checks)
            passed = all(c["passed"] for c in checks)

            if passed:
                entity_id = str(row_data.get(entity_id_field) or bronze_row.get("provider_record_id", ""))
                rights_context = payload.get("rights") or {}
                if rights_mode() != "off":
                    envelope_refs = list(rights_context.get("envelope_refs") or [])
                    if rights_context.get("envelope_ref"):
                        envelope_refs.append(rights_context["envelope_ref"])
                    derivation = await authorize_derivation(
                        tenant_id,
                        artifact={"kind": "silver_record", "id": f"{source_tag}:{entity_id}", "tenant_id": tenant_id},
                        input_envelope_refs=sorted(set(envelope_refs)),
                        policy_set_ref=rights_context.get("policy_set_ref"),
                        transform="feature_extraction",
                        evidence={"lineage": rights_context.get("lineage_root_ref") or bronze_row.get("id")},
                    )
                    if not derivation.proceed:
                        failed_checks = ["rights_derivation_blocked"]
                        rejection_reasons.append({
                            "bronze_id": bronze_row.get("id"),
                            "provider_record_id": bronze_row.get("provider_record_id"),
                            "failed_checks": failed_checks,
                            "quality_score": score,
                            "quality_checks": checks,
                            "rights": rights_context_from_result(derivation),
                        })
                        rejected += 1
                        metrics.increment("dune_feeder_rejected", labels={"reason": "rights_derivation_blocked"})
                        continue
                    if derivation.decision:
                        rights_context = {
                            **rights_context,
                            "rights_decision_refs": sorted(set(
                                (rights_context.get("rights_decision_refs") or [])
                                + [derivation.decision.decision_id]
                            )),
                            "decision_outcomes": sorted(set(
                                (rights_context.get("decision_outcomes") or [])
                                + [derivation.decision.outcome]
                            )),
                            "envelope_refs": sorted(set(
                                envelope_refs + derivation.decision.envelope_refs
                            )),
                        }
                await silver_repo.upsert_record(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    source="dune",
                    source_tag=source_tag,
                    normalized={
                        **row_data,
                        "promotion_status": "promoted",
                        "promotion_checked_at": _iso_now(),
                        "quality_score": score,
                        "quality_checks": checks,
                        "freshness_status": "fresh",
                        "rights": rights_context,
                    },
                    bronze_id=bronze_row.get("id", ""),
                    tenant_id=tenant_id,
                )
                promoted += 1
                metrics.increment("dune_feeder_promoted", labels={"source_tag": source_tag})
            else:
                failed_checks = [c["check"] for c in checks if not c["passed"]]
                rejection_reasons.append({
                    "bronze_id": bronze_row.get("id"),
                    "provider_record_id": bronze_row.get("provider_record_id"),
                    "failed_checks": failed_checks,
                    "quality_score": score,
                    "quality_checks": checks,
                })
                rejected += 1
                metrics.increment("dune_feeder_rejected", labels={"reason": failed_checks[0] if failed_checks else "unknown"})
                logger.debug(
                    f"Dune row rejected: tenant={tenant_id} tag={source_tag} "
                    f"id={bronze_row.get('provider_record_id')} checks={failed_checks}"
                )

        logger.info(
            f"Dune promotion: tenant={tenant_id} tag={source_tag} "
            f"promoted={promoted} rejected={rejected}"
        )
        return {
            "source_tag": source_tag,
            "tenant_id": tenant_id,
            "promoted_count": promoted,
            "rejected_count": rejected,
            "total_evaluated": promoted + rejected,
            "promotion_rate": promoted / (promoted + rejected) if (promoted + rejected) else 0.0,
            "rejection_reasons": rejection_reasons[:50],  # cap response size
        }


# ---------------------------------------------------------------------------
# FeederHealthRepository — tracks per-feeder run metrics for Kyber
# ---------------------------------------------------------------------------

class FeederRunRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("dune_feeder_runs")


_feeder_runs = FeederRunRepository()


async def record_feeder_run(
    tenant_id: str,
    source: str,
    source_tag: str,
    rows_ingested: int,
    rows_promoted: int,
    rows_rejected: int,
    status: str = "ok",
    error: Optional[str] = None,
) -> dict[str, Any]:
    """Persist a feeder run record for Kyber health visibility."""
    run_id = hashlib.sha256(f"{tenant_id}:{source}:{source_tag}".encode()).hexdigest()[:24]
    now = _iso_now()
    record = {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "source": source,
        "source_tag": source_tag,
        "rows_ingested": rows_ingested,
        "rows_promoted": rows_promoted,
        "rows_rejected": rows_rejected,
        "promotion_rate": rows_promoted / rows_ingested if rows_ingested else 0.0,
        "rejection_rate": rows_rejected / rows_ingested if rows_ingested else 0.0,
        "status": status,
        "error": error,
        "ran_at": now,
    }
    return await _feeder_runs.insert(run_id, record)


async def get_feeder_health(tenant_id: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    """Return recent feeder run records, optionally scoped to a tenant."""
    filters: dict[str, Any] = {}
    if tenant_id:
        filters["tenant_id"] = tenant_id
    return await _feeder_runs.find_many(filters=filters, limit=limit)


promotion_service = PromotionService()
