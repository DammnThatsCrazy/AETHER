"""
Aether Service — Customer Self-Service API Keys

Allows authenticated tenants to manage their own API keys without needing
admin privileges. All operations are scoped to request.state.tenant.tenant_id.

Endpoints:
    GET    /v1/me/api-keys          List caller's API keys (keys masked)
    POST   /v1/me/api-keys          Create a new API key
    PATCH  /v1/me/api-keys/{id}     Rename a key
    DELETE /v1/me/api-keys/{id}     Revoke a key
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics
from repositories.repos import APIKeyRepository

logger = get_logger("aether.service.me")
router = APIRouter(prefix="/v1/me", tags=["Me — API Keys"])

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


@router.get("/api-keys")
async def list_my_api_keys(request: Request):
    """List all API keys for the calling tenant."""
    tenant = _require_tenant(request)
    keys = await _key_repo.find_many(filters={"tenant_id": tenant.tenant_id})
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "api_keys": [_safe_key(k) for k in keys],
        "count": len(keys),
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
