"""Read-only metering-evidence routes (§3.16).

Strictly single-tenant. Exposes the metering-evidence record for a metered
event id, scoped to the calling tenant (fail-closed isolation). No mutations.

Router: ``router`` (prefix ``/v1/metering/evidence``).

NOT wired into ``main.py`` — the integrator should ``include_router`` this.
Gated by ``tenant_actor`` (actor/tenant context) + ``require_permission("read")``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, NotFoundError
from shared.decorators import require_permission
from shared.logger.logger import get_logger

from services.security.request_context import tenant_actor

from .service import MeteringEvidenceService

logger = get_logger("aether.metering_evidence.routes")

router = APIRouter(prefix="/v1/metering/evidence", tags=["Metering Evidence"])

_service = MeteringEvidenceService()


@router.get("/{metered_event_id}")
async def explain_metered_event(
    metered_event_id: str,
    request: Request,
    _tenant: TenantContext = Depends(require_permission("read")),
) -> dict:
    """Explain why a metered event was billed or excluded (tenant-scoped)."""
    actor = tenant_actor(request)
    tenant_id = actor.tenant_id or ""
    record = await _service.explain(metered_event_id, tenant_id=tenant_id)
    if record is None:
        raise NotFoundError("metering_evidence")
    return APIResponse(data=record).to_dict()
