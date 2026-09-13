"""
Aether Service — Ingestion
Event validation, normalization, and queuing from SDK, API feeds, and Agent.
Tech: Node.js (Fastify) in prod — Python/FastAPI scaffold.
Scaling: Horizontal autoscaling on event volume.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from shared.common.common import (
    APIResponse,
    BadRequestError,
    utc_now,
)
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

logger = get_logger("aether.service.ingestion")
router = APIRouter(prefix="/v1/ingest", tags=["Ingestion"])

# Dependencies (injected at app startup)
_producer = EventProducer()


# ── Request / Response Models ─────────────────────────────────────────

class SDKEvent(BaseModel):
    event_type: str = Field(..., description="e.g. page_view, click, custom")
    session_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
    user_id: str | None = None
    device_id: str | None = None


class BatchEventsRequest(BaseModel):
    events: list[SDKEvent] = Field(..., min_length=1, max_length=500)


class APIFeedEvent(BaseModel):
    source: str = Field(..., description="e.g. dune, strategy, custom_api")
    entity_type: str
    data: dict[str, Any]


# ── Routes ────────────────────────────────────────────────────────────

@router.post("/events")
async def ingest_single_event(event: SDKEvent, request: Request):
    """Ingest a single SDK event."""
    tenant = request.state.tenant
    validated = _validate_and_normalize(event, tenant.tenant_id)

    await _producer.publish(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=tenant.tenant_id,
        source_service="ingestion",
        payload=validated,
    ))

    return APIResponse(data={"event_id": validated["event_id"], "status": "accepted"}).to_dict()


@router.post("/events/batch")
async def ingest_batch_events(batch: BatchEventsRequest, request: Request):
    """Ingest a batch of SDK events (up to 500)."""
    tenant = request.state.tenant
    event_ids = []

    events_to_publish = []
    for sdk_event in batch.events:
        validated = _validate_and_normalize(sdk_event, tenant.tenant_id)
        event_ids.append(validated["event_id"])
        events_to_publish.append(Event(
            topic=Topic.SDK_EVENTS_VALIDATED,
            tenant_id=tenant.tenant_id,
            source_service="ingestion",
            payload=validated,
        ))

    await _producer.publish_batch(events_to_publish)

    return APIResponse(
        data={"accepted": len(event_ids), "event_ids": event_ids}
    ).to_dict()


@router.post("/feed")
async def ingest_api_feed(feed_event: APIFeedEvent, request: Request):
    """Ingest data from external API feeds (Dune, Strategy, etc.)."""
    tenant = request.state.tenant

    await _producer.publish(Event(
        topic=Topic.API_FEED_RAW,
        tenant_id=tenant.tenant_id,
        source_service="ingestion",
        payload={
            "source": feed_event.source,
            "entity_type": feed_event.entity_type,
            "data": feed_event.data,
            "received_at": utc_now().isoformat(),
        },
    ))

    return APIResponse(data={"status": "accepted", "source": feed_event.source}).to_dict()


# ── Internal Helpers ──────────────────────────────────────────────────

def _validate_and_normalize(event: SDKEvent, tenant_id: str) -> dict:
    """Validate event fields and normalize to canonical schema."""
    if not event.event_type:
        raise BadRequestError("event_type is required")

    return {
        "event_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "event_type": event.event_type.lower().strip(),
        "session_id": event.session_id,
        "user_id": event.user_id,
        "device_id": event.device_id,
        "properties": event.properties,
        "timestamp": event.timestamp or utc_now().isoformat(),
        "ingested_at": utc_now().isoformat(),
    }
