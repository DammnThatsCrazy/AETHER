"""Read-only metering-evidence routes (§3.16) + tenant reconcile (§7).

Strictly single-tenant. Exposes the metering-evidence record for a metered
event id, scoped to the calling tenant (fail-closed isolation), and a
tenant-scoped quota<->metering reconciliation report whose ``status`` is
:data:`RECONCILIATION_CONFLICT` when the usage truths disagree.

Router: ``router`` (prefix ``/v1/metering/evidence``).

NOT wired into ``main.py`` — the integrator should ``include_router`` this.
Gated by ``tenant_actor`` (actor/tenant context) + ``require_permission("read")``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.decorators import require_permission
from shared.logger.logger import get_logger

from services.security.request_context import tenant_actor

from .reconciliation import ReconciliationEngine
from .service import MeteringEvidenceService

logger = get_logger("aether.metering_evidence.routes")

router = APIRouter(prefix="/v1/metering/evidence", tags=["Metering Evidence"])

_service = MeteringEvidenceService()
_reconciliation = ReconciliationEngine()


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


@router.post("/reconcile")
async def reconcile_usage(
    request: Request,
    _tenant: TenantContext = Depends(require_permission("read")),
) -> dict:
    """Reconcile quota counters vs metering for the calling tenant (§7).

    Query params ``period_start`` / ``period_end`` (ISO 8601) bound the
    metering read. Returns a :class:`ReconciliationReport`; ``status`` is
    ``RECONCILIATION_CONFLICT`` with typed ``discrepancies`` when the usage
    truths disagree — never silent.
    """
    actor = tenant_actor(request)
    tenant_id = actor.tenant_id or ""
    period_start = request.query_params.get("period_start")
    period_end = request.query_params.get("period_end")
    if not period_start or not period_end:
        raise BadRequestError(
            "period_start and period_end query params are required (ISO 8601)"
        )
    report = await _reconciliation.reconcile(tenant_id, period_start, period_end)
    return APIResponse(data=report.to_dict()).to_dict()
