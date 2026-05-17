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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
from repositories.repos import InvestigationRepository

logger = get_logger("aether.service.investigation")

router = APIRouter(prefix="/v1/investigations", tags=["Investigations"])

_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "open":      frozenset({"triage", "active", "escalated", "closed"}),
    "triage":    frozenset({"active", "escalated", "closed"}),
    "active":    frozenset({"escalated", "closed"}),
    "escalated": frozenset({"closed"}),
    "closed":    frozenset(),
}

_repo = InvestigationRepository()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(request: Request, tenant_id: str, permission: str = "read") -> None:
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


async def _get_case(case_id: str, tenant_id: str) -> dict:
    row = await _repo.find_by_id(case_id)
    if row is None or row.get("tenantId") != tenant_id:
        raise NotFoundError(f"InvestigationCase {case_id!r} not found")
    return row


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
    producer: EventProducer = Depends(get_producer),
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
    case_dict = case.model_dump()
    case_dict["tenant_id"] = case.tenantId  # repo filter key
    result = await _repo.create(case_dict)
    logger.info("investigation_case_created", extra={"case_id": case.id, "tenant_id": case.tenantId})
    metrics.increment("investigation_case_created")
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_CREATED,
        tenant_id=case.tenantId,
        payload={"case_id": case.id, "title": case.title, "status": case.status},
    ))
    return InvestigationCase(**result)


@router.get("", response_model=list[InvestigationCase])
async def list_cases(
    request: Request,
    tenantId: str = Query(...),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[InvestigationCase]:
    """List investigation cases for the authenticated tenant, optionally filtered by status."""
    _require(request, tenantId, "read")
    rows = await _repo.list_by_tenant(tenantId, status=status, limit=limit)
    return [InvestigationCase(**r) for r in rows]


@router.get("/{case_id}", response_model=InvestigationCase)
async def get_case(
    case_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> InvestigationCase:
    """Retrieve a single investigation case by ID."""
    _require(request, tenantId, "read")
    row = await _get_case(case_id, tenantId)
    return InvestigationCase(**row)


@router.patch("/{case_id}/status", response_model=InvestigationCase)
async def transition_status(
    case_id: str,
    body: StatusTransitionRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> InvestigationCase:
    """Transition an investigation case status using the enforced state machine."""
    _require(request, body.tenantId, "write")
    row = await _get_case(case_id, body.tenantId)
    previous = row.get("status")
    if body.status not in _VALID_TRANSITIONS.get(previous or "open", frozenset()):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status transition: {previous!r} → {body.status!r}",
        )
    updated = await _repo.update(case_id, {"status": body.status, "updatedAt": _utc_now()})
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
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_STATUS_CHANGED,
        tenant_id=body.tenantId,
        payload={"case_id": case_id, "from": previous, "to": body.status},
    ))
    return InvestigationCase(**updated)


@router.post("/{case_id}/evidence", response_model=InvestigationCase)
async def add_evidence(
    case_id: str,
    body: AddEvidenceRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> InvestigationCase:
    """Append one or more EvidenceRef entries to an investigation case."""
    _require(request, body.tenantId, "write")
    row = await _get_case(case_id, body.tenantId)
    existing_evidence = row.get("evidence") or []
    new_evidence = existing_evidence + [e.model_dump() for e in body.evidence]
    updated = await _repo.update(case_id, {"evidence": new_evidence, "updatedAt": _utc_now()})
    logger.info(
        "investigation_evidence_added",
        extra={"case_id": case_id, "count": len(body.evidence)},
    )
    metrics.increment("investigation_evidence_added")
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_UPDATED,
        tenant_id=body.tenantId,
        payload={"case_id": case_id, "update": "evidence_added", "count": len(body.evidence)},
    ))
    return InvestigationCase(**updated)


@router.post("/{case_id}/annotations", response_model=InvestigationCase)
async def add_annotation(
    case_id: str,
    body: AddAnnotationRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> InvestigationCase:
    """Add a new annotation authored by the specified user to an investigation case."""
    _require(request, body.tenantId, "write")
    row = await _get_case(case_id, body.tenantId)
    annotation = InvestigationAnnotation(
        id=str(uuid.uuid4()),
        authorId=body.authorId,
        body=body.body,
        entityRefs=body.entityRefs or None,
        evidenceRefs=body.evidenceRefs or None,
        createdAt=_utc_now(),
    )
    existing_annotations = row.get("annotations") or []
    new_annotations = existing_annotations + [annotation.model_dump()]
    updated = await _repo.update(case_id, {"annotations": new_annotations, "updatedAt": _utc_now()})
    logger.info(
        "investigation_annotation_added",
        extra={"case_id": case_id, "annotation_id": annotation.id},
    )
    metrics.increment("investigation_annotation_added")
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_UPDATED,
        tenant_id=body.tenantId,
        payload={"case_id": case_id, "update": "annotation_added", "annotation_id": annotation.id},
    ))
    return InvestigationCase(**updated)
