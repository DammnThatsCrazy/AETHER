"""Fraud Network Intelligence — API routes.

Endpoints:
    POST /v1/fraud/networks/build              Build a fraud network from anchor entities
    GET  /v1/fraud/networks                    List networks for a tenant
    GET  /v1/fraud/networks/{network_id}       Get network details
    GET  /v1/fraud/networks/{network_id}/graph Cytoscape-ready graph payload
    GET  /v1/fraud/networks/{network_id}/members  List network members
    GET  /v1/fraud/networks/{network_id}/evidence List evidence refs
    GET  /v1/fraud/networks/{network_id}/timeline Network event timeline
    POST /v1/fraud/networks/{network_id}/refresh  Re-run detection
    POST /v1/fraud/networks/{network_id}/open-investigation  Create case
    POST /v1/fraud/networks/{network_id}/annotate  Add annotation
    POST /v1/fraud/networks/{network_id}/suppress  Suppress network
    POST /v1/fraud/networks/{network_id}/escalate  Escalate network
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from config.settings import settings
from dependencies.providers import get_graph, get_producer
from repositories.repos import (
    FraudNetworkEdgeRepository,
    FraudNetworkMemberRepository,
    FraudNetworkRepository,
    InvestigationRepository,
)
from services.fraud_networks.detectors import (
    detect_agentic_delegation_abuse,
    detect_circular_transfers,
    detect_commerce_abuse,
    detect_reward_farming,
    detect_shared_device,
    detect_shared_ip,
    detect_split_merge,
    detect_wallet_cluster,
)
from services.fraud_networks.evidence import build_evidence_refs
from services.fraud_networks.models import (
    FraudNetworkBuildRequest,
    FraudNetworkGraphEdge,
    FraudNetworkGraphNode,
    FraudNetworkGraphResponse,
    FraudNetworkMember,
    FraudNetworkResponse,
    NetworkAnnotateRequest,
    NetworkOpenInvestigationRequest,
    NetworkStatusUpdateRequest,
)
from services.fraud_networks.roles import assign_roles_to_members
from services.fraud_networks.scoring import score_cluster_risk, score_confidence
from services.operational_intelligence.models import EntityRef, EvidenceRef, InvestigationCase
from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.fraud_networks")

router = APIRouter(prefix="/v1/fraud/networks", tags=["Fraud Network Intelligence"])

_networks = FraudNetworkRepository()
_members = FraudNetworkMemberRepository()
_edges_repo = FraudNetworkEdgeRepository()
_investigations = InvestigationRepository()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_feature() -> None:
    if not settings.fraud_intelligence.fraud_networks_enabled:
        raise NotFoundError("Fraud Networks feature is not enabled")


def _require(request: Request, tenant_id: str, permission: str = "fraud:read") -> None:
    _require_feature()
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


async def _get_network(network_id: str, tenant_id: str) -> dict:
    row = await _networks.get(network_id)
    if row is None or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"FraudNetwork {network_id!r} not found")
    return row


def _to_response(row: dict) -> FraudNetworkResponse:
    return FraudNetworkResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        label=row.get("label"),
        network_type=row.get("network_type", "unknown"),
        status=row.get("status", "active"),
        risk_score=row.get("risk_score", 0.0),
        confidence_score=row.get("confidence_score", 0.0),
        member_count=row.get("member_count", 0),
        edge_count=row.get("edge_count", 0),
        anchor_entity_ids=row.get("anchor_entity_ids", []),
        evidence_refs=[EvidenceRef(**e) for e in row.get("evidence_refs", [])],
        detected_signals=row.get("detected_signals", []),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
        metadata=row.get("metadata", {}),
    )


async def _run_detection_pipeline(
    tenant_id: str,
    anchor_entity_ids: list[str],
    max_depth: int,
) -> tuple[list[dict], list[dict], list[Any]]:
    """Run all detectors against transfers/sessions/wallets for the anchors.

    In production this would fetch from the repo. We fetch what's available;
    in-memory backend returns empty lists which yield zero-signal networks.
    Returns (member_dicts, transfer_dicts, detector_results).
    """
    from repositories.repos import TransferRepository, WalletRepository

    transfer_repo = TransferRepository()
    wallet_repo = WalletRepository()

    # Collect transfers involving any anchor entity (up to max_depth hops)
    seen_entities: set[str] = set(anchor_entity_ids)
    transfers: list[dict] = []
    frontier = list(anchor_entity_ids)

    for _ in range(max_depth):
        next_frontier: list[str] = []
        for eid in frontier:
            outbound = await transfer_repo.find_many(
                filters={"from_entity_id": eid, "tenant_id": tenant_id}, limit=200
            )
            inbound = await transfer_repo.find_many(
                filters={"to_entity_id": eid, "tenant_id": tenant_id}, limit=200
            )
            for t in outbound + inbound:
                transfers.append(t)
                for field in ("from_entity_id", "to_entity_id"):
                    neighbor = t.get(field, "")
                    if neighbor and neighbor not in seen_entities:
                        seen_entities.add(neighbor)
                        next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    # Collect wallet links
    wallet_links: list[dict] = []
    for eid in seen_entities:
        wallets = await wallet_repo.find_many(
            filters={"owner_entity_id": eid, "tenant_id": tenant_id}, limit=50
        )
        for w in wallets:
            wallet_links.append({
                "entity_id": eid,
                "wallet_address": w.get("address", ""),
                "chain": w.get("chain", "unknown"),
            })

    # Build member stubs from seen entities
    member_dicts = [
        {
            "entity_id": eid,
            "entity_type": "user",
            "is_anchor": eid in anchor_entity_ids,
            "account_age_days": 365,
        }
        for eid in seen_entities
    ]

    # Run detectors
    sessions: list[dict] = []
    detector_results = (
        detect_shared_device(sessions)
        + detect_shared_ip(sessions)
        + detect_wallet_cluster(wallet_links)
        + detect_circular_transfers(transfers, max_depth=max_depth)
        + detect_split_merge(transfers)
        + detect_reward_farming([])
        + detect_agentic_delegation_abuse([], transfers)
        + detect_commerce_abuse([], [])
    )

    return member_dicts, transfers, detector_results


@router.post("/build", response_model=None)
async def build_network(
    body: FraudNetworkBuildRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Build a fraud network by clustering entities connected to anchor IDs."""
    _require(request, body.tenant_id, "fraud:evaluate")
    now = _utc_now()

    member_dicts, transfers, detector_results = await _run_detection_pipeline(
        tenant_id=body.tenant_id,
        anchor_entity_ids=body.anchor_entity_ids,
        max_depth=min(body.max_depth, settings.fraud_intelligence.max_network_depth),
    )

    # Classify roles
    roles = assign_roles_to_members(member_dicts, transfers)

    network_id = str(uuid.uuid4())
    evidence_refs = build_evidence_refs(detector_results, network_id, body.tenant_id, now)

    # Score the cluster
    member_risk_scores = [50.0] * len(member_dicts)
    edge_risk_scores = [40.0] * max(len(transfers), 1)
    signal_names = list({r[0] for r in detector_results})
    cycle_count = sum(1 for r in detector_results if r[0] == "circular_transfer")

    risk_score = score_cluster_risk(
        member_risk_scores=member_risk_scores,
        edge_risk_scores=edge_risk_scores,
        cycle_count=cycle_count,
        signal_count=len(signal_names),
        network_type=body.network_type or "unknown",
    )
    confidence_score = score_confidence(
        evidence_count=len(evidence_refs),
        signal_overlap=len(signal_names),
        member_count=len(member_dicts),
        has_circular_transfer=cycle_count > 0,
        has_shared_device=any(r[0] == "shared_device" for r in detector_results),
    )

    # Determine network type
    inferred_type = body.network_type
    if inferred_type is None:
        if cycle_count > 0:
            inferred_type = "layering_network"
        elif any(r[0] == "reward_farming" for r in detector_results):
            inferred_type = "reward_farming_ring"
        elif any(r[0] == "agentic_delegation_abuse" for r in detector_results):
            inferred_type = "delegation_abuse_cluster"
        else:
            inferred_type = "unknown"

    network = {
        "id": network_id,
        "tenant_id": body.tenant_id,
        "label": body.label,
        "network_type": inferred_type,
        "status": "active",
        "risk_score": risk_score,
        "confidence_score": confidence_score,
        "member_count": len(member_dicts),
        "edge_count": len(transfers),
        "anchor_entity_ids": body.anchor_entity_ids,
        "evidence_refs": [e.model_dump() for e in evidence_refs],
        "detected_signals": signal_names,
        "created_at": now,
        "updated_at": now,
        "metadata": body.metadata,
    }
    await _networks.create(network)

    # Persist members
    for m in member_dicts:
        eid = m["entity_id"]
        member_row = {
            "id": str(uuid.uuid4()),
            "network_id": network_id,
            "tenant_id": body.tenant_id,
            "entity_id": eid,
            "entity_type": m.get("entity_type", "user"),
            "role": roles.get(eid, "unknown"),
            "risk_score": 50.0,
            "confidence": confidence_score,
            "in_degree": 0,
            "out_degree": 0,
            "evidence_refs": [],
            "joined_at": now,
            "metadata": {},
        }
        await _members.create(member_row)

    # Project to graph (best-effort)
    try:
        vertex = Vertex(
            vertex_type=VertexType.FRAUD_NETWORK,
            vertex_id=network_id,
            properties={
                "tenant_id": body.tenant_id,
                "risk_score": str(risk_score),
                "network_type": inferred_type,
                "status": "active",
            },
        )
        await graph.upsert_vertex(vertex)
        for eid in body.anchor_entity_ids:
            edge = Edge(
                edge_type=EdgeType.MEMBER_OF_FRAUD_NETWORK,
                from_vertex_id=eid,
                to_vertex_id=network_id,
                properties={"role": "anchor", "tenant_id": body.tenant_id},
            )
            await graph.add_edge(edge)
    except Exception as exc:
        logger.warning("fraud_network_graph_projection_failed", extra={"error": str(exc)})

    await producer.publish(Event(
        topic=Topic.FRAUD_NETWORK_CREATED,
        tenant_id=body.tenant_id,
        source_service="fraud_networks",
        payload={"network_id": network_id, "risk_score": risk_score, "member_count": len(member_dicts)},
    ))
    metrics.increment("fraud_network_built")
    return _to_response(network).model_dump()


@router.get("", response_model=None)
async def list_networks(
    request: Request,
    tenant_id: str = Query(...),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """List fraud networks for the authenticated tenant."""
    _require(request, tenant_id, "fraud:read")
    rows = await _networks.list_by_tenant(tenant_id, status=status, limit=limit)
    networks = [_to_response(r).model_dump() for r in rows]
    return APIResponse(data=networks, meta={"count": len(networks)}).to_dict()


@router.get("/{network_id}", response_model=None)
async def get_network(
    network_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Get a single fraud network by ID."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_network(network_id, tenant_id)
    return _to_response(row).model_dump()


@router.get("/{network_id}/graph", response_model=None)
async def get_network_graph(
    network_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Return a Cytoscape-ready graph payload for the fraud network."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_network(network_id, tenant_id)
    member_rows = await _members.list_by_network(network_id)
    edge_rows = await _edges_repo.list_by_network(network_id)
    anchor_ids = set(row.get("anchor_entity_ids", []))

    nodes = [
        FraudNetworkGraphNode(
            id=m["entity_id"],
            label=m.get("entity_id", ""),
            entity_type=m.get("entity_type", "user"),
            role=m.get("role", "unknown"),
            risk_score=m.get("risk_score", 0.0),
            confidence=m.get("confidence", 0.0),
            is_anchor=m["entity_id"] in anchor_ids,
            metadata=m.get("metadata", {}),
        )
        for m in member_rows
    ]

    edges = [
        FraudNetworkGraphEdge(
            id=e["id"],
            source=e.get("from_entity_id", ""),
            target=e.get("to_entity_id", ""),
            edge_type=e.get("edge_type", "TRANSFERRED"),
            risk_score=e.get("risk_score", 0.0),
            transfer_count=e.get("transfer_count", 0),
            metadata=e.get("metadata", {}),
        )
        for e in edge_rows
    ]

    result = FraudNetworkGraphResponse(
        network_id=network_id,
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
        computed_at=_utc_now(),
    )
    metrics.increment("fraud_network_graph_requested")
    return result.model_dump()


@router.get("/{network_id}/members", response_model=None)
async def get_members(
    network_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """List all members of a fraud network with their classified roles."""
    _require(request, tenant_id, "fraud:read")
    await _get_network(network_id, tenant_id)
    member_rows = await _members.list_by_network(network_id)
    members = [
        FraudNetworkMember(
            id=m["id"],
            network_id=network_id,
            tenant_id=tenant_id,
            entity_id=m["entity_id"],
            entity_type=m.get("entity_type", "user"),
            role=m.get("role", "unknown"),
            risk_score=m.get("risk_score", 0.0),
            confidence=m.get("confidence", 0.0),
            in_degree=m.get("in_degree", 0),
            out_degree=m.get("out_degree", 0),
            evidence_refs=[EvidenceRef(**e) for e in m.get("evidence_refs", [])],
            joined_at=m.get("joined_at", ""),
            metadata=m.get("metadata", {}),
        ).model_dump()
        for m in member_rows
    ]
    return APIResponse(data=members, meta={"count": len(members)}).to_dict()


@router.get("/{network_id}/evidence", response_model=None)
async def get_evidence(
    network_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """List evidence refs attached to a fraud network."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_network(network_id, tenant_id)
    refs = [EvidenceRef(**e).model_dump() for e in row.get("evidence_refs", [])]
    return APIResponse(data=refs, meta={"count": len(refs)}).to_dict()


@router.get("/{network_id}/timeline", response_model=None)
async def get_timeline(
    network_id: str,
    request: Request,
    tenant_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    """Return a chronological timeline of state changes for the network."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_network(network_id, tenant_id)
    timeline = [
        {"event": "network_created", "at": row.get("created_at"), "detail": {"status": "active"}},
    ]
    if row.get("status") in ("suppressed", "escalated", "closed"):
        timeline.append({
            "event": f"network_{row['status']}",
            "at": row.get("updated_at"),
            "detail": {"status": row["status"]},
        })
    return APIResponse(data=timeline[:limit], meta={"count": len(timeline)}).to_dict()


@router.post("/{network_id}/refresh", response_model=None)
async def refresh_network(
    network_id: str,
    request: Request,
    tenant_id: str = Query(...),
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Re-run the full detection pipeline for an existing network."""
    _require(request, tenant_id, "fraud:evaluate")
    row = await _get_network(network_id, tenant_id)
    anchor_ids = row.get("anchor_entity_ids", [])

    member_dicts, transfers, detector_results = await _run_detection_pipeline(
        tenant_id=tenant_id,
        anchor_entity_ids=anchor_ids,
        max_depth=settings.fraud_intelligence.max_network_depth,
    )

    signal_names = list({r[0] for r in detector_results})
    evidence_refs = build_evidence_refs(detector_results, network_id, tenant_id)
    cycle_count = sum(1 for r in detector_results if r[0] == "circular_transfer")

    risk_score = score_cluster_risk(
        member_risk_scores=[50.0] * max(len(member_dicts), 1),
        edge_risk_scores=[40.0] * max(len(transfers), 1),
        cycle_count=cycle_count,
        signal_count=len(signal_names),
        network_type=row.get("network_type", "unknown"),
    )
    confidence_score = score_confidence(
        evidence_count=len(evidence_refs),
        signal_overlap=len(signal_names),
        member_count=len(member_dicts),
        has_circular_transfer=cycle_count > 0,
        has_shared_device=any(r[0] == "shared_device" for r in detector_results),
    )
    now = _utc_now()
    updated = await _networks.update(network_id, {
        "risk_score": risk_score,
        "confidence_score": confidence_score,
        "member_count": len(member_dicts),
        "detected_signals": signal_names,
        "evidence_refs": [e.model_dump() for e in evidence_refs],
        "updated_at": now,
    })
    await producer.publish(Event(
        topic=Topic.FRAUD_NETWORK_REFRESHED,
        tenant_id=tenant_id,
        source_service="fraud_networks",
        payload={"network_id": network_id, "risk_score": risk_score},
    ))
    metrics.increment("fraud_network_refreshed")
    return _to_response(updated).model_dump()


@router.post("/{network_id}/open-investigation", response_model=None)
async def open_investigation(
    network_id: str,
    body: NetworkOpenInvestigationRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
    graph: GraphClient = Depends(get_graph),
) -> dict:
    """Create an InvestigationCase linked to this fraud network."""
    _require(request, body.tenant_id, "fraud:evaluate")
    row = await _get_network(network_id, body.tenant_id)

    now = _utc_now()
    case_id = str(uuid.uuid4())
    title = body.title or f"Fraud Network Investigation: {row.get('network_type', 'unknown')} ({network_id[:8]})"

    members = await _members.list_by_network(network_id)
    subjects = [
        EntityRef(kind="user", id=m["entity_id"]).model_dump()
        for m in members[:20]  # cap at 20 subjects
    ]

    case = {
        "id": case_id,
        "tenantId": body.tenant_id,
        "tenant_id": body.tenant_id,
        "title": title,
        "status": "open",
        "subjects": subjects,
        "graphStateId": network_id,
        "evidence": row.get("evidence_refs", []),
        "annotations": [],
        "createdBy": body.created_by,
        "createdAt": now,
        "updatedAt": now,
    }
    await _investigations.create(case)

    # Project ATTACHED_TO_CASE edge
    try:
        edge = Edge(
            edge_type=EdgeType.ATTACHED_TO_CASE,
            from_vertex_id=network_id,
            to_vertex_id=case_id,
            properties={"tenant_id": body.tenant_id},
        )
        await graph.add_edge(edge)
    except Exception as exc:
        logger.warning("fraud_network_case_graph_edge_failed", extra={"error": str(exc)})

    await producer.publish(Event(
        topic=Topic.INVESTIGATION_CASE_CREATED,
        tenant_id=body.tenant_id,
        source_service="fraud_networks",
        payload={"case_id": case_id, "network_id": network_id, "title": title},
    ))
    metrics.increment("fraud_network_investigation_opened")
    return {"case_id": case_id, "title": title, "status": "open", "created_at": now}


@router.post("/{network_id}/annotate", response_model=None)
async def annotate_network(
    network_id: str,
    body: NetworkAnnotateRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Add a plain-text annotation to a fraud network."""
    _require(request, body.tenant_id, "fraud:evaluate")
    row = await _get_network(network_id, body.tenant_id)
    now = _utc_now()
    annotation = {
        "id": str(uuid.uuid4()),
        "author_id": body.author_id,
        "body": body.body,
        "created_at": now,
    }
    existing = row.get("annotations", [])
    updated = await _networks.update(network_id, {
        "annotations": existing + [annotation],
        "updated_at": now,
    })
    await producer.publish(Event(
        topic=Topic.FRAUD_NETWORK_UPDATED,
        tenant_id=body.tenant_id,
        source_service="fraud_networks",
        payload={"network_id": network_id, "update": "annotated"},
    ))
    metrics.increment("fraud_network_annotated")
    return _to_response(updated).model_dump()


@router.post("/{network_id}/suppress", response_model=None)
async def suppress_network(
    network_id: str,
    body: NetworkStatusUpdateRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Mark a fraud network as suppressed (analyst reviewed, no action needed)."""
    _require(request, body.tenant_id, "fraud:evaluate")
    await _get_network(network_id, body.tenant_id)
    now = _utc_now()
    updated = await _networks.update_status(
        network_id, "suppressed", reason=body.reason, updated_at=now
    )
    await producer.publish(Event(
        topic=Topic.FRAUD_NETWORK_SUPPRESSED,
        tenant_id=body.tenant_id,
        source_service="fraud_networks",
        payload={"network_id": network_id, "reason": body.reason},
    ))
    metrics.increment("fraud_network_suppressed")
    return _to_response(updated).model_dump()


@router.post("/{network_id}/escalate", response_model=None)
async def escalate_network(
    network_id: str,
    body: NetworkStatusUpdateRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Escalate a fraud network for senior analyst or compliance review."""
    _require(request, body.tenant_id, "fraud:evaluate")
    await _get_network(network_id, body.tenant_id)
    now = _utc_now()
    updated = await _networks.update_status(
        network_id, "escalated", reason=body.reason, updated_at=now
    )
    await producer.publish(Event(
        topic=Topic.FRAUD_NETWORK_ESCALATED,
        tenant_id=body.tenant_id,
        source_service="fraud_networks",
        payload={"network_id": network_id, "reason": body.reason},
    ))
    metrics.increment("fraud_network_escalated")
    return _to_response(updated).model_dump()
