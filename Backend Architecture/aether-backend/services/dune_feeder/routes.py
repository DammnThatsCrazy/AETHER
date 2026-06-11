"""
Aether Service — Dune Analytics Feeder Routes

Admin-only API endpoints for the governed Dune feeder.
All routes require admin or operator role.

Endpoints:
    POST /v1/admin/dune-feeder/ingest          Land a Dune query result in Bronze
    GET  /v1/admin/dune-feeder/health          Feeder health status
    POST /v1/admin/dune-feeder/rollback        Rollback by source_tag
    GET  /v1/admin/dune-feeder/audit/{tag}     Audit trail for a source_tag
    POST /v1/admin/dune-feeder/promote/{tag}   Promote Bronze to Silver
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

from services.dune_feeder.models import (
    FeederIngestRequest,
    FeederRollbackRequest,
)
from services.dune_feeder.service import dune_feeder_service

logger = get_logger("aether.service.dune_feeder.routes")
router = APIRouter(prefix="/v1/admin/dune-feeder", tags=["Dune Feeder (Admin)"])


def _require_admin(request: Request) -> None:
    """Require admin or operator role on the request tenant context."""
    request.state.tenant.require_any_permission("admin", "kyber:operator")


# ── Ingest ────────────────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest_dune_result(body: FeederIngestRequest, request: Request):
    """
    Ingest a Dune Analytics query result into the Bronze data tier.

    Enforces freshness and quality gates before landing any rows.
    Silver promotion is NOT automatic — operators must call /promote/{source_tag}.
    Graph state is NEVER mutated by this endpoint.
    """
    _require_admin(request)

    response = dune_feeder_service.ingest(body)

    metrics.increment(
        "dune_feeder_api_ingest",
        labels={"domain": body.domain, "query_id": body.query_result.query_id},
    )
    return APIResponse(data=response.model_dump()).to_dict()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def feeder_health(request: Request):
    """Return health and operational metrics for the Dune feeder service."""
    _require_admin(request)

    health = dune_feeder_service.get_health()
    return APIResponse(data=health.model_dump()).to_dict()


# ── Rollback ──────────────────────────────────────────────────────────────────

@router.post("/rollback")
async def rollback_source_tag(body: FeederRollbackRequest, request: Request):
    """
    Roll back all Bronze and Silver records matching source_tag.

    This is a destructive operation — records are permanently removed from
    both tiers. Use audit/{source_tag} first to inspect records before
    rolling back.
    """
    _require_admin(request)

    deleted = dune_feeder_service.rollback(body.source_tag)

    metrics.increment("dune_feeder_api_rollback", labels={"source_tag": body.source_tag})
    return APIResponse(data={
        "source_tag": body.source_tag,
        "records_deleted": deleted,
    }).to_dict()


# ── Audit ─────────────────────────────────────────────────────────────────────

@router.get("/audit/{source_tag}")
async def audit_source_tag(source_tag: str, request: Request):
    """
    Return the full audit trail (all Bronze records) for a source_tag.

    Records are returned sorted by row_index; capped at 200 rows in the
    response payload.
    """
    _require_admin(request)

    records = dune_feeder_service.audit(source_tag)
    if not records:
        raise NotFoundError(f"source_tag '{source_tag}'")

    return APIResponse(data={
        "source_tag": source_tag,
        "record_count": len(records),
        "records": records[:200],
    }).to_dict()


# ── Silver promotion ──────────────────────────────────────────────────────────

@router.post("/promote/{source_tag}")
async def promote_to_silver(source_tag: str, request: Request):
    """
    Promote all valid Bronze rows with matching source_tag to Silver.

    Only rows with promotion_status='bronze' and quality_score >= 0.8 are
    eligible.  Rows marked 'rejected' are never promoted.

    NOTE: Silver rows are still isolated from the canonical graph.
    Any graph candidate generation must go through a separate review queue.
    """
    _require_admin(request)

    if not source_tag or not source_tag.strip():
        raise BadRequestError("source_tag must not be empty")

    promoted = dune_feeder_service.promote_to_silver(source_tag)

    metrics.increment(
        "dune_feeder_api_promote",
        labels={"source_tag": source_tag},
    )
    return APIResponse(data={
        "source_tag": source_tag,
        "rows_promoted": promoted,
    }).to_dict()
