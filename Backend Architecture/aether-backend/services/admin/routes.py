"""
Aether Service — Admin
Tenant management, billing, and API key management.
"""

from __future__ import annotations

import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import settings
from shared.auth.auth import PlanTier, legacy_tier_to_plan, APIKeyTier
from shared.billing.overage import OverageCalculator
from shared.billing import stripe_client, stripe_repository
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)
from shared.logger.logger import get_logger
from shared.plans.catalog import PLAN_CATALOG
from repositories.repos import AdminRepository, APIKeyRepository
from shared.events.events import EventProducer, Event, Topic

logger = get_logger("aether.service.admin")
router = APIRouter(prefix="/v1/admin", tags=["Admin"])

_repo = AdminRepository()
_key_repo = APIKeyRepository()
_producer = EventProducer()

_API_KEY_RATE_LIMIT = 10  # max keys per tenant per hour
_rate_limit_cache: dict[str, list[float]] = {}


def _check_api_key_rate_limit(tenant_id: str) -> None:
    import time
    now = time.monotonic()
    window = _rate_limit_cache.setdefault(tenant_id, [])
    _rate_limit_cache[tenant_id] = [t for t in window if now - t < 3600]
    if len(_rate_limit_cache[tenant_id]) >= _API_KEY_RATE_LIMIT:
        raise BadRequestError(f"Rate limit exceeded: max {_API_KEY_RATE_LIMIT} API keys per tenant per hour")
    _rate_limit_cache[tenant_id].append(now)


def _resolve_plan_tier(request: Request, fallback: str = "P1") -> PlanTier:
    """Determine the plan tier for a billing query.

    Preference order:
      1. request.state.tenant.plan_tier (set by AuthMiddleware)
      2. legacy api_key_tier mapped to a PlanTier
      3. default to P1
    """
    tenant = getattr(request.state, "tenant", None)
    if tenant is not None:
        plan = getattr(tenant, "plan_tier", None)
        if isinstance(plan, PlanTier):
            return plan
        legacy = getattr(tenant, "api_key_tier", None)
        if isinstance(legacy, APIKeyTier):
            return legacy_tier_to_plan(legacy)
    try:
        return PlanTier(fallback)
    except ValueError:
        return PlanTier.P1_HOBBYIST


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _resolve_plan_tier_for_tenant(
    request: Request, tenant_id: str,
) -> PlanTier:
    """Pick the PlanTier for an arbitrary tenant_id (used for billing).

    For self-tenant requests, falls back to the auth context's plan_tier
    (matches existing /billing endpoints). For cross-tenant admin requests,
    reads the authoritative plan_tier from tenant_billing_accounts so quota
    and pricing reflect the BILLED tenant, not the caller.
    """
    caller = getattr(request.state, "tenant", None)
    if caller is not None and getattr(caller, "tenant_id", "") == tenant_id:
        return _resolve_plan_tier(request)
    try:
        from shared.billing import stripe_repository
        account = await stripe_repository.get_billing_account(tenant_id)
    except Exception as e:
        logger.debug(f"plan_tier lookup for {tenant_id} failed: {e}")
        account = None
    if account and account.get("plan_tier"):
        try:
            return PlanTier(account["plan_tier"])
        except ValueError:
            pass
    return PlanTier.P1_HOBBYIST


class TenantCreate(BaseModel):
    name: str
    plan: str = Field(default="free", pattern="^(free|pro|enterprise)$")
    contact_email: str
    settings: dict[str, Any] = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class APIKeyCreate(BaseModel):
    name: str
    tier: str = Field(default="free", pattern="^(free|pro|enterprise)$")
    permissions: list[str] = Field(default_factory=lambda: ["read"])


@router.post("/tenants")
async def create_tenant(body: TenantCreate, request: Request):
    request.state.tenant.require_permission("admin")
    tenant_id = str(uuid.uuid4())
    tenant = await _repo.insert(tenant_id, {
        **body.model_dump(),
        "status": "active",
    })
    return APIResponse(data=tenant).to_dict()


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    tenant = await _repo.find_by_id_or_fail(tenant_id)
    return APIResponse(data=tenant).to_dict()


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: TenantUpdate, request: Request):
    request.state.tenant.require_permission("admin")
    tenant = await _repo.update(tenant_id, body.model_dump(exclude_none=True))
    return APIResponse(data=tenant).to_dict()


@router.post("/tenants/{tenant_id}/api-keys")
async def create_api_key(tenant_id: str, body: APIKeyCreate, request: Request):
    """Create a new API key for a tenant. Registers it in both the key repo and the auth cache."""
    request.state.tenant.require_permission("admin")
    _check_api_key_rate_limit(tenant_id)
    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()

    await _key_repo.insert(hashed[:12], {
        "tenant_id": tenant_id,
        "name": body.name,
        "tier": body.tier,
        "permissions": body.permissions,
        "key_hash": hashed,
        "last_used_at": None,
    })

    # Register with the auth validator for async Redis lookup
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        await registry.api_key_validator.register_api_key(
            api_key=raw_key,
            tenant_id=tenant_id,
            role="editor",
            tier=body.tier,
            permissions=body.permissions,
        )
    except Exception as e:
        logger.warning(f"Failed to register key in auth cache: {e}")

    actor = getattr(request.state.tenant, "entity_id", "unknown")
    logger.info("API key created: tenant=%s name=%s actor=%s", tenant_id, body.name, actor)
    try:
        await _producer.publish(Event(
            topic=Topic.ADMIN_API_KEY_CREATED,
            tenant_id=tenant_id,
            payload={"name": body.name, "tier": body.tier, "actor": actor},
        ))
    except Exception:
        pass

    return APIResponse(data={
        "api_key": raw_key,
        "name": body.name,
        "tier": body.tier,
        "message": "Store this key securely — it will not be shown again.",
    }).to_dict()


@router.get("/tenants/{tenant_id}/api-keys")
async def list_api_keys(tenant_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    keys = await _key_repo.find_many(filters={"tenant_id": tenant_id})
    safe_keys = [{k: v for k, v in key.items() if k != "key_hash"} for key in keys]
    return APIResponse(data=safe_keys).to_dict()


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    await _key_repo.delete(key_id)
    return APIResponse(data={"revoked": True}).to_dict()


@router.get("/tenants/{tenant_id}/billing")
async def get_billing(tenant_id: str, request: Request):
    """Return current plan, usage, quota, and overage for the billing period."""
    request.state.tenant.require_permission("billing")

    plan_tier = _resolve_plan_tier(request)
    plan = PLAN_CATALOG[plan_tier]
    period = _current_period()
    pricing_option = settings.rate_limit.pricing_option

    # Resolve quota engine + DB pool from app state if available
    redis_client = None
    db_pool = None
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        quota_engine = getattr(registry, "quota_engine", None)
        if quota_engine is not None:
            redis_client = getattr(quota_engine, "_redis", None)
        from repositories.repos import get_pool
        db_pool = await get_pool()
    except Exception as e:
        logger.debug(f"Billing data sources partial: {e}")

    calculator = OverageCalculator(
        redis_client=redis_client,
        db_pool=db_pool,
        pricing_option=pricing_option,
    )
    invoice = await calculator.calculate(tenant_id, plan_tier, period)
    remaining = max(0, plan.monthly_quota - invoice.total_requests)

    return APIResponse(data={
        "tenant_id": tenant_id,
        "plan": {
            "plan_id": plan.plan_id,
            "display_name": plan.display_name,
            "target_user": plan.target_user,
            "monthly_quota": plan.monthly_quota,
            "burst_rpm": plan.burst_rpm,
            "member_cap": plan.member_cap,
            "service_count": plan.service_count,
            "subscription_fee": str(invoice.plan_fee),
            "pricing_option": pricing_option,
        },
        "usage": {
            "billing_period": period,
            "total_requests": invoice.total_requests,
            "included_quota": plan.monthly_quota,
            "remaining": remaining,
            "overage_requests": invoice.overage_request_count,
        },
        "overage": {
            "line_items": [li.to_dict() for li in invoice.line_items],
            "total": str(invoice.total_overage),
        },
        "projected_period_total": str(invoice.period_total),
    }).to_dict()


@router.get("/tenants/{tenant_id}/billing/usage")
async def get_usage_detail(tenant_id: str, request: Request):
    """Return detailed per-service usage breakdown for the current period."""
    request.state.tenant.require_permission("billing")

    plan_tier = _resolve_plan_tier(request)
    plan = PLAN_CATALOG[plan_tier]
    period = _current_period()

    redis_client = None
    db_pool = None
    overage_by_service: dict[str, int] = {}
    total_requests = 0
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        quota_engine = getattr(registry, "quota_engine", None)
        if quota_engine is not None:
            redis_client = getattr(quota_engine, "_redis", None)
            overage_by_service = await quota_engine.get_overage_counts(
                tenant_id, period,
            )
            total_requests = await quota_engine.get_total_used(
                tenant_id, period,
            )
        from repositories.repos import get_pool
        db_pool = await get_pool()
    except Exception as e:
        logger.debug(f"Usage detail sources partial: {e}")

    return APIResponse(data={
        "tenant_id": tenant_id,
        "billing_period": period,
        "plan_tier": plan.plan_id,
        "monthly_quota": plan.monthly_quota,
        "total_requests": total_requests,
        "remaining": max(0, plan.monthly_quota - total_requests),
        "overage_by_service": overage_by_service,
        "overage_total": sum(overage_by_service.values()),
    }).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# STRIPE BILLING — Checkout, Portal, Invoices, Webhook
#
# Stripe Price IDs come from settings.stripe_billing (env vars). PLAN_CATALOG
# remains the single source of truth for plan identity, quota, RPM, and
# pricing. Local-mode mocked URLs are produced by stripe_client when
# AETHER_ENV=local and Stripe configuration is incomplete.
# ═══════════════════════════════════════════════════════════════════════════


def _enforce_tenant_scope(request: Request, tenant_id: str) -> None:
    """Caller may only manage its own tenant unless it has the admin role."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise ForbiddenError("Authenticated tenant context required")
    caller_tenant = getattr(tenant, "tenant_id", "")
    role = getattr(tenant, "role", None)
    role_value = getattr(role, "value", role)
    if caller_tenant == tenant_id:
        return
    if role_value == "admin" or tenant.has_permission("admin"):
        return
    raise ForbiddenError("Cross-tenant billing access denied")


async def _resolve_contact_email(
    tenant_id: str, body_email: Optional[str],
) -> Optional[str]:
    if body_email:
        return body_email
    account = await stripe_repository.get_billing_account(tenant_id)
    if account and account.get("contact_email"):
        return account["contact_email"]
    try:
        tenant_record = await _repo.find_by_id(tenant_id)
        if tenant_record and tenant_record.get("contact_email"):
            return tenant_record["contact_email"]
    except Exception:
        pass
    return None


class CheckoutSessionCreate(BaseModel):
    plan_tier: str = Field(pattern="^P[1-4]$")
    contact_email: Optional[str] = None


class OverageInvoiceCreate(BaseModel):
    billing_period: Optional[str] = None  # YYYY-MM; defaults to current period


@router.post("/tenants/{tenant_id}/billing/checkout-session")
async def create_checkout_session(
    tenant_id: str, body: CheckoutSessionCreate, request: Request,
):
    """Create a Stripe subscription Checkout Session for the requested plan.

    Local plan_tier is NOT updated here; only customer.subscription.updated
    confirms the change.
    """
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    try:
        plan_tier = PlanTier(body.plan_tier)
    except ValueError:
        raise BadRequestError(f"Unknown plan_tier: {body.plan_tier!r}")
    if plan_tier not in PLAN_CATALOG:
        raise BadRequestError(f"Plan {plan_tier.value} not in PLAN_CATALOG")

    contact_email = await _resolve_contact_email(tenant_id, body.contact_email)
    account = await stripe_repository.get_billing_account(tenant_id)
    existing_customer_id = account.get("stripe_customer_id") if account else None
    customer_id = await stripe_client.create_or_get_customer(
        tenant_id=tenant_id,
        contact_email=contact_email,
        existing_customer_id=existing_customer_id,
    )
    await stripe_repository.upsert_billing_account(
        tenant_id=tenant_id,
        contact_email=contact_email,
        plan_tier=(account.get("plan_tier") if account else None),
    )
    if customer_id and customer_id != existing_customer_id:
        await stripe_repository.update_customer_mapping(
            tenant_id=tenant_id,
            stripe_customer_id=customer_id,
            contact_email=contact_email,
        )

    session = await stripe_client.create_checkout_session(
        tenant_id=tenant_id,
        plan_tier=plan_tier,
        contact_email=contact_email,
        customer_id=customer_id,
    )
    return APIResponse(data={
        "url": session.url,
        "session_id": session.session_id,
        "mocked": session.mocked,
        "plan_tier": plan_tier.value,
    }).to_dict()


@router.post("/tenants/{tenant_id}/billing/portal-session")
async def create_portal_session(tenant_id: str, request: Request):
    """Create a Stripe Billing Portal session for an existing customer."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    account = await stripe_repository.get_billing_account(tenant_id)
    customer_id = account.get("stripe_customer_id") if account else None
    portal = await stripe_client.create_portal_session(
        tenant_id=tenant_id, customer_id=customer_id,
    )
    return APIResponse(data={
        "url": portal.url,
        "mocked": portal.mocked,
    }).to_dict()


@router.get("/tenants/{tenant_id}/billing/invoices")
async def list_billing_invoices(
    tenant_id: str, request: Request, limit: int = 50,
):
    """List locally synced Stripe invoices for a tenant."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    invoices = await stripe_repository.list_invoices(tenant_id, limit=limit)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "invoices": [_invoice_to_dict(inv) for inv in invoices],
        "count": len(invoices),
    }).to_dict()


@router.get("/tenants/{tenant_id}/billing/invoices/{invoice_id}")
async def get_billing_invoice(
    tenant_id: str, invoice_id: str, request: Request,
):
    """Return one locally synced Stripe invoice for a tenant."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    invoice = await stripe_repository.get_invoice(tenant_id, invoice_id)
    if invoice is None:
        raise NotFoundError("Invoice")
    return APIResponse(data=_invoice_to_dict(invoice)).to_dict()


@router.post("/tenants/{tenant_id}/billing/overage-invoice")
async def create_overage_invoice(
    tenant_id: str, body: OverageInvoiceCreate, request: Request,
):
    """Create a Stripe overage invoice for the tenant's billing period.

    Disabled (501-style 400 BadRequest) when STRIPE_OVERAGE_PRICE_ID is not
    configured. Idempotent on (tenant_id, billing_period).
    """
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    cfg = settings.stripe_billing
    if not cfg.overage_invoicing_enabled:
        raise BadRequestError(
            "Stripe overage invoicing is not configured. "
            "Set STRIPE_OVERAGE_PRICE_ID to enable Stripe-charged overage."
        )

    # Use the BILLED tenant's plan_tier, not the caller's. Cross-tenant admin
    # access is permitted by _enforce_tenant_scope, but overage quota and
    # pricing must reflect the target tenant.
    plan_tier = await _resolve_plan_tier_for_tenant(request, tenant_id)
    plan = PLAN_CATALOG[plan_tier]
    period = body.billing_period or _current_period()

    # Idempotency: if a successful attempt already exists for this period,
    # return it instead of double-charging.
    existing = await stripe_repository.get_overage_invoice_attempt(
        tenant_id, period,
    )
    if existing and existing.get("status") in ("succeeded", "submitted"):
        return APIResponse(data={
            "tenant_id": tenant_id,
            "billing_period": period,
            "status": existing["status"],
            "stripe_invoice_id": existing.get("stripe_invoice_id"),
            "stripe_invoice_item_id": existing.get("stripe_invoice_item_id"),
            "overage_requests": existing.get("overage_requests", 0),
            "amount_cents": existing.get("amount_cents"),
            "idempotent": True,
        }).to_dict()

    # Reuse existing Aether overage calculation as the source of truth.
    redis_client = None
    db_pool = None
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        quota_engine = getattr(registry, "quota_engine", None)
        if quota_engine is not None:
            redis_client = getattr(quota_engine, "_redis", None)
        from repositories.repos import get_pool
        db_pool = await get_pool()
    except Exception as e:
        logger.debug(f"Overage calc data sources partial: {e}")

    calculator = OverageCalculator(
        redis_client=redis_client,
        db_pool=db_pool,
        pricing_option=settings.rate_limit.pricing_option,
    )
    invoice_proj = await calculator.calculate(tenant_id, plan_tier, period)

    overage_requests = invoice_proj.overage_request_count
    amount_cents = int((invoice_proj.total_overage * 100).to_integral_value())

    if overage_requests <= 0 or amount_cents <= 0:
        await stripe_repository.record_overage_invoice_attempt(
            tenant_id=tenant_id,
            billing_period=period,
            overage_requests=overage_requests,
            amount_cents=amount_cents,
            status="skipped_no_overage",
        )
        return APIResponse(data={
            "tenant_id": tenant_id,
            "billing_period": period,
            "status": "skipped_no_overage",
            "overage_requests": overage_requests,
            "amount_cents": amount_cents,
        }).to_dict()

    account = await stripe_repository.get_billing_account(tenant_id)
    customer_id = account.get("stripe_customer_id") if account else None
    if not customer_id:
        raise BadRequestError(
            "No Stripe customer mapping for tenant. Run a Checkout flow first."
        )

    try:
        result = await stripe_client.create_overage_invoice_item(
            tenant_id=tenant_id,
            customer_id=customer_id,
            billing_period=period,
            overage_requests=overage_requests,
            amount_cents=amount_cents,
        )
    except Exception as e:
        await stripe_repository.record_overage_invoice_attempt(
            tenant_id=tenant_id,
            billing_period=period,
            overage_requests=overage_requests,
            amount_cents=amount_cents,
            status="failed",
            error=str(e),
        )
        raise

    await stripe_repository.record_overage_invoice_attempt(
        tenant_id=tenant_id,
        billing_period=period,
        overage_requests=overage_requests,
        amount_cents=amount_cents,
        stripe_invoice_id=result.get("stripe_invoice_id"),
        stripe_invoice_item_id=result.get("stripe_invoice_item_id"),
        status="submitted",
    )
    return APIResponse(data={
        "tenant_id": tenant_id,
        "billing_period": period,
        "status": "submitted",
        "stripe_invoice_id": result.get("stripe_invoice_id"),
        "stripe_invoice_item_id": result.get("stripe_invoice_item_id"),
        "overage_requests": overage_requests,
        "amount_cents": amount_cents,
        "plan_tier": plan.plan_id,
    }).to_dict()


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

# Plans considered "active" enough to apply the requested price as plan_tier.
_ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
# Statuses where Aether access should be downgraded to P1.
_DOWNGRADE_SUBSCRIPTION_STATUSES = {"canceled", "unpaid", "incomplete_expired"}


def _invoice_to_dict(inv: dict[str, Any]) -> dict[str, Any]:
    """Normalize an invoice row (DB or in-memory) to a JSON-friendly dict."""
    def _iso(v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    return {
        "stripe_invoice_id": inv.get("stripe_invoice_id"),
        "tenant_id": inv.get("tenant_id"),
        "stripe_customer_id": inv.get("stripe_customer_id"),
        "stripe_subscription_id": inv.get("stripe_subscription_id"),
        "status": inv.get("status"),
        "currency": inv.get("currency"),
        "amount_due": inv.get("amount_due"),
        "amount_paid": inv.get("amount_paid"),
        "amount_remaining": inv.get("amount_remaining"),
        "hosted_invoice_url": inv.get("hosted_invoice_url"),
        "invoice_pdf": inv.get("invoice_pdf"),
        "period_start": _iso(inv.get("period_start")),
        "period_end": _iso(inv.get("period_end")),
        "created_at": _iso(inv.get("created_at")),
        "updated_at": _iso(inv.get("updated_at")),
    }


def _ts_to_datetime(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _extract_subscription_price_id(sub_obj: dict[str, Any]) -> Optional[str]:
    items = sub_obj.get("items") or {}
    data = items.get("data") if isinstance(items, dict) else None
    if not data:
        return None
    first = data[0] if isinstance(data, list) and data else None
    if not first:
        return None
    price = first.get("price") or {}
    return price.get("id") if isinstance(price, dict) else None


def _extract_invoice_payload(
    invoice_obj: dict[str, Any], fallback_tenant_id: Optional[str] = None,
) -> dict[str, Any]:
    """Normalize a Stripe invoice object to the columns we persist."""
    metadata = invoice_obj.get("metadata") or {}
    tenant_id = (
        metadata.get("tenant_id")
        or invoice_obj.get("tenant_id")
        or fallback_tenant_id
    )
    period_start = invoice_obj.get("period_start")
    period_end = invoice_obj.get("period_end")
    # Many invoice events come from `lines` with periods; fall back to top-level.
    if period_start is None or period_end is None:
        lines = (invoice_obj.get("lines") or {}).get("data") or []
        if lines:
            period = (lines[0] or {}).get("period") or {}
            period_start = period_start or period.get("start")
            period_end = period_end or period.get("end")
    return {
        "stripe_invoice_id": invoice_obj.get("id"),
        "tenant_id": tenant_id,
        "stripe_customer_id": invoice_obj.get("customer"),
        "stripe_subscription_id": invoice_obj.get("subscription"),
        "status": invoice_obj.get("status"),
        "currency": invoice_obj.get("currency"),
        "amount_due": invoice_obj.get("amount_due"),
        "amount_paid": invoice_obj.get("amount_paid"),
        "amount_remaining": invoice_obj.get("amount_remaining"),
        "hosted_invoice_url": invoice_obj.get("hosted_invoice_url"),
        "invoice_pdf": invoice_obj.get("invoice_pdf"),
        "period_start": _ts_to_datetime(period_start),
        "period_end": _ts_to_datetime(period_end),
        "created_at": _ts_to_datetime(invoice_obj.get("created")),
    }


async def _resolve_tenant_for_event(
    obj: dict[str, Any],
) -> Optional[str]:
    """Find the Aether tenant_id for a Stripe object (subscription / invoice)."""
    metadata = obj.get("metadata") or {}
    if metadata.get("tenant_id"):
        return metadata["tenant_id"]
    if obj.get("client_reference_id"):
        return obj["client_reference_id"]
    customer = obj.get("customer")
    if customer:
        acct = await stripe_repository.get_by_stripe_customer_id(customer)
        if acct:
            return acct.get("tenant_id")
    sub_id = obj.get("subscription") or obj.get("id")
    if sub_id:
        acct = await stripe_repository.get_by_stripe_subscription_id(sub_id)
        if acct:
            return acct.get("tenant_id")
    return None


async def _refresh_api_key_plan_tier(tenant_id: str, plan_tier: PlanTier) -> None:
    """Propagate plan_tier change to cached API keys used by middleware.

    The middleware reads PlanTier from the TenantContext built by
    APIKeyValidator. Cached keys live in CacheClient under api_key:<hash>; we
    walk known tenant API keys and refresh their cached plan_tier so
    BurstRateLimiter / QuotaEngine see the updated plan immediately.
    """
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        cache = registry.cache
        from shared.cache.cache import CacheKey, TTL
    except Exception:
        return
    try:
        keys = await _key_repo.find_many(filters={"tenant_id": tenant_id}, limit=200)
    except Exception:
        keys = []
    for key in keys:
        key_hash = key.get("key_hash")
        if not key_hash:
            continue
        try:
            cache_key = CacheKey.api_key(key_hash)
            cached = await cache.get_json(cache_key)
            if cached:
                cached["plan_tier"] = plan_tier.value
                await cache.set_json(cache_key, cached, ttl=TTL.DAY)
        except Exception as e:  # pragma: no cover — best-effort propagation
            logger.debug(f"plan_tier cache refresh failed: {e}")


async def _handle_checkout_session_completed(obj: dict[str, Any]) -> None:
    tenant_id = await _resolve_tenant_for_event(obj)
    if not tenant_id:
        logger.warning("checkout.session.completed missing tenant mapping")
        return
    metadata = obj.get("metadata") or {}
    contact_email = (
        metadata.get("contact_email")
        or obj.get("customer_email")
        or obj.get("customer_details", {}).get("email")
    )
    customer_id = obj.get("customer")
    subscription_id = obj.get("subscription")
    await stripe_repository.upsert_billing_account(
        tenant_id=tenant_id, contact_email=contact_email,
    )
    await stripe_repository.update_customer_mapping(
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        contact_email=contact_email,
    )
    # Do NOT update plan_tier here — wait for customer.subscription.updated.


async def _handle_subscription_event(
    obj: dict[str, Any], deleted: bool = False,
) -> None:
    tenant_id = await _resolve_tenant_for_event(obj)
    if not tenant_id:
        logger.warning("subscription event missing tenant mapping")
        return
    subscription_id = obj.get("id")
    customer_id = obj.get("customer")
    status = "canceled" if deleted else obj.get("status")
    price_id = _extract_subscription_price_id(obj)
    current_period_end = _ts_to_datetime(obj.get("current_period_end"))

    await stripe_repository.update_customer_mapping(
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
    )
    await stripe_repository.update_subscription_state(
        tenant_id=tenant_id,
        stripe_subscription_id=subscription_id,
        stripe_price_id=price_id,
        subscription_status=status,
        current_period_end=current_period_end,
    )

    if deleted or status in _DOWNGRADE_SUBSCRIPTION_STATUSES:
        await stripe_repository.update_plan_tier(
            tenant_id, PlanTier.P1_HOBBYIST.value,
        )
        await _refresh_api_key_plan_tier(tenant_id, PlanTier.P1_HOBBYIST)
        return

    if status in _ACTIVE_SUBSCRIPTION_STATUSES:
        plan_tier = stripe_client.get_plan_for_price_id(price_id or "")
        if plan_tier is None:
            logger.warning(
                f"Subscription event for {tenant_id} has unknown price {price_id!r} "
                "— leaving plan_tier unchanged"
            )
            return
        await stripe_repository.update_plan_tier(tenant_id, plan_tier.value)
        await _refresh_api_key_plan_tier(tenant_id, plan_tier)


async def _handle_invoice_event(
    event_type: str, obj: dict[str, Any],
) -> None:
    tenant_id = await _resolve_tenant_for_event(obj)
    payload = _extract_invoice_payload(obj, fallback_tenant_id=tenant_id)
    if not payload.get("tenant_id"):
        logger.debug(f"{event_type}: no tenant mapping; skipping invoice upsert")
        return
    if event_type in ("invoice.paid", "invoice.payment_succeeded"):
        payload["status"] = payload.get("status") or "paid"
    elif event_type == "invoice.payment_failed":
        # Preserve Stripe-provided status; only default if missing.
        payload["status"] = payload.get("status") or "open"
    await stripe_repository.upsert_invoice(payload)


@router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request):
    """Stripe webhook endpoint.

    Public from the Aether auth layer (added to PUBLIC_PATHS) but protected
    by Stripe-Signature verification. Idempotent: each event_id is processed
    at most once.
    """
    sig_header = request.headers.get("Stripe-Signature", "")
    payload = await request.body()
    try:
        event = stripe_client.construct_webhook_event(payload, sig_header)
    except BadRequestError as e:
        return JSONResponse(status_code=400, content=e.to_dict())

    event_id = event.get("id") if isinstance(event, dict) else getattr(event, "id", "")
    event_type = (
        event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
    )
    data_obj = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else getattr(getattr(event, "data", None), "object", {}) or {}
    )

    # Idempotency claim: insert the event_id row first. If the insert fails
    # (transient DB error) the helper raises and we return 5xx so Stripe
    # retries — never silently drop a real first-time event.
    try:
        is_new = await stripe_repository.record_webhook_event_once(
            event_id or "", event_type or "",
        )
    except Exception as e:
        logger.warning(
            f"Failed to claim Stripe webhook idempotency row for {event_id}: {e}"
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": 500,
                               "message": "Webhook idempotency store unavailable"}},
        )
    if not is_new:
        return APIResponse(data={
            "received": True,
            "event_id": event_id,
            "duplicate": True,
        }).to_dict()

    # On handler failure, release the claim so Stripe retries can re-process
    # this event. Without the release, transient handler errors would leave
    # tenant plan/invoice state permanently stale.
    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_session_completed(data_obj)
        elif event_type == "customer.subscription.created":
            await _handle_subscription_event(data_obj, deleted=False)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_event(data_obj, deleted=False)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_event(data_obj, deleted=True)
        elif event_type in (
            "invoice.paid",
            "invoice.payment_succeeded",
            "invoice.payment_failed",
            "invoice.finalized",
            "invoice.created",
        ):
            await _handle_invoice_event(event_type, data_obj)
        else:
            logger.debug(f"Unhandled Stripe event: {event_type}")
    except Exception as e:
        logger.warning(
            f"Error handling Stripe event {event_type} ({event_id}): {e}"
        )
        # Release the idempotency claim so Stripe's retry can re-attempt.
        try:
            await stripe_repository.delete_webhook_event(event_id or "")
        except Exception as cleanup_err:  # pragma: no cover — best-effort
            logger.warning(
                f"Failed to release webhook idempotency claim {event_id}: "
                f"{cleanup_err}"
            )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": f"Webhook handler error: {e}",
                }
            },
        )

    return APIResponse(data={
        "received": True,
        "event_id": event_id,
        "event_type": event_type,
    }).to_dict()

# ── Kyber strategic observability and revenue intelligence ────────────────

from services.admin.kyber_strategic import KyberStrategicObservability, Window
from services.intelligence.repositories import (
    ActionFeedbackRepository,
    DecisionRepository,
    OutcomeRepository,
    PlaybookRepository,
    PlaybookRunRepository,
    RecommendationFeedbackRepository,
    RecommendationRepository,
)

_kyber_recommendations = RecommendationRepository()
_kyber_decisions = DecisionRepository()
_kyber_actions = ActionFeedbackRepository()
_kyber_outcomes = OutcomeRepository()
_kyber_playbooks = PlaybookRepository()
_kyber_playbook_runs = PlaybookRunRepository()
_kyber_feedback = RecommendationFeedbackRepository()


def _require_kyber_operator(request: Request) -> None:
    """Require Olympus Labs operator/admin access for internal Kyber views."""
    request.state.tenant.require_permission("admin")


async def _kyber_observability(window: Window = "30d") -> KyberStrategicObservability:
    limit = 10000
    tenants = await _repo.find_many(limit=limit)
    recommendations = await _kyber_recommendations.find_many(limit=limit)
    decisions = await _kyber_decisions.find_many(limit=limit)
    actions = await _kyber_actions.find_many(limit=limit)
    outcomes = await _kyber_outcomes.find_many(limit=limit)
    feedback = await _kyber_feedback.find_many(limit=limit)
    playbooks = await _kyber_playbooks.find_many(limit=limit)
    runs = await _kyber_playbook_runs.find_many(limit=limit)
    return KyberStrategicObservability(tenants, recommendations, decisions, actions, outcomes, feedback, playbooks, runs, window)


@router.get("/kyber/strategic-overview")
async def kyber_strategic_overview(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    return APIResponse(data=observability.response({"overview": observability.strategic_overview().model_dump()})).to_dict()


@router.get("/kyber/tenant-value-health")
async def kyber_tenant_value_health(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.tenant_health()]
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


@router.get("/kyber/tenant-expansion-opportunities")
async def kyber_tenant_expansion_opportunities(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.tenant_health() if item.expansion_score >= 0.5]
    items.sort(key=lambda item: item["expansion_score"], reverse=True)
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


@router.get("/kyber/tenant-churn-risk")
async def kyber_tenant_churn_risk(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.tenant_health() if item.churn_risk_score >= 0.4]
    items.sort(key=lambda item: item["churn_risk_score"], reverse=True)
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


@router.get("/kyber/recommendation-family-performance")
async def kyber_recommendation_family_performance(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.family_performance()]
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


@router.get("/kyber/playbook-performance")
async def kyber_playbook_performance(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.playbook_performance()]
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


@router.get("/kyber/outcome-capture-health")
async def kyber_outcome_capture_health(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    tenants = observability.tenant_health()
    weak = [item.model_dump() for item in tenants if item.outcome_capture_rate < 0.4 and item.recommendations_generated > 0]
    summary = {
        "average_outcome_capture_rate": round(sum(item.outcome_capture_rate for item in tenants) / len(tenants), 4) if tenants else 0.0,
        "tenants_below_threshold": len(weak),
        "threshold": 0.4,
    }
    return APIResponse(data=observability.response({"summary": summary, "items": weak, "count": len(weak)})).to_dict()


@router.get("/kyber/model-confidence-drift")
async def kyber_model_confidence_drift(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    return APIResponse(data=observability.response({"report": observability.model_confidence_drift().model_dump()})).to_dict()


@router.get("/kyber/vertical-solution-signals")
async def kyber_vertical_solution_signals(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.vertical_solution_signals()]
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


@router.get("/kyber/revenue-opportunities")
async def kyber_revenue_opportunities(request: Request, window: Window = "30d"):
    _require_kyber_operator(request)
    observability = await _kyber_observability(window)
    items = [item.model_dump() for item in observability.revenue_opportunities()]
    return APIResponse(data=observability.response({"items": items, "count": len(items)})).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# KYBER OPERATOR — AGENTIC OBSERVABILITY
# ═══════════════════════════════════════════════════════════════════════════

from collections import Counter, defaultdict  # noqa: E402

from repositories.repos import (  # noqa: E402
    AgentConfigRepository,
    BehaviorProfileRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
    DelegationRepository,
)
from services.security.request_context import require_kyber_operator as _require_kyber_operator  # noqa: E402

_op_agent_configs = AgentConfigRepository()
_op_behavior_profiles = BehaviorProfileRepository()
_op_payment_intents = PaymentIntentRepository()
_op_settlements = SettlementEventRepository()
_op_delegations = DelegationRepository()

_LIMIT = 10000


@router.get("/operator/agentic/overview")
async def operator_agentic_overview(request: Request):
    """Aggregate agentic + x402 metrics across all tenants."""
    _require_kyber_operator(request)

    agents = await _op_agent_configs.find_many(limit=_LIMIT)
    behavior_profiles = await _op_behavior_profiles.find_many(limit=_LIMIT)
    intents = await _op_payment_intents.find_many(limit=_LIMIT)
    settlements = await _op_settlements.find_many(limit=_LIMIT)
    delegations = await _op_delegations.find_many(limit=_LIMIT)

    agent_ids = {a.get("agent_id") for a in agents if a.get("agent_id")}
    tenant_ids = {a.get("tenant_id") for a in agents if a.get("tenant_id")}
    settled_count = sum(1 for s in settlements if s.get("status") in {"settled", "paid", "success"})
    failed_count = sum(1 for s in settlements if s.get("status") in {"failed"})
    timeout_count = sum(1 for s in settlements if s.get("status") == "timeout")
    abandoned_count = sum(1 for i in intents if i.get("abandoned_reason"))
    total = len(settlements)

    # Subagent count: delegations where grantee is a known agent
    subagent_count = sum(1 for d in delegations if d.get("grantee_entity_id") in agent_ids and not d.get("revoked_at"))

    # High-risk: agents whose behavior_profile risk_score > 0.7
    high_risk = sum(1 for bp in behavior_profiles if float((bp.get("risk_score") or 0)) > 0.7)

    # Top protocols, providers, capabilities from intents
    protocol_counts: Counter = Counter(i.get("protocol", "") for i in intents if i.get("protocol"))
    provider_counts: Counter = Counter(i.get("provider", "") for i in intents if i.get("provider"))
    capability_counts: Counter = Counter(i.get("capability_requested", "") for i in intents if i.get("capability_requested"))

    # Recent failures (last 10)
    recent_failures = sorted(
        [s for s in settlements if s.get("status") in {"failed", "timeout"}],
        key=lambda s: s.get("occurred_at", ""),
        reverse=True,
    )[:10]

    return APIResponse(data={
        "tenant_count": len(tenant_ids),
        "active_agent_count": len(agents),
        "active_subagent_count": subagent_count,
        "x402_flow_count": len(intents),
        "payment_intent_count": len(intents),
        "settlement_event_count": total,
        "settlement_success_rate": round(settled_count / total, 4) if total else 0.0,
        "failed_settlement_count": failed_count,
        "timeout_count": timeout_count,
        "abandoned_payment_count": abandoned_count,
        "authorization_violation_count": 0,
        "spend_limit_violation_count": 0,
        "high_risk_agent_count": high_risk,
        "top_protocols": [{"id": k, "count": v} for k, v in protocol_counts.most_common(10)],
        "top_providers": [{"id": k, "count": v} for k, v in provider_counts.most_common(10)],
        "top_capabilities": [{"id": k, "count": v} for k, v in capability_counts.most_common(10)],
        "recent_failures": recent_failures,
    }).to_dict()


@router.get("/operator/agentic/agents")
async def operator_agentic_agents(request: Request):
    """List all agents across tenants."""
    _require_kyber_operator(request)
    agents = await _op_agent_configs.find_many(limit=_LIMIT)
    return APIResponse(data={"agents": agents, "count": len(agents)}).to_dict()


@router.get("/operator/agentic/x402/flows")
async def operator_x402_flows(request: Request):
    """x402 payment intent explorer across all tenants."""
    _require_kyber_operator(request)
    intents = await _op_payment_intents.find_many(limit=_LIMIT)
    return APIResponse(data={"flows": intents, "count": len(intents)}).to_dict()


@router.get("/operator/agentic/x402/failures")
async def operator_x402_failures(request: Request):
    """Failed settlement events across all tenants."""
    _require_kyber_operator(request)
    settlements = await _op_settlements.find_many(limit=_LIMIT)
    failures = [s for s in settlements if s.get("status") in {"failed"}]
    return APIResponse(data={"failures": failures, "count": len(failures)}).to_dict()


@router.get("/operator/agentic/x402/timeouts")
async def operator_x402_timeouts(request: Request):
    """Timeout settlement events across all tenants."""
    _require_kyber_operator(request)
    settlements = await _op_settlements.find_many(limit=_LIMIT)
    timeouts = [s for s in settlements if s.get("status") == "timeout"]
    return APIResponse(data={"timeouts": timeouts, "count": len(timeouts)}).to_dict()


@router.get("/operator/agentic/settlements")
async def operator_agentic_settlements(request: Request):
    """All settlement events across all tenants."""
    _require_kyber_operator(request)
    settlements = await _op_settlements.find_many(limit=_LIMIT)
    return APIResponse(data={"settlements": settlements, "count": len(settlements)}).to_dict()


@router.get("/operator/agentic/delegations")
async def operator_agentic_delegations(request: Request):
    """All delegations across all tenants."""
    _require_kyber_operator(request)
    delegations = await _op_delegations.find_many(limit=_LIMIT)
    return APIResponse(data={"delegations": delegations, "count": len(delegations)}).to_dict()


@router.get("/operator/agentic/subagents")
async def operator_agentic_subagents(request: Request):
    """Subagent relationships (delegations where grantee is a known agent)."""
    _require_kyber_operator(request)
    delegations = await _op_delegations.find_many(limit=_LIMIT)
    agents = await _op_agent_configs.find_many(limit=_LIMIT)
    agent_ids = {a.get("agent_id") for a in agents if a.get("agent_id")}
    subagent_links = [
        d for d in delegations
        if d.get("grantee_entity_id") in agent_ids or d.get("grantor_entity_id") in agent_ids
    ]
    return APIResponse(data={"subagent_relationships": subagent_links, "count": len(subagent_links)}).to_dict()


@router.get("/operator/agentic/anomalies")
async def operator_agentic_anomalies(request: Request):
    """Rule-based anomaly flags across all tenants."""
    _require_kyber_operator(request)

    settlements = await _op_settlements.find_many(limit=_LIMIT)
    intents = await _op_payment_intents.find_many(limit=_LIMIT)

    # Count per agent
    failed_by_agent: Counter = Counter()
    timeout_by_agent: Counter = Counter()
    spend_by_agent: dict[str, float] = defaultdict(float)

    for s in settlements:
        agent_id = s.get("agent_id", "")
        if s.get("status") in {"failed"}:
            failed_by_agent[agent_id] += 1
        if s.get("status") == "timeout":
            timeout_by_agent[agent_id] += 1

    for i in intents:
        agent_id = i.get("agent_id", "")
        try:
            spend_by_agent[agent_id] += float(i.get("amount") or 0)
        except (TypeError, ValueError):
            pass

    # Compute average spend for spike detection
    spend_values = list(spend_by_agent.values())
    avg_spend = sum(spend_values) / len(spend_values) if spend_values else 0.0

    anomalies: list[dict] = []

    for agent_id, count in failed_by_agent.items():
        if count > 3:
            anomalies.append({
                "type": "repeated_payment_failure",
                "agent_id": agent_id,
                "failed_count": count,
                "threshold": 3,
            })

    for agent_id, count in timeout_by_agent.items():
        if count > 5:
            anomalies.append({
                "type": "payment_timeout_spike",
                "agent_id": agent_id,
                "timeout_count": count,
                "threshold": 5,
            })

    for agent_id, total_spend in spend_by_agent.items():
        if avg_spend > 0 and total_spend > avg_spend * 5:
            anomalies.append({
                "type": "agent_spend_limit_exceeded",
                "agent_id": agent_id,
                "total_spend": total_spend,
                "avg_spend": avg_spend,
                "ratio": round(total_spend / avg_spend, 2),
            })

    return APIResponse(data={"anomalies": anomalies, "count": len(anomalies)}).to_dict()


@router.get("/operator/agentic/agents/{agent_id}")
async def operator_agentic_agent_detail(agent_id: str, request: Request):
    """Single agent detail across all tenants."""
    _require_kyber_operator(request)
    config = await _op_agent_configs.find_by_id(agent_id)
    if config is None:
        raise NotFoundError("Agent")
    behavior = await _op_behavior_profiles.find_by_id(agent_id)
    intents = await _op_payment_intents.find_many(filters={"agent_id": agent_id}, limit=100)
    settlements = await _op_settlements.find_many(filters={"agent_id": agent_id}, limit=100)
    delegations_received = await _op_delegations.find_many(
        filters={"grantee_entity_id": agent_id}, limit=100
    )
    return APIResponse(data={
        "agent_id": agent_id,
        "config": config,
        "behavior_profile": behavior,
        "payment_intent_count": len(intents),
        "settlement_count": len(settlements),
        "delegation_count": len(delegations_received),
        "recent_intents": intents[:10],
        "recent_settlements": settlements[:10],
    }).to_dict()


@router.get("/operator/agentic/authorization-violations")
async def operator_agentic_authorization_violations(request: Request):
    """Delegations or authorization events that exceeded their scope (rule-based)."""
    _require_kyber_operator(request)
    delegations = await _op_delegations.find_many(limit=_LIMIT)
    # Flag delegations that were revoked (potential scope violation signal)
    revoked = [d for d in delegations if d.get("revoked_at")]
    return APIResponse(data={
        "violations": revoked,
        "count": len(revoked),
        "note": "Shows revoked delegations as an authorization violation signal.",
    }).to_dict()


@router.get("/operator/agentic/spend-limits")
async def operator_agentic_spend_limits(request: Request):
    """Agents near or over estimated spend thresholds."""
    _require_kyber_operator(request)
    intents = await _op_payment_intents.find_many(limit=_LIMIT)
    spend_by_agent: dict[str, float] = defaultdict(float)
    for i in intents:
        agent_id = i.get("agent_id", "")
        try:
            spend_by_agent[agent_id] += float(i.get("amount") or 0)
        except (TypeError, ValueError):
            pass
    spend_values = list(spend_by_agent.values())
    avg = sum(spend_values) / len(spend_values) if spend_values else 0.0
    over_limit = [
        {"agent_id": aid, "total_spend": spend, "ratio_vs_avg": round(spend / avg, 2) if avg else None}
        for aid, spend in spend_by_agent.items()
        if avg > 0 and spend > avg * 3
    ]
    return APIResponse(data={"over_limit": over_limit, "count": len(over_limit), "avg_spend": avg}).to_dict()


@router.get("/operator/agentic/trust")
async def operator_agentic_trust(request: Request):
    """Trust score overview for agents across all tenants."""
    _require_kyber_operator(request)
    profiles = await _op_behavior_profiles.find_many(limit=_LIMIT)
    rows = [
        {
            "agent_id": p.get("entity_id") or p.get("agent_id"),
            "tenant_id": p.get("tenant_id"),
            "trust_score": p.get("trust_score"),
            "risk_score": p.get("risk_score"),
            "anomaly_score": p.get("anomaly_score"),
        }
        for p in profiles
        if p.get("entity_id") or p.get("agent_id")
    ]
    rows.sort(key=lambda r: float(r.get("risk_score") or 0), reverse=True)
    return APIResponse(data={"trust_profiles": rows, "count": len(rows)}).to_dict()
