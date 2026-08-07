"""Mobile gateway API — /v1/mobile (tenant / Aether).

Flag-gated via ``settings.mobile.enabled`` (default OFF → 404). Registers native
installations and their push subscriptions. Scope is ``t:{tenant_id}``; app_kind is
forced to ``aether`` (the operator plane gets its own gateway). Only the hash of a
push token is stored — never the raw token.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator

from config.settings import settings
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, NotFoundError
from services.mobile.config import DISTRIBUTION_PROFILES

from services.mobile import service as mobile_service

router = APIRouter(prefix="/v1/mobile", tags=["Mobile Gateway"])


def _require_enabled() -> None:
    if not settings.mobile.enabled:
        raise NotFoundError("mobile gateway (feature not enabled)")


def _tenant(request: Request, permission: str) -> TenantContext:
    _require_enabled()
    tenant: TenantContext = request.state.tenant
    tenant.require_permission(permission)
    return tenant


def _principal(tenant: TenantContext) -> str:
    return tenant.user_id or tenant.tenant_id


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: Optional[str] = None
    platform: str
    bundle_id: str
    environment: str
    device_name: Optional[str] = None
    push_token: Optional[str] = None
    push_provider: Optional[str] = None
    app_version: Optional[str] = None
    distribution_profile: Optional[str] = None

    @field_validator("distribution_profile")
    @classmethod
    def _distribution_profile(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in DISTRIBUTION_PROFILES:
            raise ValueError(
                f"distribution_profile must be one of {', '.join(DISTRIBUTION_PROFILES)}"
            )
        return v


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    provider: str
    push_token: str
    environment: str


class DeepLinkResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Only opaque ids travel — never PII / graph. Principal, scope and elevation are
    # derived server-side from the session, never trusted from the client.
    installation_id: str
    continuation_id: str


@router.post("/installations")
async def register_installation(request: Request, payload: RegistrationRequest) -> APIResponse:
    tenant = _tenant(request, "write")
    result = await mobile_service.register(
        scope=mobile_service.tenant_scope(tenant.tenant_id),
        principal_id=_principal(tenant),
        installation_id=payload.installation_id,
        platform=payload.platform,
        bundle_id=payload.bundle_id,
        environment=payload.environment,
        device_name=payload.device_name,
        push_token=payload.push_token,
        push_provider=payload.push_provider,
        app_version=payload.app_version,
        distribution_profile=payload.distribution_profile,
    )
    return APIResponse(data=result)


@router.get("/config")
async def get_mobile_config(request: Request, installation_id: str = Query(...)) -> APIResponse:
    """Return the typed MobileConfig for the requesting installation.

    Scoped to the authenticated tenant. Returns 404 when ``mobile.enabled`` is
    OFF (via ``_tenant`` → ``_require_enabled``, mirroring the other gateway
    routes) and 404 when the installation does not exist in the tenant scope.
    """
    tenant = _tenant(request, "read")
    result = await mobile_service.get_config(
        scope=mobile_service.tenant_scope(tenant.tenant_id),
        installation_id=installation_id,
    )
    if result is None:
        raise NotFoundError("installation not found")
    return APIResponse(data=result)


@router.get("/installations")
async def list_installations(request: Request) -> APIResponse:
    tenant = _tenant(request, "read")
    rows = await mobile_service.list_for_principal(
        mobile_service.tenant_scope(tenant.tenant_id), _principal(tenant)
    )
    return APIResponse(data={"installations": rows})


@router.get("/installations/{installation_id}")
async def get_installation(request: Request, installation_id: str = Path(...)) -> APIResponse:
    tenant = _tenant(request, "read")
    row = await mobile_service.get(
        mobile_service.tenant_scope(tenant.tenant_id), installation_id
    )
    if row is None:
        raise NotFoundError("installation not found")
    return APIResponse(data=row)


@router.delete("/installations/{installation_id}")
async def revoke_installation(request: Request, installation_id: str = Path(...)) -> APIResponse:
    tenant = _tenant(request, "write")
    row = await mobile_service.revoke(
        mobile_service.tenant_scope(tenant.tenant_id), installation_id
    )
    if row is None:
        raise NotFoundError("installation not found")
    return APIResponse(data=row)


@router.post("/deep-links/resolve")
async def resolve_deep_link(request: Request, payload: DeepLinkResolveRequest) -> APIResponse:
    """Resolve an opaque mobile deep link to a bounded continuation projection.

    Fail-closed: every failure that could leak a continuation's existence returns the
    same ``{"resolved": false, "reason": "unresolvable"}`` body. Restricted
    continuations require a stepped-up session (``step_up`` permission on the tenant
    plane; the Kyber device-proof step-up is the operator plane, deferred)."""
    tenant = _tenant(request, "read")
    result = await mobile_service.resolve_deep_link(
        scope=mobile_service.tenant_scope(tenant.tenant_id),
        principal_id=_principal(tenant),
        installation_id=payload.installation_id,
        continuation_id=payload.continuation_id,
        elevated=tenant.has_permission("step_up"),
    )
    return APIResponse(data=result)


@router.post("/installations/{installation_id}/subscriptions")
async def add_subscription(
    request: Request, payload: SubscriptionRequest, installation_id: str = Path(...)
) -> APIResponse:
    tenant = _tenant(request, "write")
    sub = await mobile_service.add_subscription(
        scope=mobile_service.tenant_scope(tenant.tenant_id),
        installation_id=installation_id,
        principal_id=_principal(tenant),
        platform=payload.platform,
        provider=payload.provider,
        push_token=payload.push_token,
        environment=payload.environment,
    )
    if sub is None:
        raise NotFoundError("installation not found")
    return APIResponse(data=sub)


# ── Bounded, redacted projections (M3a, decision-log D12) ────────────────────
#
# Each surface COMPOSES owning-service truth (profile-360 summary, campaign-360
# overview, the single canonical inbox, saved-views store, noesis conversations)
# and returns a bounded, redacted projection — it never re-calculates
# Profile360/Campaign360/graph truth. Wire fields are snake_case (D6).
# See services/mobile/projections.py for the projection builders.

from services.mobile.projections import MobileProjectionService

_projection_service = MobileProjectionService()


@router.get("/today")
async def get_today_projection(
    request: Request, profile_user_id: Optional[str] = Query(default=None)
) -> APIResponse:
    """Today digest — alert counts + recent redacted alert titles + a bounded,
    redacted profile summary peek."""
    tenant = _tenant(request, "read")
    result = await _projection_service.today_digest(
        tenant_id=tenant.tenant_id,
        profile_user_id=profile_user_id,
    )
    return APIResponse(data=result)


@router.get("/profile")
async def get_profile_projection(request: Request, user_id: str = Query(...)) -> APIResponse:
    """Bounded, redacted profile-360 summary composed from the owning profile
    service — never re-calculated."""
    tenant = _tenant(request, "read")
    result = await _projection_service.profile_summary(
        tenant_id=tenant.tenant_id, user_id=user_id
    )
    if result is None:
        raise NotFoundError("profile summary not found")
    return APIResponse(data=result)


@router.get("/campaign")
async def get_campaign_projection(
    request: Request, campaign_id: str = Query(...)
) -> APIResponse:
    """Bounded, redacted campaign-360 summary composed from the owning campaign
    service — never re-calculated."""
    tenant = _tenant(request, "read")
    result = await _projection_service.campaign_summary(
        tenant_id=tenant.tenant_id, campaign_id=campaign_id
    )
    return APIResponse(data=result)


@router.get("/alerts")
async def get_alerts_projection(
    request: Request,
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    """Redacted alerts inbox — composed from the single canonical
    ``notification_inbox`` (never a second inbox)."""
    tenant = _tenant(request, "read")
    result = await _projection_service.alerts_inbox(
        tenant_id=tenant.tenant_id, unread_only=unread, limit=limit, offset=offset
    )
    return APIResponse(data=result)


@router.get("/briefing")
async def get_explore_briefing(
    request: Request,
    views_limit: int = Query(default=5, ge=1, le=50),
    conversations_limit: int = Query(default=5, ge=1, le=20),
) -> APIResponse:
    """Lightweight explore briefing — saved views (exploration store) + recent
    Noesis conversations, bounded and redacted."""
    tenant = _tenant(request, "read")
    result = await _projection_service.explore_briefing(
        tenant_id=tenant.tenant_id,
        views_limit=views_limit,
        conversations_limit=conversations_limit,
    )
    return APIResponse(data=result)
