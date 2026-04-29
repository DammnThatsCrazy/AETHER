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
from pydantic import BaseModel, Field

from config.settings import settings
from shared.auth.auth import PlanTier, legacy_tier_to_plan, APIKeyTier
from shared.billing.overage import OverageCalculator
from shared.common.common import APIResponse
from shared.logger.logger import get_logger
from shared.plans.catalog import PLAN_CATALOG
from repositories.repos import AdminRepository, APIKeyRepository

logger = get_logger("aether.service.admin")
router = APIRouter(prefix="/v1/admin", tags=["Admin"])

_repo = AdminRepository()
_key_repo = APIKeyRepository()


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
