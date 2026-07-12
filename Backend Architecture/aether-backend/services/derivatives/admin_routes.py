"""Kyber operator surfaces for Derivatives Intelligence —
/v1/admin/kyber/derivatives. Operator-gated, audited, observation-only."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from config.settings import settings
from repositories.derivatives_repos import (
    ConnectorCheckpointRepo,
    ReconciliationVarianceRepo,
    StreamGapRepo,
)
from shared.auth.auth import Permissions
from shared.common.common import ForbiddenError
from services.derivatives.adapters import DERIVATIVES_ADAPTERS, get_adapter
from services.derivatives.adapters.conformance import run_conformance
from services.derivatives.foundation import require_flag

admin_router = APIRouter(prefix="/v1/admin/kyber/derivatives/runtime", tags=["kyber-derivatives"])


from services.security.request_context import is_kyber_operator as _is_kyber_operator


def _gate(request: Request) -> None:
    require_flag(settings.derivatives.kyber_enabled, "Kyber Derivatives Ops")
    tenant = request.state.tenant
    # Canonical fail-closed operator check (replaces the never-set
    # is_platform_admin flag): only kyber:operator grant or the operator
    # tenant-id allowlist passes; Aether tenants (incl. Role.ADMIN) are denied.
    if not _is_kyber_operator(tenant):
        raise ForbiddenError("Kyber operator access required; Aether tenants may not access Kyber")
    tenant.require_permission(Permissions.DERIVATIVES_OPERATOR)


@admin_router.get("/fleet")
async def adapter_fleet(request: Request):
    """Adapter registry with honest implementation statuses."""
    _gate(request)
    return {
        "items": [adapter.descriptor() for adapter in DERIVATIVES_ADAPTERS.values()],
        "count": len(DERIVATIVES_ADAPTERS),
    }


@admin_router.get("/checkpoints")
async def list_checkpoints(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    _gate(request)
    rows = await ConnectorCheckpointRepo().find_many(limit=limit)
    return {"items": rows, "count": len(rows)}


@admin_router.get("/stream-gaps")
async def list_stream_gaps(
    request: Request, status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    _gate(request)
    filters = {"status": status} if status else None
    rows = await StreamGapRepo().find_many(filters, limit=limit)
    return {"items": rows, "count": len(rows)}


@admin_router.get("/variances")
async def list_variances(
    request: Request, status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    _gate(request)
    filters = {"status": status} if status else None
    rows = await ReconciliationVarianceRepo().find_many(filters, limit=limit)
    return {"items": rows, "count": len(rows)}


@admin_router.post("/conformance/{adapter_id}", status_code=201)
async def run_adapter_conformance(adapter_id: str, request: Request):
    """Run the conformance suite against a registered adapter (audited)."""
    _gate(request)
    adapter = get_adapter(adapter_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"unknown adapter: {adapter_id}")
    report = await run_conformance(adapter)
    return report
