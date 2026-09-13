"""Tenant-facing Security & Governance routes.

All endpoints are strictly scoped to the calling tenant. No cross-tenant data and
no Olympus operator internals are ever exposed here.

    GET  /v1/security/me/permissions
    GET  /v1/security/audit-events
    GET  /v1/security/policies
    GET  /v1/security/data-retention
    POST /v1/security/data-requests
    GET  /v1/security/data-requests
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .access_control import access_control
from .audit_ledger import audit_ledger
from .contracts import DataRequestType, sanitize_metadata
from .policy_engine import policy_engine
from .repositories import SecurityAuditEventRepository
from .request_context import tenant_actor
from .retention import data_retention_service

logger = get_logger("aether.security.routes")
router = APIRouter(prefix="/v1/security", tags=["Security & Governance"])

_audit_repo = SecurityAuditEventRepository()

# Fields safe to expose to tenants (no integrity chain internals, no IP of others).
_TENANT_AUDIT_FIELDS = (
    "audit_event_id", "tenant_id", "event_type", "resource_type", "resource_id",
    "action", "outcome", "policy_decision_id", "created_at",
)


def _safe_audit(row: dict) -> dict:
    out = {k: row.get(k) for k in _TENANT_AUDIT_FIELDS}
    out["metadata"] = sanitize_metadata(row.get("metadata") or {})
    return out


@router.get("/me/permissions")
async def my_permissions(request: Request) -> dict:
    actor = tenant_actor(request)
    grants = access_control.grants_for_roles(actor.roles)
    return APIResponse(data={
        "actor_id": actor.actor_id,
        "tenant_id": actor.tenant_id,
        "roles": actor.roles,
        "permissions": [g.model_dump() for g in grants],
    }).to_dict()


@router.get("/audit-events")
async def my_audit_events(request: Request, limit: int = Query(50, le=200)) -> dict:
    actor = tenant_actor(request)
    rows = await _audit_repo.latest_for_tenant(actor.tenant_id, limit=limit)
    return APIResponse(data={
        "tenant_id": actor.tenant_id,
        "items": [_safe_audit(r) for r in rows],
        "count": len(rows),
    }).to_dict()


@router.get("/policies")
async def my_policy_decisions(request: Request, limit: int = Query(50, le=200)) -> dict:
    actor = tenant_actor(request)
    rows = await policy_engine.list_decisions(actor.tenant_id, limit=limit)
    return APIResponse(data={"tenant_id": actor.tenant_id, "items": rows, "count": len(rows)}).to_dict()


@router.get("/data-retention")
async def my_retention_policies(request: Request) -> dict:
    actor = tenant_actor(request)
    policies = await data_retention_service.list_policies(actor.tenant_id)
    return APIResponse(data={"tenant_id": actor.tenant_id, "items": policies, "count": len(policies)}).to_dict()


class DataRequestBody(BaseModel):
    request_type: DataRequestType
    target_resource_type: Optional[str] = None
    target_resource_id: Optional[str] = None
    legal_hold_note: Optional[str] = None


@router.post("/data-requests")
async def create_data_request(body: DataRequestBody, request: Request) -> dict:
    actor = tenant_actor(request)
    req = await data_retention_service.create_request(
        tenant_id=actor.tenant_id, request_type=body.request_type,
        requested_by=actor.actor_id, actor_type='tenant_user',
        target_resource_type=body.target_resource_type,
        target_resource_id=body.target_resource_id,
        legal_hold_note=body.legal_hold_note,
    )
    return APIResponse(data=req.model_dump()).to_dict()


@router.get("/data-requests")
async def list_data_requests(request: Request, limit: int = Query(50, le=200)) -> dict:
    actor = tenant_actor(request)
    rows = await data_retention_service.list_requests(actor.tenant_id, limit=limit)
    return APIResponse(data={"tenant_id": actor.tenant_id, "items": rows, "count": len(rows)}).to_dict()
