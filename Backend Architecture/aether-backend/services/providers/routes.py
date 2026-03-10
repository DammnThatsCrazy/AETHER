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

from fastapi import APIRouter, Request

from services.providers.models import (
    ProviderKeyCreate,
    ProviderKeyResponse,
    ProviderRouteRequest,
    UsageQuery,
)
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics

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
    """Store or update an encrypted BYOK API key."""
    request.state.tenant.require_permission("admin")
    tenant_id = request.state.tenant.tenant_id
    gateway = _get_gateway(request)

    await gateway.key_vault.store_key(
        tenant_id=tenant_id,
        provider_name=body.provider_name,
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

    keys = await gateway.key_vault.list_keys(tenant_id)
    result = []
    for sk in keys:
        result.append(ProviderKeyResponse(
            provider_name=sk.provider_name,
            masked_key=sk.masked_key,
            endpoint=sk.endpoint or None,
            enabled=sk.enabled,
            stored_at=sk.stored_at,
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
    """Health status for all providers with circuit breaker states."""
    request.state.tenant.require_permission("admin")
    gateway = _get_gateway(request)

    return await gateway.router.health()


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
