"""Risk Overlay — API routes.

Endpoints:
    POST /v1/risk-overlays/fraud       Build overlay from fraud network
    POST /v1/risk-overlays/flow        Build overlay from flow trace
    GET  /v1/risk-overlays             List saved overlay snapshots
    GET  /v1/risk-overlays/{id}        Get a saved overlay snapshot
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request

from config.settings import settings
from dependencies.providers import get_producer
from repositories.repos import RiskOverlaySnapshotRepository
from services.risk_overlay.builder import build_flow_overlay, build_fraud_overlay
from services.risk_overlay.models import RiskOverlayBuildRequest, RiskOverlayGraph
from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.risk_overlay")

router = APIRouter(prefix="/v1/risk-overlays", tags=["Risk Overlays"])

_snapshots = RiskOverlaySnapshotRepository()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_feature() -> None:
    if not settings.fraud_intelligence.risk_overlays_enabled:
        raise NotFoundError("Risk Overlays feature is not enabled")


def _require(request: Request, tenant_id: str, permission: str = "fraud:read") -> None:
    _require_feature()
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


@router.post("/fraud", response_model=None)
async def build_fraud_network_overlay(
    body: RiskOverlayBuildRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Build and save a risk graph overlay from a fraud network."""
    _require(request, body.tenant_id, "fraud:evaluate")

    if body.source_type != "fraud_network":
        from shared.common.common import BadRequestError
        raise BadRequestError("source_type must be 'fraud_network' for this endpoint")

    overlay = await build_fraud_overlay(body.tenant_id, body.source_id)

    now = _utc_now()
    snapshot_id = str(uuid.uuid4())
    snapshot = {
        "id": snapshot_id,
        "tenant_id": body.tenant_id,
        "source_id": body.source_id,
        "source_type": "fraud_network",
        "label": body.label,
        "overlay": overlay.model_dump(),
        "node_count": overlay.node_count,
        "edge_count": overlay.edge_count,
        "overlay_risk_score": overlay.overlay_risk_score,
        "computed_at": overlay.computed_at,
        "created_at": now,
        "metadata": body.metadata,
    }
    await _snapshots.create(snapshot)

    await producer.publish(Event(
        topic=Topic.RISK_OVERLAY_GENERATED,
        tenant_id=body.tenant_id,
        source_service="risk_overlay",
        payload={
            "overlay_id": snapshot_id,
            "source_type": "fraud_network",
            "source_id": body.source_id,
            "node_count": overlay.node_count,
        },
    ))
    metrics.increment("risk_overlay_generated", labels={"source_type": "fraud_network"})
    return {"id": snapshot_id, "overlay": overlay.model_dump(), "created_at": now}


@router.post("/flow", response_model=None)
async def build_flow_trace_overlay(
    body: RiskOverlayBuildRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Build and save a risk graph overlay from a flow trace."""
    _require(request, body.tenant_id, "fraud:evaluate")

    if body.source_type != "flow_trace":
        from shared.common.common import BadRequestError
        raise BadRequestError("source_type must be 'flow_trace' for this endpoint")

    overlay = await build_flow_overlay(body.tenant_id, body.source_id)

    now = _utc_now()
    snapshot_id = str(uuid.uuid4())
    snapshot = {
        "id": snapshot_id,
        "tenant_id": body.tenant_id,
        "source_id": body.source_id,
        "source_type": "flow_trace",
        "label": body.label,
        "overlay": overlay.model_dump(),
        "node_count": overlay.node_count,
        "edge_count": overlay.edge_count,
        "overlay_risk_score": overlay.overlay_risk_score,
        "computed_at": overlay.computed_at,
        "created_at": now,
        "metadata": body.metadata,
    }
    await _snapshots.create(snapshot)

    await producer.publish(Event(
        topic=Topic.RISK_OVERLAY_GENERATED,
        tenant_id=body.tenant_id,
        source_service="risk_overlay",
        payload={
            "overlay_id": snapshot_id,
            "source_type": "flow_trace",
            "source_id": body.source_id,
            "node_count": overlay.node_count,
        },
    ))
    metrics.increment("risk_overlay_generated", labels={"source_type": "flow_trace"})
    return {"id": snapshot_id, "overlay": overlay.model_dump(), "created_at": now}


@router.get("", response_model=None)
async def list_overlays(
    request: Request,
    tenant_id: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """List risk overlay snapshots for the authenticated tenant."""
    _require(request, tenant_id, "fraud:read")
    rows = await _snapshots.list_by_tenant(tenant_id, limit=limit)
    return APIResponse(data=rows, meta={"count": len(rows)}).to_dict()


@router.get("/{overlay_id}", response_model=None)
async def get_overlay(
    overlay_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Get a specific risk overlay snapshot by ID."""
    _require(request, tenant_id, "fraud:read")
    row = await _snapshots.get(overlay_id)
    if row is None or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"RiskOverlay {overlay_id!r} not found")
    return row
