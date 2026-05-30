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

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from shared.auth.auth import PlanTier
from shared.billing import stripe_client, stripe_repository
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.billing")

router = APIRouter(prefix="/v1/billing", tags=["Billing"])
admin_overage_router = APIRouter(prefix="/v1/admin/billing", tags=["Admin — Billing"])


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
