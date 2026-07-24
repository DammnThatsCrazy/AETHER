"""Agent Access Intelligence — capability catalog read APIs (PR 2, Phase A).

Tenant-scoped read surface over the maintained capability inventory
(``capability_catalog`` + ``capability_installations``), plus operator-only Kyber
aggregate views. The inventory lives under unclaimed prefixes
(``/v1/capability-catalog``, ``/v1/capability-installations``) because
``GET /v1/capabilities`` is already owned by ``services/capabilities/`` as a
release/feature-surface discovery endpoint (see the PR 2 source-of-truth doc §3).

Tenant handlers read ``request.state.tenant`` (a ``TenantContext``), call
``require_permission("read")`` and scope by ``tenant.tenant_id``. Kyber routes are
gated by ``Depends(require_kyber_operator)`` and read cross-tenant aggregates.
NotFoundError raised by the service is handled by the app's exception handlers.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from services.security.request_context import require_kyber_operator
from services.agent_access_intelligence.catalog_service import capability_catalog_service

logger = get_logger("aether.service.agent_access_intelligence.routes")

# ── Router setup ──────────────────────────────────────────────────────────────

catalog_router = APIRouter(
    prefix="/v1/capability-catalog",
    tags=["Agent Access Intelligence"],
)

installations_router = APIRouter(
    prefix="/v1/capability-installations",
    tags=["Agent Access Intelligence"],
)

kyber_router = APIRouter(
    prefix="/v1/kyber/capability-catalog",
    tags=["Kyber — Agent Access Intelligence"],
    dependencies=[Depends(require_kyber_operator)],
)


# ══════════════════════════════════════════════════════════════════════════════
# CAPABILITY CATALOG ROUTES (tenant-scoped)
# ══════════════════════════════════════════════════════════════════════════════

@catalog_router.get("")
async def list_capabilities(
    request: Request,
    provider: Optional[str] = Query(default=None),
    server_name: Optional[str] = Query(default=None),
    tool_name: Optional[str] = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List observed capabilities for the authenticated tenant, with optional filters."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await capability_catalog_service.list_capabilities(
        tenant_id,
        provider=provider,
        server_name=server_name,
        tool_name=tool_name,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@catalog_router.get("/overview")
async def catalog_overview(request: Request):
    """Summary of the tenant's capability inventory (counts by kind / provider)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    return APIResponse(data=await capability_catalog_service.catalog_overview(tenant_id)).to_dict()


@catalog_router.get("/{capability_id}")
async def get_capability(capability_id: str, request: Request):
    """Detail for a single capability (fail-closed — NotFound on tenant mismatch)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    return APIResponse(
        data=await capability_catalog_service.get_capability(tenant_id, capability_id)
    ).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# CAPABILITY INSTALLATION ROUTES (tenant-scoped)
# ══════════════════════════════════════════════════════════════════════════════

@installations_router.get("")
async def list_installations(
    request: Request,
    agent_id: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List agent↔server installations for the authenticated tenant, with optional filters."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await capability_catalog_service.list_installations(
        tenant_id,
        agent_id=agent_id,
        provider=provider,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@installations_router.get("/{installation_id}")
async def get_installation(installation_id: str, request: Request):
    """Detail for a single installation (fail-closed — NotFound on tenant mismatch)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    return APIResponse(
        data=await capability_catalog_service.get_installation(tenant_id, installation_id)
    ).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# KYBER OPERATOR ROUTES (cross-tenant aggregate; operator-gated)
# ══════════════════════════════════════════════════════════════════════════════

@kyber_router.get("/health")
async def catalog_health(request: Request):
    """Cross-tenant capability catalog health aggregate (operator-only)."""
    return APIResponse(data=await capability_catalog_service.catalog_health()).to_dict()


@kyber_router.get("/shadow")
async def catalog_shadow(request: Request):
    """Unattributed capabilities — honest Phase-A shadow precursor (operator-only)."""
    return APIResponse(data=await capability_catalog_service.catalog_unattributed()).to_dict()
