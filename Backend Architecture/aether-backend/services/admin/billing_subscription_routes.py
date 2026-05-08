"""
Aether Service — Admin Billing Subscription

Subscription mutations on top of the existing read-only
GET /v1/admin/tenants/{tenant_id}/billing endpoint. Wraps the
shared.billing.stripe_repository helpers so KYBER's commerce surface can
change plans, cancel, and reactivate subscriptions without touching Stripe
directly from the operator UI.

Endpoints:
    GET    /v1/admin/tenants/{tenant_id}/billing/subscription
    POST   /v1/admin/tenants/{tenant_id}/billing/subscription/change-plan
    POST   /v1/admin/tenants/{tenant_id}/billing/subscription/cancel
    POST   /v1/admin/tenants/{tenant_id}/billing/subscription/reactivate

Invoice listing/detail is served by services.admin.routes — this module
only adds the subscription mutations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from services.admin.routes import _enforce_tenant_scope
from shared.auth.auth import PlanTier
from shared.billing import stripe_repository
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.admin.billing_subscription")
router = APIRouter(prefix="/v1/admin/tenants", tags=["Admin — Billing"])


VALID_PLAN_TIERS = [t.value for t in PlanTier]
VALID_CANCEL_REASONS = [
    "voluntary", "non_payment", "downgrade", "fraud", "tos_violation", "support_request",
]


class ChangePlanRequest(BaseModel):
    plan_tier: str = Field(..., description="One of " + "|".join(VALID_PLAN_TIERS))
    effective_at: Optional[str] = None  # ISO timestamp; default = immediately


class CancelSubscriptionRequest(BaseModel):
    reason: str = Field(default="voluntary", description="One of " + "|".join(VALID_CANCEL_REASONS))
    cancel_at_period_end: bool = True
    note: Optional[str] = None


class ReactivateSubscriptionRequest(BaseModel):
    note: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _require_account(tenant_id: str) -> dict[str, Any]:
    account = await stripe_repository.get_billing_account(tenant_id)
    if not account:
        raise NotFoundError(f"Billing account not found for tenant: {tenant_id}")
    return account


@router.get("/{tenant_id}/billing/subscription")
async def get_subscription(tenant_id: str, request: Request):
    """Return the current subscription state."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)
    account = await _require_account(tenant_id)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "plan_tier": account.get("plan_tier"),
        "subscription_id": account.get("stripe_subscription_id"),
        "status": account.get("subscription_status"),
        "cancel_at_period_end": account.get("cancel_at_period_end", False),
        "current_period_start": account.get("current_period_start"),
        "current_period_end": account.get("current_period_end"),
        "updated_at": account.get("updated_at"),
    }).to_dict()


@router.post("/{tenant_id}/billing/subscription/change-plan")
async def change_plan(tenant_id: str, body: ChangePlanRequest, request: Request):
    """Move a tenant to a different plan tier."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    if body.plan_tier not in VALID_PLAN_TIERS:
        raise BadRequestError(
            f"Invalid plan_tier '{body.plan_tier}'. Valid: {VALID_PLAN_TIERS}"
        )
    await _require_account(tenant_id)

    await stripe_repository.update_plan_tier(tenant_id, body.plan_tier)
    metrics.increment("billing_plan_changes", labels={"to_tier": body.plan_tier})
    logger.info(f"Plan changed: tenant={tenant_id} new_tier={body.plan_tier}")

    account = await stripe_repository.get_billing_account(tenant_id)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "plan_tier": account.get("plan_tier") if account else body.plan_tier,
        "effective_at": body.effective_at or _now(),
    }).to_dict()


@router.post("/{tenant_id}/billing/subscription/cancel")
async def cancel_subscription(tenant_id: str, body: CancelSubscriptionRequest, request: Request):
    """Cancel the subscription (default: at end of current period)."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)

    if body.reason not in VALID_CANCEL_REASONS:
        raise BadRequestError(
            f"Invalid reason '{body.reason}'. Valid: {VALID_CANCEL_REASONS}"
        )
    account = await _require_account(tenant_id)

    new_status = "canceling" if body.cancel_at_period_end else "canceled"
    await stripe_repository.update_subscription_state(
        tenant_id=tenant_id,
        subscription_status=new_status,
    )
    metrics.increment("billing_subscriptions_canceled", labels={"reason": body.reason})
    logger.info(
        f"Subscription cancel: tenant={tenant_id} reason={body.reason} "
        f"at_period_end={body.cancel_at_period_end}"
    )
    return APIResponse(data={
        "tenant_id": tenant_id,
        "status": new_status,
        "cancel_at_period_end": body.cancel_at_period_end,
        "reason": body.reason,
        "note": body.note,
        "subscription_id": account.get("stripe_subscription_id"),
        "canceled_at": _now(),
    }).to_dict()


@router.post("/{tenant_id}/billing/subscription/reactivate")
async def reactivate_subscription(tenant_id: str, body: ReactivateSubscriptionRequest, request: Request):
    """Reactivate a canceling subscription. No-op if already active."""
    request.state.tenant.require_permission("billing")
    _enforce_tenant_scope(request, tenant_id)
    account = await _require_account(tenant_id)
    current = account.get("subscription_status")

    if current not in ("canceling", "canceled"):
        return APIResponse(data={
            "tenant_id": tenant_id,
            "status": current,
            "noop": True,
        }).to_dict()

    await stripe_repository.update_subscription_state(
        tenant_id=tenant_id,
        subscription_status="active",
    )
    metrics.increment("billing_subscriptions_reactivated")
    logger.info(f"Subscription reactivated: tenant={tenant_id}")
    return APIResponse(data={
        "tenant_id": tenant_id,
        "status": "active",
        "cancel_at_period_end": False,
        "note": body.note,
        "reactivated_at": _now(),
    }).to_dict()


