"""Payment Rail Observability routes.

* ``webhook_router`` (``/v1/integrations/webhooks/payment-rails``) — public
  provider webhook ingestion: no API key, HMAC-verified per adapter with the
  tenant's vault secret, tenant resolved from ``X-Aether-Tenant-ID`` (same
  contract as the connector public webhooks; the prefix is already in
  feature-gate PUBLIC_PATH_PREFIXES).
* ``router`` (``/v1/integrations/providers``) — tenant-authenticated provider
  status/sync and cross-provider payment-rail reads.

Named providers only; unknown providers are 404. Aether observes payments —
it never executes, settles, or custodies.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config.settings import settings
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)
from shared.logger.logger import get_logger

from services.integrations.providers.payment_rails import ADAPTERS, get_adapter
from services.integrations.providers.payment_rails.service import (
    get_payment_rails_service,
    provider_enabled,
)

logger = get_logger("aether.payment_rails.routes")

router = APIRouter(prefix="/v1/integrations/providers", tags=["Payment Rails"])
webhook_router = APIRouter(
    prefix="/v1/integrations/webhooks/payment-rails",
    tags=["Payment Rails — Webhooks"],
)


def _require_rails_enabled() -> None:
    if not settings.payment_rails.enabled:
        raise BadRequestError(
            "Payment Rail Observability is not enabled (AETHER_PAYMENT_RAILS_ENABLED=false)"
        )


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


# ── Public provider webhooks (HMAC-verified inside the service) ───────────

@webhook_router.post("/{provider}")
async def payment_rail_webhook(provider: str, request: Request):
    """Public webhook receiver for the five named payment rail providers.

    - No API key; the adapter verifies the provider HMAC signature against
      the tenant's vault secret before anything is parsed or persisted.
    - Tenant resolved from the ``X-Aether-Tenant-ID`` header.
    """
    _require_rails_enabled()
    tenant_id = request.headers.get("X-Aether-Tenant-ID", "").strip()
    if not tenant_id:
        raise BadRequestError("X-Aether-Tenant-ID header is required")

    payload = await request.body()
    signature = (
        request.headers.get("X-Signature")
        or request.headers.get("Moonpay-Signature-V2")
        or request.headers.get("X-CC-Webhook-Signature")
        or request.headers.get("Stripe-Signature")
        or request.headers.get("X-Webhook-Signature")
    )
    timestamp = request.headers.get("X-Signature-Timestamp") or request.headers.get(
        "X-Webhook-Timestamp"
    )

    result = await get_payment_rails_service().handle_webhook(
        tenant_id, provider, payload, signature, timestamp
    )
    return APIResponse(data=result).to_dict()


# ── Tenant provider controls ──────────────────────────────────────────────

class SyncRequest(BaseModel):
    """Optional provider-shaped records for deterministic (non-network) sync."""
    records: Optional[list[dict[str, Any]]] = None


@router.post("/{provider}/sync")
async def sync_provider(provider: str, body: SyncRequest, request: Request):
    """Trigger provider status polling for open funding sessions."""
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "write")
    result = await get_payment_rails_service().status_sync(
        tenant_id, provider, records=body.records
    )
    return APIResponse(data=result).to_dict()


@router.get("/{provider}/status")
async def provider_status(provider: str, request: Request):
    """Adapter configuration/health state for one named provider."""
    _require_rails_enabled()
    tenant_id = _tenant_id(request)
    adapter = get_adapter(provider)
    enabled = provider_enabled(adapter.provider_name)
    context = await adapter.health_context(tenant_id, enabled)
    if not context["configured"]:
        return APIResponse(data=adapter.not_configured()).to_dict()
    return APIResponse(data={**context, "status_map": adapter.status_map().model_dump()}).to_dict()


# ── Tenant cross-provider reads ───────────────────────────────────────────

@router.get("/payment-rails/sessions")
async def list_funding_sessions(
    request: Request,
    provider: Optional[str] = None,
    status: Optional[str] = None,
    flow_type: Optional[str] = None,
    rail: Optional[str] = None,
    reconciliation_state: Optional[str] = None,
    campaign_id: Optional[str] = None,
    journey_id: Optional[str] = None,
    limit: int = 100,
):
    _require_rails_enabled()
    tenant_id = _tenant_id(request)
    if provider is not None and provider not in ADAPTERS:
        raise NotFoundError(f"Unknown payment rail provider: {provider}")
    sessions = await get_payment_rails_service().repos.sessions.list_for_tenant(
        tenant_id,
        provider=provider,
        status=status,
        flow_type=flow_type,
        rail=rail,
        reconciliation_state=reconciliation_state,
        campaign_id=campaign_id,
        journey_id=journey_id,
        limit=limit,
    )
    return APIResponse(data={"sessions": sessions}).to_dict()


@router.get("/payment-rails/sessions/{session_id}")
async def get_funding_session(session_id: str, request: Request):
    _require_rails_enabled()
    tenant_id = _tenant_id(request)
    service = get_payment_rails_service()
    record = await service.repos.sessions.get(tenant_id, session_id)
    reconciliation = await service.repos.reconciliation.get_for_session(tenant_id, session_id)
    return APIResponse(data={"session": record, "reconciliation": reconciliation}).to_dict()


@router.get("/payment-rails/reconciliation")
async def list_reconciliation(
    request: Request,
    state: Optional[str] = None,
    provider: Optional[str] = None,
    limit: int = 100,
):
    _require_rails_enabled()
    tenant_id = _tenant_id(request)
    records = await get_payment_rails_service().repos.reconciliation.list_for_tenant(
        tenant_id, provider=provider
    )
    if state:
        records = [r for r in records if r.get("state") == state]
    return APIResponse(data={"reconciliation": records[:limit]}).to_dict()


@router.get("/payment-rails/health")
async def payment_rails_health(request: Request):
    _require_rails_enabled()
    tenant_id = _tenant_id(request)
    health = await get_payment_rails_service().health(tenant_id)
    return APIResponse(
        data={"providers": [h.model_dump(mode="json") for h in health]}
    ).to_dict()
