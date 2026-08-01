"""
Aether Service — Customer Self-Service

Profile, API key management, and account endpoints for authenticated tenants.
All operations are scoped to request.state.tenant.tenant_id.

Endpoints:
    GET    /v1/me                   Tenant profile + plan + billing summary
    GET    /v1/me/usage             Current-period usage stats (quota, RPM, days remaining)
    GET    /v1/me/api-keys          List caller's API keys (paginated, keys masked)
    POST   /v1/me/api-keys          Create a new API key
    PATCH  /v1/me/api-keys/{id}     Rename a key
    DELETE /v1/me/api-keys/{id}     Revoke a key
    GET    /v1/me/sessions          List active and historical human sessions
    DELETE /v1/me/sessions/{id}     Revoke one human session
    POST   /v1/me/sessions/revoke-others  Revoke every session except this one
    DELETE /v1/me/account           Self-service account deletion
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError, ServiceUnavailableError
from shared.logger.logger import get_logger, metrics
from repositories.repos import APIKeyRepository

logger = get_logger("aether.service.me")
router = APIRouter(prefix="/v1/me", tags=["Me"])

_key_repo = APIKeyRepository()

_VALID_PERMISSIONS = {"read", "write", "ingest", "analytics", "billing"}
_VALID_PLATFORMS = {"web", "ios", "android", "react-native", "node", "other"}


class APIKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    platform: str | None = Field(
        default=None,
        description="Optional SDK platform this key is intended for "
        "(web|ios|android|react-native|node|other).",
    )


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
    try:
        repo = AdminRepository()
        tenant_record = await repo.find_by_id(tenant.tenant_id) or {}
    except Exception as exc:
        raise ServiceUnavailableError("Tenant profile repository unavailable") from exc

    # Billing account (subscription status, period)
    try:
        acct = await stripe_repository.get_billing_account(tenant.tenant_id)
        billing = (
            {
                "subscription_status": acct.get("subscription_status"),
                "current_period_end": acct.get("current_period_end"),
                "stripe_customer_id": acct.get("stripe_customer_id"),
            }
            if acct
            else None
        )
    except Exception as exc:
        raise ServiceUnavailableError("Billing repository unavailable") from exc

    key_count = await _key_repo.count(filters={"tenant_id": tenant.tenant_id})

    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "name": tenant_record.get("name"),
        "contact_email": tenant_record.get("contact_email"),
        "plan": {
            "plan_id": plan.plan_id if plan else (plan_tier.value if plan_tier else None),
            "display_name": plan.display_name if plan else None,
            "monthly_quota": plan.monthly_quota if plan else None,
            "burst_rpm": plan.burst_rpm if plan else None,
        } if plan_tier else None,
        "billing": billing,
        "api_key_count": key_count,
        # Whether the caller may manage tenant-wide SDK remote config
        # (publish / rollback). Drives admin-gated controls in the dashboard.
        "is_admin": tenant.has_permission("admin"),
    }).to_dict()


@router.get("/usage")
async def get_my_usage(request: Request):
    """Return current-period usage stats: quota consumption, peak RPM, and days remaining.

    Events-used and RPM-peak are derived from the ingestion metrics store.
    Missing observations are explicitly unavailable and repository failures
    propagate as dependency failures rather than measured zeroes.
    """
    tenant = _require_tenant(request)
    from shared.plans.catalog import PLAN_CATALOG
    from shared.auth.auth import PlanTier

    plan_tier = getattr(tenant, "plan_tier", None)
    plan = PLAN_CATALOG.get(plan_tier) if plan_tier else None

    monthly_quota = plan.monthly_quota if plan else None
    burst_rpm = plan.burst_rpm if plan else None

    # Billing period: calendar month (1st → last day).
    today = date.today()
    period_start = today.replace(day=1)
    # First day of next month minus one day = last day of this month.
    if today.month == 12:
        period_end = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(today.year, today.month + 1, 1) - timedelta(days=1)
    days_remaining = (period_end - today).days

    # Try to pull real event counts from the ingestion metrics layer.
    try:
        from repositories.repos import AdminRepository
        repo = AdminRepository()
        usage_record = await repo.get_tenant_usage(
            tenant_id=tenant.tenant_id,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
    except Exception as exc:
        raise ServiceUnavailableError("Usage repository unavailable") from exc

    events_used = usage_record.get("events_used") if usage_record else None
    rpm_peak = usage_record.get("rpm_peak") if usage_record else None
    overage_events = (
        max(0, events_used - monthly_quota)
        if isinstance(events_used, int) and isinstance(monthly_quota, int)
        else None
    )

    metrics.increment("me_usage_fetched")
    return APIResponse(data={
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "events_used": events_used,
        "events_quota": monthly_quota,
        "rpm_peak": rpm_peak,
        "rpm_limit": burst_rpm,
        "overage_events": overage_events,
        "days_remaining": days_remaining,
        "availability": "available" if usage_record else "insufficient_evidence",
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

    # Validate optional platform tag
    if body.platform is not None and body.platform not in _VALID_PLATFORMS:
        from shared.common.common import BadRequestError
        raise BadRequestError(
            f"Invalid platform: {body.platform!r}. Valid: {sorted(_VALID_PLATFORMS)}"
        )

    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()

    record = await _key_repo.insert(hashed[:12], {
        "tenant_id": tenant.tenant_id,
        "name": body.name,
        "tier": tenant.api_key_tier.value,
        "permissions": body.permissions,
        "platform": body.platform,
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
        "platform": body.platform,
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


@router.get("/sessions")
async def list_my_sessions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List durable human sessions for the authenticated tenant."""
    tenant = _require_tenant(request)
    from services.auth.sessions import session_service

    sessions, total = await session_service.list_for_tenant(
        tenant.tenant_id, limit=limit, offset=offset
    )
    return APIResponse(data={
        "sessions": sessions,
        "count": len(sessions),
        "total": total,
        "limit": limit,
        "offset": offset,
    }).to_dict()


@router.delete("/sessions/{session_id}")
async def revoke_my_session(session_id: str, request: Request):
    """Revoke a tenant-owned session; cross-tenant identifiers are not revealed."""
    tenant = _require_tenant(request)
    from services.auth.sessions import session_service

    if not await session_service.revoke_for_tenant(tenant.tenant_id, session_id):
        raise NotFoundError(f"Session {session_id}")
    metrics.increment("human_sessions_revoked")
    return APIResponse(data={"revoked": True, "id": session_id}).to_dict()


@router.post("/sessions/revoke-others")
async def revoke_my_other_sessions(request: Request):
    """Revoke all other sessions using the caller's validated session identity."""
    tenant = _require_tenant(request)
    raw_token = request.cookies.get("aether_session") or request.headers.get("X-Session-Token")
    if not raw_token:
        from shared.common.common import BadRequestError
        raise BadRequestError("A human session credential is required")
    from services.auth.sessions import session_service

    try:
        current = await session_service.validate_session(raw_token)
    except Exception as exc:
        raise ForbiddenError("Current session is invalid") from exc
    if current.get("tenant_id") != tenant.tenant_id:
        raise ForbiddenError("Current session does not belong to this tenant")
    current_session_id = current["id"]
    revoked = await session_service.revoke_other_sessions(
        tenant.tenant_id, current_session_id
    )
    metrics.increment("human_sessions_revoked", value=revoked)
    return APIResponse(data={"revoked_count": revoked}).to_dict()
