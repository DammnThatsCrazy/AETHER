"""
Aether — Approval Service Routes (L3b+).

All approval lifecycle endpoints: queue, assign, decide, escalate,
revoke, replay, evidence, and graph impact preview.

Mounted at /v1/approvals by the app factory.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

from .approvals import ApprovalService, ApprovalStatus

logger = get_logger("aether.service.x402.approvals_routes")
router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

_approvals = ApprovalService()


# ── Request Models ────────────────────────────────────────────────────────────

class DecideRequest(BaseModel):
    action: str            # "approve" | "reject" | "escalate"
    reason: str
    notes: Optional[str] = None
    override: bool = False


class AssignRequest(BaseModel):
    assignee_id: str
    assignee_type: str = "user"


class EscalateRequest(BaseModel):
    escalate_to: str
    reason: Optional[str] = None


class RevokeRequest(BaseModel):
    reason: str


class ReplayRequest(BaseModel):
    context_overrides: Optional[dict[str, Any]] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_approvals(
    request: Request,
    status: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List approval queue with optional filters."""
    request.state.tenant.require_permission("approvals:read")
    tenant_id = request.state.tenant.tenant_id

    status_enum = ApprovalStatus(status) if status else None
    items = await _approvals.list_queue(
        tenant_id=tenant_id,
        status=status_enum,
        assigned_to=assigned_to,
    )
    page = items[offset: offset + limit]
    return APIResponse(data=[a.model_dump() for a in page]).to_dict()


@router.get("/{approval_id}")
async def get_approval(approval_id: str, request: Request):
    """Get approval detail."""
    request.state.tenant.require_permission("approvals:read")
    tenant_id = request.state.tenant.tenant_id
    record = await _approvals.get(tenant_id, approval_id)
    if record is None:
        raise NotFoundError("approval")
    return APIResponse(data=record.model_dump()).to_dict()


@router.post("/{approval_id}/assign")
async def assign_approval(
    approval_id: str,
    body: AssignRequest,
    request: Request,
):
    """Assign an approval to an approver."""
    request.state.tenant.require_permission("approvals:write")
    tenant_id = request.state.tenant.tenant_id
    actor_id = getattr(request.state.tenant, "user_id", None) or "system"
    record = await _approvals.assign(
        tenant_id=tenant_id,
        approval_id=approval_id,
        assignee_id=body.assignee_id,
        assigned_by=actor_id,
    )
    return APIResponse(data=record.model_dump()).to_dict()


@router.post("/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    body: DecideRequest,
    request: Request,
):
    """Submit a decision: approve | reject | escalate."""
    request.state.tenant.require_any_permission("approvals:write", "commerce:approve")
    if body.override:
        request.state.tenant.require_permission("commerce:admin")
    tenant_id = request.state.tenant.tenant_id
    actor_id = getattr(request.state.tenant, "user_id", None) or "system"
    record = await _approvals.decide(
        tenant_id=tenant_id,
        approval_id=approval_id,
        action=body.action,
        decided_by=actor_id,
        reason=body.reason,
        is_override=body.override,
    )
    return APIResponse(data=record.model_dump()).to_dict()


@router.post("/{approval_id}/escalate")
async def escalate_approval(
    approval_id: str,
    body: EscalateRequest,
    request: Request,
):
    """Escalate by submitting an 'escalate' decision action."""
    request.state.tenant.require_permission("approvals:write")
    tenant_id = request.state.tenant.tenant_id
    actor_id = getattr(request.state.tenant, "user_id", None) or "system"
    record = await _approvals.decide(
        tenant_id=tenant_id,
        approval_id=approval_id,
        action="escalate",
        decided_by=actor_id,
        reason=body.reason or f"escalated to {body.escalate_to}",
    )
    return APIResponse(data=record.model_dump()).to_dict()


@router.post("/{approval_id}/revoke")
async def revoke_approval(
    approval_id: str,
    body: RevokeRequest,
    request: Request,
):
    """Revoke a previously approved request."""
    request.state.tenant.require_permission("approvals:write")
    tenant_id = request.state.tenant.tenant_id
    actor_id = getattr(request.state.tenant, "user_id", None) or "system"
    record = await _approvals.revoke(
        tenant_id=tenant_id,
        approval_id=approval_id,
        revoked_by=actor_id,
        reason=body.reason,
    )
    return APIResponse(data=record.model_dump()).to_dict()


@router.post("/{approval_id}/replay")
async def replay_approval(
    approval_id: str,
    body: ReplayRequest,
    request: Request,
):
    """Deterministic Lab replay — re-evaluates policies without mutating state."""
    request.state.tenant.require_permission("approvals:read")
    tenant_id = request.state.tenant.tenant_id
    record = await _approvals.get(tenant_id, approval_id)
    if record is None:
        raise NotFoundError("approval")
    # Replay returns the approval with context_overrides applied (read-only)
    evidence = await _approvals.evidence_bundle(tenant_id, approval_id)
    return APIResponse(data={
        "approval": record.model_dump(),
        "evidence": evidence,
        "context_overrides": body.context_overrides or {},
        "replay_mode": True,
    }).to_dict()


@router.get("/{approval_id}/evidence")
async def get_approval_evidence(approval_id: str, request: Request):
    """Retrieve the full evidence bundle."""
    request.state.tenant.require_permission("approvals:read")
    tenant_id = request.state.tenant.tenant_id
    evidence = await _approvals.evidence_bundle(tenant_id, approval_id)
    return APIResponse(data=evidence).to_dict()


@router.get("/{approval_id}/preview")
async def get_graph_impact_preview(approval_id: str, request: Request):
    """Preview which graph vertices/edges will be written if approved."""
    request.state.tenant.require_permission("approvals:read")
    tenant_id = request.state.tenant.tenant_id
    record = await _approvals.get(tenant_id, approval_id)
    if record is None:
        raise NotFoundError("approval")
    # Returns a deterministic description of expected graph mutations
    preview = {
        "approval_id": approval_id,
        "challenge_id": record.challenge_id,
        "expected_vertices": [
            {"type": "PaymentAuthorization", "id": f"{tenant_id}:auth:{approval_id}"},
            {"type": "ApprovalDecision", "id": f"{tenant_id}:decision:{approval_id}"},
        ],
        "expected_edges": [
            {"type": "AUTHORIZED_BY", "from": f"{tenant_id}:req:{record.challenge_id}",
             "to": f"{tenant_id}:auth:{approval_id}"},
            {"type": "APPROVED_BY", "from": f"{tenant_id}:decision:{approval_id}",
             "to": f"{tenant_id}:user:{record.assigned_to or 'unknown'}"},
        ],
        "note": "preview only — no graph mutations until decision is submitted",
    }
    return APIResponse(data=preview).to_dict()
