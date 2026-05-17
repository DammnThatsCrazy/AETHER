"""Governance routes — policy decision evaluation and audit endpoints for GovernanceDecision.

    POST  /v1/governance/decisions/evaluate   Evaluate a policy decision
    GET   /v1/governance/decisions            List decisions for a tenant
    GET   /v1/governance/decisions/{id}       Get a specific decision
    GET   /v1/governance/audit                Audit trail of decisions for a tenant
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics
from services.operational_intelligence.models import (
    EntityRef,
    EvidenceRef,
    ExplainabilityMetadata,
    InvestigationAnnotation,
    InvestigationCase,
    GovernanceDecision,
    EventPipelineEnvelope,
    TenantScopedRequest,
)

logger = get_logger("aether.service.governance")

router = APIRouter(prefix="/v1/governance", tags=["Governance"])

# ── In-memory store ───────────────────────────────────────────────────────────

_DECISIONS: dict[str, GovernanceDecision] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


def _get_decision(decision_id: str, tenant_id: str) -> GovernanceDecision:
    decision = _DECISIONS.get(decision_id)
    if decision is None or decision.tenantId != tenant_id:
        raise NotFoundError(f"GovernanceDecision {decision_id!r} not found")
    return decision


# ── Request models ────────────────────────────────────────────────────────────

class PolicyEvaluationRequest(TenantScopedRequest):
    principal: EntityRef
    action: str
    resource: EntityRef
    context: dict[str, Any] = Field(default_factory=dict)
    policyIds: list[str] = Field(default_factory=list)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/decisions/evaluate", response_model=GovernanceDecision)
async def evaluate_decision(
    body: PolicyEvaluationRequest,
    request: Request,
) -> GovernanceDecision:
    """Evaluate a policy decision for the given principal, action, and resource.

    MVP logic: allow all requests unless context contains {"deny": True}.
    The decision is stored for audit purposes and returned immediately.
    """
    _require(request, body.tenantId, "write")

    allowed = not bool(body.context.get("deny", False))

    policy_summary = (
        f"Policies evaluated: {', '.join(body.policyIds)}"
        if body.policyIds
        else "No explicit policies specified; default-allow applied."
    )
    explanation = ExplainabilityMetadata(
        summary=policy_summary,
        features=None,
        evidence=[],
        lineageEventIds=None,
        policyIds=body.policyIds or None,
    )

    decision = GovernanceDecision(
        id=str(uuid.uuid4()),
        tenantId=body.tenantId,
        principal=body.principal,
        action=body.action,
        resource=body.resource,
        allowed=allowed,
        policies=body.policyIds,
        obligations=None,
        explanation=explanation,
        evaluatedAt=_utc_now(),
    )
    _DECISIONS[decision.id] = decision
    logger.info(
        "governance_decision_evaluated",
        extra={
            "decision_id": decision.id,
            "allowed": allowed,
            "action": body.action,
            "tenant_id": body.tenantId,
        },
    )
    metrics.increment("governance_decision_evaluated")
    return decision


@router.get("/decisions", response_model=list[GovernanceDecision])
async def list_decisions(
    request: Request,
    tenantId: str = Query(...),
    principal_id: Optional[str] = Query(default=None),
    allowed: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[GovernanceDecision]:
    """List governance decisions for the authenticated tenant with optional filters."""
    _require(request, tenantId, "read")
    results = [
        d for d in _DECISIONS.values()
        if d.tenantId == tenantId
        and (principal_id is None or d.principal.id == principal_id)
        and (allowed is None or d.allowed == allowed)
    ]
    return results[:limit]


@router.get("/decisions/{decision_id}", response_model=GovernanceDecision)
async def get_decision(
    decision_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> GovernanceDecision:
    """Retrieve a specific governance decision by ID."""
    _require(request, tenantId, "read")
    return _get_decision(decision_id, tenantId)


@router.get("/audit", response_model=list[GovernanceDecision])
async def audit_trail(
    request: Request,
    tenantId: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: Optional[str] = Query(default=None),
) -> list[GovernanceDecision]:
    """Return the audit trail of governance decisions for the authenticated tenant."""
    _require(request, tenantId, "read")
    results = [
        d for d in _DECISIONS.values()
        if d.tenantId == tenantId
        and (principal_id is None or d.principal.id == principal_id)
    ]
    metrics.increment("governance_audit_read")
    return results[:limit]
