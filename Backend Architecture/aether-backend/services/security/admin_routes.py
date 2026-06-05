"""Kyber admin Security & Governance routes.

Operator-facing governance control plane. Every endpoint requires the existing
admin permission gate AND routes through the governance services (which emit
audit events). Tenant-specific endpoints return aggregates or governed records.

    GET   /v1/admin/kyber/security/overview
    GET   /v1/admin/kyber/security/audit-events
    GET   /v1/admin/kyber/security/policy-decisions
    GET   /v1/admin/kyber/security/tenant-isolation
    GET   /v1/admin/kyber/security/operator-access
    GET   /v1/admin/kyber/security/data-retention
    POST  /v1/admin/kyber/security/data-retention/policies
    PATCH /v1/admin/kyber/security/data-retention/policies/{policy_id}
    GET   /v1/admin/kyber/security/data-requests
    PATCH /v1/admin/kyber/security/data-requests/{data_request_id}
    GET   /v1/admin/kyber/security/governance-evidence-packs
    POST  /v1/admin/kyber/security/governance-evidence-packs/generate
    POST  /v1/admin/kyber/security/break-glass/request
    POST  /v1/admin/kyber/security/break-glass/{request_id}/approve
    POST  /v1/admin/kyber/security/break-glass/{request_id}/deny
    POST  /v1/admin/kyber/security/break-glass/{request_id}/revoke
    GET   /v1/admin/kyber/security/break-glass
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .access_control import ROLE_GRANTS, ROLE_SPECS
from .break_glass import break_glass_service
from .contracts import (
    DataRequestStatus,
    EvidencePackType,
    RetentionDeleteBehavior,
    RetentionResourceType,
)
from .evidence_packs import evidence_pack_service
from .isolation_verifier import tenant_isolation_verifier
from .policy_engine import policy_engine
from .repositories import SecurityAuditEventRepository
from .request_context import require_kyber_operator
from .retention import data_retention_service

logger = get_logger("aether.security.admin_routes")
admin_router = APIRouter(prefix="/v1/admin/kyber/security", tags=["Admin — Kyber Security & Governance"])

_audit_repo = SecurityAuditEventRepository()


def _require_admin(request: Request):
    # Read-tier gate: fail-closed Olympus-operator check. No Aether tenant — even
    # one holding the legacy "admin" permission — may access these routes.
    return require_kyber_operator(request)


def _require_privileged(request: Request):
    # Mutation-tier gate: operator AND admin. A read-only `kyber:operator` token
    # must not be able to edit retention policies, process data requests, or
    # approve/deny/revoke break-glass grants.
    actor = require_kyber_operator(request)
    request.state.tenant.require_permission("admin")
    return actor


@admin_router.get("/overview")
async def overview(request: Request) -> dict:
    _require_admin(request)
    events = await _audit_repo.list_all(limit=5000)
    decisions = await policy_engine.list_decisions(limit=2000)
    blocked = [d for d in decisions if not d.get("allowed")]
    isolation = await tenant_isolation_verifier.latest()
    break_glass = await break_glass_service.list_requests(limit=500)
    data = {
        "audit_events_total": len(events),
        "audit_events_by_outcome": dict(Counter(e.get("outcome") for e in events)),
        "policy_decisions_total": len(decisions),
        "policy_blocks_total": len(blocked),
        "active_break_glass": len([b for b in break_glass if b.get("status") == "approved"]),
        "tenant_isolation_status": (isolation or {}).get("overall_status", "unknown"),
        "roles_configured": len(ROLE_SPECS),
        "not_certified": True,
        "disclaimer": "Security-review evidence only; no compliance certification is claimed.",
    }
    return APIResponse(data=data).to_dict()


@admin_router.get("/audit-events")
async def audit_events(
    request: Request, tenant_id: Optional[str] = None, limit: int = Query(100, le=500),
) -> dict:
    _require_admin(request)
    rows = (
        await _audit_repo.list_for_tenant(tenant_id, limit=limit) if tenant_id
        else await _audit_repo.list_all(limit=limit)
    )
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@admin_router.get("/policy-decisions")
async def policy_decisions(
    request: Request, tenant_id: Optional[str] = None, limit: int = Query(100, le=500),
) -> dict:
    _require_admin(request)
    rows = await policy_engine.list_decisions(tenant_id, limit=limit)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@admin_router.get("/tenant-isolation")
async def tenant_isolation(request: Request, run: bool = False) -> dict:
    actor = _require_admin(request)
    result = await tenant_isolation_verifier.run(actor.actor_id) if run else (
        await tenant_isolation_verifier.latest() or await tenant_isolation_verifier.run(actor.actor_id)
    )
    return APIResponse(data=result).to_dict()


@admin_router.get("/operator-access")
async def operator_access(request: Request) -> dict:
    _require_admin(request)
    roles = {
        role: [g.model_dump() for g in ROLE_GRANTS.get(role, [])]
        for role in ROLE_SPECS if role.startswith("olympus_") or role == "auditor"
    }
    break_glass = await break_glass_service.list_requests(limit=500)
    return APIResponse(data={
        "operator_roles": roles,
        "break_glass_requests": break_glass,
        "active_grants": [b for b in break_glass if b.get("status") == "approved"],
    }).to_dict()


@admin_router.get("/data-retention")
async def data_retention(request: Request, tenant_id: Optional[str] = None) -> dict:
    _require_admin(request)
    policies = await data_retention_service.list_policies(tenant_id)
    return APIResponse(data={"items": policies, "count": len(policies)}).to_dict()


class RetentionPolicyBody(BaseModel):
    tenant_id: Optional[str] = None
    resource_type: RetentionResourceType
    retention_days: int = 365
    delete_behavior: RetentionDeleteBehavior = 'soft_delete'
    legal_hold_supported: bool = True
    enabled: bool = True


@admin_router.post("/data-retention/policies")
async def create_retention_policy(body: RetentionPolicyBody, request: Request) -> dict:
    actor = _require_privileged(request)
    pol = await data_retention_service.create_policy(
        tenant_id=body.tenant_id, resource_type=body.resource_type,
        retention_days=body.retention_days, delete_behavior=body.delete_behavior,
        legal_hold_supported=body.legal_hold_supported, enabled=body.enabled,
        actor_id=actor.actor_id,
    )
    return APIResponse(data=pol.model_dump()).to_dict()


class RetentionPolicyUpdate(BaseModel):
    retention_days: Optional[int] = None
    delete_behavior: Optional[RetentionDeleteBehavior] = None
    legal_hold_supported: Optional[bool] = None
    enabled: Optional[bool] = None


@admin_router.patch("/data-retention/policies/{policy_id}")
async def update_retention_policy(policy_id: str, body: RetentionPolicyUpdate, request: Request) -> dict:
    actor = _require_privileged(request)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    row = await data_retention_service.update_policy(policy_id, updates, actor_id=actor.actor_id)
    return APIResponse(data=row).to_dict()


@admin_router.get("/data-requests")
async def data_requests(
    request: Request, tenant_id: Optional[str] = None, limit: int = Query(100, le=500),
) -> dict:
    _require_admin(request)
    rows = await data_retention_service.list_requests(tenant_id, limit=limit)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


class DataRequestUpdate(BaseModel):
    status: DataRequestStatus
    result_summary: str = ""


@admin_router.patch("/data-requests/{data_request_id}")
async def process_data_request(data_request_id: str, body: DataRequestUpdate, request: Request) -> dict:
    actor = _require_privileged(request)
    row = await data_retention_service.process_request(
        data_request_id, status=body.status, result_summary=body.result_summary,
        actor_id=actor.actor_id,
    )
    return APIResponse(data=row).to_dict()


@admin_router.get("/governance-evidence-packs")
async def list_evidence_packs(
    request: Request, tenant_id: Optional[str] = None, limit: int = Query(100, le=500),
) -> dict:
    _require_admin(request)
    rows = await evidence_pack_service.list_packs(tenant_id, limit=limit)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


class EvidencePackBody(BaseModel):
    pack_type: EvidencePackType
    tenant_id: Optional[str] = None


@admin_router.post("/governance-evidence-packs/generate")
async def generate_evidence_pack(body: EvidencePackBody, request: Request) -> dict:
    actor = _require_privileged(request)
    pack = await evidence_pack_service.generate(
        pack_type=body.pack_type, requested_by=actor.actor_id, tenant_id=body.tenant_id,
    )
    return APIResponse(data=pack.model_dump()).to_dict()


# ── Break-glass ─────────────────────────────────────────────────────────────

class BreakGlassBody(BaseModel):
    tenant_id: str
    reason: str
    requested_scope: str = "read"
    window_hours: int = 4


@admin_router.post("/break-glass/request")
async def break_glass_request(body: BreakGlassBody, request: Request) -> dict:
    actor = _require_privileged(request)
    req = await break_glass_service.request(
        tenant_id=body.tenant_id, requested_by=actor.actor_id, reason=body.reason,
        requested_scope=body.requested_scope, window_hours=body.window_hours,
    )
    return APIResponse(data=req.model_dump()).to_dict()


@admin_router.post("/break-glass/{request_id}/approve")
async def break_glass_approve(request_id: str, request: Request) -> dict:
    actor = _require_privileged(request)
    req = await break_glass_service.approve(request_id=request_id, approved_by=actor.actor_id)
    return APIResponse(data=req.model_dump()).to_dict()


class DenyBody(BaseModel):
    reason: str = ""


@admin_router.post("/break-glass/{request_id}/deny")
async def break_glass_deny(request_id: str, body: DenyBody, request: Request) -> dict:
    actor = _require_privileged(request)
    req = await break_glass_service.deny(request_id=request_id, approved_by=actor.actor_id, reason=body.reason)
    return APIResponse(data=req.model_dump()).to_dict()


@admin_router.post("/break-glass/{request_id}/revoke")
async def break_glass_revoke(request_id: str, request: Request) -> dict:
    actor = _require_privileged(request)
    req = await break_glass_service.revoke(request_id=request_id, revoked_by=actor.actor_id)
    return APIResponse(data=req.model_dump()).to_dict()


@admin_router.get("/break-glass")
async def break_glass_list(request: Request, tenant_id: Optional[str] = None) -> dict:
    _require_admin(request)
    rows = await break_glass_service.list_requests(tenant_id, limit=500)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()
