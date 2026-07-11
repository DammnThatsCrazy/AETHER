"""
Aether Service — Customer Billing

Self-serve billing endpoints for authenticated tenants. Wraps Stripe
Checkout and Billing Portal sessions, exposes invoice history, and
provides an admin endpoint to trigger the overage invoice cycle.

Endpoints:
    GET   /v1/billing/plans                     List all available plan tiers
    POST  /v1/billing/checkout                  Create Stripe Checkout session
    POST  /v1/billing/portal                    Create Stripe Billing Portal session
    GET   /v1/billing/invoices                  List invoices for calling tenant
    GET   /v1/billing/invoices/{invoice_id}     Get single invoice
    POST  /v1/admin/billing/overage-cycle       Trigger overage invoice cycle (admin)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from config.settings import settings
from shared.auth.auth import PlanTier
from shared.billing import stripe_client, stripe_repository
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

from services.security.request_context import require_kyber_operator

logger = get_logger("aether.service.billing")

router = APIRouter(prefix="/v1/billing", tags=["Billing"])
admin_overage_router = APIRouter(prefix="/v1/admin/billing", tags=["Admin — Billing"])
kyber_revops_router = APIRouter(
    prefix="/v1/admin/kyber/revops",
    tags=["Admin — Kyber Revenue Operations"],
    dependencies=[Depends(require_kyber_operator)],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan_tier: str  # P1 | P2 | P3 | P4


class PortalRequest(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------

@router.get("/plans")
async def list_plans():
    """Return all available plan tiers. Public — no auth required."""
    from shared.plans.catalog import PLAN_CATALOG
    plans = [
        {
            "plan_id": plan.plan_id,
            "display_name": plan.display_name,
            "price_monthly": int(plan.pricing.option_a),
            "monthly_quota": plan.monthly_quota,
            "burst_rpm": plan.burst_rpm,
            "service_count": plan.service_count,
            "target_user": plan.target_user,
        }
        for plan in PLAN_CATALOG.values()
    ]
    return APIResponse(data={"plans": plans}).to_dict()


@router.post("/checkout")
async def create_checkout_session(body: CheckoutRequest, request: Request):
    """Create a Stripe Checkout session for a plan upgrade."""
    tenant = _require_tenant(request)
    try:
        plan_tier = PlanTier(body.plan_tier)
    except ValueError:
        raise BadRequestError(f"Invalid plan_tier: {body.plan_tier!r}. Valid: P1 P2 P3 P4")

    # Fetch any existing Stripe customer ID for this tenant
    account = await stripe_repository.get_billing_account(tenant.tenant_id)
    customer_id = (account or {}).get("stripe_customer_id")
    contact_email = (account or {}).get("contact_email")

    session = await stripe_client.create_checkout_session(
        tenant_id=tenant.tenant_id,
        plan_tier=plan_tier,
        contact_email=contact_email,
        customer_id=customer_id,
    )
    metrics.increment("billing_checkout_sessions_created", labels={"plan": plan_tier.value})
    return APIResponse(data={
        "session_id": session.session_id,
        "url": session.url,
        "mocked": session.mocked,
    }).to_dict()


@router.post("/portal")
async def create_portal_session(request: Request):
    """Create a Stripe Billing Portal session for the calling tenant."""
    tenant = _require_tenant(request)
    account = await stripe_repository.get_billing_account(tenant.tenant_id)
    customer_id = (account or {}).get("stripe_customer_id")

    session = await stripe_client.create_portal_session(
        tenant_id=tenant.tenant_id,
        customer_id=customer_id,
    )
    metrics.increment("billing_portal_sessions_created")
    return APIResponse(data={
        "url": session.url,
        "mocked": session.mocked,
    }).to_dict()


@router.get("/invoices")
async def list_invoices(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    """List invoices for the calling tenant."""
    tenant = _require_tenant(request)
    invoices = await stripe_repository.list_invoices(tenant.tenant_id, limit=limit)
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "invoices": [_serialize_invoice(inv) for inv in invoices],
        "count": len(invoices),
    }).to_dict()


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, request: Request):
    """Get a single invoice for the calling tenant."""
    tenant = _require_tenant(request)
    inv = await stripe_repository.get_invoice(tenant.tenant_id, invoice_id)
    if not inv:
        raise NotFoundError(f"Invoice {invoice_id}")
    return APIResponse(data=_serialize_invoice(inv)).to_dict()


def _serialize_invoice(inv: dict) -> dict:
    result = {k: v for k, v in inv.items()}
    # Convert datetime objects to ISO strings for JSON serialisation
    for field in ("period_start", "period_end", "created_at", "updated_at"):
        val = result.get(field)
        if isinstance(val, datetime):
            result[field] = val.isoformat()
    return result


# ---------------------------------------------------------------------------
# Admin endpoint — trigger overage cycle
# ---------------------------------------------------------------------------

class OverageCycleRequest(BaseModel):
    billing_period: Optional[str] = None  # YYYY-MM; defaults to current month


@admin_overage_router.post("/overage-cycle")
async def trigger_overage_cycle(body: OverageCycleRequest, request: Request):
    """Manually trigger the overage invoice cycle (admin only)."""
    request.state.tenant.require_permission("admin")
    from services.billing.cycle import run_overage_cycle
    summary = await run_overage_cycle(billing_period=body.billing_period)
    return APIResponse(data=summary).to_dict()

# ── Billing-ready revenue operations (internal substrate, no payment processor) ──
from services.billing.revops import (
    BillableUsageSummaryRepository,
    EntitlementService,
    ExpansionBillingService,
    InvoicePreviewRepository,
    InvoicePreviewService,
    MeteringService,
    RevenueLeakageService,
    RevenueLeakageSignalRepository,
    TenantContractProfile,
    TenantContractProfileRepository,
    TenantEntitlement,
    TenantEntitlementRepository,
    UsageMeteringEvent,
    UsageMeteringEventRepository,
    UsageSummaryService,
    ValueCreatedEvent,
    ValueCreatedEventRepository,
    ValueCreatedEventService,
)

_contract_profiles = TenantContractProfileRepository()
_tenant_entitlements = TenantEntitlementRepository()
_usage_events = UsageMeteringEventRepository()
_usage_summaries = BillableUsageSummaryRepository()
_invoice_previews = InvoicePreviewRepository()
_value_events = ValueCreatedEventRepository()
_leakage_signals = RevenueLeakageSignalRepository()
_metering_service = MeteringService(_usage_events)
_entitlement_service = EntitlementService(_contract_profiles, _tenant_entitlements)
_usage_summary_service = UsageSummaryService(_usage_events, _entitlement_service, _usage_summaries)
_invoice_preview_service = InvoicePreviewService()
_value_created_service = ValueCreatedEventService()
_revenue_leakage_service = RevenueLeakageService()
_expansion_billing_service = ExpansionBillingService()

# External billing provider readiness (behind flags; internal-only by default).
from services.billing.providers import (
    get_billing_provider,
    load_mappings,
    provider_status_summary,
)


def _current_billing_window() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def _tenant_safe_contract(contract: dict | None) -> dict:
    if not contract:
        return {"package_id": None, "plan_tier": None, "contract_status": None, "billing_model": None, "billing_period": "monthly", "currency": "USD"}
    return {k: contract.get(k) for k in ("contract_profile_id", "tenant_id", "package_id", "plan_tier", "contract_status", "billing_model", "billing_period", "currency", "contract_start_date", "contract_end_date", "renewal_date")}


def _tenant_safe_entitlement(ent: dict) -> dict:
    return {k: ent.get(k) for k in ("entitlement_id", "tenant_id", "package_id", "feature_key", "enabled", "included_quantity", "overage_allowed", "reset_period", "created_at", "updated_at")}


def _tenant_safe_invoice(inv: dict) -> dict:
    safe = {k: inv.get(k) for k in ("invoice_preview_id", "tenant_id", "contract_profile_id", "billing_period_start", "billing_period_end", "line_items", "value_created_summary", "status", "generated_at", "updated_at")}
    for item in safe.get("line_items") or []:
        item.pop("unit_price_notes", None)
        item.pop("amount_notes", None)
    return safe


@router.get("/plan")
async def get_billing_plan(request: Request):
    tenant = _require_tenant(request)
    contract = await _contract_profiles.get_for_tenant(tenant.tenant_id)
    entitlements = await _tenant_entitlements.list_for_tenant(tenant.tenant_id)
    return APIResponse(data={"plan": _tenant_safe_contract(contract), "enabled_modules": [e["feature_key"] for e in entitlements if e.get("enabled", True)]}).to_dict()


@router.get("/entitlements")
async def get_billing_entitlements(request: Request):
    tenant = _require_tenant(request)
    entitlements = await _tenant_entitlements.list_for_tenant(tenant.tenant_id)
    return APIResponse(data={"tenant_id": tenant.tenant_id, "entitlements": [_tenant_safe_entitlement(e) for e in entitlements]}).to_dict()


@router.get("/usage")
async def get_billing_usage(request: Request, start: Optional[str] = None, end: Optional[str] = None):
    tenant = _require_tenant(request)
    start, end = (start, end) if start and end else _current_billing_window()
    events = await _usage_events.list_for_tenant_period(tenant.tenant_id, start, end)
    return APIResponse(data={"tenant_id": tenant.tenant_id, "billing_period_start": start, "billing_period_end": end, "events": events, "count": len(events)}).to_dict()


@router.get("/usage/summary")
async def get_billing_usage_summary(request: Request, start: Optional[str] = None, end: Optional[str] = None):
    tenant = _require_tenant(request)
    start, end = (start, end) if start and end else _current_billing_window()
    summary = await _usage_summary_service.calculate(tenant.tenant_id, start, end)
    return APIResponse(data=summary).to_dict()


@router.get("/invoice-previews")
async def list_invoice_previews(request: Request):
    tenant = _require_tenant(request)
    previews = await _invoice_previews.find_many(filters={"tenant_id": tenant.tenant_id}, limit=100)
    return APIResponse(data={"tenant_id": tenant.tenant_id, "items": [_tenant_safe_invoice(p) for p in previews], "count": len(previews)}).to_dict()


@router.get("/value-created")
async def list_value_created(request: Request, start: Optional[str] = None, end: Optional[str] = None):
    tenant = _require_tenant(request)
    if start and end:
        values = await _value_events.list_for_tenant_period(tenant.tenant_id, start, end)
    else:
        values = await _value_events.find_many(filters={"tenant_id": tenant.tenant_id}, limit=100)
    customer_safe = [{k: v.get(k) for k in ("value_event_id", "tenant_id", "source_type", "source_id", "value_type", "value_amount", "currency", "confidence", "attribution_notes", "occurred_at")} for v in values]
    return APIResponse(data={"tenant_id": tenant.tenant_id, "items": customer_safe, "count": len(customer_safe)}).to_dict()


@kyber_revops_router.get("/overview")
async def kyber_revops_overview(request: Request):
    request.state.tenant.require_permission("admin")
    contracts = await _contract_profiles.find_many(limit=10000)
    previews = await _invoice_previews.find_many(limit=10000)
    leakage = await _leakage_signals.find_many(limit=10000)
    values = await _value_events.find_many(limit=10000)
    opps = await _expansion_billing_service.opportunities()
    model_mix: dict[str, int] = {}
    for c in contracts:
        model_mix[c.get("billing_model", "unknown")] = model_mix.get(c.get("billing_model", "unknown"), 0) + 1
    return APIResponse(data={
        "active_contracts": sum(1 for c in contracts if c.get("contract_status") == "active"),
        "billing_model_mix": model_mix,
        "usage_based_tenants": model_mix.get("usage_based", 0) + model_mix.get("hybrid", 0),
        "enterprise_contract_tenants": model_mix.get("enterprise_contract", 0),
        "pilot_tenants": model_mix.get("pilot", 0),
        "tenants_with_overages": len({s.get("tenant_id") for s in leakage if s.get("leakage_type") == "overage_not_priced"}),
        "tenants_underutilizing_contract": 0,
        "estimated_billable_usage": sum(float(v.get("quantity") or 0) for v in await _usage_events.find_many(limit=10000) if v.get("billable")),
        "value_created_total": round(sum(float(v.get("value_amount") or 0) for v in values), 2),
        "invoice_previews_pending_review": sum(1 for p in previews if p.get("status") in {"draft", "review_ready"}),
        "expansion_billing_opportunities": len(opps),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }).to_dict()


@kyber_revops_router.get("/contracts")
async def kyber_revops_contracts(request: Request):
    request.state.tenant.require_permission("admin")
    items = await _contract_profiles.find_many(limit=10000)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.get("/contracts/{tenant_id}")
async def kyber_get_contract(tenant_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    return APIResponse(data=await _contract_profiles.get_for_tenant(tenant_id)).to_dict()


@kyber_revops_router.post("/contracts/{tenant_id}")
async def kyber_create_contract(tenant_id: str, body: TenantContractProfile, request: Request):
    request.state.tenant.require_permission("admin")
    payload = body.model_dump()
    payload["tenant_id"] = tenant_id
    return APIResponse(data=await _contract_profiles.insert(payload["contract_profile_id"], payload)).to_dict()


@kyber_revops_router.patch("/contracts/{tenant_id}")
async def kyber_update_contract(tenant_id: str, body: dict, request: Request):
    request.state.tenant.require_permission("admin")
    existing = await _contract_profiles.get_for_tenant(tenant_id)
    if not existing:
        raise NotFoundError("contract profile")
    body.pop("tenant_id", None)
    body.pop("contract_profile_id", None)
    return APIResponse(data=await _contract_profiles.update(existing["contract_profile_id"], body)).to_dict()


@kyber_revops_router.get("/entitlements/{tenant_id}")
async def kyber_list_entitlements(tenant_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    items = await _tenant_entitlements.list_for_tenant(tenant_id)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.post("/entitlements/{tenant_id}")
async def kyber_create_entitlement(tenant_id: str, body: TenantEntitlement, request: Request):
    request.state.tenant.require_permission("admin")
    payload = body.model_dump()
    payload["tenant_id"] = tenant_id
    return APIResponse(data=await _tenant_entitlements.insert(payload["entitlement_id"], payload)).to_dict()


@kyber_revops_router.patch("/entitlements/{entitlement_id}")
async def kyber_update_entitlement(entitlement_id: str, body: dict, request: Request):
    request.state.tenant.require_permission("admin")
    body.pop("tenant_id", None)
    body.pop("entitlement_id", None)
    return APIResponse(data=await _tenant_entitlements.update(entitlement_id, body)).to_dict()


@kyber_revops_router.get("/usage")
async def kyber_usage_all(request: Request):
    request.state.tenant.require_permission("admin")
    items = await _usage_events.find_many(limit=10000)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.get("/usage/{tenant_id}")
async def kyber_usage_tenant(tenant_id: str, request: Request, start: Optional[str] = None, end: Optional[str] = None):
    request.state.tenant.require_permission("admin")
    if start and end:
        items = await _usage_events.list_for_tenant_period(tenant_id, start, end)
    else:
        items = await _usage_events.find_many(filters={"tenant_id": tenant_id}, limit=10000)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.post("/metering-events")
async def kyber_create_metering_event(body: UsageMeteringEvent, request: Request):
    request.state.tenant.require_permission("admin")
    event = await _metering_service.record_event(body)
    return APIResponse(data={"metering_disabled": event is None, "event": event}).to_dict()


@kyber_revops_router.get("/invoice-previews")
async def kyber_invoice_previews(request: Request):
    request.state.tenant.require_permission("admin")
    items = await _invoice_previews.find_many(limit=10000)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.post("/invoice-previews/{tenant_id}/generate")
async def kyber_generate_invoice_preview(tenant_id: str, request: Request, start: Optional[str] = None, end: Optional[str] = None):
    request.state.tenant.require_permission("admin")
    start, end = (start, end) if start and end else _current_billing_window()
    return APIResponse(data=await _invoice_preview_service.generate(tenant_id, start, end)).to_dict()


@kyber_revops_router.patch("/invoice-previews/{invoice_preview_id}")
async def kyber_update_invoice_preview(invoice_preview_id: str, body: dict, request: Request):
    request.state.tenant.require_permission("admin")
    status = body.get("status")
    if status not in {"draft", "review_ready", "approved", "exported"}:
        raise BadRequestError("Invalid invoice preview status")
    return APIResponse(data=await _invoice_preview_service.update_status(invoice_preview_id, status)).to_dict()


@kyber_revops_router.get("/value-created")
async def kyber_value_created(request: Request):
    request.state.tenant.require_permission("admin")
    items = await _value_events.find_many(limit=10000)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.get("/revenue-leakage")
async def kyber_revenue_leakage(request: Request, tenant_id: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None):
    request.state.tenant.require_permission("admin")
    if tenant_id and start and end:
        await _revenue_leakage_service.detect(tenant_id, start, end)
    items = await _leakage_signals.find_many(filters={"tenant_id": tenant_id} if tenant_id else None, limit=10000)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@kyber_revops_router.get("/expansion-billing-opportunities")
async def kyber_expansion_billing_opportunities(request: Request, tenant_id: Optional[str] = None):
    request.state.tenant.require_permission("admin")
    items = await _expansion_billing_service.opportunities(tenant_id=tenant_id)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


# ── External billing provider readiness (behind flags) ───────────────────────

@kyber_revops_router.get("/provider-status")
async def kyber_billing_provider_status(request: Request):
    """Operator view of external billing provider/sync status. No secrets."""
    request.state.tenant.require_permission("admin")
    return APIResponse(data=provider_status_summary()).to_dict()


@kyber_revops_router.get("/product-mappings")
async def kyber_billing_product_mappings(request: Request):
    """Product/price mapping catalog + status (provider ids only, no secrets)."""
    request.state.tenant.require_permission("admin")
    mappings = [m.model_dump() for m in load_mappings()]
    return APIResponse(data={"items": mappings, "count": len(mappings)}).to_dict()


@router.get("/payment-status")
async def get_billing_payment_status(request: Request):
    """Tenant-facing payment status. Customer-safe: shows provider-managed status
    only when an external provider is enabled; otherwise internally managed.
    Never exposes revenue leakage, overage strategy, or provider debug details."""
    tenant = _require_tenant(request)
    provider = get_billing_provider()
    status = await provider.sync_payment_status(tenant_id=tenant.tenant_id)
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "payment_status": status,
        "billing_provider_mode": provider.provider_type,
        "external_billing_enabled": settings.external_billing.external_billing_enabled,
    }).to_dict()
