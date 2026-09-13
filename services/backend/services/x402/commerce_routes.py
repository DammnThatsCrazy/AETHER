"""
Aether Service — Commerce Control Plane Routes
Production routes for the full x402 v2 lifecycle and approval workflow.

All routes require a valid `request.state.tenant` (TenantContext) and
explicit permission checks. Responses use the standard APIResponse envelope.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from .approvals import get_approval_service
from .commerce_models import (
    ApprovalPriority,
    ApprovalStatus,
    ProtectedResource,
)
from .commerce_store import get_commerce_store
from .control_plane import ControlPlaneError, get_control_plane
from .entitlements import get_entitlement_service
from .facilitators import (
    get_asset_registry,
    get_facilitator_registry,
    seed_facilitators_and_assets,
)
from .policies import get_policy_engine
from .pricing import PricingEngine
from .resources import (
    get_resource_registry,
    seed_aether_native_resources,
)

logger = get_logger("aether.service.x402.commerce_routes")
router = APIRouter(prefix="/v1/x402", tags=["x402-commerce"])


def _tenant_id(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    return tenant.tenant_id


def _require_perm(request: Request, perm: str) -> None:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    # Support both require_permission() and has_permission() patterns
    if hasattr(tenant, "require_permission"):
        try:
            tenant.require_permission(perm)
            return
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
    if hasattr(tenant, "has_permission") and not tenant.has_permission(perm):
        raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")


# ─── Request bodies ────────────────────────────────────────────────────

class ChallengeRequest(BaseModel):
    resource_id: str
    requester_id: str
    requester_type: str = "agent"
    chain: str = "eip155:8453"
    asset_symbol: str = "USDC"
    recipient: Optional[str] = None


class ApprovalDecisionBody(BaseModel):
    action: str  # approve|reject|escalate
    decided_by: str
    reason: str
    is_override: bool = False


class ApprovalAssignBody(BaseModel):
    assignee_id: str
    assigned_by: str


class ApprovalRevokeBody(BaseModel):
    revoked_by: str
    reason: str


class AuthorizeBody(BaseModel):
    approval_id: str
    payer: str


class VerifyBody(BaseModel):
    authorization_id: str
    tx_hash: str


class GrantAccessBody(BaseModel):
    entitlement_id: str
    request_url: str = ""
    request_method: str = "GET"


class RequestApprovalBody(BaseModel):
    challenge_id: str
    priority: str = "normal"
    reason: str = ""
    context: dict[str, Any] = {}


class ResourceCreateBody(BaseModel):
    resource: ProtectedResource


class PreflightBody(BaseModel):
    holder_id: str
    resource_id: str


class PolicySimulateBody(BaseModel):
    resource_id: str
    requester_id: str
    amount_usd: float
    asset_symbol: str = "USDC"
    chain: str = "eip155:8453"


# ─── Preflight ─────────────────────────────────────────────────────────

@router.post("/access/preflight")
async def preflight(body: PreflightBody, request: Request):
    _require_perm(request, "x402:read")
    plane = get_control_plane()
    result = await plane.preflight(_tenant_id(request), body.holder_id, body.resource_id)
    return APIResponse(data=result.model_dump()).to_dict()


# ─── Challenge / lifecycle ─────────────────────────────────────────────

@router.post("/challenge")
async def issue_challenge(body: ChallengeRequest, request: Request):
    _require_perm(request, "commerce:challenge")
    plane = get_control_plane()
    try:
        req = await plane.issue_challenge(
            tenant_id=_tenant_id(request),
            resource_id=body.resource_id,
            requester_id=body.requester_id,
            requester_type=body.requester_type,
            chain=body.chain,
            asset_symbol=body.asset_symbol,
            recipient=body.recipient,
        )
        return APIResponse(data=req.model_dump()).to_dict()
    except ControlPlaneError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)})


@router.post("/approval/request")
async def request_approval(body: RequestApprovalBody, request: Request):
    _require_perm(request, "commerce:challenge")
    plane = get_control_plane()
    try:
        priority = ApprovalPriority(body.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {body.priority}")
    try:
        approval, decision = await plane.request_approval(
            tenant_id=_tenant_id(request),
            challenge_id=body.challenge_id,
            priority=priority,
            reason=body.reason,
            context=body.context,
        )
        return APIResponse(
            data={"approval": approval.model_dump(), "policy_decision": decision.model_dump()}
        ).to_dict()
    except ControlPlaneError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)})


@router.post("/authorize")
async def authorize_payment(body: AuthorizeBody, request: Request):
    _require_perm(request, "commerce:settle")
    plane = get_control_plane()
    try:
        auth = await plane.authorize_payment(
            _tenant_id(request), body.approval_id, body.payer
        )
        return APIResponse(data=auth.model_dump()).to_dict()
    except ControlPlaneError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)})


@router.post("/verify")
async def verify_and_settle(body: VerifyBody, request: Request):
    _require_perm(request, "commerce:verify")
    plane = get_control_plane()
    try:
        result = await plane.verify_and_settle(
            _tenant_id(request), body.authorization_id, body.tx_hash
        )
        return APIResponse(data=result).to_dict()
    except ControlPlaneError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)})


@router.post("/access/grant")
async def grant_access(body: GrantAccessBody, request: Request):
    _require_perm(request, "entitlements:write")
    plane = get_control_plane()
    try:
        result = await plane.grant_access(
            _tenant_id(request),
            body.entitlement_id,
            body.request_url,
            body.request_method,
        )
        return APIResponse(data=result).to_dict()
    except ControlPlaneError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": str(e)})


# ─── Explainability ────────────────────────────────────────────────────

@router.get("/explain/{challenge_id}")
async def explain_challenge(challenge_id: str, request: Request):
    _require_perm(request, "x402:read")
    plane = get_control_plane()
    trace = await plane.explain(_tenant_id(request), challenge_id)
    return APIResponse(data=trace.model_dump()).to_dict()


# ─── Resources ─────────────────────────────────────────────────────────

@router.get("/resources")
async def list_resources(request: Request):
    _require_perm(request, "x402:read")
    registry = get_resource_registry()
    resources = await registry.list(_tenant_id(request), active_only=True)
    return APIResponse(data=[r.model_dump() for r in resources]).to_dict()


@router.post("/resources")
async def create_resource(body: ResourceCreateBody, request: Request):
    _require_perm(request, "resources:admin")
    registry = get_resource_registry()
    body.resource.tenant_id = _tenant_id(request)
    result = await registry.register(body.resource)
    return APIResponse(data=result.model_dump()).to_dict()


@router.post("/resources/seed")
async def seed_resources(request: Request):
    """Seed all Aether-native protected resources (Day-1 GA)."""
    _require_perm(request, "resources:admin")
    tid = _tenant_id(request)
    resources = await seed_aether_native_resources(tid)
    await seed_facilitators_and_assets(tid)
    return APIResponse(
        data={"resources": len(resources), "tenant_id": tid}
    ).to_dict()


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: str, request: Request):
    _require_perm(request, "x402:read")
    registry = get_resource_registry()
    resource = await registry.get(_tenant_id(request), resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return APIResponse(data=resource.model_dump()).to_dict()


# ─── Facilitators / Assets ─────────────────────────────────────────────

@router.get("/facilitators")
async def list_facilitators(request: Request):
    _require_perm(request, "x402:read")
    registry = get_facilitator_registry()
    items = await registry.list(_tenant_id(request))
    return APIResponse(data=[f.model_dump() for f in items]).to_dict()


@router.get("/assets")
async def list_assets(request: Request):
    _require_perm(request, "x402:read")
    registry = get_asset_registry()
    items = await registry.list(_tenant_id(request))
    return APIResponse(data=[a.model_dump() for a in items]).to_dict()


# ─── Policies ──────────────────────────────────────────────────────────

@router.post("/policies/simulate")
async def simulate_policy(body: PolicySimulateBody, request: Request):
    _require_perm(request, "commerce:policy")
    resources = get_resource_registry()
    resource = await resources.get(_tenant_id(request), body.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    engine = get_policy_engine()
    decision = await engine.simulate(
        _tenant_id(request),
        resource,
        body.requester_id,
        body.amount_usd,
        body.asset_symbol,
        body.chain,
    )
    return APIResponse(data=decision.model_dump()).to_dict()


@router.get("/pricing/{resource_id}")
async def quote_price(resource_id: str, request: Request, plan: Optional[str] = None):
    _require_perm(request, "x402:read")
    engine = PricingEngine()
    try:
        quote = await engine.resolve_price(_tenant_id(request), resource_id, plan_code=plan)
        return APIResponse(data=quote).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Budget Policies ────────────────────────────────────────────────────

class _BudgetPolicyCreate(BaseModel):
    subject_id: str
    subject_type: str = "agent"
    daily_cap_usd: float = 100.0
    monthly_cap_usd: float = 1000.0
    per_transaction_cap_usd: float = 50.0


@router.post("/policies/budget")
async def create_budget_policy(body: _BudgetPolicyCreate, request: Request):
    """Create or replace a spending budget policy for an agent or user."""
    _require_perm(request, "x402:write")
    from .commerce_models import BudgetPolicy
    store = get_commerce_store()
    policy = BudgetPolicy(
        tenant_id=_tenant_id(request),
        subject_id=body.subject_id,
        subject_type=body.subject_type,
        daily_cap_usd=body.daily_cap_usd,
        monthly_cap_usd=body.monthly_cap_usd,
        per_transaction_cap_usd=body.per_transaction_cap_usd,
    )
    result = await store.put_budget_policy(policy)
    return APIResponse(data=result.model_dump()).to_dict()


@router.get("/policies/budget")
async def list_budget_policies(request: Request):
    """List all active budget policies for the authenticated tenant."""
    _require_perm(request, "x402:read")
    store = get_commerce_store()
    policies = await store.list_budget_policies(_tenant_id(request))
    return APIResponse(data=[p.model_dump() for p in policies]).to_dict()


@router.get("/policies/budget/{subject_id}")
async def get_budget_policy(subject_id: str, request: Request):
    """Get the active budget policy for a specific agent or user."""
    _require_perm(request, "x402:read")
    store = get_commerce_store()
    policy = await store.get_budget_policy(_tenant_id(request), subject_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"No budget policy for subject {subject_id!r}")
    return APIResponse(data=policy.model_dump()).to_dict()


# ─── Approvals ─────────────────────────────────────────────────────────

approvals_router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


@approvals_router.get("")
async def list_approvals(
    request: Request, status: Optional[str] = None, assigned_to: Optional[str] = None
):
    _require_perm(request, "approvals:read")
    service = get_approval_service()
    status_enum = ApprovalStatus(status) if status else None
    items = await service.list_queue(_tenant_id(request), status=status_enum, assigned_to=assigned_to)
    return APIResponse(data=[a.model_dump() for a in items]).to_dict()


@approvals_router.get("/{approval_id}")
async def get_approval(approval_id: str, request: Request):
    _require_perm(request, "approvals:read")
    service = get_approval_service()
    approval = await service.get(_tenant_id(request), approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return APIResponse(data=approval.model_dump()).to_dict()


@approvals_router.post("/{approval_id}/assign")
async def assign_approval(approval_id: str, body: ApprovalAssignBody, request: Request):
    _require_perm(request, "approvals:write")
    service = get_approval_service()
    try:
        result = await service.assign(
            _tenant_id(request), approval_id, body.assignee_id, body.assigned_by
        )
        return APIResponse(data=result.model_dump()).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@approvals_router.post("/{approval_id}/decide")
async def decide_approval(approval_id: str, body: ApprovalDecisionBody, request: Request):
    _require_perm(request, "commerce:approve")
    plane = get_control_plane()
    try:
        result = await plane.apply_decision(
            tenant_id=_tenant_id(request),
            approval_id=approval_id,
            action=body.action,
            decided_by=body.decided_by,
            reason=body.reason,
            is_override=body.is_override,
        )
        return APIResponse(data=result.model_dump()).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@approvals_router.post("/{approval_id}/revoke")
async def revoke_approval(approval_id: str, body: ApprovalRevokeBody, request: Request):
    _require_perm(request, "approvals:write")
    service = get_approval_service()
    try:
        result = await service.revoke(
            _tenant_id(request), approval_id, body.revoked_by, body.reason
        )
        return APIResponse(data=result.model_dump()).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@approvals_router.get("/{approval_id}/evidence")
async def evidence_bundle(approval_id: str, request: Request):
    _require_perm(request, "approvals:read")
    service = get_approval_service()
    try:
        bundle = await service.evidence_bundle(_tenant_id(request), approval_id)
        return APIResponse(data=bundle).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@approvals_router.post("/{approval_id}/replay")
async def replay_approval(approval_id: str, request: Request):
    """Deterministic replay — does not mutate production state."""
    _require_perm(request, "approvals:read")
    service = get_approval_service()
    approval = await service.get(_tenant_id(request), approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    # Replay evaluates policy again and returns what would be decided
    resources = get_resource_registry()
    resource = await resources.get(_tenant_id(request), approval.resource_id)
    engine = get_policy_engine()
    decision = await engine.simulate(
        _tenant_id(request),
        resource,
        approval.requester_id,
        approval.amount_usd,
        approval.asset_symbol,
        approval.chain,
    ) if resource else None
    return APIResponse(
        data={
            "approval": approval.model_dump(),
            "replay_decision": decision.model_dump() if decision else None,
            "mode": "deterministic",
        }
    ).to_dict()


@approvals_router.post("/{approval_id}/escalate")
async def escalate_approval(approval_id: str, request: Request):
    """Escalate an approval to a higher authority."""
    _require_perm(request, "approvals:write")
    service = get_approval_service()
    body = await request.json()
    escalate_to = body.get("escalate_to", "")
    reason = body.get("reason", f"escalated to {escalate_to}")
    actor_id = getattr(request.state.tenant, "user_id", None) or "system"
    try:
        result = await service.decide(
            tenant_id=_tenant_id(request),
            approval_id=approval_id,
            action="escalate",
            decided_by=actor_id,
            reason=reason,
        )
        return APIResponse(data=result.model_dump()).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@approvals_router.get("/{approval_id}/preview")
async def graph_impact_preview(approval_id: str, request: Request):
    """Preview which graph vertices/edges will be written if approved."""
    _require_perm(request, "approvals:read")
    service = get_approval_service()
    approval = await service.get(_tenant_id(request), approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    tenant_id = _tenant_id(request)
    preview = {
        "approval_id": approval_id,
        "challenge_id": approval.challenge_id,
        "expected_vertices": [
            {"type": "PaymentAuthorization", "id": f"{tenant_id}:auth:{approval_id}"},
            {"type": "ApprovalDecision", "id": f"{tenant_id}:decision:{approval_id}"},
        ],
        "expected_edges": [
            {
                "type": "AUTHORIZED_BY",
                "from": f"{tenant_id}:req:{approval.challenge_id}",
                "to": f"{tenant_id}:auth:{approval_id}",
            },
            {
                "type": "APPROVED_BY",
                "from": f"{tenant_id}:decision:{approval_id}",
                "to": f"{tenant_id}:user:{approval.assigned_to or 'unknown'}",
            },
        ],
        "note": "preview only — no graph mutations until decision is submitted",
    }
    return APIResponse(data=preview).to_dict()


# ─── Entitlements ──────────────────────────────────────────────────────

entitlements_router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])


@entitlements_router.get("")
async def list_entitlements(
    request: Request, holder_id: Optional[str] = None, active_only: bool = True
):
    _require_perm(request, "entitlements:read")
    service = get_entitlement_service()
    if holder_id:
        items = await service.list_for_holder(_tenant_id(request), holder_id, active_only)
    else:
        items = []
    return APIResponse(data=[e.model_dump() for e in items]).to_dict()


@entitlements_router.get("/{entitlement_id}")
async def get_entitlement(entitlement_id: str, request: Request):
    _require_perm(request, "entitlements:read")
    store = get_commerce_store()
    e = await store.get_entitlement(_tenant_id(request), entitlement_id)
    if not e:
        raise HTTPException(status_code=404, detail="Entitlement not found")
    return APIResponse(data=e.model_dump()).to_dict()


@entitlements_router.post("/{entitlement_id}/revoke")
async def revoke_entitlement(entitlement_id: str, request: Request, reason: str = "", revoked_by: str = "system"):
    _require_perm(request, "entitlements:write")
    service = get_entitlement_service()
    try:
        result = await service.revoke(_tenant_id(request), entitlement_id, revoked_by, reason)
        return APIResponse(data=result.model_dump()).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Diagnostics ───────────────────────────────────────────────────────

diagnostics_router = APIRouter(prefix="/v1/diagnostics/commerce", tags=["commerce-diagnostics"])


@diagnostics_router.get("/health")
async def commerce_health(request: Request):
    _require_perm(request, "x402:read")
    store = get_commerce_store()
    tid = _tenant_id(request)
    approvals = await store.list_approvals(tid)
    settlements = await store.list_settlements(tid)

    # Evidence-based health: derived from real facilitator health, settlement
    # backlog, and verification outcomes — never a hardcoded True.
    from .commerce_models import SettlementState

    facilitators = await get_facilitator_registry().list(tid)
    fac_down = [f for f in facilitators if f.health_status == "down"]
    fac_degraded = [f for f in facilitators if f.health_status == "degraded"]
    pending_settlements = sum(1 for s in settlements if s.state == SettlementState.PENDING)
    failed_settlements = sum(1 for s in settlements if s.state == SettlementState.FAILED)

    # Health degradation is driven by RECENT failures only — a settlement store
    # retains history, so counting all-time failures would pin the endpoint to
    # `degraded` forever after a single historical invalid payment, even once
    # facilitators and every later payment have recovered. The lifetime count is
    # still reported separately below.
    from datetime import timedelta

    from shared.common.common import utc_now
    from shared.temporal.instant import try_parse_instant

    _HEALTH_FAILURE_WINDOW_SECONDS = 3600
    _cutoff = utc_now() - timedelta(seconds=_HEALTH_FAILURE_WINDOW_SECONDS)
    recent_failed = 0
    for s in settlements:
        if s.state != SettlementState.FAILED:
            continue
        _ts, _ = try_parse_instant(
            str(getattr(s, "updated_at", "") or getattr(s, "settled_at", "") or "")
        )
        if _ts is not None and _ts >= _cutoff:
            recent_failed += 1

    # No usable facilitator, or every facilitator down → unhealthy; a RECENT
    # failed settlement or all-degraded facilitators → degraded; else healthy.
    if not facilitators or len(fac_down) == len(facilitators):
        status = "unhealthy"
    elif recent_failed or (fac_degraded and not any(
        f.health_status == "healthy" for f in facilitators
    )):
        status = "degraded"
    else:
        status = "healthy"

    return APIResponse(
        data={
            "approvals": {
                "total": len(approvals),
                "pending": sum(1 for a in approvals if a.status == ApprovalStatus.PENDING),
                "assigned": sum(1 for a in approvals if a.status == ApprovalStatus.ASSIGNED),
                "approved": sum(1 for a in approvals if a.status == ApprovalStatus.APPROVED),
                "rejected": sum(1 for a in approvals if a.status == ApprovalStatus.REJECTED),
                "expired": sum(1 for a in approvals if a.status == ApprovalStatus.EXPIRED),
            },
            "settlements": {
                "total": len(settlements),
                "pending": pending_settlements,
                "failed": failed_settlements,          # lifetime
                "recent_failed": recent_failed,        # within the health window
            },
            "facilitators": {
                "total": len(facilitators),
                "down": len(fac_down),
                "degraded": len(fac_degraded),
            },
            "status": status,
            # honest boolean derived from status, not asserted
            "healthy": status == "healthy",
        }
    ).to_dict()


@diagnostics_router.get("/stuck-approvals")
async def stuck_approvals(request: Request):
    _require_perm(request, "x402:read")
    service = get_approval_service()
    tid = _tenant_id(request)
    count = await service.sweep_expired(tid)
    expired = await service.list_queue(tid, status=ApprovalStatus.EXPIRED)
    return APIResponse(data={"swept": count, "expired": [a.model_dump() for a in expired]}).to_dict()
