
"""
Aether Service — Responsiveness & Time-to-Value API

Single-tenant, read-heavy observability surface wired into the real spine:

  GET  /v1/responsiveness                    Full tenant envelope
  GET  /v1/responsiveness/activation-milestones
  GET  /v1/responsiveness/surface-readiness
  GET  /v1/responsiveness/sdk-heartbeats
  GET  /v1/responsiveness/provider-sync-states
  GET  /v1/responsiveness/graph-hydration
  GET  /v1/responsiveness/projections
  GET  /v1/responsiveness/lens-projections
  GET  /v1/responsiveness/timeline-projection
  GET  /v1/responsiveness/background-jobs
  GET  /v1/responsiveness/measurements
  GET  /v1/responsiveness/performance-budgets
  POST /v1/responsiveness/projections/{projection_id}/rebuild   (stub — real impl in phase 5)
  POST /v1/responsiveness/providers/{provider_id}/retry          (stub — real impl in phase 3)

Every endpoint is single-tenant (tenant from request.state.tenant), returns
an ``APIResponse(data=...)`` envelope, and degrades gracefully when the spine
has not yet recorded state for a tenant (missing data is honest, not 404).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Path, Query, Request, Depends

from shared.auth.auth import Permissions, TenantContext
from shared.common.common import APIResponse, utc_now
from shared.logger.logger import get_logger

from .models import SURFACE_NAMES, FIRST_VALUE_KINDS
from .service import get_responsiveness_service

logger = get_logger("aether.responsiveness.routes")

router = APIRouter(prefix="/v1/responsiveness", tags=["Responsiveness & Time-to-Value"])


async def _require_tenant(request: Request) -> TenantContext:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.READ)
    return tenant


def _tenant_id(tenant: TenantContext) -> str:
    return tenant.tenant_id


def _environment(tenant: TenantContext) -> str:
    return getattr(tenant, "environment", "local") or "local"


# ── full envelope ──────────────────────────────────────────────────────────────

@router.get("")
async def get_responsiveness(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    envelope = await get_responsiveness_service().get_responsiveness(
        _tenant_id(tenant), _environment(tenant)
    )
    return APIResponse(data=envelope).to_dict()


# ── activation milestones ──────────────────────────────────────────────────────

@router.get("/activation-milestones")
async def get_activation_milestones(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    milestone = await get_responsiveness_service().get_activation_milestone(
        _tenant_id(tenant)
    )
    return APIResponse(data=milestone or {}).to_dict()


# ── surface readiness ──────────────────────────────────────────────────────────

@router.get("/surface-readiness")
async def get_surface_readiness_list(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    surfaces = await get_responsiveness_service().list_surface_readiness(
        _tenant_id(tenant)
    )
    return APIResponse(data=surfaces).to_dict()


@router.get("/surface-readiness/{surface}")
async def get_surface_readiness_one(
    request: Request,
    surface: str = Path(..., pattern="^[a-z][a-z0-9_]*$"),
    tenant: TenantContext = Depends(_require_tenant),
):
    if surface not in SURFACE_NAMES:
        return APIResponse(data=None).to_dict()
    readiness = await get_responsiveness_service().get_surface_readiness(
        _tenant_id(tenant), surface
    )
    return APIResponse(data=readiness.to_dict()).to_dict()


# ── sdk heartbeats ─────────────────────────────────────────────────────────────

@router.get("/sdk-heartbeats")
async def get_sdk_heartbeats(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    heartbeats = await get_responsiveness_service().get_heartbeat_states(
        _tenant_id(tenant)
    )
    return APIResponse(data=heartbeats).to_dict()


# ── provider sync states ───────────────────────────────────────────────────────

@router.get("/provider-sync-states")
async def get_provider_sync_states(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    syncs = await get_responsiveness_service().get_provider_sync_states(
        _tenant_id(tenant)
    )
    return APIResponse(data=syncs).to_dict()


# ── graph hydration ────────────────────────────────────────────────────────────

@router.get("/graph-hydration")
async def get_graph_hydration(
    request: Request,
    graph_version: str = Query(default="current", description="graph version identifier"),
    tenant: TenantContext = Depends(_require_tenant),
):
    state = await get_responsiveness_service().get_graph_hydration_state(
        _tenant_id(tenant), graph_version
    )
    return APIResponse(data=state or {}).to_dict()


# ── projections ────────────────────────────────────────────────────────────────

@router.get("/projections")
async def get_projection_states(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    projections = await get_responsiveness_service().get_projection_states(
        _tenant_id(tenant)
    )
    return APIResponse(data=projections).to_dict()


# ── lens projections ───────────────────────────────────────────────────────────

@router.get("/lens-projections")
async def get_lens_projection_states(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    projections = await get_responsiveness_service().list_lens_projection_states(
        _tenant_id(tenant)
    )
    return APIResponse(data=projections).to_dict()


# ── timeline projection ────────────────────────────────────────────────────────

@router.get("/timeline-projection")
async def get_timeline_projection(
    request: Request,
    scope_hash: str = Query(
        default="default",
        description="timeline scope hash (entity_scope:grain:window)",
    ),
    tenant: TenantContext = Depends(_require_tenant),
):
    state = await get_responsiveness_service().get_timeline_projection_state(
        _tenant_id(tenant), scope_hash
    )
    return APIResponse(data=state or {}).to_dict()


# ── background jobs ────────────────────────────────────────────────────────────

@router.get("/background-jobs")
async def get_background_jobs(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    jobs = await get_responsiveness_service().list_background_jobs(
        _tenant_id(tenant)
    )
    return APIResponse(data=jobs).to_dict()


# ── measurements ───────────────────────────────────────────────────────────────

@router.get("/measurements")
async def get_measurements(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    tenant: TenantContext = Depends(_require_tenant),
):
    rows = await get_responsiveness_service()._repo.list_measurements(
        _tenant_id(tenant), limit=limit
    )
    return APIResponse(data=rows).to_dict()


# ── performance budgets ────────────────────────────────────────────────────────

@router.get("/performance-budgets")
async def get_performance_budgets(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    budgets = await get_responsiveness_service().get_performance_budgets()
    return APIResponse(data=budgets).to_dict()


# ── operator actions (stub hooks; real impl in later phases) ──────────────────

@router.post("/projections/{projection_id}/rebuild")
async def rebuild_projection(
    request: Request,
    projection_id: str = Path(..., min_length=1, max_length=200),
    tenant: TenantContext = Depends(_require_tenant),
):
    """Stub: trigger an async projection rebuild.

    Real implementation (phase 5) enqueues a ``projection_rebuild_job`` via the
    job center and returns the job id. Until then it records a measurement and
    returns the intent.
    """
    await get_responsiveness_service().record_measurement(
        _tenant_id(tenant),
        {
            "surface": "projection",
            "interaction": f"rebuild:{projection_id}",
            "metric": "rebuild_intent",
            "value": 1,
            "status": "queued",
            "measured_at": utc_now().isoformat(),
            "environment": _environment(tenant),
        },
    )
    return APIResponse(
        data={
            "projection_id": projection_id,
            "tenant_id": _tenant_id(tenant),
            "status": "queued",
            "message": "projection rebuild not yet wired (phase 5)",
        }
    ).to_dict()


@router.post("/providers/{provider_id}/retry")
async def retry_provider_sync(
    request: Request,
    provider_id: str = Path(..., min_length=1, max_length=200),
    tenant: TenantContext = Depends(_require_tenant),
):
    """Stub: retry a provider sync.

    Real implementation (phase 3) re-runs the provider sample/pull path and
    returns the operation id. Until then it records a measurement and returns
    the intent.
    """
    await get_responsiveness_service().record_measurement(
        _tenant_id(tenant),
        {
            "surface": "provider",
            "interaction": f"retry:{provider_id}",
            "metric": "retry_intent",
            "value": 1,
            "status": "queued",
            "measured_at": utc_now().isoformat(),
            "environment": _environment(tenant),
        },
    )
    return APIResponse(
        data={
            "provider_id": provider_id,
            "tenant_id": _tenant_id(tenant),
            "status": "queued",
            "message": "provider retry not yet wired (phase 3)",
        }
    ).to_dict()


# ── first-value kinds (read-only contract aid) ────────────────────────────────

@router.get("/first-value-kinds")
async def list_first_value_kinds(
    request: Request,
    tenant: TenantContext = Depends(_require_tenant),
):
    return APIResponse(data=sorted(FIRST_VALUE_KINDS)).to_dict()
