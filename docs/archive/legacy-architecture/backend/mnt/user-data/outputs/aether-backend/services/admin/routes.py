"""
Aether Service — Admin
Tenant management, billing, and API key management.
Tech: Node.js (Fastify) + DynamoDB. Scaling: Low traffic, minimal.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from repositories.repos import AdminRepository
from shared.common.common import APIResponse, utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.admin")
router = APIRouter(prefix="/v1/admin", tags=["Admin"])

_repo = AdminRepository()


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


# Stub key store
_api_keys: dict[str, dict] = {}


# ── Tenant Management ─────────────────────────────────────────────────

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


# ── API Key Management ────────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/api-keys")
async def create_api_key(tenant_id: str, body: APIKeyCreate, request: Request):
    request.state.tenant.require_permission("admin")
    raw_key = f"ak_{uuid.uuid4().hex[:24]}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()

    _api_keys[hashed] = {
        "id": hashed[:12],
        "tenant_id": tenant_id,
        "name": body.name,
        "tier": body.tier,
        "permissions": body.permissions,
        "created_at": utc_now().isoformat(),
        "last_used_at": None,
    }

    return APIResponse(data={
        "api_key": raw_key,  # Only shown once
        "name": body.name,
        "tier": body.tier,
        "message": "Store this key securely — it will not be shown again.",
    }).to_dict()


@router.get("/tenants/{tenant_id}/api-keys")
async def list_api_keys(tenant_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    keys = [
        {k: v for k, v in key.items() if k != "api_key"}
        for key in _api_keys.values()
        if key["tenant_id"] == tenant_id
    ]
    return APIResponse(data=keys).to_dict()


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    _api_keys.pop(key_id, None)
    return APIResponse(data={"revoked": True}).to_dict()


# ── Billing (stub) ────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/billing")
async def get_billing(tenant_id: str, request: Request):
    request.state.tenant.require_permission("billing")
    return APIResponse(data={
        "tenant_id": tenant_id,
        "plan": "free",
        "current_period_usage": {"events": 0, "api_calls": 0, "ml_inferences": 0},
        "limits": {"events_per_month": 100000, "api_calls_per_month": 50000},
    }).to_dict()
