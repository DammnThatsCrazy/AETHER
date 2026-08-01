"""Client-sync feed API — GET /v1/client-sync (tenant / Aether).

Flag-gated via ``settings.client_sync.enabled`` (default OFF → 404). Returns an
ordered, gap-free slice of the durable per-scope change log since ``cursor``. Each
event carries ids + a revision only; the client re-fetches through its normal
scoped endpoints, so the graph is never replicated.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from config.settings import settings
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

from services.client_sync import service as client_sync_service

logger = get_logger("aether.service.client_sync")
router = APIRouter(prefix="/v1/client-sync", tags=["Client Sync"])


def _tenant(request: Request) -> TenantContext:
    if not settings.client_sync.enabled:
        raise NotFoundError("client-sync feed (feature not enabled)")
    tenant: TenantContext = request.state.tenant
    tenant.require_permission("read")
    return tenant


@router.get("")
async def client_sync(
    request: Request,
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> APIResponse:
    tenant = _tenant(request)
    scope_key = f"t:{tenant.tenant_id}"
    data = await client_sync_service.read(scope_key, cursor, limit)
    return APIResponse(data=data)
