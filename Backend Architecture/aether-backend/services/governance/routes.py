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
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_producer
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
from repositories.repos import GovernanceRepository

logger = get_logger("aether.service.governance")

router = APIRouter(prefix="/v1/governance", tags=["Governance"])

_repo = GovernanceRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


async def _get_decision(decision_id: str, tenant_id: str) -> dict:
    row = await _repo.find_by_id(decision_id)
    if row is None or row.get("tenantId") != tenant_id:
        raise NotFoundError(f"GovernanceDecision {decision_id!r} not found")
    return row


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
    producer: EventProducer = Depends(get_producer),
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
    decision_dict = decision.model_dump()
    decision_dict["tenant_id"] = decision.tenantId  # repo filter key
    decision_dict["principal_id"] = body.principal.id  # flat key for list_by_tenant filter
    result = await _repo.create(decision_dict)
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
    await producer.publish(Event(
        topic=Topic.GOVERNANCE_DECISION_EVALUATED,
        tenant_id=body.tenantId,
        payload={"decision_id": decision.id, "allowed": allowed, "action": body.action},
    ))
    return GovernanceDecision(**result)


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
    rows = await _repo.list_by_tenant(tenantId, principal_id=principal_id, allowed=allowed, limit=limit)
    return [GovernanceDecision(**r) for r in rows]


@router.get("/decisions/{decision_id}", response_model=GovernanceDecision)
async def get_decision(
    decision_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> GovernanceDecision:
    """Retrieve a specific governance decision by ID."""
    _require(request, tenantId, "read")
    row = await _get_decision(decision_id, tenantId)
    return GovernanceDecision(**row)


@router.get("/audit", response_model=list[GovernanceDecision])
async def audit_trail(
    request: Request,
    tenantId: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: Optional[str] = Query(default=None),
) -> list[GovernanceDecision]:
    """Return the audit trail of governance decisions for the authenticated tenant."""
    _require(request, tenantId, "read")
    rows = await _repo.list_by_tenant(tenantId, principal_id=principal_id, limit=limit)
    metrics.increment("governance_audit_read")
    return [GovernanceDecision(**r) for r in rows]
