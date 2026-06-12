"""
Aether Service — Dune Analytics Feeder Routes

Admin-only API endpoints for the governed Dune feeder.
All routes require admin or operator role.

Endpoints:
    POST /v1/admin/dune-feeder/ingest              Land a Dune query result in Bronze
    GET  /v1/admin/dune-feeder/health              Feeder health status
    POST /v1/admin/dune-feeder/rollback            Rollback by source_tag
    GET  /v1/admin/dune-feeder/audit/{tag}         Audit trail for a source_tag (tenant-scoped)
    POST /v1/admin/dune-feeder/promote/{tag}       Promote Bronze to Silver
    POST /v1/admin/dune-feeder/materialize-gold    Materialize Gold from Silver
    GET  /v1/admin/dune-feeder/gold                List Gold records
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse, BadRequestError, NotFoundError, ServiceUnavailableError
from shared.logger.logger import get_logger, metrics

_MEMORY_STORE_ENVS = frozenset({"local", "test"})


def _require_memory_store_env() -> None:
    """Raise 503 if running outside local/test — in-memory store is not durable."""
    env = os.getenv("AETHER_ENV", "local")
    if env not in _MEMORY_STORE_ENVS:
        raise ServiceUnavailableError(
            "Dune feeder in-memory store is only available in local/test environments. "
            "Configure a persistent lake repository backend before enabling this endpoint in staging/production."
        )

from services.dune_feeder.models import (
    FeederGoldMaterializeRequest,
    FeederIngestRequest,
    FeederRollbackRequest,
)
from services.dune_feeder.service import dune_feeder_service

logger = get_logger("aether.service.dune_feeder.routes")
router = APIRouter(prefix="/v1/admin/dune-feeder", tags=["Dune Feeder (Admin)"])


def _require_admin(request: Request) -> None:
    """Require admin or operator role on the request tenant context."""
    request.state.tenant.require_any_permission("admin", "kyber:operator")


def _authenticated_tenant_scope(request: Request) -> Optional[str]:
    """Return the tenant_scope of the authenticated caller, or None for platform admins."""
    tenant = request.state.tenant
    # kyber:operator (platform-level) may omit scope; tenant admins are scoped to their tenant
    if hasattr(tenant, "tenant_id") and tenant.tenant_id and not getattr(tenant, "is_platform_admin", False):
        return tenant.tenant_id
    return None


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
    _require_memory_store_env()

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
    Roll back all Bronze, Silver, and Gold records matching source_tag.

    This is a destructive operation — records are permanently removed from all
    tiers. Use audit/{source_tag} first to inspect records before rolling back.
    """
    _require_admin(request)
    _require_memory_store_env()

    # Non-platform-admin callers are always scoped to their own tenant regardless
    # of what tenant_scope they supplied in the request body.
    auth_scope = _authenticated_tenant_scope(request)
    effective_scope = auth_scope if auth_scope is not None else body.tenant_scope
    deleted = dune_feeder_service.rollback(body.source_tag, tenant_scope=effective_scope)

    metrics.increment("dune_feeder_api_rollback", labels={"source_tag": body.source_tag})
    return APIResponse(data={
        "source_tag": body.source_tag,
        "records_deleted": deleted,
    }).to_dict()


# ── Audit ─────────────────────────────────────────────────────────────────────

@router.get("/audit/{source_tag}")
async def audit_source_tag(
    source_tag: str,
    request: Request,
    tenant_scope: Optional[str] = Query(
        None,
        description=(
            "Restrict audit to records ingested under this tenant scope. "
            "When omitted, platform admins (kyber:operator) see all scopes; "
            "tenant admins are automatically restricted to their own scope."
        ),
    ),
):
    """
    Return the full audit trail (all Bronze records) for a source_tag.

    Records are scoped by the authenticated caller's tenant to prevent one tenant
    admin from reading another tenant's Bronze rows via a shared source_tag.
    Records are returned sorted by row_index; capped at 200 rows.
    """
    _require_admin(request)

    # Derive effective scope: explicit parameter takes precedence, then authenticated
    # tenant scope (prevents cross-tenant reads when no explicit scope is given).
    effective_scope = tenant_scope or _authenticated_tenant_scope(request)

    records = dune_feeder_service.audit(source_tag, tenant_scope=effective_scope)
    if not records:
        raise NotFoundError(f"source_tag '{source_tag}'")

    return APIResponse(data={
        "source_tag": source_tag,
        "tenant_scope": effective_scope,
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
    _require_memory_store_env()

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


# ── Gold materialization ──────────────────────────────────────────────────────

@router.post("/materialize-gold")
async def materialize_gold(body: FeederGoldMaterializeRequest, request: Request):
    """
    Materialize Gold aggregates from all Silver rows with matching source_tag.

    Gold records are domain-level aggregates keyed by (source_tag, domain, query_id,
    tenant_scope) — tenant scope is always included in the key so rows from different
    tenants sharing a source_tag are never merged.

    Silver rows that have already been materialized are skipped (idempotent).
    Gold is the final curated tier — still isolated from the canonical graph.
    """
    _require_admin(request)
    _require_memory_store_env()

    if not body.source_tag or not body.source_tag.strip():
        raise BadRequestError("source_tag must not be empty")

    created = dune_feeder_service.promote_to_gold(body.source_tag, tenant_scope=body.tenant_scope)

    metrics.increment(
        "dune_feeder_api_materialize_gold",
        labels={"source_tag": body.source_tag},
    )
    return APIResponse(data={
        "source_tag": body.source_tag,
        "gold_records_created": created,
    }).to_dict()


@router.get("/gold")
async def list_gold_records(
    request: Request,
    source_tag: Optional[str] = Query(None),
    tenant_scope: Optional[str] = Query(None),
):
    """List Gold materialized records, optionally filtered by source_tag and tenant_scope."""
    _require_admin(request)

    effective_scope = tenant_scope or _authenticated_tenant_scope(request)
    records = dune_feeder_service.get_gold_records(source_tag=source_tag, tenant_scope=effective_scope)
    return APIResponse(data={
        "record_count": len(records),
        "records": records,
    }).to_dict()
