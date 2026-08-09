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
    RateLimitedError,
)
from shared.logger.logger import get_logger, metrics

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


def _require_legacy_header_route() -> None:
    """Guard the unsafe legacy header-tenant webhook route.

    The ``/{provider}`` route lets a public caller select the tenant via an
    ``X-Aether-Tenant-ID`` header. It is available ONLY in local development AND
    only when explicitly opted in (``AETHER_PAYMENT_LEGACY_WEBHOOK_ROUTE_ENABLED``).
    Everywhere else it returns a uniform 404 — indistinguishable from a route that
    does not exist — so a public caller can never select a tenant by header in
    staging or production. The durable ``/{provider}/{endpoint_id}`` route is the
    authoritative path.
    """
    from services.integrations.providers.payment_rails.base import _is_local_env

    if not (settings.payment_rails.legacy_webhook_route_enabled and _is_local_env()):
        raise NotFoundError("not found")


def _tenant_id(request: Request, permission: str = "read") -> str:
    """Resolve the calling tenant for a payment-rails route.

    Delegates to :func:`require_payment_rails_entitlement`, which runs the
    permission check AND the plan-tier entitlement gate. The entitlement gate is
    default-OFF (``entitlement_gate_enabled``) so behavior is byte-for-byte
    unchanged until the integration pass opts in; when enabled, a tenant whose
    plan ranks below ``min_plan_tier`` is denied 403 even though its role holds
    the permission. Every tenant route on this router funnels through here, so
    the payment-rails entitlement key is enforced centrally.
    """
    from services.integrations.providers.payment_rails.entitlement_gate import (
        require_payment_rails_entitlement,
    )

    return require_payment_rails_entitlement(request, permission)


async def _rate_limit_tenant_action(action: str, tenant_id: str, limit: int) -> None:
    """Enforce a per-tenant, per-minute budget on a tenant-initiated write action.

    Fails open (a cache outage never blocks a permission-gated admin action) and
    raises a retryable 429 when the budget is exceeded. ``limit <= 0`` disables it.
    """
    from services.integrations.providers.payment_rails.rate_limit import (
        payment_tenant_action_rate_limiter,
    )

    allowed = await payment_tenant_action_rate_limiter.allow(
        action=action, tenant_id=tenant_id, limit=limit
    )
    if not allowed:
        raise RateLimitedError(retry_after=60)


# ── Public provider webhooks (HMAC-verified inside the service) ───────────

@webhook_router.post("/{provider}")
async def payment_rail_webhook(provider: str, request: Request):
    """LEGACY, local-development-only webhook receiver (header-selected tenant).

    Retained ONLY for local development behind
    ``AETHER_PAYMENT_LEGACY_WEBHOOK_ROUTE_ENABLED``; returns a uniform 404 in
    every non-local environment (see :func:`_require_legacy_header_route`). It
    resolves the tenant from ``X-Aether-Tenant-ID``, which a public caller must
    never control — use the durable ``/{provider}/{endpoint_id}`` route in
    staging/production, where the tenant and environment are server-resolved.
    """
    _require_rails_enabled()
    _require_legacy_header_route()
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
        # Unknown/revoked/cross-provider/cross-tenant/cross-environment endpoint id.
        # Metered (metadata only) so repeated probing is alertable; the external
        # response is a uniform 404 that never reveals which dimension mismatched.
        metrics.increment("payment_rail_webhook_unknown_endpoint_total",
                          labels={"provider": provider})
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
    """Optional provider-shaped records for deterministic (non-network) sync.

    ``environment`` threads the sandbox/live credential environment explicitly so
    the pull resolves the correct credential version and provider host; when
    omitted the service derives it from the deployment environment.
    """
    records: Optional[list[dict[str, Any]]] = None
    environment: Optional[str] = None


@router.post("/{provider}/sync")
async def sync_provider(provider: str, body: SyncRequest, request: Request):
    """Trigger provider status polling for open funding sessions."""
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "write")
    await _rate_limit_tenant_action(
        "sync", tenant_id, settings.payment_rails.tenant_sync_rate_limit_per_minute
    )
    kwargs: dict[str, Any] = {"records": body.records}
    if body.environment:
        kwargs["environment"] = body.environment
    result = await get_payment_rails_service().status_sync(
        tenant_id, provider, **kwargs
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
    # Per-session delivery lifecycle: the metadata-only receipt(s) for this
    # funding session — current stage, canonical event ids, outbox record +
    # publication state, repair attempts, last error classification. Never any
    # secret or raw sensitive payload. `delivery` is the latest receipt's stage
    # so a caller has a single at-a-glance delivery state.
    receipts = [
        r for r in await service.repos.receipts.list_for_tenant(tenant_id, limit=1000)
        if r.get("funding_session_id") == session_id
    ]
    receipts.sort(key=lambda r: r.get("last_attempted_at") or r.get("received_at") or "")
    latest = receipts[-1] if receipts else None
    delivery = {
        "stage": (latest or {}).get("current_stage"),
        "canonical_event_ids": (latest or {}).get("canonical_event_ids", []),
        "outbox_record_id": (latest or {}).get("outbox_record_id"),
        "outbox_publication_state": (latest or {}).get("outbox_publication_state"),
        "repair_attempts": (latest or {}).get("repair_attempts", 0),
        "repair_eligible": bool(
            latest and latest.get("current_stage") not in (
                "completed", "consumed_or_projected", "outbox_published",
                "rejected", "quarantined", "dead_lettered",
            )
        ),
        "last_error_classification": (latest or {}).get("last_error_classification"),
    } if latest else None
    return APIResponse(data={
        "session": record,
        "reconciliation": reconciliation,
        "receipts": receipts,
        "delivery": delivery,
    }).to_dict()


@router.get("/payment-rails/diagnostics")
async def tenant_diagnostics(request: Request, provider: Optional[str] = None):
    """Tenant-scoped payment-rail diagnostics (the tenant's own view).

    Returns the shared, typed ``TenantDiagnosticsResponse`` for the authenticated
    tenant only — per-provider adapter + health (nested), credential-slot states
    (no secret values), webhook-endpoint registration state, polling health /
    cursor age, delivery backlogs, recent safe audit records, and recent repair
    outcomes. Reuses the same builder the Kyber operator surface uses, re-scoped
    to the caller's tenant so nothing cross-tenant is ever exposed.
    """
    _require_rails_enabled()
    tenant_id = _tenant_id(request)
    from services.integrations.providers.payment_rails.kyber_aggregate import (
        build_tenant_diagnostics,
    )

    response = await build_tenant_diagnostics(
        get_payment_rails_service(), tenant_id, provider
    )
    return APIResponse(data=response.model_dump(mode="json")).to_dict()


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
    """On-demand (admin) canonical-delivery repair for this tenant.

    Scans the durable receipt ledger for incomplete deliveries AND funding
    sessions with an emission gap (a crash before emission or an outbox-relay
    outage), and idempotently re-drives canonical emission / outbox enqueue — the
    deterministic canonical id dedupes on both delivery paths, so the call is safe
    to repeat and never double-emits or double-bills. Tenant-scoped, authorized
    (admin), idempotent, and audited. ``limit`` bounds the per-call scan (clamped
    to 1..2000). Returns the per-run repair counters.
    """
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    await _rate_limit_tenant_action(
        "repair", tenant_id, settings.payment_rails.tenant_repair_rate_limit_per_minute
    )
    bounded = max(1, min(int(limit), 2000))
    service = get_payment_rails_service()
    stats = await service.run_canonical_repair(tenant_id, limit=bounded)
    await service.repos.audit.record(tenant_id, {
        "action": "canonical_repair_manual",
        "provider": "*",
        "actor": _endpoint_actor(request),
        "detail": stats,
    })
    return APIResponse(data=stats).to_dict()


@router.post("/payment-rails/replay")
async def replay_dead_lettered(
    request: Request,
    provider: Optional[str] = None,
    rid: Optional[str] = None,
    limit: int = 500,
):
    """On-demand (admin) replay of dead-lettered receipts into the pipeline.

    Manual escape hatch paired with the repair worker's automatic dead-lettering:
    flips each terminal dead-lettered receipt back to a recoverable
    ``repair_pending`` state (resetting its bounded repair counter) and re-drives
    ONE idempotent canonical-repair pass so the replayed deliveries actually
    progress. Idempotent — a receipt already out of the dead-letter state is
    skipped — and audited. Tenant-scoped, authorized (admin); ``provider`` and
    ``rid`` scope the selection and are re-scoped to the caller's tenant. ``limit``
    bounds the scan (clamped to 1..2000).
    """
    _require_rails_enabled()
    tenant_id = _tenant_id(request, "admin")
    await _rate_limit_tenant_action(
        "replay", tenant_id, settings.payment_rails.tenant_repair_rate_limit_per_minute
    )
    bounded = max(1, min(int(limit), 2000))
    service = get_payment_rails_service()
    result = await service.replay_dead_lettered(
        tenant_id, provider=provider, rid=rid, limit=bounded,
        actor=_endpoint_actor(request),
    )
    return APIResponse(data=result).to_dict()
