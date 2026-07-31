"""Payment Rail Observability routes.

* ``webhook_router`` (``/v1/integrations/webhooks/payment-rails``) — public
  provider webhook ingestion: no API key, provider-native signature verified
  with the tenant's vault secret, tenant resolved from ``X-Aether-Tenant-ID`` (same
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

    - No API key; the provider's native signature (compound Stripe/MoonPay
      headers, Coinbase body-hex, etc.) is verified against the tenant's vault
      secret before anything is parsed or persisted.
    - Tenant resolved from the ``X-Aether-Tenant-ID`` header. The
      ``/{provider}/{endpoint_id}`` route is the server-resolved-tenant path.
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


def _webhook_signature_header(request: Request) -> Optional[str]:
    return (
        request.headers.get("Stripe-Signature")
        or request.headers.get("Moonpay-Signature-V2")
        or request.headers.get("X-CC-Webhook-Signature")
        or request.headers.get("X-Signature")
        or request.headers.get("X-Webhook-Signature")
    )


@webhook_router.post("/{provider}/{endpoint_id}")
async def payment_rail_webhook_by_endpoint(provider: str, endpoint_id: str, request: Request):
    """Provider webhook receiver with a durable, server-resolved endpoint id.

    The tenant and environment are resolved from the endpoint registry — never a
    request header. Unknown/revoked/mismatched endpoints return a uniform 404
    that does not reveal whether the id, tenant, or provider exists. The provider
    signature is verified natively before anything is parsed or persisted.
    """
    _require_rails_enabled()
    from services.integrations.providers.payment_rails.webhook_endpoints import (
        webhook_endpoint_registry,
    )

    endpoint = await webhook_endpoint_registry.resolve(endpoint_id, provider)
    if endpoint is None:
        raise NotFoundError("webhook endpoint")

    payload = await request.body()
    signature = _webhook_signature_header(request)
    timestamp = request.headers.get("X-Signature-Timestamp") or request.headers.get(
        "X-Webhook-Timestamp"
    )
    result = await get_payment_rails_service().handle_verified_webhook(
        endpoint["tenant_id"], provider, endpoint["environment"],
        payload, signature, timestamp, endpoint_id=endpoint_id,
    )
    if not result.get("handled"):
        # Verified failures (bad/stale/missing signature) are permanent 4xx so
        # the provider does not retry; durable acceptance would return 2xx.
        raise BadRequestError(f"webhook rejected: {result.get('reason', 'unverified')}")
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


# ── Webhook endpoint management (tenant-admin) ────────────────────────────

class WebhookEndpointCreate(BaseModel):
    environment: str = "sandbox"


def _endpoint_actor(request: Request) -> str:
    t = request.state.tenant
    return getattr(t, "principal_id", None) or getattr(t, "tenant_id", None) or "tenant-admin"


@router.post("/{provider}/webhook-endpoints")
async def create_webhook_endpoint(provider: str, body: WebhookEndpointCreate, request: Request):
    """Mint a durable, high-entropy public webhook endpoint id for this provider."""
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    if provider not in ADAPTERS:
        raise NotFoundError("provider")
    from services.integrations.providers.payment_rails.webhook_endpoints import (
        webhook_endpoint_registry,
    )
    ep = await webhook_endpoint_registry.create(
        tenant_id, provider, body.environment, created_by=_endpoint_actor(request)
    )
    return APIResponse(data=ep).to_dict()


@router.get("/{provider}/webhook-endpoints")
async def list_webhook_endpoints(provider: str, request: Request):
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    from services.integrations.providers.payment_rails.webhook_endpoints import (
        webhook_endpoint_registry,
    )
    return APIResponse(
        data=await webhook_endpoint_registry.list_for(tenant_id, provider)
    ).to_dict()


@router.post("/{provider}/webhook-endpoints/rotate")
async def rotate_webhook_endpoint(provider: str, body: WebhookEndpointCreate, request: Request):
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    if provider not in ADAPTERS:
        raise NotFoundError("provider")
    from services.integrations.providers.payment_rails.webhook_endpoints import (
        webhook_endpoint_registry,
    )
    ep = await webhook_endpoint_registry.rotate(
        tenant_id, provider, body.environment, actor=_endpoint_actor(request)
    )
    return APIResponse(data=ep).to_dict()


@router.post("/{provider}/webhook-endpoints/{endpoint_id}/revoke")
async def revoke_webhook_endpoint(provider: str, endpoint_id: str, request: Request):
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    from services.integrations.providers.payment_rails.webhook_endpoints import (
        webhook_endpoint_registry,
    )
    ok = await webhook_endpoint_registry.revoke(tenant_id, endpoint_id, actor=_endpoint_actor(request))
    if not ok:
        raise NotFoundError("webhook endpoint")
    return APIResponse(data={"endpoint_id": endpoint_id, "state": "revoked"}).to_dict()


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


@router.post("/payment-rails/canonical-backlog/repair")
async def repair_canonical_backlog(request: Request, limit: int = 500):
    """On-demand (admin) recovery of funding sessions with a canonical-delivery
    gap — implied ``payment_*`` events never delivered because of a crash before
    emission or an outbox relay outage. Re-drives emission idempotently (the
    deterministic canonical id dedupes on both delivery paths), so the call is
    safe to repeat. ``limit`` bounds the per-call scan (clamped to 1..2000).
    Returns ``{scanned, repaired, events_reemitted}``.
    """
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    bounded = max(1, min(int(limit), 2000))
    stats = await get_payment_rails_service().repair_canonical_backlog(
        tenant_id, limit=bounded
    )
    return APIResponse(data=stats).to_dict()
