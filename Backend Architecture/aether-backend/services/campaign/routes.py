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
from pydantic import BaseModel, Field, field_validator

from shared.common.common import (
    APIResponse, BadRequestError, NotFoundError, ServiceUnavailableError,
    PaginatedResponse, PaginationMeta,
)
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from shared.observability import trace_request, emit_latency
from dependencies.providers import get_producer
from repositories.repos import CampaignRepository
from services.campaign.ad_source_links import (
    ad_connect_options,
    connect_ad_source,
    overview_sources,
    set_source_account,
    set_source_enabled,
)
from services.campaign.exploration import CampaignPopulationExplorer
from services.measurement.connectors.ad_accounts import (
    is_ad_account_family,
    run_credential_test,
)
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.measurement_connector_repo import (
    MeasurementConnectorRepository,
)
from services.measurement.repositories.spend_repo import SpendRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = get_logger("aether.service.campaign")
router = APIRouter(prefix="/v1/campaigns", tags=["Campaigns"])

_repo = CampaignRepository()
_connector_repo = MeasurementConnectorRepository()
_explorer = CampaignPopulationExplorer(
    touchpoint_repo=TouchpointRepository(),
    conversion_repo=ConversionRepository(),
    run_repo=AttributionRunRepository(),
    journey_repo=JourneyRepository(),
    spend_repo=SpendRepository(),
)


def _list_source_status(degraded: bool, items: list) -> str:
    """Distinguish "the read failed" from "there is genuinely nothing".

    These handlers catch broadly and substitute an empty list, which without a
    status makes a broken read indistinguishable from an empty result. That is
    how GET /v1/campaigns/mapping-reviews returned an empty 200 to every caller
    for as long as its service call raised TypeError — the endpoint looked
    healthy and simply reported no work to do.

    Matches the vocabulary already used by the profile360 endpoints:
    ``missing`` (not consulted), ``empty`` (consulted, nothing there),
    ``available`` (consulted, has rows).
    """
    if degraded:
        return "missing"
    return "available" if items else "empty"


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
    properties: dict[str, Any] = Field(default_factory=dict)


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
        "campaign_id": campaign_id,
        "tenant_id": tenant.tenant_id,
        **body.model_dump(),
        # Operator-created campaigns are always custom-origin: the registry
        # contract distinguishes them from provider-synced (external) campaigns,
        # and a record without the label breaks that distinction downstream.
        "origin": "custom",
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

    # Write to the canonical touchpoint store. This is the ONLY durable path —
    # TOUCHPOINT_RECORDED has no subscriber — so a write failure must fail the
    # request. Previously the failure was swallowed and the event published,
    # returning 200 for a touchpoint that was never stored anywhere.
    tp_repo = TouchpointRepository()
    try:
        await tp_repo.upsert_from_campaign_touchpoint(
            tenant_id=tenant.tenant_id,
            campaign_id=campaign_id,
            touchpoint_id=touchpoint_id,
            data=touchpoint,
        )
    except Exception as exc:
        logger.error("Canonical touchpoint write failed: %s", exc)
        raise ServiceUnavailableError(
            "Touchpoint could not be durably recorded — please retry"
        ) from exc

    # Publish only after the durable write has succeeded.
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
    provider = campaign.get("primary_platform")
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
        refs_degraded = False
        ref_repo = ExternalRefRepository(None)
        refs = await ref_repo.list_for_campaign(tenant.tenant_id, campaign_id)
    except Exception as exc:
        logger.warning("external-refs unavailable: %s", exc)
        refs = []
        refs_degraded = True

    metrics.increment("campaign_external_refs_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "items": refs,
        "source_status": _list_source_status(refs_degraded, refs),
    }).to_dict()


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
        aliases_degraded = False
        alias_repo = AliasRepository(None)
        aliases = await alias_repo.list_for_campaign(tenant.tenant_id, campaign_id)
    except Exception as exc:
        logger.warning("aliases unavailable: %s", exc)
        aliases = []
        aliases_degraded = True

    metrics.increment("campaign_aliases_read")
    return APIResponse(data={
        "campaign_id": campaign_id,
        "items": aliases,
        "source_status": _list_source_status(aliases_degraded, aliases),
    }).to_dict()


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
    sources_degraded = False
    try:
        items = await _connector_repo.list_for_tenant(tenant.tenant_id)
    except Exception as exc:
        logger.warning("campaign sources list failed: %s", exc)
        items = []
        sources_degraded = True
    return APIResponse(data={
        "items": items,
        "source_status": _list_source_status(sources_degraded, items),
    }).to_dict()


@sources_router.post("")
async def connect_campaign_source(body: CampaignSourceCreate, request: Request):
    """Connect a new campaign source (ad platform).

    The connector is persisted through the canonical repository. A write failure
    surfaces as 503 rather than returning a fabricated ``connector_id`` for a
    source that was never stored (and that no subsequent ``list`` could see).
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        connector = await _connector_repo.create(
            tenant_id=tenant.tenant_id,
            connector_type=body.platform,
            name=body.display_name,
            config=body.config,
        )
    except Exception as exc:
        logger.error("source connect failed: %s", exc)
        raise ServiceUnavailableError(
            "Campaign source could not be connected — please retry"
        ) from exc
    metrics.increment("campaign_sources_connected", labels={"platform": body.platform})
    return APIResponse(data={
        "connector_id": connector["connector_id"],
        "platform": body.platform,
        "status": connector.get("status", "active"),
    }).to_dict()


@sources_router.get("/{connector_id}/health")
async def get_source_health(connector_id: str, request: Request):
    """Return health status of a campaign source connector."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    try:
        connector = await _connector_repo.get(tenant.tenant_id, connector_id)
    except Exception as exc:
        logger.error("source health read failed: %s", exc)
        raise ServiceUnavailableError(
            "Campaign source health unavailable — please retry"
        ) from exc
    if connector is None:
        raise BadRequestError(f"Campaign source {connector_id} not found")
    return APIResponse(data={
        "connector_id": connector_id,
        "status": connector.get("health_status", "unknown"),
        "name": connector.get("name"),
        "connector_type": connector.get("connector_type"),
        "last_sync_at": connector.get("last_sync_at"),
        "last_success_at": connector.get("last_success_at"),
        "error_count": connector.get("error_count", 0),
        "health_message": connector.get("health_message"),
    }).to_dict()


@sources_router.post("/{connector_id}/sync")
async def trigger_sync(connector_id: str, request: Request):
    """Trigger an incremental sync for a campaign source."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        queued = await _connector_repo.request_sync(tenant.tenant_id, connector_id)
    except Exception as exc:
        logger.error("sync trigger failed: %s", exc)
        raise ServiceUnavailableError(
            "Sync could not be queued — please retry"
        ) from exc
    if not queued:
        raise BadRequestError(f"Campaign source {connector_id} not found")
    metrics.increment("campaign_source_sync_triggered", labels={"connector_id": connector_id})
    return APIResponse(data={"connector_id": connector_id, "status": "queued"}).to_dict()


# =============================================================================
# Advertising connect flow (additive, WS-2) — /v1/campaign-sources/*
#
# Read-model + connect surface for the advertising convergence: list catalog ad
# platforms (options), connect a single-account source, test its credentials,
# select its account, disable/enable. Orchestration lives in
# services/campaign/ad_source_links.py; account/campaign resolution after a
# source is anchored stays in the /v1/mapping-review surface.
# =============================================================================


class AdConnectRequest(BaseModel):
    # A connect without a platform is meaningless — rejected at the edge.
    platform: str = Field(..., min_length=1, description="Ad platform family or its alias (e.g. google_ads, twitter, facebook)")
    name: Optional[str] = None
    # Complete credential set for the family (identifiers + secrets). A partial
    # set is rejected because the connector store has no config-update path.
    config: dict[str, Any] = Field(default_factory=dict)


class AdAccountSelectRequest(BaseModel):
    # Single-account manual selection: the account identifier the source is
    # bound to (customer_id / ad_account_id / advertiser_id / account_id).
    account_id: str = Field(..., min_length=1)


@sources_router.get("/overview")
async def campaign_sources_overview(request: Request):
    """Redacted overview of every connected campaign source.

    Never returns ``config`` — only non-secret facts (account id,
    secret-configured, health/sync state) projected by ad_source_links.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    degraded = False
    try:
        overview = await overview_sources(_connector_repo, tenant_id=tenant.tenant_id)
    except Exception as exc:
        logger.warning("campaign sources overview failed: %s", exc)
        degraded = True
        overview = {"items": [], "counts": {"total": 0, "active": 0, "disabled": 0, "ad_families": 0}, "ad_families": []}
    items = overview["items"]
    return APIResponse(data={
        "items": items,
        "counts": overview["counts"],
        "ad_families": overview["ad_families"],
        "source_status": _list_source_status(degraded, items),
    }).to_dict()


@sources_router.get("/ad-options")
async def campaign_sources_ad_options(request: Request):
    """List the ad platforms the tenant can connect, with connect state."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:read")
    degraded = False
    try:
        options = await ad_connect_options(_connector_repo, tenant_id=tenant.tenant_id)
    except Exception as exc:
        logger.warning("campaign sources ad-options failed: %s", exc)
        degraded = True
        options = []
    return APIResponse(data={
        "items": options,
        "source_status": _list_source_status(degraded, options),
    }).to_dict()


@sources_router.post("/connect")
async def connect_ad_campaign_source(body: AdConnectRequest, request: Request):
    """Connect (idempotently) an ad-platform campaign source.

    Idempotent per active source: if the tenant already has an active source
    for the platform, that source is returned unchanged (config is never
    silently overwritten). Incomplete credential sets and unbacked platforms
    are rejected with a clear message.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        result = await connect_ad_source(
            _connector_repo,
            tenant_id=tenant.tenant_id,
            platform=body.platform,
            name=body.name,
            config=body.config,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        logger.error("ad source connect failed: %s", exc)
        raise ServiceUnavailableError(
            "Ad platform could not be connected — please retry"
        ) from exc
    metrics.increment(
        "campaign_source_ad_connected",
        labels={"platform": result.get("platform", ""), "already": str(result.get("already_connected", False))},
    )
    return APIResponse(data=result).to_dict()


@sources_router.post("/{connector_id}/test")
async def test_campaign_source_credentials(connector_id: str, request: Request):
    """Run a live credential probe for an ad-platform source.

    Executes the family's own connector credential/health check against the
    stored config and reports the result. The probe is never persisted — a test
    must not fabricate a sync or health fact for a source that was not synced.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    connector = await _connector_repo.get(tenant.tenant_id, connector_id)
    if connector is None:
        raise BadRequestError(f"Campaign source {connector_id} not found")
    family = connector.get("connector_type") or ""
    if not is_ad_account_family(family):
        raise BadRequestError(
            f"Source {connector_id} is not an ad-platform source ({family!r}); "
            "credential tests apply to ad platforms only"
        )
    try:
        result = await run_credential_test(family, connector.get("config") or {})
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        logger.error("credential test failed: connector=%s %s", connector_id, exc)
        raise ServiceUnavailableError(
            "Credential test could not run — please retry"
        ) from exc
    metrics.increment("campaign_source_ad_tested", labels={"platform": family})
    return APIResponse(data=result).to_dict()


@sources_router.post("/{connector_id}/account")
async def select_campaign_source_account(connector_id: str, body: AdAccountSelectRequest, request: Request):
    """Select the single account an active ad source is bound to.

    Ad platforms have no account discovery, so selection is explicit/manual.
    Because the connector store has no config-update path, changing the account
    rotates the source: the current active row is archived (disabled) and a
    fresh active row carries the same credentials under the new account.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        result = await set_source_account(
            _connector_repo,
            tenant_id=tenant.tenant_id,
            connector_id=connector_id,
            account_id=body.account_id,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        logger.error("source account selection failed: %s", exc)
        raise ServiceUnavailableError(
            "Account selection failed — please retry"
        ) from exc
    metrics.increment("campaign_source_ad_account_set", labels={"platform": result.get("platform", "")})
    return APIResponse(data=result).to_dict()


@sources_router.post("/{connector_id}/disable")
async def disable_campaign_source(connector_id: str, request: Request):
    """Disable a campaign source (stops scheduling; row stays as history)."""
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        result = await set_source_enabled(
            _connector_repo, tenant_id=tenant.tenant_id,
            connector_id=connector_id, enabled=False,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        logger.error("source disable failed: %s", exc)
        raise ServiceUnavailableError("Source could not be disabled — please retry") from exc
    metrics.increment("campaign_source_disabled")
    return APIResponse(data=result).to_dict()


@sources_router.post("/{connector_id}/enable")
async def enable_campaign_source(connector_id: str, request: Request):
    """Re-enable a disabled campaign source.

    Refused when another active source exists for the same ad family, so the
    one-active-per-family invariant is never broken by re-enabling an archived
    row.
    """
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    try:
        result = await set_source_enabled(
            _connector_repo, tenant_id=tenant.tenant_id,
            connector_id=connector_id, enabled=True,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        logger.error("source enable failed: %s", exc)
        raise ServiceUnavailableError("Source could not be enabled — please retry") from exc
    metrics.increment("campaign_source_enabled")
    return APIResponse(data=result).to_dict()


# =============================================================================
# Mapping Review router (/v1/mapping-review)
# =============================================================================

mapping_router = APIRouter(prefix="/v1/mapping-review", tags=["Mapping Review"])


class ReviewResolve(BaseModel):
    # campaign_id is persisted as a UUID column; a malformed value is rejected
    # at the edge instead of surfacing as a database error mid-resolution.
    campaign_id: str
    note: Optional[str] = None

    @field_validator("campaign_id")
    @classmethod
    def _campaign_id_must_be_uuid(cls, value: str) -> str:
        uuid.UUID(value)
        return value


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
    reviews_degraded = False
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
        reviews_degraded = True
    next_cursor = reviews[-1].get("review_id") if len(reviews) == limit else None
    return APIResponse(data={
        "items": reviews,
        "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": next_cursor is not None},
        "source_status": _list_source_status(reviews_degraded, reviews),
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

