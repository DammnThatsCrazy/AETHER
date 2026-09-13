"""Authenticated account-lifecycle routes.

This router is intentionally not mounted here. The orchestrator must mount it
after the existing auth middleware and route-policy registration are updated.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from services.account_lifecycle.service import account_lifecycle_service
from shared.common.common import APIResponse, ForbiddenError, UnauthorizedError

router = APIRouter(prefix="/v1/account-lifecycle", tags=["Account Lifecycle"])


class DeletionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=256)
    reauth_evidence: dict[str, Any]


class CancelRequest(BaseModel):
    reauth_evidence: dict[str, Any]


def _tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise UnauthorizedError("authentication required")
    tenant.require_permission("admin")
    return tenant


def _actor_id(tenant) -> str:
    return str(getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", ""))


@router.post("/deletion")
async def request_deletion(body: DeletionRequest, request: Request) -> dict:
    tenant = _tenant(request)
    result = await account_lifecycle_service.request_deletion(
        tenant_id=tenant.tenant_id,
        actor_id=_actor_id(tenant),
        idempotency_key=body.idempotency_key,
        reauth_evidence=body.reauth_evidence,
    )
    return APIResponse(data=result).to_dict()


@router.get("/deletion/{workflow_id}")
async def get_deletion_status(workflow_id: str, request: Request) -> dict:
    tenant = _tenant(request)
    result = await account_lifecycle_service.get_status(
        workflow_id, tenant_id=tenant.tenant_id
    )
    return APIResponse(data=result).to_dict()


@router.post("/deletion/{workflow_id}/cancel")
async def cancel_deletion(
    workflow_id: str, body: CancelRequest, request: Request
) -> dict:
    tenant = _tenant(request)
    result = await account_lifecycle_service.cancel_during_window(
        workflow_id,
        tenant_id=tenant.tenant_id,
        actor_id=_actor_id(tenant),
        reauth_evidence=body.reauth_evidence,
    )
    return APIResponse(data=result).to_dict()


@router.post("/deletion/{workflow_id}/process-retry")
async def process_retry(workflow_id: str, request: Request) -> dict:
    tenant = _tenant(request)
    result = await account_lifecycle_service.process_retry(
        workflow_id, tenant_id=tenant.tenant_id
    )
    return APIResponse(data=result).to_dict()
