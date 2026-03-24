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

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, utc_now
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

    records = await repo.query_by_source_tag(source_tag)
    return APIResponse(data={
        "domain": domain,
        "source_tag": source_tag,
        "record_count": len(records),
        "records": records[:50],  # Cap response size
    }).to_dict()


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

    results = await repo.get_metrics(entity_id)
    return APIResponse(data={"entity_id": entity_id, "metrics": results}).to_dict()


@router.get("/quality/{domain}")
async def check_quality(domain: str, request: Request):
    """Run data quality checks on a domain's Bronze tier."""
    request.state.tenant.require_permission("admin")

    repo = _BRONZE_REPOS.get(domain)
    if not repo:
        raise BadRequestError(f"Unknown domain: {domain}")

    result = await run_quality_checks(repo, domain)
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
