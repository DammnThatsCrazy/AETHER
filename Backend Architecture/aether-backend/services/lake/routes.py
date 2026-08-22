"""
Aether Service — Data Lake API

Exposes lake management endpoints:
- Ingest provider data into Bronze
- Promote Bronze to Silver (validate/normalize)
- Materialize Gold metrics/features
- Query lake tiers
- Rollback by source_tag
- Run quality checks
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics
from repositories.lake import (
    BronzeRepository, SilverRepository, GoldRepository,
    bronze_market, bronze_onchain, bronze_social, bronze_identity,
    bronze_governance, bronze_tradfi,
    silver_market, silver_onchain, silver_social, silver_identity,
    gold_market, gold_onchain, gold_identity,
    run_quality_checks,
)

logger = get_logger("aether.service.lake")
router = APIRouter(prefix="/v1/lake", tags=["Data Lake"])


# ── Read-completeness metadata ───────────────────────────────────────────
# Capped list/metric reads return a bare list, so a truncated result is
# otherwise indistinguishable from "this is everything" (false certainty).
# These build a small additive `meta` block for the existing APIResponse
# envelope so callers can tell. Keep both files' helpers in sync.

def _probe_completeness(limit: int, fetched: int) -> dict:
    """Exact completeness meta from an over-fetch relative to `limit`.

    Call with `fetched` = the row count returned when the underlying query
    already retrieved (or was asked to retrieve) more than `limit` rows —
    typically a `limit + 1` probe. `has_more` is a fact, not a guess: the
    fetch would only return more than `limit` rows if more than `limit`
    rows actually exist.
    """
    has_more = fetched > limit
    return {"limit": limit, "returned": min(fetched, limit), "truncated": has_more, "has_more": has_more}


def _heuristic_completeness(limit: int, returned: int) -> dict:
    """Conservative completeness meta when a limit+1 probe isn't feasible
    (e.g. the underlying repository call enforces a fixed internal cap with
    no adjustable limit parameter).

    We cannot distinguish "exactly `limit` rows exist" from "more rows
    exist beyond `limit`", so we conservatively assume truncation whenever
    the result exactly fills the limit. This can over-report truncation but
    never under-report it — never imply completeness when truncation is
    possible.
    """
    truncated = limit > 0 and returned == limit
    return {"limit": limit, "returned": returned, "truncated": truncated, "has_more": truncated}


# Domain routing
_BRONZE_REPOS: dict[str, BronzeRepository] = {
    "market": bronze_market,
    "onchain": bronze_onchain,
    "social": bronze_social,
    "identity": bronze_identity,
    "governance": bronze_governance,
    "tradfi": bronze_tradfi,
}

_SILVER_REPOS: dict[str, SilverRepository] = {
    "market": silver_market,
    "onchain": silver_onchain,
    "social": silver_social,
    "identity": silver_identity,
}

_GOLD_REPOS: dict[str, GoldRepository] = {
    "market": gold_market,
    "onchain": gold_onchain,
    "identity": gold_identity,
}


# ── Models ────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    domain: str = Field(..., description="Data domain: market, onchain, social, identity, governance, tradfi")
    source: str = Field(..., description="Provider name: defillama, binance, etc.")
    source_tag: str = Field(..., description="Unique run/batch identifier for auditability")
    records: list[dict] = Field(..., description="Raw records to ingest")


class RollbackRequest(BaseModel):
    domain: str
    source_tag: str
    tiers: list[str] = Field(default=["bronze", "silver"], description="Tiers to rollback")


class MaterializeRequest(BaseModel):
    domain: str
    metric_name: str
    entity_id: str
    entity_type: str
    value: Any
    dimensions: dict = Field(default_factory=dict)
    source_tag: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest_to_bronze(body: IngestRequest, request: Request):
    """Ingest raw provider data into Bronze tier."""
    request.state.tenant.require_permission("write")

    repo = _BRONZE_REPOS.get(body.domain)
    if not repo:
        raise BadRequestError(f"Unknown domain: {body.domain}. Available: {list(_BRONZE_REPOS.keys())}")

    count = await repo.ingest_batch(
        records=body.records,
        source=body.source,
        source_tag=body.source_tag,
        tenant_id=request.state.tenant.tenant_id,
    )

    metrics.increment("lake_ingest_api", labels={"domain": body.domain, "source": body.source})
    return APIResponse(data={
        "domain": body.domain,
        "source": body.source,
        "source_tag": body.source_tag,
        "records_submitted": len(body.records),
        "records_ingested": count,
    }).to_dict()


@router.post("/rollback")
async def rollback_by_source_tag(body: RollbackRequest, request: Request):
    """Rollback records by source_tag across specified tiers."""
    request.state.tenant.require_permission("admin")

    results = {}
    for tier in body.tiers:
        if tier == "bronze":
            repo = _BRONZE_REPOS.get(body.domain)
            if repo:
                results["bronze"] = await repo.rollback_by_source_tag(body.source_tag)
        elif tier == "silver":
            repo = _SILVER_REPOS.get(body.domain)
            if repo:
                results["silver"] = await repo.rollback_by_source_tag(body.source_tag)

    return APIResponse(data={
        "domain": body.domain,
        "source_tag": body.source_tag,
        "deleted": results,
    }).to_dict()


@router.get("/audit/{domain}/{source_tag}")
async def audit_source_tag(domain: str, source_tag: str, request: Request):
    """Query all records for a source_tag (audit trail)."""
    request.state.tenant.require_permission("read")

    repo = _BRONZE_REPOS.get(domain)
    if not repo:
        raise BadRequestError(f"Unknown domain: {domain}")

    page_cap = 50
    records = await repo.query_by_source_tag(source_tag)
    # query_by_source_tag already fetches up to its own default (100), well
    # beyond page_cap, so we already have the evidence to say for certain
    # whether the 50-row page below is complete — no separate probe needed.
    return APIResponse(
        data={
            "domain": domain,
            "source_tag": source_tag,
            "record_count": len(records),
            "records": records[:page_cap],  # Cap response size
        },
        meta=_probe_completeness(page_cap, len(records)),
    ).to_dict()


@router.post("/materialize")
async def materialize_gold(body: MaterializeRequest, request: Request):
    """Write a Gold metric/feature/highlight."""
    request.state.tenant.require_permission("write")

    repo = _GOLD_REPOS.get(body.domain)
    if not repo:
        raise BadRequestError(f"Unknown Gold domain: {body.domain}")

    result = await repo.materialize(
        metric_name=body.metric_name,
        entity_id=body.entity_id,
        entity_type=body.entity_type,
        value=body.value,
        dimensions=body.dimensions,
        source_tag=body.source_tag,
        tenant_id=request.state.tenant.tenant_id,
    )
    return APIResponse(data=result).to_dict()


@router.get("/gold/{domain}/{entity_id}")
async def query_gold(domain: str, entity_id: str, request: Request):
    """Query Gold metrics for an entity."""
    request.state.tenant.require_permission("read")

    repo = _GOLD_REPOS.get(domain)
    if not repo:
        raise BadRequestError(f"Unknown Gold domain: {domain}")

    # GoldRepository.get_metrics() enforces a fixed internal cap (200) with
    # no adjustable limit parameter, so an exact limit+1 probe isn't
    # feasible from here — heuristic completeness only.
    gold_metrics_cap = 200
    results = await repo.get_metrics(entity_id, tenant_id=request.state.tenant.tenant_id)
    return APIResponse(
        data={"entity_id": entity_id, "metrics": results},
        meta=_heuristic_completeness(gold_metrics_cap, len(results)),
    ).to_dict()


@router.get("/quality/{domain}")
async def check_quality(domain: str, request: Request):
    """Run data quality checks on a domain's Bronze tier."""
    request.state.tenant.require_permission("admin")

    repo = _BRONZE_REPOS.get(domain)
    if not repo:
        raise BadRequestError(f"Unknown domain: {domain}")

    result = await run_quality_checks(repo, domain)
    return APIResponse(data=result).to_dict()


class PromoteRequest(BaseModel):
    domain: str = Field(..., description="Data domain: market, onchain, social, identity, governance, tradfi")
    source_tag: str = Field(..., description="source_tag of the Bronze batch to promote")
    entity_type: str = Field(default="dune_row", description="Entity type for Silver records")
    entity_id_field: str = Field(default="id", description="Row field to use as entity_id")
    required_fields: list[str] = Field(default_factory=list, description="Fields that must be present and non-null")
    max_age_hours: float = Field(default=24.0, description="Maximum row age in hours for freshness gate")
    null_rate_threshold: float = Field(default=0.3, description="Maximum fraction of null fields allowed (0.0–1.0)")


@router.post("/promote")
async def promote_bronze_to_silver(body: PromoteRequest, request: Request):
    """Promote Bronze rows to Silver after freshness and quality gates.

    Only rows from source=dune (or any source with per-row provenance) are
    evaluated. Rows that pass all gates are upserted to Silver; rejected rows
    are summarised in the response with per-row failure reasons.
    """
    request.state.tenant.require_permission("write")
    tenant_id = request.state.tenant.tenant_id

    bronze_repo = _BRONZE_REPOS.get(body.domain)
    silver_repo = _SILVER_REPOS.get(body.domain)
    if not bronze_repo:
        raise BadRequestError(f"Unknown domain: {body.domain}")
    if not silver_repo:
        raise BadRequestError(f"No Silver tier for domain: {body.domain}")

    from services.integrations.dune_feeder.service import promotion_service, record_feeder_run
    result = await promotion_service.promote_batch(
        bronze_repo=bronze_repo,
        silver_repo=silver_repo,
        source_tag=body.source_tag,
        tenant_id=tenant_id,
        entity_type=body.entity_type,
        entity_id_field=body.entity_id_field,
        required_fields=body.required_fields,
        max_age_hours=body.max_age_hours,
        null_rate_threshold=body.null_rate_threshold,
    )
    await record_feeder_run(
        tenant_id=tenant_id,
        source="dune",
        source_tag=body.source_tag,
        rows_ingested=result["total_evaluated"],
        rows_promoted=result["promoted_count"],
        rows_rejected=result["rejected_count"],
        status="ok",
    )
    metrics.increment("lake_promote_api", labels={"domain": body.domain})
    return APIResponse(data=result).to_dict()


@router.get("/status")
async def lake_status(request: Request):
    """Get lake status across all domains and tiers."""
    request.state.tenant.require_permission("read")

    status = {}
    for domain, repo in _BRONZE_REPOS.items():
        count = await repo.count()
        status[domain] = {"bronze": count}

    for domain, repo in _SILVER_REPOS.items():
        count = await repo.count()
        status.setdefault(domain, {})["silver"] = count

    for domain, repo in _GOLD_REPOS.items():
        count = await repo.count()
        status.setdefault(domain, {})["gold"] = count

    return APIResponse(data=status).to_dict()
