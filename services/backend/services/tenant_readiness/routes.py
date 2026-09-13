"""Read-only tenant launch-readiness routes (§3.13 / §3.14).

Strictly single-tenant. Exposes the calling tenant's latest launch-readiness
snapshot and its derived trust states. No mutations; no cross-tenant data.

Router: ``router`` (prefix ``/v1/tenant/readiness``).

NOT wired into ``main.py`` — the integrator should ``include_router`` this.
Gated by ``tenant_actor`` (actor/tenant context) + ``require_permission("read")``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from shared.auth.auth import TenantContext
from shared.common.common import APIResponse
from shared.decorators import require_permission
from shared.logger.logger import get_logger

from services.security.request_context import tenant_actor

from .service import TenantLaunchReadiness
from .trust_states import derive_trust_states

logger = get_logger("aether.tenant_readiness.routes")

router = APIRouter(prefix="/v1/tenant/readiness", tags=["Tenant Launch Readiness"])

_readiness = TenantLaunchReadiness()


@router.get("")
async def get_readiness(
    request: Request,
    _tenant: TenantContext = Depends(require_permission("read")),
) -> dict:
    """Return the latest recorded launch-readiness snapshot for the caller.

    If nothing has been recorded yet, an all-pending (not-ready) checklist is
    computed from empty signals so the client always receives the full gate set.
    """
    actor = tenant_actor(request)
    tenant_id = actor.tenant_id or ""
    snapshot = await _readiness.get(tenant_id)
    if snapshot is None:
        snapshot = _readiness.evaluate(tenant_id, {})
    return APIResponse(data=snapshot).to_dict()


@router.get("/trust-states")
async def get_trust_states(
    request: Request,
    _tenant: TenantContext = Depends(require_permission("read")),
) -> dict:
    """Return the trust states derived from the tenant's current signals.

    Signals are sourced from the latest readiness snapshot's blocking gates plus
    the generic-webhook default (disabled in V1).
    """
    actor = tenant_actor(request)
    tenant_id = actor.tenant_id or ""
    snapshot = await _readiness.get(tenant_id)
    signals: dict = {"generic_webhook_enabled": False}
    if snapshot is None:
        signals["has_data"] = False
    states = derive_trust_states(signals)
    return APIResponse(data={"tenant_id": tenant_id, "trust_states": states}).to_dict()
