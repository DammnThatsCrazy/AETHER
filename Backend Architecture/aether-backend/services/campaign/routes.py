"""
Aether Service — Campaign
Campaign management and reporting. Attribution is delegated to the canonical
measurement engine (services/measurement). This service owns campaign metadata
and touchpoint recording only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import (
    APIResponse, BadRequestError, NotFoundError,
    PaginatedResponse, PaginationMeta,
)
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from shared.observability import trace_request, emit_latency
from dependencies.providers import get_producer
from repositories.repos import CampaignRepository

logger = get_logger("aether.service.campaign")
router = APIRouter(prefix="/v1/campaigns", tags=["Campaigns"])

_repo = CampaignRepository()


# ── Request Models ───────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    channel: str = Field(..., description="e.g. email, social, paid_search, organic")
    start_date: str
    end_date: Optional[str] = None
    budget_usd: Optional[float] = None
    utm_params: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    end_date: Optional[str] = None
    budget_usd: Optional[float] = None
    status: Optional[str] = None


class TouchpointCreate(BaseModel):
    """Validated touchpoint input."""
    channel: Optional[str] = None
    source: str = ""
    user_id: str = ""
    session_id: str = ""
    event_type: str = "pageview"
    is_conversion: bool = False
    revenue_usd: float = Field(default=0.0, ge=0.0)
    timestamp: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


# ── CRUD Routes ──────────────────────────────────────────────────────

@router.get("")
async def list_campaigns(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None, description="Opaque cursor from previous page (keyset on created_at)"),
    status: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
):
    """List campaigns with keyset cursor pagination.

    Pass the `next_cursor` value from the previous response to get the next page.
    Offset-based pagination is no longer supported to avoid deep-scan performance issues.
    """
    tenant = request.state.tenant
    filters: dict[str, Any] = {"tenant_id": tenant.tenant_id}
    if status:
        filters["status"] = status
    if channel:
        filters["channel"] = channel

    # Keyset: if cursor provided, fetch only campaigns created after cursor timestamp
    # cursor is an ISO datetime string (created_at of last item on previous page)
    offset = 0  # always 0 — cursor replaces offset
    if cursor:
        try:
            from datetime import datetime
            cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
            # We can't pass created_at > cursor through find_many's equality filter API,
            # so we over-fetch and filter in Python for local mode.
            # In production the repository layer applies the keyset filter via SQL.
            all_rows = await _repo.find_many(filters=filters, limit=limit + 500, offset=0)
            campaigns = [
                r for r in all_rows
                if (r.get("created_at") or "") > cursor
            ][:limit]
        except (ValueError, TypeError):
            campaigns = await _repo.find_many(filters=filters, limit=limit, offset=0)
    else:
        campaigns = await _repo.find_many(filters=filters, limit=limit, offset=0)

    next_cursor = campaigns[-1].get("created_at") if len(campaigns) == limit else None
    return {
        "data": campaigns,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.post("")
async def create_campaign(
    body: CampaignCreate,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    campaign_id = str(uuid.uuid4())
    campaign = await _repo.insert(campaign_id, {
        "tenant_id": tenant.tenant_id,
        **body.model_dump(),
        "status": "active",
    })
    await producer.publish(Event(
        topic=Topic.CAMPAIGN_CREATED,
        tenant_id=tenant.tenant_id,
        source_service="campaign",
        payload={"campaign_id": campaign_id, **body.model_dump()},
    ))
    metrics.increment("campaigns_created")
    return APIResponse(data=campaign).to_dict()


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str, request: Request):
    tenant = request.state.tenant
    campaign = await _repo.find_by_id(campaign_id)
    if campaign is None or campaign.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Campaign")
    metrics.increment("campaigns_read")
    return APIResponse(data=campaign).to_dict()


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")

    # Verify ownership before mutation
    existing = await _repo.find_by_id(campaign_id)
    if existing is None or existing.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Campaign")

    campaign = await _repo.update(campaign_id, body.model_dump(exclude_none=True))
    await producer.publish(Event(
        topic=Topic.CAMPAIGN_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="campaign",
        payload={"campaign_id": campaign_id, **body.model_dump(exclude_none=True)},
    ))
    metrics.increment("campaigns_updated")
    return APIResponse(data=campaign).to_dict()


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")

    # Verify ownership before mutation
    existing = await _repo.find_by_id(campaign_id)
    if existing is None or existing.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Campaign")

    await _repo.delete(campaign_id)
    await producer.publish(Event(
        topic=Topic.CAMPAIGN_DELETED,
        tenant_id=tenant.tenant_id,
        source_service="campaign",
        payload={"campaign_id": campaign_id},
    ))
    metrics.increment("campaigns_deleted")
    return APIResponse(data={"deleted": True}).to_dict()


# ── Attribution (read-only — delegated to measurement engine) ────────

@router.get("/{campaign_id}/attribution")
async def get_attribution(
    campaign_id: str,
    request: Request,
    model: str = Query(default="last_touch"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """Return attribution credits for a campaign from the canonical measurement engine.

    Credits are pre-computed per conversion by the attribution engine and stored
    in attribution_credits. This endpoint aggregates persisted credits by campaign.
    The measurement engine owns all attribution calculation — this route is read-only.
    """
    tenant = request.state.tenant
    campaign = await _repo.find_by_id(campaign_id)
    if campaign is None or campaign.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Campaign")

    ctx = trace_request(request, service="campaign")

    try:
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        run_repo = AttributionRunRepository()
        summary = await run_repo.campaign_credit_summary(
            tenant_id=tenant.tenant_id,
            campaign_id=campaign_id,
            model_type=model,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        logger.warning(
            "Attribution credits unavailable for campaign=%s: %s — returning empty summary",
            campaign_id, exc,
        )
        summary = {
            "conversions": 0,
            "attributed_gross_revenue": 0.0,
            "attributed_net_revenue": 0.0,
            "total_credit_weight": 0.0,
            "touchpoint_count": 0,
            "quality": {"status": "not_provisioned", "message": str(exc)},
        }

    emit_latency("campaign_attribution", ctx.elapsed_ms(), labels={"model": model})
    metrics.increment("campaign_attribution_computed", labels={"model": model})

    return APIResponse(data={
        "campaign_id": campaign_id,
        "campaign_name": campaign.get("name", ""),
        "model": model,
        "period": {"start": start_date, "end": end_date},
        **summary,
    }).to_dict()


@router.post("/{campaign_id}/touchpoints")
async def record_touchpoint(
    campaign_id: str,
    body: TouchpointCreate,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Record a campaign touchpoint via the canonical measurement pipeline.

    Touchpoints are written to silver_campaign_touchpoint_facts for durable
    storage and downstream attribution. The old Redis/in-memory store is no
    longer used.
    """
    tenant = request.state.tenant

    campaign = await _repo.find_by_id(campaign_id)
    if campaign is None or campaign.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Campaign")

    touchpoint_id = str(uuid.uuid4())
    touchpoint = {
        "touchpoint_id": touchpoint_id,
        "campaign_id": campaign_id,
        "tenant_id": tenant.tenant_id,
        "channel": body.channel or campaign.get("channel", "unknown"),
        "source": body.source,
        "user_id": body.user_id,
        "session_id": body.session_id,
        "event_type": body.event_type,
        "is_conversion": body.is_conversion,
        "revenue_usd": body.revenue_usd,
        "occurred_at": body.timestamp or datetime.now(timezone.utc).isoformat(),
        "properties": body.properties,
    }

    # Write to canonical touchpoint store
    try:
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        tp_repo = TouchpointRepository()
        await tp_repo.upsert_from_campaign_touchpoint(
            tenant_id=tenant.tenant_id,
            campaign_id=campaign_id,
            touchpoint_id=touchpoint_id,
            data=touchpoint,
        )
    except Exception as exc:
        # Log but do not fail the request — event bus handles the canonical write
        logger.warning("Canonical touchpoint write deferred: %s", exc)

    await producer.publish(Event(
        topic=Topic.TOUCHPOINT_RECORDED,
        tenant_id=tenant.tenant_id,
        source_service="campaign",
        payload=touchpoint,
    ))

    metrics.increment("campaign_touchpoints_recorded")
    return APIResponse(data=touchpoint).to_dict()
