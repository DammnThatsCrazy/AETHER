"""
Aether Service — Admin
Tenant management, billing, and API key management.
"""

from __future__ import annotations

import uuid
import hashlib
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, utc_now
from shared.logger.logger import get_logger
from repositories.repos import AdminRepository, APIKeyRepository

logger = get_logger("aether.service.admin")
router = APIRouter(prefix="/v1/admin", tags=["Admin"])

_repo = AdminRepository()
_key_repo = APIKeyRepository()


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
    request.state.tenant.require_permission("billing")
    return APIResponse(data={
        "tenant_id": tenant_id,
        "plan": "free",
        "current_period_usage": {"events": 0, "api_calls": 0, "ml_inferences": 0},
        "limits": {"events_per_month": 100000, "api_calls_per_month": 50000},
    }).to_dict()
