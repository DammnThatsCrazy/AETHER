"""Mobile gateway API — /v1/mobile (tenant / Aether).

Flag-gated via ``settings.mobile.enabled`` (default OFF → 404). Registers native
installations and their push subscriptions. Scope is ``t:{tenant_id}``; app_kind is
forced to ``aether`` (the operator plane gets its own gateway). Only the hash of a
push token is stored — never the raw token.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict

from config.settings import settings
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, NotFoundError

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


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    provider: str
    push_token: str
    environment: str


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
    )
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
