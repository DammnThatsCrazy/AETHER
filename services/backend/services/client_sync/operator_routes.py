"""Kyber operator client-sync feed — GET /v1/kyber/client-sync (operator / Kyber).

The operator read-path twin of the tenant feed. M5 producers emit operator-scoped
changes (``o:{operator_id}``) for command receipts, incident updates, Kyber
session revocations and operator continuations; this route is how a workforce
client catches up on them durably. It reads the SAME ``sync_change_log`` /
``sync_cursor_counter`` via the SAME ``client_sync_service.read`` — there is no
second feed. Events carry ids + a revision only; the client re-fetches through
its normal scoped endpoints.

Gates, mirroring the tenant route AND the Kyber continuation router:
  * ``settings.client_sync.enabled`` (default OFF) → 404, indistinguishable
    from an unmounted route (D8).
  * ``require_kyber_access(SELF_CAPABILITY)`` — only a live, device-bound
    workforce session can reach the surface, and the scope is ALWAYS
    ``o:{context.operator_id}`` taken from the authenticated session, never from
    the request body or query string.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from config.settings import settings
from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

from services.client_sync import service as client_sync_service
from services.kyber.access.capabilities import SELF_CAPABILITY
from services.kyber.access.dependencies import (
    KyberAccessContext,
    require_kyber_access,
)

logger = get_logger("aether.service.client_sync.operator")
operator_router = APIRouter(prefix="/v1/kyber/client-sync", tags=["Kyber Client Sync"])


@operator_router.get("")
async def operator_client_sync(
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> APIResponse:
    if not settings.client_sync.enabled:
        raise NotFoundError("client-sync feed (feature not enabled)")
    scope_key = f"o:{context.operator_id}"
    data = await client_sync_service.read(scope_key, cursor, limit)
    return APIResponse(data=data)
