"""
Aether Service — Campaign
Campaign management and reporting. Attribution is delegated to the canonical
measurement engine (services/measurement). This service owns campaign metadata
and touchpoint recording only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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
from services.campaign.exploration import CampaignPopulationExplorer
from services.measurement.repositories.touchpoint_repo import TouchpointRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.spend_repo import SpendRepository

logger = get_logger("aether.service.campaign")
router = APIRouter(prefix="/v1/campaigns", tags=["Campaigns"])

_repo = CampaignRepository()
_explorer = CampaignPopulationExplorer(
    touchpoint_repo=TouchpointRepository(),
    conversion_repo=ConversionRepository(),
    run_repo=AttributionRunRepository(),
    journey_repo=JourneyRepository(),
    spend_repo=SpendRepository(),
)


# ── Request Models ───────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    # An unnamed campaign cannot be identified by an operator in any surface
    # that lists it, so an empty name is rejected rather than stored.
    name: str = Field(..., min_length=1)
    channel: str = Field(..., min_length=1, description="e.g. email, social, paid_search, organic")
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


class CampaignGraphRequest(BaseModel):
    """Campaign-anchored graph query — hard budget limits enforced in explorer."""
    population: str = "observed"
    time_range: Optional[dict[str, str]] = None
    relationship_layers: Optional[list[str]] = None
    depth: int = Field(default=2, ge=1, le=3)
    max_nodes: int = Field(default=200, ge=1, le=500)
    max_edges: int = Field(default=600, ge=1, le=1500)
    filters: Optional[dict[str, Any]] = None
    continuation_token: Optional[str] = None
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
        start_at = _attribution_boundary(start_date, exclusive_end=False)
        end_at = _attribution_boundary(end_date, exclusive_end=True)
    except ValueError as exc:
        raise BadRequestError(f"Invalid attribution date: {exc}")

    try:
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        run_repo = AttributionRunRepository()
        summary = await run_repo.campaign_credit_summary(
            tenant_id=tenant.tenant_id,
            campaign_id=campaign_id,
            model_type=model,
            start_date=start_at,
            end_date=end_at,
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


def _attribution_boundary(value: Optional[str], *, exclusive_end: bool) -> Optional[datetime]:
    if not value:
        return None
    date_only = len(value) == 10
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if exclusive_end and date_only:
        parsed += timedelta(days=1)
    return parsed


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


# ── Campaign 360 Exploration Routes ──────────────────────────────────────────

async def _require_campaign(campaign_id: str, tenant) -> dict[str, Any]:
    """Fetch campaign and verify tenant ownership. Raises NotFoundError on mismatch."""
    campaign = await _repo.find_by_id(campaign_id)
    if campaign is None or campaign.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Campaign")
    return campaign


@router.get("/{campaign_id}/overview")
async def get_campaign_overview(
    campaign_id: str,
    request: Request,
    time_start: Optional[str] = Query(default=None),
    time_end: Optional[str] = Query(default=None),
    tz: Optional[str] = Query(default=None),
    attribution_model: str = Query(default="last_touch"),
    attribution_run_id: Optional[str] = Query(default=None),
):
    """Reconciled campaign overview: spend, population funnel, attribution, ROAS, quality."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    campaign = await _require_campaign(campaign_id, tenant)

    ctx = trace_request(request, service="campaign")
    time_range = None
    if time_start or time_end:
        time_range = {"start": time_start or "", "end": time_end or "", "tz": tz or "UTC"}

    overview = await _explorer.get_overview(
        tenant.tenant_id, campaign_id, campaign,
        time_range=time_range,
        attribution_model=attribution_model,
        attribution_run_id=attribution_run_id,
    )
    emit_latency("campaign_overview", ctx.elapsed_ms())
    metrics.increment("campaign_overview_read")
    return APIResponse(data=overview).to_dict()


@router.get("/{campaign_id}/touchpoints")
async def get_campaign_touchpoints(
    campaign_id: str,
    request: Request,
    channel: Optional[str] = Query(default=None),
    touchpoint_type: Optional[str] = Query(default=None),
    after: Optional[str] = Query(default=None),
    before: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: Optional[str] = Query(default=None),
):
    """Read touchpoints for a campaign with optional time and channel filters."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    from services.measurement.repositories.touchpoint_repo import TouchpointRepository
    tp_repo = TouchpointRepository()
    from datetime import datetime
    after_dt = datetime.fromisoformat(after.replace("Z", "+00:00")) if after else None
    before_dt = datetime.fromisoformat(before.replace("Z", "+00:00")) if before else None

    rows = await tp_repo.list_by_campaign(
        tenant.tenant_id, campaign_id,
        after_occurred=after_dt,
        before_occurred=before_dt,
        channel=channel,
        touchpoint_type=touchpoint_type,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = rows[-1].get("occurred_at") if len(rows) == limit else None
    metrics.increment("campaign_touchpoints_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "items": rows,
        "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
    }).to_dict()


# ── Communications surfaces (Phase 19) ───────────────────────────────────────

@router.get("/{campaign_id}/messages")
async def get_campaign_messages(campaign_id: str, request: Request):
    """Messages tab: per-message dimension rows merged with engagement stats.

    Human-qualified metrics exclude suspected machine activity; the raw
    provider-reported numbers ride alongside so the funnel toggle needs no
    second request.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    from services.comms.repository import CampaignMessageRepository, CommsFactsRepository
    dims = await CampaignMessageRepository().list_for_campaign(tenant.tenant_id, campaign_id)
    stats = await CommsFactsRepository().message_stats(tenant.tenant_id, campaign_id)

    dims_by_ext = {str(d.get("external_message_id")): d for d in dims}
    items = []
    seen = set()
    for stat in stats:
        ext_id = str(stat.get("external_message_id"))
        seen.add(ext_id)
        dim = dims_by_ext.get(ext_id, {})
        items.append({
            "external_message_id": ext_id,
            "message_id": str(dim["message_id"]) if dim.get("message_id") else None,
            "name": dim.get("name"),
            "status": dim.get("status", "active"),
            "sequence_step": stat.get("sequence_step") or dim.get("sequence_step"),
            "variant_id": dim.get("variant_id"),
            "delivered": int(stat.get("delivered") or 0),
            "human_clicks": int(stat.get("human_clicks") or 0),
            "replies": int(stat.get("replies") or 0),
            "bounces": int(stat.get("bounces") or 0),
            "machine_events": int(stat.get("machine_events") or 0),
            "total_events": int(stat.get("total_events") or 0),
        })
    # Synced messages that have no engagement yet still appear.
    for ext_id, dim in dims_by_ext.items():
        if ext_id not in seen:
            items.append({
                "external_message_id": ext_id,
                "message_id": str(dim["message_id"]) if dim.get("message_id") else None,
                "name": dim.get("name"),
                "status": dim.get("status", "active"),
                "sequence_step": dim.get("sequence_step"),
                "variant_id": dim.get("variant_id"),
                "delivered": 0, "human_clicks": 0, "replies": 0,
                "bounces": 0, "machine_events": 0, "total_events": 0,
            })
    metrics.increment("campaign_messages_read")
    return APIResponse(data={"campaign_id": campaign_id, "items": items}).to_dict()


@router.get("/{campaign_id}/messages/{external_message_id}")
async def get_campaign_message_detail(
    campaign_id: str,
    external_message_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
):
    """Message detail: dimension record, engagement facts, and link rollup."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    campaign = await _require_campaign(campaign_id, tenant)

    from services.comms.repository import CampaignMessageRepository, CommsFactsRepository
    facts_repo = CommsFactsRepository()
    provider = campaign.get("primary_platform") or "klaviyo"
    dim = await CampaignMessageRepository().get_by_external_id(
        tenant.tenant_id, provider, external_message_id,
    )
    stats = await facts_repo.message_stats(tenant.tenant_id, campaign_id)
    stat = next(
        (s for s in stats if str(s.get("external_message_id")) == external_message_id), {},
    )
    links = [
        l for l in await facts_repo.link_stats(tenant.tenant_id, campaign_id)
        if l.get("external_message_id") in (external_message_id, None)
    ]
    metrics.increment("campaign_message_detail_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "external_message_id": external_message_id,
        "message": {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in (dim or {}).items()},
        "stats": {k: int(v or 0) for k, v in stat.items() if k != "external_message_id"},
        "links": links,
    }).to_dict()


@router.get("/{campaign_id}/links")
async def get_campaign_links(campaign_id: str, request: Request):
    """Link performance: human-qualified clicks and unique clickers per link."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    from services.comms.repository import CommsFactsRepository
    links = await CommsFactsRepository().link_stats(tenant.tenant_id, campaign_id)
    metrics.increment("campaign_links_read")
    return APIResponse(data={"campaign_id": campaign_id, "items": links}).to_dict()


@router.get("/{campaign_id}/comms-population")
async def get_campaign_comms_population(
    campaign_id: str,
    request: Request,
    stage: Optional[str] = Query(default=None, pattern="^(observed|attempted|delivered|engaged|replied)$"),
    bounced: Optional[bool] = Query(default=None),
    suppressed: Optional[bool] = Query(default=None),
    unsubscribed: Optional[bool] = Query(default=None),
    complained: Optional[bool] = Query(default=None),
    human_qualified: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Recipient population with communication stages and filters (Phase 19).

    Stages reflect the highest state each recipient reached
    (attempted → delivered → engaged → replied); delivery flags (bounced,
    complained, unsubscribed, suppressed) compose with stage filters.
    Every row links to Profile360; recipients are alias-keyed — no raw
    addresses.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    from services.comms.repository import CommsFactsRepository
    rows = await CommsFactsRepository().campaign_population(
        tenant.tenant_id, campaign_id,
        stage=stage, bounced=bounced, suppressed=suppressed,
        unsubscribed=unsubscribed, complained=complained,
        human_qualified=human_qualified, limit=limit,
    )
    stage_counts: dict[str, int] = {}
    for row in rows:
        stage_counts[row["stage"]] = stage_counts.get(row["stage"], 0) + 1
    metrics.increment("campaign_comms_population_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "items": rows,
        "stage_counts": stage_counts,
        "count": len(rows),
    }).to_dict()


@router.get("/{campaign_id}/comms-funnel")
async def get_campaign_comms_funnel(campaign_id: str, request: Request):
    """Email funnel with provider-reported and human-qualified modes.

    ``provider_reported`` counts every provider event; ``human_qualified``
    excludes suspected machine activity and automated replies (ADR-C8).
    Rates are computed against delivered recipients.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    from services.comms.repository import CommsFactsRepository
    funnel = await CommsFactsRepository().campaign_funnel(tenant.tenant_id, campaign_id)
    funnel = {k: int(v or 0) for k, v in funnel.items()}
    delivered = funnel.get("delivered", 0)

    from shared.measurement.compute import rate_result
    from shared.measurement.registry import get_definition

    def measured_rate(metric_name: str, numerator: int, denominator: int) -> dict:
        definition = get_definition(metric_name)
        value, state, uncertainty, sufficiency = rate_result(
            numerator,
            denominator,
            metric_name=metric_name,
            definition=definition,
        )
        return {
            "metric_name": metric_name,
            "metric_version": definition.version if definition else "1",
            "value": round(value, 4) if value is not None else None,
            "value_state": state.value,
            "unit": definition.unit if definition else "ratio",
            "sufficiency": sufficiency,
            "uncertainty": (
                uncertainty.model_dump(mode="json") if uncertainty else None
            ),
            "lineage": {
                "source": "comms_facts",
                "tenant_id": tenant.tenant_id,
                "campaign_id": campaign_id,
                "denominator": "delivered",
            },
        }

    measurement_integrity = {
        "provider_open_rate": measured_rate(
            "email_open_rate", funnel.get("reported_opens", 0), delivered
        ),
        "provider_click_rate": measured_rate(
            "email_click_rate", funnel.get("reported_clicks", 0), delivered
        ),
        "human_open_rate": measured_rate(
            "email_open_rate", funnel.get("human_opens", 0), delivered
        ),
        "human_click_rate": measured_rate(
            "email_click_rate", funnel.get("human_clicks", 0), delivered
        ),
        "human_reply_rate": measured_rate(
            "email_reply_rate", funnel.get("replies", 0), delivered
        ),
        "machine_event_rate": measured_rate(
            "machine_event_rate",
            funnel.get("machine_events", 0),
            funnel.get("total_events", 0),
        ),
    }

    metrics.increment("campaign_comms_funnel_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "modes": {
            "provider_reported": {
                "sent": funnel.get("sent", 0),
                "delivered": delivered,
                "opens": funnel.get("reported_opens", 0),
                "clicks": funnel.get("reported_clicks", 0),
                "open_rate": measurement_integrity["provider_open_rate"]["value"],
                "click_rate": measurement_integrity["provider_click_rate"]["value"],
                "open_rate_result": measurement_integrity["provider_open_rate"],
                "click_rate_result": measurement_integrity["provider_click_rate"],
            },
            "human_qualified": {
                "sent": funnel.get("sent", 0),
                "delivered": delivered,
                "opens": funnel.get("human_opens", 0),
                "clicks": funnel.get("human_clicks", 0),
                "replies": funnel.get("replies", 0),
                "open_rate": measurement_integrity["human_open_rate"]["value"],
                "click_rate": measurement_integrity["human_click_rate"]["value"],
                "reply_rate": measurement_integrity["human_reply_rate"]["value"],
                "open_rate_result": measurement_integrity["human_open_rate"],
                "click_rate_result": measurement_integrity["human_click_rate"],
                "reply_rate_result": measurement_integrity["human_reply_rate"],
            },
        },
        "delivery": {
            "deferred": funnel.get("deferred", 0),
            "dropped": funnel.get("dropped", 0),
            "hard_bounces": funnel.get("hard_bounces", 0),
            "soft_bounces": funnel.get("soft_bounces", 0),
            "complaints": funnel.get("complaints", 0),
            "unsubscribes": funnel.get("unsubscribes", 0),
            "suppressions": funnel.get("suppressions", 0),
        },
        "quality": {
            "machine_events": funnel.get("machine_events", 0),
            "total_events": funnel.get("total_events", 0),
            "machine_event_rate": measurement_integrity["machine_event_rate"]["value"],
            "machine_event_rate_result": measurement_integrity["machine_event_rate"],
        },
        "measurement_integrity": measurement_integrity,
    }).to_dict()


@router.get("/{campaign_id}/population")
async def get_campaign_population(
    campaign_id: str,
    request: Request,
    population: str = Query(default="observed"),
    channel: Optional[str] = Query(default=None),
    cluster_id: Optional[str] = Query(default=None),
    time_start: Optional[str] = Query(default=None),
    time_end: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
):
    """Paginated population for a campaign at a given funnel stage."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    ctx = trace_request(request, service="campaign")
    time_range = None
    if time_start or time_end:
        time_range = {"start": time_start or "", "end": time_end or ""}

    result = await _explorer.get_population(
        tenant.tenant_id, campaign_id,
        population=population,
        time_range=time_range,
        channel=channel,
        cluster_id=cluster_id,
        limit=limit,
        cursor=cursor,
    )
    emit_latency("campaign_population", ctx.elapsed_ms())
    metrics.increment("campaign_population_read")
    return APIResponse(data=result).to_dict()


@router.get("/{campaign_id}/entities")
async def get_campaign_entities(
    campaign_id: str,
    request: Request,
    entity_type: Optional[str] = Query(default=None),
    time_start: Optional[str] = Query(default=None),
    time_end: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
):
    """Entity-level view of campaign participants, optionally filtered by type."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    time_range = None
    if time_start or time_end:
        time_range = {"start": time_start or "", "end": time_end or ""}
    entity_types = [entity_type] if entity_type else None

    result = await _explorer.get_entities(
        tenant.tenant_id, campaign_id,
        entity_types=entity_types,
        time_range=time_range,
        limit=limit,
        cursor=cursor,
    )
    metrics.increment("campaign_entities_read")
    return APIResponse(data=result).to_dict()


@router.get("/{campaign_id}/clusters")
async def get_campaign_clusters(
    campaign_id: str,
    request: Request,
    attribution_run_id: Optional[str] = Query(default=None),
    time_start: Optional[str] = Query(default=None),
    time_end: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
):
    """Cluster rollup with attribution economics for a campaign."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    time_range = None
    if time_start or time_end:
        time_range = {"start": time_start or "", "end": time_end or ""}

    result = await _explorer.get_clusters(
        tenant.tenant_id, campaign_id,
        time_range=time_range,
        attribution_run_id=attribution_run_id,
        limit=limit,
        cursor=cursor,
    )
    metrics.increment("campaign_clusters_read")
    return APIResponse(data=result).to_dict()


@router.get("/{campaign_id}/journeys")
async def get_campaign_journeys(
    campaign_id: str,
    request: Request,
    time_start: Optional[str] = Query(default=None),
    time_end: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
):
    """Journey versions that include this campaign."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    time_range = None
    if time_start or time_end:
        time_range = {"start": time_start or "", "end": time_end or ""}

    result = await _explorer.get_journeys(
        tenant.tenant_id, campaign_id,
        time_range=time_range,
        limit=limit,
        cursor=cursor,
    )
    metrics.increment("campaign_journeys_read")
    return APIResponse(data=result).to_dict()


@router.get("/{campaign_id}/conversions")
async def get_campaign_conversions(
    campaign_id: str,
    request: Request,
    cluster_id: Optional[str] = Query(default=None),
    conversion_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    attribution_run_id: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    after: Optional[str] = Query(default=None),
    before: Optional[str] = Query(default=None),
    include_unattributed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
):
    """Conversions linked to a campaign, with rich filtering."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    from services.measurement.repositories.conversion_repo import ConversionRepository
    cv_repo = ConversionRepository()
    from datetime import datetime
    after_dt = datetime.fromisoformat(after.replace("Z", "+00:00")) if after else None
    before_dt = datetime.fromisoformat(before.replace("Z", "+00:00")) if before else None

    rows = await cv_repo.list_by_campaign(
        tenant.tenant_id, campaign_id,
        cluster_id=cluster_id,
        conversion_type=conversion_type,
        status=status,
        attribution_run_id=attribution_run_id,
        channel=channel,
        after_occurred=after_dt,
        before_occurred=before_dt,
        include_unattributed=include_unattributed,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = rows[-1].get("occurred_at") if len(rows) == limit else None
    metrics.increment("campaign_conversions_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "items": rows,
        "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
    }).to_dict()


@router.post("/{campaign_id}/graph")
async def get_campaign_graph(
    campaign_id: str,
    body: CampaignGraphRequest,
    request: Request,
):
    """Campaign-anchored graph query. Hard limits: depth ≤ 3, nodes ≤ 500, edges ≤ 1500."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    ctx = trace_request(request, service="campaign")
    logger.info(
        "campaign graph query tenant=%s campaign=%s depth=%d",
        tenant.tenant_id, campaign_id, body.depth,
    )

    result = await _explorer.get_graph_anchor(
        tenant.tenant_id, campaign_id,
        request=body.model_dump(),
    )
    emit_latency("campaign_graph", ctx.elapsed_ms(), labels={"depth": str(body.depth)})
    metrics.increment("campaign_graph_queries")
    return APIResponse(data=result).to_dict()


# =============================================================================
# Campaign Registry sub-routes (external refs, aliases)
# =============================================================================

def _get_registry():
    from services.campaign.registry import CampaignRegistryService
    return CampaignRegistryService()


@router.get("/{campaign_id}/external-refs")
async def list_external_refs(campaign_id: str, request: Request):
    """List all external platform references for a canonical campaign."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    try:
        from services.campaign.repository import ExternalRefRepository
        ref_repo = ExternalRefRepository(None)
        refs = await ref_repo.list_for_campaign(tenant.tenant_id, campaign_id)
    except Exception as exc:
        logger.warning("external-refs unavailable: %s", exc)
        refs = []

    metrics.increment("campaign_external_refs_read")
    return APIResponse(data={"campaign_id": campaign_id, "items": refs}).to_dict()


class AliasCreate(BaseModel):
    alias_type: str = Field(..., description="e.g. utm_campaign, utm_id, external_campaign_id")
    alias_value: str
    platform: Optional[str] = None
    external_account_id: Optional[str] = None
    source: Optional[str] = None
    medium: Optional[str] = None


@router.get("/{campaign_id}/aliases")
async def list_aliases(campaign_id: str, request: Request):
    """List active campaign aliases."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    await _require_campaign(campaign_id, tenant)

    try:
        from services.campaign.repository import AliasRepository
        alias_repo = AliasRepository(None)
        aliases = await alias_repo.list_for_campaign(tenant.tenant_id, campaign_id)
    except Exception as exc:
        logger.warning("aliases unavailable: %s", exc)
        aliases = []

    metrics.increment("campaign_aliases_read")
    return APIResponse(data={"campaign_id": campaign_id, "items": aliases}).to_dict()


@router.post("/{campaign_id}/aliases")
async def add_alias(campaign_id: str, body: AliasCreate, request: Request):
    """Add a campaign alias (used for UTM/tracking resolution)."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    await _require_campaign(campaign_id, tenant)

    try:
        registry = _get_registry()
        alias_id = await registry.add_alias(
            tenant_id=tenant.tenant_id,
            campaign_id=campaign_id,
            alias_type=body.alias_type,
            alias_value=body.alias_value,
            platform=body.platform,
            external_account_id=body.external_account_id,
            source=body.source,
            medium=body.medium,
            created_by=getattr(tenant, "user_id", "api"),
        )
    except Exception as exc:
        raise BadRequestError(str(exc)) from exc

    metrics.increment("campaign_aliases_created")
    return APIResponse(data={"alias_id": str(alias_id) if alias_id else None}).to_dict()


@router.delete("/{campaign_id}/aliases/{alias_id}")
async def expire_alias(campaign_id: str, alias_id: str, request: Request):
    """Expire an active campaign alias."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    await _require_campaign(campaign_id, tenant)

    try:
        registry = _get_registry()
        await registry.expire_alias(tenant.tenant_id, alias_id)
    except Exception as exc:
        raise BadRequestError(str(exc)) from exc

    metrics.increment("campaign_aliases_expired")
    return APIResponse(data={"expired": True, "alias_id": alias_id}).to_dict()


# =============================================================================
# Campaign Sources router (/v1/campaign-sources)
# =============================================================================

sources_router = APIRouter(prefix="/v1/campaign-sources", tags=["Campaign Sources"])


class CampaignSourceCreate(BaseModel):
    # A source with an empty platform cannot be routed to a connector or
    # reconciled against provider truth, so it is rejected at the edge rather
    # than persisted as an unusable row.
    platform: str = Field(..., min_length=1)
    display_name: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


@sources_router.get("")
async def list_campaign_sources(request: Request):
    """List all connected campaign sources for the tenant."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT * FROM measurement_connectors WHERE tenant_id = $1 ORDER BY created_at DESC",
            tenant.tenant_id,
        ) if pool else []
        items = [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("campaign sources list failed: %s", exc)
        items = []
    return APIResponse(data={"items": items}).to_dict()


@sources_router.post("")
async def connect_campaign_source(body: CampaignSourceCreate, request: Request):
    """Connect a new campaign source (ad platform)."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    connector_id = str(uuid.uuid4())
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool:
            await pool.execute(
                """
                INSERT INTO measurement_connectors
                  (connector_id, tenant_id, connector_type, name, config, status,
                   cursor_state, health_status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'active', '{}'::jsonb, 'unknown', NOW(), NOW())
                """,
                connector_id, tenant.tenant_id, body.platform,
                body.display_name or body.platform,
                __import__("json").dumps(body.config) if body.config else "{}",
            )
    except Exception as exc:
        logger.warning("source connect failed: %s", exc)
    metrics.increment("campaign_sources_connected", labels={"platform": body.platform})
    return APIResponse(data={"connector_id": connector_id, "platform": body.platform}).to_dict()


@sources_router.get("/{connector_id}/health")
async def get_source_health(connector_id: str, request: Request):
    """Return health status of a campaign source connector."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT connector_id, connector_type, name, status, health_status, health_message, "
            "last_sync_at, last_success_at, error_count FROM measurement_connectors "
            "WHERE tenant_id = $1 AND connector_id = $2",
            tenant.tenant_id, connector_id,
        ) if pool else None
        if row is None:
            raise BadRequestError(f"Campaign source {connector_id} not found")
        health = {
            "connector_id": connector_id,
            "status": row["health_status"],
            "name": row["name"],
            "connector_type": row["connector_type"],
            "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
            "last_success_at": row["last_success_at"].isoformat() if row["last_success_at"] else None,
            "error_count": row["error_count"],
            "health_message": row["health_message"],
        }
        return APIResponse(data=health).to_dict()
    except BadRequestError:
        raise
    except Exception as exc:
        logger.warning("health_check unavailable: %s", exc)
        return APIResponse(data={"connector_id": connector_id, "status": "unknown", "error": str(exc)}).to_dict()


@sources_router.post("/{connector_id}/sync")
async def trigger_sync(connector_id: str, request: Request):
    """Trigger an incremental sync for a campaign source."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT connector_id FROM measurement_connectors WHERE tenant_id = $1 AND connector_id = $2",
            tenant.tenant_id, connector_id,
        ) if pool else None
        if row is None:
            raise BadRequestError(f"Campaign source {connector_id} not found")
        # Record sync request — the scheduler picks this up on its next tick.
        if pool:
            await pool.execute(
                "UPDATE measurement_connectors SET next_sync_at = NOW(), updated_at = NOW() "
                "WHERE tenant_id = $1 AND connector_id = $2",
                tenant.tenant_id, connector_id,
            )
        metrics.increment("campaign_source_sync_triggered", labels={"connector_id": connector_id})
        return APIResponse(data={"connector_id": connector_id, "status": "queued"}).to_dict()
    except BadRequestError:
        raise
    except Exception as exc:
        logger.warning("sync trigger failed: %s", exc)
        raise BadRequestError(str(exc)) from exc


# =============================================================================
# Mapping Review router (/v1/mapping-review)
# =============================================================================

mapping_router = APIRouter(prefix="/v1/mapping-review", tags=["Mapping Review"])


class ReviewResolve(BaseModel):
    campaign_id: str
    note: Optional[str] = None


class ReviewIgnore(BaseModel):
    note: Optional[str] = None


@mapping_router.get("")
async def list_mapping_reviews(
    request: Request,
    status: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
):
    """List campaign mapping reviews."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    try:
        registry = _get_registry()
        reviews = await registry.list_mapping_reviews(
            tenant_id=tenant.tenant_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except Exception as exc:
        logger.warning("mapping reviews unavailable: %s", exc)
        reviews = []
    next_cursor = reviews[-1].get("review_id") if len(reviews) == limit else None
    return APIResponse(data={
        "items": reviews,
        "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
    }).to_dict()


@mapping_router.post("/{review_id}/resolve")
async def resolve_mapping_review(review_id: str, body: ReviewResolve, request: Request):
    """Resolve a mapping review by assigning a canonical campaign_id."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        registry = _get_registry()
        await registry.resolve_review(
            tenant_id=tenant.tenant_id,
            review_id=review_id,
            campaign_id=body.campaign_id,
            resolved_by=getattr(tenant, "user_id", "api"),
            note=body.note,
        )
    except Exception as exc:
        raise BadRequestError(str(exc)) from exc
    metrics.increment("campaign_mapping_reviews_resolved")
    return APIResponse(data={"review_id": review_id, "status": "resolved"}).to_dict()


@mapping_router.post("/{review_id}/ignore")
async def ignore_mapping_review(review_id: str, body: ReviewIgnore, request: Request):
    """Ignore a mapping review (no auto-resolution will be attempted)."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        registry = _get_registry()
        await registry.ignore_review(tenant.tenant_id, review_id)
    except Exception as exc:
        raise BadRequestError(str(exc)) from exc
    metrics.increment("campaign_mapping_reviews_ignored")
    return APIResponse(data={"review_id": review_id, "status": "ignored"}).to_dict()


@mapping_router.post("/{review_id}/reopen")
async def reopen_mapping_review(review_id: str, request: Request):
    """Reopen an ignored or resolved mapping review."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        registry = _get_registry()
        await registry.reopen_review(tenant.tenant_id, review_id)
    except Exception as exc:
        raise BadRequestError(str(exc)) from exc
    return APIResponse(data={"review_id": review_id, "status": "open"}).to_dict()


# =============================================================================
# Campaign Quality router (/v1/campaign-quality)
# =============================================================================

quality_router = APIRouter(prefix="/v1/campaign-quality", tags=["Campaign Quality"])


@quality_router.get("")
async def get_campaign_quality(request: Request):
    """Return measurement quality metrics for the tenant's campaign data."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    try:
        registry = _get_registry()
        quality = await registry.get_mapping_quality(tenant.tenant_id)
    except Exception as exc:
        logger.warning("campaign quality unavailable: %s", exc)
        quality = {"error": str(exc), "status": "unavailable"}
    metrics.increment("campaign_quality_read")
    return APIResponse(data=quality).to_dict()

