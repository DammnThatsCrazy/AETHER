"""Data Quality & Intelligence Quality routes.

* ``tenant_router`` (prefix ``/v1/data-quality``) — tenant-safe data-quality
  views for Aether. Strictly single-tenant; never exposes other tenants,
  platform-wide drift internals, or infrastructure metadata.
* ``admin_router`` (prefix ``/v1/admin/kyber/intelligence-quality``) — internal
  Kyber intelligence-quality command center. Gated by the fail-closed Olympus
  operator check (no Aether tenant may access Kyber); mutations additionally
  require the admin permission. Views are aggregate-only.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.data_quality.service import (
    ROUTE_TO_DIMENSION,
    drift_service,
    intelligence_quality_service,
)

logger = get_logger("aether.service.data_quality.routes")

tenant_router = APIRouter(prefix="/v1/data-quality", tags=["Data Quality"])
admin_router = APIRouter(
    prefix="/v1/admin/kyber/intelligence-quality",
    tags=["Admin — Kyber Intelligence Quality"],
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _current_tenant_id(request: Request) -> str:
    request.state.tenant.require_permission("read")
    tenant_id = getattr(request.state.tenant, "tenant_id", None)
    if not tenant_id:
        raise ForbiddenError("Tenant context is required")
    return tenant_id


def _require_operator(request: Request):
    """Read-tier Kyber gate — fail-closed Olympus operator check."""
    from services.security.request_context import require_kyber_operator

    return require_kyber_operator(request)


def _require_privileged(request: Request):
    """Mutation-tier Kyber gate — operator AND admin."""
    actor = _require_operator(request)
    request.state.tenant.require_permission("admin")
    return actor


class DriftResolve(BaseModel):
    resolution_note: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Tenant-facing data quality (single-tenant, tenant-safe)
# ═══════════════════════════════════════════════════════════════════════════

@tenant_router.get("/overview")
async def data_quality_overview(request: Request):
    tenant_id = _current_tenant_id(request)
    return APIResponse(data=await intelligence_quality_service.overview(tenant_id)).to_dict()


async def _tenant_dimension(request: Request, route_key: str):
    tenant_id = _current_tenant_id(request)
    return APIResponse(data=await intelligence_quality_service.dimension_report(route_key, tenant_id)).to_dict()


@tenant_router.get("/events")
async def data_quality_events(request: Request):
    return await _tenant_dimension(request, "events")


@tenant_router.get("/schema")
async def data_quality_schema(request: Request):
    return await _tenant_dimension(request, "schema")


@tenant_router.get("/identity")
async def data_quality_identity(request: Request):
    return await _tenant_dimension(request, "identity")


@tenant_router.get("/graph")
async def data_quality_graph(request: Request):
    return await _tenant_dimension(request, "graph")


@tenant_router.get("/profile")
async def data_quality_profile(request: Request):
    return await _tenant_dimension(request, "profile")


@tenant_router.get("/recommendations")
async def data_quality_recommendations(request: Request):
    return await _tenant_dimension(request, "recommendations")


@tenant_router.get("/outcomes")
async def data_quality_outcomes(request: Request):
    return await _tenant_dimension(request, "outcomes")


@tenant_router.get("/playbooks")
async def data_quality_playbooks(request: Request):
    return await _tenant_dimension(request, "playbooks")


# ═══════════════════════════════════════════════════════════════════════════
# Kyber intelligence quality (operator-gated, aggregate-only)
# ═══════════════════════════════════════════════════════════════════════════

@admin_router.get("/overview")
async def intelligence_quality_overview(request: Request):
    _require_operator(request)
    return APIResponse(data=await intelligence_quality_service.overview(None, scope="platform")).to_dict()


@admin_router.get("/tenants")
async def intelligence_quality_tenants(request: Request, tenant_ids: Optional[str] = Query(default=None)):
    _require_operator(request)
    ids = [t.strip() for t in tenant_ids.split(",") if t.strip()] if tenant_ids else None
    return APIResponse(data={"items": await intelligence_quality_service.list_tenant_scores(ids)}).to_dict()


@admin_router.get("/drift-events")
async def intelligence_quality_drift_events(
    request: Request,
    drift_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    _require_operator(request)
    items = await drift_service.list(drift_type=drift_type, status=status)
    return APIResponse(data={"items": items}).to_dict()


@admin_router.get("/schema-drift")
async def intelligence_quality_schema_drift(request: Request):
    _require_operator(request)
    report = await intelligence_quality_service.dimension_report("schema", None)
    drift = await drift_service.list(drift_type="schema_drift")
    return APIResponse(data={"report": report, "drift_events": drift}).to_dict()


@admin_router.get("/identity")
async def intelligence_quality_identity(request: Request):
    _require_operator(request)
    return APIResponse(data=await intelligence_quality_service.dimension_report("identity", None)).to_dict()


@admin_router.get("/graph")
async def intelligence_quality_graph(request: Request):
    _require_operator(request)
    return APIResponse(data=await intelligence_quality_service.dimension_report("graph", None)).to_dict()


@admin_router.get("/recommendations")
async def intelligence_quality_recommendations(request: Request):
    _require_operator(request)
    return APIResponse(data=await intelligence_quality_service.dimension_report("recommendations", None)).to_dict()


@admin_router.get("/outcomes")
async def intelligence_quality_outcomes(request: Request):
    _require_operator(request)
    return APIResponse(data=await intelligence_quality_service.dimension_report("outcomes", None)).to_dict()


@admin_router.get("/playbooks")
async def intelligence_quality_playbooks(request: Request):
    _require_operator(request)
    return APIResponse(data=await intelligence_quality_service.dimension_report("playbooks", None)).to_dict()


@admin_router.get("/contamination")
async def intelligence_quality_contamination(request: Request):
    _require_operator(request)
    report = await intelligence_quality_service.contamination_report(None)
    events = await drift_service.list(drift_type="tenant_data_contamination")
    return APIResponse(data={"report": report, "drift_events": events}).to_dict()


@admin_router.post("/drift-events/{drift_event_id}/acknowledge")
async def intelligence_quality_acknowledge(drift_event_id: str, request: Request):
    actor = _require_privileged(request)
    existing = await drift_service.get(drift_event_id)
    if existing is None:
        raise NotFoundError("drift_event")
    updated = await drift_service.acknowledge(drift_event_id, actor=actor.actor_id)
    return APIResponse(data=updated).to_dict()


@admin_router.post("/drift-events/{drift_event_id}/resolve")
async def intelligence_quality_resolve(drift_event_id: str, request: Request, body: DriftResolve | None = None):
    actor = _require_privileged(request)
    existing = await drift_service.get(drift_event_id)
    if existing is None:
        raise NotFoundError("drift_event")
    updated = await drift_service.resolve(
        drift_event_id,
        actor=actor.actor_id,
        actor_type="olympus_operator",
        resolution_note=(body.resolution_note if body else None),
    )
    return APIResponse(data=updated).to_dict()
