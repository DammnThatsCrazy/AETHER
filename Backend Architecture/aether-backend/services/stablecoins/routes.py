"""Stablecoin Intelligence tenant and Kyber operator routes.

Feature-flagged; all routes default off until PR2-PR4 product surfaces are
verified in staging. Router is registered unconditionally in main.py so the
feature flag can be checked per-request without a restart.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from repositories.stablecoin_repos import (
    StablecoinObservationRepository,
    StablecoinPollingCheckpointRepository,
    StablecoinProviderHealthRepository,
    StablecoinReconciliationRepository,
)
from services.agentic_observability.foundation import active_tenant_id, require_permission
from services.security.request_context import require_kyber_operator, require_kyber_tenant_scope
from services.stablecoins.polling import StablecoinPollingScheduler
from services.stablecoins.profile360 import StablecoinProfile360Composer
from shared.common.common import APIResponse, utc_now

router = APIRouter(prefix="/v1/stablecoin", tags=["stablecoin-intelligence"])
kyber_router = APIRouter(
    prefix="/v1/admin/kyber/stablecoin",
    tags=["kyber-stablecoin"],
    dependencies=[Depends(require_kyber_operator)],
)
# Unprefixed: profile-360 composition lives under the platform /v1/profile family.
profile_router = APIRouter(tags=["stablecoin-intelligence"])


def _feature_enabled(request: Request) -> bool:
    try:
        from config.settings import settings
        return bool(settings.stablecoin_intelligence.enabled and not settings.stablecoin_intelligence.kill_switch)
    except Exception:
        return False


@router.get("/health")
async def stablecoin_health() -> dict[str, str]:
    return {"status": "ok", "domain": "stablecoin_intelligence", "feature_gate": "off_by_default"}


@kyber_router.get("/health")
async def kyber_stablecoin_health() -> dict[str, str]:
    return {"status": "ok", "domain": "kyber_stablecoin_operations", "feature_gate": "off_by_default"}


@profile_router.get("/v1/profile/{profile_id}/stablecoins")
async def stablecoin_profile(profile_id: str, request: Request, kind: str = Query("overview"), limit: int = Query(100, ge=1, le=500)):
    require_permission(request, "read")
    if not _feature_enabled(request):
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is disabled")
    tenant_id = active_tenant_id(request)
    data = await StablecoinProfile360Composer().compose(tenant_id=tenant_id, profile_id=profile_id, kind=kind, limit=limit)
    return APIResponse(data=data).to_dict()


@profile_router.get("/v1/stablecoins/observations")
async def list_stablecoin_observations(request: Request, limit: int = Query(100, ge=1, le=500)):
    require_permission(request, "read")
    if not _feature_enabled(request):
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is disabled")
    tenant_id = active_tenant_id(request)
    rows = await StablecoinObservationRepository().find_many(filters={"tenant_id": tenant_id}, limit=limit)
    return APIResponse(data={"tenant_id": tenant_id, "items": rows, "count": len(rows)}).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# Kyber operator diagnostics — reconciliation / finality / cursor / repair.
# Read-only diagnostics plus a single non-destructive repair action (re-queue a
# failed poll checkpoint for retry). Operator-gated via the router dependency;
# a tenant_id query param is additionally tenant-scope checked.
# ═══════════════════════════════════════════════════════════════════════════


class StablecoinOperatorDiagnostics:
    """Operator diagnostics surface for the stablecoin observer stack.

    Exposes backlog/cursor-age/finality/reconciliation health without mutating
    state, plus one non-destructive repair (re-queue a failed poll checkpoint).
    """

    def __init__(
        self,
        scheduler: StablecoinPollingScheduler | None = None,
        reconciliation: StablecoinReconciliationRepository | None = None,
        health: StablecoinProviderHealthRepository | None = None,
    ) -> None:
        self.scheduler = scheduler or StablecoinPollingScheduler()
        self.reconciliation = reconciliation or StablecoinReconciliationRepository()
        self.health = health or StablecoinProviderHealthRepository()

    async def reconciliation_records(
        self, *, tenant_id: str = "", status: str = "", limit: int = 100
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        if status:
            filters["state"] = status
        rows = await self.reconciliation.find_many(filters=filters, limit=limit)
        return {"items": rows, "count": len(rows)}

    async def finality_status(
        self, *, tenant_id: str = "", chain_id: str = "", limit: int = 100
    ) -> dict[str, Any]:
        if not tenant_id:
            return {
                "scanned": 0, "backlog": 0, "backlog_by_status": {},
                "recent_finality_polls": [], "error": "tenant_id required",
            }
        scheduler = self.scheduler
        backlog = await scheduler.backlog(tenant_id=tenant_id, chain_id=chain_id) if chain_id else 0
        breakdown = await scheduler.backlog_by_status(tenant_id=tenant_id, chain_id=chain_id) if chain_id else {}
        recent = await scheduler.poll_checkpoints(tenant_id=tenant_id, poll_type="finality", limit=limit)
        return {
            "tenant_id": tenant_id,
            "chain_id": chain_id or "",
            "backlog": backlog,
            "backlog_by_status": breakdown,
            "recent_finality_polls": recent,
        }

    async def cursor_status(
        self, *, tenant_id: str = "", limit: int = 100
    ) -> dict[str, Any]:
        scheduler = self.scheduler
        checkpoints = await scheduler.poll_checkpoints(
            tenant_id=tenant_id, poll_type="provider", limit=limit
        )
        providers = sorted({str(c.get("provider") or "") for c in checkpoints if c.get("provider")})
        ages: dict[str, float | None] = {}
        for provider in providers:
            ages[provider] = await scheduler.cursor_age_seconds(tenant_id=tenant_id, provider=provider)
        return {
            "tenant_id": tenant_id,
            "providers": providers,
            "cursor_age_seconds": ages,
            "recent_provider_polls": checkpoints,
        }

    async def provider_health(
        self, *, tenant_id: str = "", limit: int = 100
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        rows = await self.health.find_many(filters=filters, limit=limit)
        return {"items": rows, "count": len(rows)}

    async def repair_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        """Re-queue a failed/denied poll checkpoint for retry.

        Non-destructive and idempotent: a checkpoint that is already queued (or
        healthy) is returned unchanged; only failed/denied/degraded checkpoints
        are re-queued.
        """
        if not checkpoint_id:
            raise ValueError("checkpoint_id is required for repair")
        repo = StablecoinPollingCheckpointRepository()
        checkpoint = await repo.find_by_id(checkpoint_id)
        if checkpoint is None:
            return {"repaired": False, "checkpoint_id": checkpoint_id, "reason": "not_found"}
        current = str(checkpoint.get("status") or "")
        if current in {"failed", "entitlement_denied", "readiness_denied", "degraded"}:
            updated = {**checkpoint, "status": "queued_for_retry", "retry_requested_at": utc_now().isoformat()}
            await repo.update(checkpoint_id, updated)
            return {"repaired": True, "checkpoint_id": checkpoint_id, "from": current, "to": "queued_for_retry"}
        return {"repaired": False, "checkpoint_id": checkpoint_id, "from": current, "reason": "not_repairable"}


def _diagnostics(request: Request) -> StablecoinOperatorDiagnostics:
    return StablecoinOperatorDiagnostics()


def _scope_tenant(request: Request, tenant_id: str) -> str:
    if tenant_id:
        require_kyber_tenant_scope(tenant_id, request)
    return tenant_id


@kyber_router.get("/reconciliation")
async def operator_reconciliation(
    request: Request,
    tenant_id: str = Query(""),
    status: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
):
    scoped = _scope_tenant(request, tenant_id)
    return APIResponse(data=await _diagnostics(request).reconciliation_records(
        tenant_id=scoped, status=status, limit=limit
    )).to_dict()


@kyber_router.get("/finality")
async def operator_finality(
    request: Request,
    tenant_id: str = Query(""),
    chain_id: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
):
    scoped = _scope_tenant(request, tenant_id)
    return APIResponse(data=await _diagnostics(request).finality_status(
        tenant_id=scoped, chain_id=chain_id, limit=limit
    )).to_dict()


@kyber_router.get("/cursors")
async def operator_cursors(
    request: Request,
    tenant_id: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
):
    scoped = _scope_tenant(request, tenant_id)
    return APIResponse(data=await _diagnostics(request).cursor_status(
        tenant_id=scoped, limit=limit
    )).to_dict()


@kyber_router.get("/health/providers")
async def operator_provider_health(
    request: Request,
    tenant_id: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
):
    scoped = _scope_tenant(request, tenant_id)
    return APIResponse(data=await _diagnostics(request).provider_health(
        tenant_id=scoped, limit=limit
    )).to_dict()


@kyber_router.post("/repair/{checkpoint_id}")
async def operator_repair(
    request: Request,
    checkpoint_id: str = Path(..., description="stablecoin poll checkpoint id"),
):
    # Non-destructive: never deletes; re-queues a failed checkpoint for retry.
    return APIResponse(data=await _diagnostics(request).repair_checkpoint(checkpoint_id)).to_dict()
