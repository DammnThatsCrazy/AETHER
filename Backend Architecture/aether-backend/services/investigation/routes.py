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
from repositories.repos import (
    FlowTraceRepository,
    FraudNetworkRepository,
    InvestigationRepository,
)
# Capability-family metering seam (§7): durable meter + evidence for
# reconciliation at the investigations family choke point.
from services.metering_evidence.families import meter_family_usage  # noqa: E402

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
_fraud_network_repo = FraudNetworkRepository()
_flow_trace_repo = FlowTraceRepository()


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
    # Family seam: durable meter + evidence (advisory — no entitlement gate).
    await meter_family_usage(
        "investigations", case.tenantId, event_id=case.id,
        enforce=False, raise_on_metering_error=False,
    )
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


# ── Fraud intelligence integration request models ─────────────────────────────

class AttachFraudNetworkRequest(TenantScopedRequest):
    network_id: str


class AttachFlowTraceRequest(TenantScopedRequest):
    trace_id: str


class SetGraphStateRequest(TenantScopedRequest):
    overlay_snapshot_id: str


@router.post("/{case_id}/fraud-network", response_model=InvestigationCase)
async def attach_fraud_network(
    case_id: str,
    body: AttachFraudNetworkRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> InvestigationCase:
    """Attach a fraud network to an investigation case, adding its evidence refs."""
    _require(request, body.tenantId, "write")
    row = await _get_case(case_id, body.tenantId)

    network = await _fraud_network_repo.get(body.network_id)
    if network is None or network.get("tenant_id") != body.tenantId:
        raise NotFoundError(f"FraudNetwork {body.network_id!r} not found")

    network_evidence = network.get("evidence_refs", [])
    existing_evidence = row.get("evidence") or []
    new_evidence = existing_evidence + network_evidence

    # Deduplicate by id
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for e in new_evidence:
        eid = e.get("id")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            deduped.append(e)

    # Store network_id in graphStateId if not already set
    update_fields: dict = {"evidence": deduped, "updatedAt": _utc_now()}
    if not row.get("graphStateId"):
        update_fields["graphStateId"] = body.network_id

    updated = await _repo.update(case_id, update_fields)
    logger.info("investigation_fraud_network_attached", extra={"case_id": case_id, "network_id": body.network_id})
    metrics.increment("investigation_fraud_network_attached")
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_UPDATED,
        tenant_id=body.tenantId,
        payload={"case_id": case_id, "update": "fraud_network_attached", "network_id": body.network_id},
    ))
    return InvestigationCase(**updated)


@router.post("/{case_id}/flow-trace", response_model=InvestigationCase)
async def attach_flow_trace(
    case_id: str,
    body: AttachFlowTraceRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> InvestigationCase:
    """Attach a flow trace to an investigation case, adding a transaction evidence ref."""
    _require(request, body.tenantId, "write")
    row = await _get_case(case_id, body.tenantId)

    trace = await _flow_trace_repo.get(body.trace_id)
    if trace is None or trace.get("tenant_id") != body.tenantId:
        raise NotFoundError(f"FlowTrace {body.trace_id!r} not found")

    trace_evidence_ref = EvidenceRef(
        id=str(uuid.uuid4()),
        type="transaction",
        source="aether.flow_trace",
        observedAt=trace.get("completed_at") or trace.get("created_at", ""),
        confidence=min(trace.get("risk_score", 0.0) / 100.0, 1.0),
        uri=f"aether://flow-trace/{body.trace_id}",
    )
    existing_evidence = row.get("evidence") or []
    new_evidence = existing_evidence + [trace_evidence_ref.model_dump()]
    updated = await _repo.update(case_id, {"evidence": new_evidence, "updatedAt": _utc_now()})
    logger.info("investigation_flow_trace_attached", extra={"case_id": case_id, "trace_id": body.trace_id})
    metrics.increment("investigation_flow_trace_attached")
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_UPDATED,
        tenant_id=body.tenantId,
        payload={"case_id": case_id, "update": "flow_trace_attached", "trace_id": body.trace_id},
    ))
    return InvestigationCase(**updated)


@router.post("/{case_id}/graph-state", response_model=InvestigationCase)
async def set_graph_state(
    case_id: str,
    body: SetGraphStateRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> InvestigationCase:
    """Store a risk overlay snapshot ID as the case's current graph state."""
    _require(request, body.tenantId, "write")
    await _get_case(case_id, body.tenantId)
    updated = await _repo.update(case_id, {
        "graphStateId": body.overlay_snapshot_id,
        "updatedAt": _utc_now(),
    })
    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_UPDATED,
        tenant_id=body.tenantId,
        payload={"case_id": case_id, "update": "graph_state_set", "overlay_id": body.overlay_snapshot_id},
    ))
    return InvestigationCase(**updated)


@router.get("/{case_id}/fraud-summary", response_model=None)
async def get_fraud_summary(
    case_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> dict:
    """Aggregate fraud networks + flow traces linked to this investigation case."""
    _require(request, tenantId, "read")
    row = await _get_case(case_id, tenantId)

    # Look up the linked fraud network via graphStateId
    network_data: dict | None = None
    graph_state_id = row.get("graphStateId")
    if graph_state_id:
        network = await _fraud_network_repo.get(graph_state_id)
        if network and network.get("tenant_id") == tenantId:
            network_data = {
                "id": network["id"],
                "network_type": network.get("network_type"),
                "risk_score": network.get("risk_score"),
                "confidence_score": network.get("confidence_score"),
                "member_count": network.get("member_count"),
                "status": network.get("status"),
            }

    # Identify flow traces referenced in evidence
    trace_ids: list[str] = []
    for ev in row.get("evidence", []):
        uri = ev.get("uri", "")
        if uri.startswith("aether://flow-trace/"):
            tid = uri.split("/")[-1]
            if tid:
                trace_ids.append(tid)

    trace_summaries: list[dict] = []
    for tid in trace_ids[:10]:
        trace = await _flow_trace_repo.get(tid)
        if trace and trace.get("tenant_id") == tenantId:
            trace_summaries.append({
                "id": trace["id"],
                "anchor_entity_id": trace.get("anchor_entity_id"),
                "risk_score": trace.get("risk_score"),
                "path_count": trace.get("path_count"),
                "cycle_detected": trace.get("cycle_detected"),
                "status": trace.get("status"),
            })

    combined_risk = max(
        (network_data or {}).get("risk_score") or 0.0,
        *[t.get("risk_score", 0.0) for t in trace_summaries],
        0.0,
    )

    return {
        "case_id": case_id,
        "fraud_network": network_data,
        "flow_traces": trace_summaries,
        "combined_risk_score": combined_risk,
        "evidence_count": len(row.get("evidence", [])),
        "subject_count": len(row.get("subjects", [])),
    }


@router.get("/{case_id}/report", response_model=None)
async def get_report(
    case_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> dict:
    """Full structured investigation report: case, subjects, networks, traces, evidence, timeline."""
    _require(request, tenantId, "read")
    row = await _get_case(case_id, tenantId)

    network_data: dict | None = None
    graph_state_id = row.get("graphStateId")
    if graph_state_id:
        network = await _fraud_network_repo.get(graph_state_id)
        if network and network.get("tenant_id") == tenantId:
            network_data = network

    trace_ids = [
        ev.get("uri", "").split("/")[-1]
        for ev in row.get("evidence", [])
        if ev.get("uri", "").startswith("aether://flow-trace/")
    ]
    traces: list[dict] = []
    for tid in trace_ids[:10]:
        trace = await _flow_trace_repo.get(tid)
        if trace and trace.get("tenant_id") == tenantId:
            traces.append(trace)

    timeline = [
        {"event": "case_opened", "at": row.get("createdAt"), "actor": row.get("createdBy")},
    ]
    if row.get("status") != "open":
        timeline.append({
            "event": f"status_changed_to_{row['status']}",
            "at": row.get("updatedAt"),
        })
    for annotation in (row.get("annotations") or []):
        timeline.append({
            "event": "annotation_added",
            "at": annotation.get("createdAt"),
            "actor": annotation.get("authorId"),
            "body": annotation.get("body"),
        })

    return {
        "report_id": str(uuid.uuid4()),
        "case": InvestigationCase(**row).model_dump(),
        "subjects": row.get("subjects", []),
        "fraud_network": network_data,
        "flow_traces": traces,
        "evidence": row.get("evidence", []),
        "annotations": row.get("annotations", []),
        "timeline": sorted(timeline, key=lambda x: x.get("at") or ""),
        "generated_at": _utc_now(),
    }


@router.post("/{case_id}/export", response_model=None)
async def export_case(
    case_id: str,
    request: Request,
    tenantId: str = Query(...),
) -> dict:
    """Return a complete JSON bundle of the investigation case for export."""
    _require(request, tenantId, "read")
    row = await _get_case(case_id, tenantId)

    network_data: dict | None = None
    graph_state_id = row.get("graphStateId")
    if graph_state_id:
        network = await _fraud_network_repo.get(graph_state_id)
        if network and network.get("tenant_id") == tenantId:
            network_data = network

    trace_ids = [
        ev.get("uri", "").split("/")[-1]
        for ev in row.get("evidence", [])
        if ev.get("uri", "").startswith("aether://flow-trace/")
    ]
    traces: list[dict] = []
    for tid in trace_ids[:10]:
        trace = await _flow_trace_repo.get(tid)
        if trace and trace.get("tenant_id") == tenantId:
            traces.append(trace)

    return {
        "export_id": str(uuid.uuid4()),
        "exported_at": _utc_now(),
        "schema_version": "1.0",
        "tenant_id": tenantId,
        "case": InvestigationCase(**row).model_dump(),
        "fraud_network": network_data,
        "flow_traces": traces,
        "evidence": row.get("evidence", []),
        "annotations": row.get("annotations", []),
        "subjects": row.get("subjects", []),
    }


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


# ── Phase 20: Snapshot linkage ─────────────────────────────────────────────

class SnapshotAttachRequest(BaseModel):
    tenantId: str
    snapshot_id: str


@router.post("/{case_id}/snapshot")
async def attach_snapshot_to_investigation(
    case_id: str,
    body: SnapshotAttachRequest,
    request: Request,
) -> dict:
    """Attach a traversal snapshot to an investigation case.

    Validates that the snapshot belongs to the same tenant as the case (fail-closed).
    """
    _require(request, body.tenantId, "write")
    from repositories.repos import TraversalSnapshotRepository
    from shared.common.common import NotFoundError

    snap_repo = TraversalSnapshotRepository()
    snap = await snap_repo.get(body.snapshot_id, body.tenantId)
    if not snap:
        raise NotFoundError(f"Snapshot {body.snapshot_id} not found for tenant {body.tenantId}")
    if snap.get("tenant_id") != body.tenantId:
        raise ForbiddenError("snapshot tenant mismatch")

    await _get_case(case_id, body.tenantId)  # validates existence and tenant
    updated = await _repo.update(case_id, {
        "snapshot_id": body.snapshot_id,
        "path_ids": snap.get("path_ids", []),
        "updatedAt": _utc_now(),
    })
    return APIResponse(data=InvestigationCase(**updated).model_dump()).to_dict()


@router.get("/{case_id}/paths")
async def get_investigation_paths(
    case_id: str,
    request: Request,
    tenantId: str = Query(..., description="Tenant ID"),
) -> dict:
    """Return the path IDs linked to an investigation's snapshot."""
    _require(request, tenantId, "read")
    from repositories.repos import TraversalSnapshotRepository
    from shared.common.common import NotFoundError

    row = await _get_case(case_id, tenantId)
    snap_id = row.get("snapshot_id")
    if not snap_id:
        return APIResponse(data={"path_ids": [], "snapshot_id": None}).to_dict()

    snap_repo = TraversalSnapshotRepository()
    snap = await snap_repo.get(snap_id, tenantId)
    if not snap:
        raise NotFoundError(f"Snapshot {snap_id} not found")

    return APIResponse(data={
        "snapshot_id": snap_id,
        "path_ids": snap.get("path_ids", []),
        "node_ids": snap.get("node_ids", []),
        "edge_ids": snap.get("edge_ids", []),
    }).to_dict()
