"""
Aether Backend — Provider Gateway Admin API Routes

BYOK key management, usage monitoring, health checks, and provider testing.

Routes:
    POST   /v1/providers/keys                Store BYOK key (encrypted at rest)
    GET    /v1/providers/keys                List tenant's BYOK keys (masked)
    DELETE /v1/providers/keys/{provider}     Delete BYOK key
    GET    /v1/providers/usage               Usage stats (filterable)
    GET    /v1/providers/usage/summary       Tenant usage summary
    GET    /v1/providers/health              All providers + circuit breaker states
    GET    /v1/providers/categories          List categories + supported providers
    POST   /v1/providers/test                Test a provider call
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.providers.models import (
    ProviderKeyCreate,
    ProviderKeyResponse,
    ProviderRouteRequest,
)
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics


class ProviderKeyRotate(BaseModel):
    new_api_key: str
    endpoint: Optional[str] = None

logger = get_logger("aether.service.providers")

router = APIRouter(prefix="/v1/providers", tags=["providers"])


# ── Helpers ────────────────────────────────────────────────────────────

def _get_gateway(request: Request):
    """Retrieve the ProviderGateway from app state."""
    return request.app.state.provider_gateway


# ══════════════════════════════════════════════════════════════════════
# KEY MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

@router.post("/keys")
@api_response
async def store_key(body: ProviderKeyCreate, request: Request):
    """Store or update an encrypted BYOK API key.

    Deprecated for financial providers: this generic single-key API predates the
    durable, multi-slot credential authority. New payment/stablecoin integrations
    should use the slot-aware API under ``/v1/providers/credentials`` instead.
    """
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    await gateway.key_vault.store_key(
        tenant_id=tenant_id,
        provider_name=body.provider_name,
        category=body.category,
        api_key=body.api_key,
        endpoint=body.endpoint or "",
    )

    metrics.increment("provider_key_stored", labels={
        "tenant_id": tenant_id, "provider": body.provider_name,
    })
    logger.info(f"BYOK key stored: tenant={tenant_id} provider={body.provider_name}")

    return {"status": "stored", "provider_name": body.provider_name}


@router.get("/keys")
@api_response
async def list_keys(request: Request):
    """List tenant's stored BYOK keys (masked)."""
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    # BYOKKeyVault.list_keys returns list[dict] (never StoredKey objects); the
    # masked identifier is derived separately and never exposes key bytes.
    keys = await gateway.key_vault.list_keys(tenant_id)
    result = []
    for sk in keys:
        provider_name = sk["provider_name"]
        result.append(ProviderKeyResponse(
            provider_name=provider_name,
            masked_key=gateway.key_vault.masked_identifier(tenant_id, provider_name),
            endpoint=sk.get("endpoint") or None,
            enabled=bool(sk.get("enabled", True)),
            stored_at=sk.get("created_at") or sk.get("updated_at") or "",
        ).model_dump())

    return result


@router.delete("/keys/{provider}")
@api_response
async def delete_key(provider: str, request: Request):
    """Remove a tenant's BYOK key for a provider."""
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    deleted = await gateway.key_vault.delete_key(tenant_id, provider)
    if not deleted:
        return {"status": "not_found", "provider_name": provider}

    metrics.increment("provider_key_deleted", labels={
        "tenant_id": tenant_id, "provider": provider,
    })
    logger.info(f"BYOK key deleted: tenant={tenant_id} provider={provider}")
    return {"status": "deleted", "provider_name": provider}


@router.post("/keys/{provider}/rotate")
@api_response
async def rotate_key(provider: str, body: ProviderKeyRotate, request: Request):
    """Rotate a BYOK key — replace the encrypted key without losing audit trail.

    Note: BYOK rotation does NOT affect lake/graph/training data rights.
    Data rights grants are separate from credential control.
    """
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    rotated = await gateway.key_vault.rotate_key(
        tenant_id=tenant_id,
        provider_name=provider,
        new_api_key=body.new_api_key,
        endpoint=body.endpoint,
    )
    if not rotated:
        return {"status": "not_found", "provider_name": provider}

    metrics.increment("provider_key_rotated", labels={
        "tenant_id": tenant_id, "provider": provider,
    })
    logger.info(f"BYOK key rotated: tenant={tenant_id} provider={provider}")
    return {
        "status": "rotated",
        "provider_name": provider,
        "updated_at": rotated.updated_at,
    }


@router.post("/keys/{provider}/revoke")
@api_response
async def revoke_key(provider: str, request: Request):
    """Revoke a BYOK key — disable it without deleting the audit record.

    The key is retained for audit. Use DELETE /keys/{provider} to fully purge.
    Note: BYOK revocation does NOT affect data rights grants — revoke those separately.
    """
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    revoked = await gateway.key_vault.revoke_key(tenant_id, provider)
    if not revoked:
        return {"status": "not_found", "provider_name": provider}

    metrics.increment("provider_key_revoked", labels={
        "tenant_id": tenant_id, "provider": provider,
    })
    logger.info(f"BYOK key revoked: tenant={tenant_id} provider={provider}")
    return {"status": "revoked", "provider_name": provider}


@router.post("/keys/{provider}/verify")
@api_response
async def verify_key(provider: str, request: Request):
    """Verify a BYOK key is stored and active — without exposing the key value.

    Returns safe metadata only: exists, active, created_at, updated_at.
    Does NOT test liveness against the external provider — use /test for that.
    """
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    return await gateway.key_vault.verify_key(tenant_id, provider)


# ══════════════════════════════════════════════════════════════════════
# USAGE
# ══════════════════════════════════════════════════════════════════════

@router.get("/usage")
@api_response
async def get_usage(request: Request, category: str = None, provider_name: str = None):
    """Usage statistics for the tenant's provider calls."""
    request.state.tenant.require_permission("billing")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    return await gateway.meter.get_usage(
        tenant_id=tenant_id,
        category=category,
        provider_name=provider_name,
    )


@router.get("/usage/summary")
@api_response
async def get_usage_summary(request: Request):
    """Summarised usage across all providers for the tenant."""
    request.state.tenant.require_permission("billing")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    return await gateway.meter.get_tenant_summary(tenant_id)


# ══════════════════════════════════════════════════════════════════════
# HEALTH & DISCOVERY
# ══════════════════════════════════════════════════════════════════════

@router.get("/health")
@api_response
async def provider_health(request: Request):
    """Health status for all providers with circuit breaker states and freshness labels."""
    from datetime import datetime, timezone

    def _staleness(last_sync: str | None) -> str:
        if not last_sync:
            return "stale"
        try:
            last = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last).total_seconds() / 60
            return "live" if age < 5 else "recent" if age < 30 else "stale"
        except (ValueError, TypeError):
            return "stale"

    request.state.tenant.require_permission("admin")
    gateway = _get_gateway(request)
    raw = await gateway.router.health()

    # Enrich each provider entry with freshness metadata
    entries = raw if isinstance(raw, list) else raw.get("providers", raw.get("data", {}).get("providers", []))
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                last_sync = entry.get("last_sync") or entry.get("last_successful_sync")
                entry.setdefault("last_successful_sync", last_sync)
                entry.setdefault("error_count", 0)
                entry["staleness_label"] = _staleness(last_sync)
        return entries
    return raw


@router.get("/categories")
@api_response
async def list_categories(request: Request):
    """List all provider categories and their supported provider names."""
    gateway = _get_gateway(request)
    return gateway.registry.get_categories()


# ══════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════

@router.post("/test")
@api_response
async def test_provider(body: ProviderRouteRequest, request: Request):
    """
    Test a provider call (verify BYOK key works).
    Routes through the gateway exactly as a real call would.
    """
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    from shared.providers.categories import ProviderCategory

    try:
        category = ProviderCategory(body.category)
    except ValueError:
        return {"success": False, "error": f"Unknown category: {body.category}"}

    result = await gateway.route(
        category=category,
        method=body.method,
        params=body.params,
        tenant_id=tenant_id,
        preferred_provider=body.preferred_provider,
    )
    return result.to_dict()
