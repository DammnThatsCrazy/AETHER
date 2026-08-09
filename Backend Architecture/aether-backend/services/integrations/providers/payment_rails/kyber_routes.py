"""Kyber operator routes for Payment Rail Observability.

Operator-gated fleet diagnostics. Aggregates never expose raw tenant-private
payloads — only adapter/config/reconciliation health and sanitized counters.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger

from services.integrations.providers.payment_rails.service import (
    get_payment_rails_service,
)

logger = get_logger("aether.payment_rails.kyber")

kyber_router = APIRouter(
    prefix="/v1/admin/kyber/payment-rails", tags=["Admin — Kyber Payment Rails"]
)


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


def _require_kyber_enabled() -> None:
    flags = settings.payment_rails
    if not (flags.enabled or flags.kyber_enabled):
        raise BadRequestError(
            "Kyber payment rails surfaces are not enabled (KYBER_PAYMENT_RAILS_ENABLED=false)"
        )


@kyber_router.get("/health")
async def fleet_health(request: Request):
    """Cross-tenant payment-rail fleet aggregates (typed operator contract).

    Returns the shared, versioned :class:`FleetHealthResponse` — fleet totals,
    per-provider fleet rows, and per-tenant fleet rows — with sanitized counters
    and health only (never tenant-private payment payloads). Unknown values are
    ``null`` (distinguished from a real 0); provider state distinguishes
    healthy / degraded / error / not_configured / disabled / unknown.
    """
    _require_kyber_enabled()
    _require_operator(request)
    from services.integrations.providers.payment_rails.kyber_aggregate import (
        build_fleet_health,
    )

    response = await build_fleet_health(get_payment_rails_service())
    return APIResponse(data=response.model_dump(mode="json")).to_dict()


@kyber_router.get("/{tenant_id}")
async def tenant_diagnostics(tenant_id: str, request: Request, provider: Optional[str] = None):
    """Per-tenant operator diagnostics (typed contract).

    Returns the shared :class:`TenantDiagnosticsResponse`: per-provider adapter +
    health (nested), credential-slot states (no secret values), webhook-endpoint
    registration state, delivery backlogs, recent safe audit records, and recent
    repair outcomes.
    """
    _require_kyber_enabled()
    _require_operator(request)
    from services.integrations.providers.payment_rails.kyber_aggregate import (
        build_tenant_diagnostics,
    )

    response = await build_tenant_diagnostics(
        get_payment_rails_service(), tenant_id, provider
    )
    return APIResponse(data=response.model_dump(mode="json")).to_dict()


@kyber_router.post("/{tenant_id}/replay")
async def replay_tenant_dead_lettered(
    tenant_id: str,
    request: Request,
    provider: Optional[str] = None,
    rid: Optional[str] = None,
    limit: int = 500,
):
    """Operator replay of a tenant's dead-lettered receipts into the pipeline.

    Same semantics as the tenant-admin replay route (``/payment-rails/replay``)
    but operator-gated and tenant-explicit: the operator resolves the tenant from
    the path — never a header — and both ``provider``/``rid`` selectors are
    re-scoped to that tenant. Flips each terminal dead-lettered receipt back to a
    recoverable state and re-drives ONE idempotent canonical-repair pass. Returns
    per-receipt outcomes plus the repair-pass counters.
    """
    _require_kyber_enabled()
    _require_operator(request)
    bounded = max(1, min(int(limit), 2000))
    service = get_payment_rails_service()
    result = await service.replay_dead_lettered(
        tenant_id, provider=provider, rid=rid, limit=bounded,
        actor="kyber_operator",
    )
    return APIResponse(data=result).to_dict()
