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

from services.integrations.providers.payment_rails import ADAPTERS
from services.integrations.providers.payment_rails.service import (
    get_payment_rails_service,
    provider_enabled,
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
    """Cross-tenant payment-rail fleet aggregates (no tenant-private payloads)."""
    _require_kyber_enabled()
    _require_operator(request)
    service = get_payment_rails_service()

    sessions = await service.repos.sessions.list_all()
    tenants = sorted({s.get("tenant_id") for s in sessions if s.get("tenant_id")})

    providers = []
    for name in ADAPTERS:
        p_sessions = [s for s in sessions if s.get("provider") == name]
        by_status: dict[str, int] = {}
        for s in p_sessions:
            by_status[s.get("status", "unresolved")] = (
                by_status.get(s.get("status", "unresolved"), 0) + 1
            )
        by_recon: dict[str, int] = {}
        for s in p_sessions:
            state = s.get("reconciliation_state", "sdk_only")
            by_recon[state] = by_recon.get(state, 0) + 1
        providers.append({
            "provider": name,
            "enabled": provider_enabled(name),
            "tenants_observed": len({s.get("tenant_id") for s in p_sessions}),
            "sessions_total": len(p_sessions),
            "sessions_by_status": by_status,
            "sessions_by_reconciliation_state": by_recon,
        })

    return APIResponse(data={
        "tenants_observed": len(tenants),
        "providers": providers,
    }).to_dict()


@kyber_router.get("/{tenant_id}")
async def tenant_diagnostics(tenant_id: str, request: Request, provider: Optional[str] = None):
    """Per-tenant adapter/config/reconciliation diagnostics for operators."""
    _require_kyber_enabled()
    _require_operator(request)
    service = get_payment_rails_service()

    health = await service.health(tenant_id)
    if provider:
        health = [h for h in health if h.provider == provider]
    audits = await service.repos.audit.list_for_tenant(
        tenant_id, provider=provider, limit=50
    )
    return APIResponse(data={
        "tenant_id": tenant_id,
        "providers": [h.model_dump(mode="json") for h in health],
        "recent_audit": audits,
    }).to_dict()
