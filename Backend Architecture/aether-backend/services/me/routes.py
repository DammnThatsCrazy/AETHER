"""
Aether Service — Customer Self-Service

Profile, API key management, and account endpoints for authenticated tenants.
All operations are scoped to request.state.tenant.tenant_id.

Endpoints:
    GET    /v1/me                   Tenant profile + plan + billing summary
    GET    /v1/me/api-keys          List caller's API keys (paginated, keys masked)
    POST   /v1/me/api-keys          Create a new API key
    PATCH  /v1/me/api-keys/{id}     Rename a key
    DELETE /v1/me/api-keys/{id}     Revoke a key
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics
from repositories.repos import APIKeyRepository

logger = get_logger("aether.service.me")
router = APIRouter(prefix="/v1/me", tags=["Me"])

_key_repo = APIKeyRepository()

_VALID_PERMISSIONS = {"read", "write", "ingest", "analytics", "billing"}


class APIKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=lambda: ["read"])


class APIKeyRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


def _safe_key(key: dict) -> dict:
    """Strip key_hash from a key record before returning to the caller."""
    return {k: v for k, v in key.items() if k != "key_hash"}


def _assert_owns_key(key: dict, tenant_id: str) -> None:
    if key.get("tenant_id") != tenant_id:
        raise ForbiddenError("Key does not belong to this tenant")


@router.get("")
async def get_my_profile(request: Request):
    """Return the calling tenant's profile: plan, billing, key count."""
    tenant = _require_tenant(request)
    from shared.plans.catalog import PLAN_CATALOG
    from shared.billing import stripe_repository
    from shared.auth.auth import PlanTier
    from repositories.repos import AdminRepository

    plan_tier = getattr(tenant, "plan_tier", None)
    plan = PLAN_CATALOG.get(plan_tier) if plan_tier else None

    # Tenant record (name, contact_email)
    tenant_record = {}
    try:
        repo = AdminRepository()
        tenant_record = await repo.find_by_id(tenant.tenant_id) or {}
    except Exception:
        pass

    # Billing account (subscription status, period)
    billing = {}
    try:
        acct = await stripe_repository.get_billing_account(tenant.tenant_id)
        if acct:
            billing = {
                "subscription_status": acct.get("subscription_status"),
                "current_period_end": acct.get("current_period_end"),
                "stripe_customer_id": acct.get("stripe_customer_id"),
            }
    except Exception:
        pass

    key_count = await _key_repo.count(filters={"tenant_id": tenant.tenant_id})

    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "name": tenant_record.get("name", ""),
        "contact_email": tenant_record.get("contact_email", ""),
        "plan": {
            "plan_id": plan.plan_id if plan else (plan_tier.value if plan_tier else "P1"),
            "display_name": plan.display_name if plan else "",
            "monthly_quota": plan.monthly_quota if plan else 0,
            "burst_rpm": plan.burst_rpm if plan else 0,
        },
        "billing": billing,
        "api_key_count": key_count,
    }).to_dict()


@router.get("/api-keys")
async def list_my_api_keys(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List API keys for the calling tenant (paginated)."""
    tenant = _require_tenant(request)
    keys = await _key_repo.find_many(
        filters={"tenant_id": tenant.tenant_id},
        limit=limit,
        offset=offset,
    )
    total = await _key_repo.count(filters={"tenant_id": tenant.tenant_id})
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "api_keys": [_safe_key(k) for k in keys],
        "count": len(keys),
        "total": total,
        "limit": limit,
        "offset": offset,
    }).to_dict()


@router.post("/api-keys")
async def create_my_api_key(body: APIKeyCreateRequest, request: Request):
    """Create a new API key scoped to the calling tenant."""
    tenant = _require_tenant(request)

    # Validate permissions
    invalid = [p for p in body.permissions if p not in _VALID_PERMISSIONS]
    if invalid:
        from shared.common.common import BadRequestError
        raise BadRequestError(f"Invalid permissions: {invalid}. Valid: {sorted(_VALID_PERMISSIONS)}")

    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()

    record = await _key_repo.insert(hashed[:12], {
        "tenant_id": tenant.tenant_id,
        "name": body.name,
        "tier": tenant.api_key_tier.value,
        "permissions": body.permissions,
        "key_hash": hashed,
        "last_used_at": None,
    })

    # Register in auth cache for immediate use
    try:
        from dependencies.providers import get_registry
        registry = get_registry()
        await registry.api_key_validator.register_api_key(
            api_key=raw_key,
            tenant_id=tenant.tenant_id,
            role="editor",
            tier=tenant.api_key_tier.value,
            permissions=body.permissions,
        )
    except Exception as e:
        logger.warning(f"Failed to register key in auth cache: {e}")

    metrics.increment("api_keys_created_self_service")
    logger.info(f"API key created (self-service): tenant={tenant.tenant_id} name={body.name!r}")
    return APIResponse(data={
        "api_key": raw_key,
        "id": record["id"],
        "name": body.name,
        "permissions": body.permissions,
        "message": "Store this key securely — it will not be shown again.",
    }).to_dict()


@router.patch("/api-keys/{key_id}")
async def rename_my_api_key(key_id: str, body: APIKeyRenameRequest, request: Request):
    """Rename an API key owned by the calling tenant."""
    tenant = _require_tenant(request)
    key = await _key_repo.find_by_id(key_id)
    if not key:
        raise NotFoundError(f"API key {key_id}")
    _assert_owns_key(key, tenant.tenant_id)

    updated = await _key_repo.update(key_id, {"name": body.name})
    return APIResponse(data=_safe_key(updated)).to_dict()


@router.delete("/api-keys/{key_id}")
async def revoke_my_api_key(key_id: str, request: Request):
    """Revoke an API key owned by the calling tenant."""
    tenant = _require_tenant(request)
    key = await _key_repo.find_by_id(key_id)
    if not key:
        raise NotFoundError(f"API key {key_id}")
    _assert_owns_key(key, tenant.tenant_id)

    await _key_repo.delete(key_id)

    # Evict from Redis auth cache
    try:
        key_hash = key.get("key_hash", "")
        if key_hash:
            from dependencies.providers import get_registry
            from shared.cache.cache import CacheKey
            registry = get_registry()
            cache_key = CacheKey.api_key(key_hash)
            await registry.cache.delete(cache_key)
    except Exception as e:
        logger.debug(f"Cache eviction failed: {e}")

    metrics.increment("api_keys_revoked_self_service")
    logger.info(f"API key revoked (self-service): tenant={tenant.tenant_id} key_id={key_id}")
    return APIResponse(data={"revoked": True, "id": key_id}).to_dict()
