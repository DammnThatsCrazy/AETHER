"""Tenant Command Center API route.

Tenant surface (authenticated via standard API-key middleware, so the tenant is
read from ``request.state.tenant`` — never from the body):

    GET  /v1/command-center    Read-only aggregated Command Center view

Read requires ``read`` permission. The endpoint is a pure composition of
existing tenant-scoped reads; it performs no writes and exposes no
operator-only fields.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from shared.auth.auth import Permissions
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .service import CommandCenterService

logger = get_logger("aether.command_center.routes")

router = APIRouter(prefix="/v1/command-center", tags=["Command Center"])

_service = CommandCenterService()


@router.get("")
async def command_center(request: Request) -> dict:
    """Return the tenant's aggregated, read-only Command Center view."""
    tenant = request.state.tenant
    tenant.require_permission(Permissions.READ)
    data = await _service.get_view(tenant.tenant_id, request)
    return APIResponse(data=data).to_dict()
