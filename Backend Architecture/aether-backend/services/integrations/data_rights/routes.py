"""
Aether — Data Rights Ledger Routes

Tenant-scoped and operator routes for data rights grant management.

Routes:
    GET    /v1/integrations/data-rights              List tenant's grants
    POST   /v1/integrations/data-rights/grants       Create grant
    GET    /v1/integrations/data-rights/grants/{id}  Get grant detail
    POST   /v1/integrations/data-rights/grants/{id}/revoke  Revoke grant
    POST   /v1/integrations/data-rights/policy-check  Evaluate policy check
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.integrations.data_rights.models import (
    DataRightsGrantCreate,
    DataRightsGrantRevoke,
    GrantStatus,
    PolicyCheckRequest,
)
from services.integrations.data_rights.service import data_rights_service

logger = get_logger("aether.service.data_rights.routes")

router = APIRouter(
    prefix="/v1/integrations/data-rights",
    tags=["Integrations — Data Rights"],
)

admin_router = APIRouter(
    prefix="/v1/admin/kyber/data-rights",
    tags=["Admin — Kyber Data Rights"],
)


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


def _actor(request: Request) -> str:
    t = getattr(request.state, "tenant", None)
    return getattr(t, "user_id", None) or getattr(t, "tenant_id", None) or "system"


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


# ══════════════════════════════════════════════════════════════════════════════
# TENANT ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("")
async def list_data_rights(
    request: Request,
    connector_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """List the tenant's data rights grants."""
    tenant_id = _tenant_id(request)

    status_enum = None
    if status:
        try:
            status_enum = GrantStatus(status)
        except ValueError:
            pass

    grants = await data_rights_service.list_grants(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status=status_enum,
    )
    return APIResponse(data={
        "items": [g.model_dump() for g in grants],
        "count": len(grants),
    }).to_dict()


@router.post("/grants")
async def create_grant(body: DataRightsGrantCreate, request: Request):
    """Create a new data rights grant.

    Fail-closed: all permissions default False unless explicitly set.
    BYOK credential does NOT imply lake ingestion or training rights.
    """
    tenant_id = _tenant_id(request, "admin")

    if body.tenant_id != tenant_id:
        raise ForbiddenError("Cannot create grants for other tenants")

    actor = _actor(request)
    grant = await data_rights_service.create_grant(body, granted_by_user_id=actor)

    return APIResponse(data=grant.model_dump()).to_dict()


@router.get("/grants/{grant_id}")
async def get_grant(grant_id: str, request: Request):
    """Get full detail for a data rights grant."""
    tenant_id = _tenant_id(request)
    grant = await data_rights_service.get_grant(grant_id)

    if not grant:
        raise NotFoundError("grant")
    if grant.tenant_id != tenant_id:
        raise ForbiddenError("Access denied to this grant")

    return APIResponse(data=grant.model_dump()).to_dict()


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(grant_id: str, body: DataRightsGrantRevoke, request: Request):
    """Revoke a data rights grant. All data use is denied immediately."""
    tenant_id = _tenant_id(request, "admin")
    grant = await data_rights_service.get_grant(grant_id)

    if not grant:
        raise NotFoundError("grant")
    if grant.tenant_id != tenant_id:
        raise ForbiddenError("Access denied to this grant")

    updated = await data_rights_service.revoke_grant(grant_id, body)
    return APIResponse(data=updated.model_dump()).to_dict()


@router.post("/policy-check")
async def policy_check(body: PolicyCheckRequest, request: Request):
    """Evaluate a specific policy check on a grant (fail-closed)."""
    tenant_id = _tenant_id(request)
    grant = await data_rights_service.get_grant(body.grant_id)

    if not grant:
        raise NotFoundError("grant")
    if grant.tenant_id != tenant_id:
        raise ForbiddenError("Access denied to this grant")

    result = await data_rights_service.check_policy(body.grant_id, body.check_type)
    return APIResponse(data=result.model_dump()).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN / KYBER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@admin_router.get("")
async def admin_list_grants(
    request: Request,
    tenant_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """Operator view: list all data rights grants across tenants."""
    _require_operator(request)

    status_enum = None
    if status:
        try:
            status_enum = GrantStatus(status)
        except ValueError:
            pass

    grants = await data_rights_service.list_grants(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status=status_enum,
    )
    return APIResponse(data={
        "items": [g.model_dump() for g in grants],
        "count": len(grants),
    }).to_dict()


@admin_router.post("/grants/{grant_id}/revoke")
async def admin_revoke_grant(grant_id: str, body: DataRightsGrantRevoke, request: Request):
    """Operator: force-revoke any grant (e.g., compliance enforcement)."""
    _require_operator(request)

    grant = await data_rights_service.get_grant(grant_id)
    if not grant:
        raise NotFoundError("grant")

    updated = await data_rights_service.revoke_grant(grant_id, body)
    return APIResponse(data=updated.model_dump()).to_dict()
