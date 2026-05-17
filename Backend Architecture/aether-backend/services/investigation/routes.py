"""Investigation routes — CRUD and status-transition endpoints for InvestigationCase.

    POST   /v1/investigations                          Create a new investigation case
    GET    /v1/investigations                          List cases for a tenant
    GET    /v1/investigations/{case_id}                Get a single case
    PATCH  /v1/investigations/{case_id}/status         Transition case status
    POST   /v1/investigations/{case_id}/evidence       Append evidence to a case
    POST   /v1/investigations/{case_id}/annotations    Add an annotation to a case
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

logger = get_logger("aether.service.investigation")

router = APIRouter(prefix="/v1/investigations", tags=["Investigations"])

# ── In-memory store ───────────────────────────────────────────────────────────

_STORE: dict[str, InvestigationCase] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


def _get_case(case_id: str, tenant_id: str) -> InvestigationCase:
    case = _STORE.get(case_id)
    if case is None or case.tenantId != tenant_id:
        raise NotFoundError(f"InvestigationCase {case_id!r} not found")
    return case


# ── Request models ────────────────────────────────────────────────────────────

class CreateCaseRequest(TenantScopedRequest):
    title: str
    subjects: list[EntityRef] = Field(default_factory=list)
    createdBy: str


class StatusTransitionRequest(BaseModel):
    tenantId: str
    status: Literal["open", "triage", "active", "escalated", "closed"]
    reason: Optional[str] = None


class AddEvidenceRequest(TenantScopedRequest):
    evidence: list[EvidenceRef]


class AddAnnotationRequest(TenantScopedRequest):
    body: str
    authorId: str
    entityRefs: list[EntityRef] = Field(default_factory=list)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=InvestigationCase)
async def create_case(
    body: CreateCaseRequest,
    request: Request,
) -> InvestigationCase:
    """Create a new investigation case with status 'open'."""
    _require(request, body.tenantId, "write")
    now = _utc_now()
    case = InvestigationCase(
        id=str(uuid.uuid4()),
        tenantId=body.tenantId,
        title=body.title,
        status="open",
        subjects=body.subjects,
        graphStateId=None,
        evidence=[],
        annotations=[],
        createdBy=body.createdBy,
        createdAt=now,
        updatedAt=now,
    )
    _STORE[case.id] = case
    logger.info("investigation_case_created", extra={"case_id": case.id, "tenant_id": case.tenantId})
    metrics.increment("investigation_case_created")
    return case


@router.get("", response_model=list[InvestigationCase])
async def list_cases(
    request: Request,
    tenantId: str = Query(...),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[InvestigationCase]:
    """List investigation cases for the authenticated tenant, optionally filtered by status."""
    _require(request, tenantId, "read")
    results = [
        c for c in _STORE.values()
        if c.tenantId == tenantId and (status is None or c.status == status)
    ]
    return results[:limit]


@router.get("/{case_id}", response_model=InvestigationCase)
async def get_case(
    case_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> InvestigationCase:
    """Retrieve a single investigation case by ID."""
    _require(request, tenantId, "read")
    return _get_case(case_id, tenantId)


@router.patch("/{case_id}/status", response_model=InvestigationCase)
async def transition_status(
    case_id: str,
    body: StatusTransitionRequest,
    request: Request,
) -> InvestigationCase:
    """Transition an investigation case to a new status (any → any for MVP)."""
    _require(request, body.tenantId, "write")
    case = _get_case(case_id, body.tenantId)
    previous = case.status
    case.status = body.status  # type: ignore[assignment]
    case.updatedAt = _utc_now()
    logger.info(
        "investigation_status_transitioned",
        extra={
            "case_id": case_id,
            "from": previous,
            "to": body.status,
            "reason": body.reason,
        },
    )
    metrics.increment("investigation_status_transitioned")
    return case


@router.post("/{case_id}/evidence", response_model=InvestigationCase)
async def add_evidence(
    case_id: str,
    body: AddEvidenceRequest,
    request: Request,
) -> InvestigationCase:
    """Append one or more EvidenceRef entries to an investigation case."""
    _require(request, body.tenantId, "write")
    case = _get_case(case_id, body.tenantId)
    case.evidence.extend(body.evidence)
    case.updatedAt = _utc_now()
    logger.info(
        "investigation_evidence_added",
        extra={"case_id": case_id, "count": len(body.evidence)},
    )
    metrics.increment("investigation_evidence_added")
    return case


@router.post("/{case_id}/annotations", response_model=InvestigationCase)
async def add_annotation(
    case_id: str,
    body: AddAnnotationRequest,
    request: Request,
) -> InvestigationCase:
    """Add a new annotation authored by the specified user to an investigation case."""
    _require(request, body.tenantId, "write")
    case = _get_case(case_id, body.tenantId)
    annotation = InvestigationAnnotation(
        id=str(uuid.uuid4()),
        authorId=body.authorId,
        body=body.body,
        entityRefs=body.entityRefs or None,
        evidenceRefs=body.evidenceRefs or None,
        createdAt=_utc_now(),
    )
    case.annotations.append(annotation)
    case.updatedAt = _utc_now()
    logger.info(
        "investigation_annotation_added",
        extra={"case_id": case_id, "annotation_id": annotation.id},
    )
    metrics.increment("investigation_annotation_added")
    return case
