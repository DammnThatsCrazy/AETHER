"""
Aether Backend — Attribution Service Routes

Exposes multi-touch attribution resolution, touchpoint recording, and
journey inspection via a REST API.

Routes:
    POST /v1/attribution/resolve              Resolve attribution for a user event
    POST /v1/attribution/touchpoints          Record a touchpoint
    GET  /v1/attribution/journey/{user_id}    Get user journey touchpoints
    DELETE /v1/attribution/journey/{user_id}  Clear user journey
    GET  /v1/attribution/models               List available attribution models
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.attribution.resolver import (
    AttributionConfig,
    AttributionResolver,
    JourneyStore,
)
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.attribution")

router = APIRouter(prefix="/v1/attribution", tags=["attribution"])


# ========================================================================
# SINGLETONS (production: injected via DI container)
# ========================================================================

_config = AttributionConfig()
_resolver = AttributionResolver(_config)
_journey_store = JourneyStore()


def _get_tenant_id(request: Request, body_tenant_id: str | None = None) -> str:
    """Extract tenant_id from auth middleware; fall back to body/env in local mode."""
    if hasattr(request.state, "tenant") and request.state.tenant:
        return request.state.tenant.tenant_id
    env = os.getenv("AETHER_ENV", "local").lower()
    if env in ("local", "test"):
        return body_tenant_id or os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev")
    raise HTTPException(status_code=401, detail="Authentication required")


# ========================================================================
# REQUEST / RESPONSE MODELS
# ========================================================================

class TouchpointRequest(BaseModel):
    """Record a single touchpoint in a user journey."""
    user_id: str = Field(..., description="User or session identifier")
    channel: str = Field(..., description="Attribution channel (e.g. social, organic)")
    source: str = Field(..., description="Traffic source (e.g. twitter, google)")
    campaign: str = ""
    event_type: str = "pageview"
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp; defaults to now")
    properties: dict[str, Any] = Field(default_factory=dict)


class ResolveRequest(BaseModel):
    """Resolve attribution for a conversion event."""
    user_id: str = Field(..., description="User or session identifier")
    event: dict[str, Any] = Field(
        default_factory=dict,
        description="The conversion / target event data",
    )
    model: Optional[str] = Field(
        None,
        description="Attribution model override; uses server default if omitted",
    )
    touchpoints: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Inline touchpoints; if omitted, uses stored journey",
    )


class TouchpointResponse(BaseModel):
    channel: str
    source: str
    campaign: str
    timestamp: str
    event_type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class CreditResponse(BaseModel):
    channel: str
    source: str
    campaign: str
    timestamp: str
    event_type: str
    weight: float
    properties: dict[str, Any] = Field(default_factory=dict)


class ResolveResponse(BaseModel):
    model_used: str
    total_credit: float
    credits: list[CreditResponse]


# ========================================================================
# ROUTES
# ========================================================================

@router.post("/resolve", response_model=None)
@api_response
async def resolve_attribution(request: Request, body: ResolveRequest):
    """
    Resolve attribution for a user event.

    If ``touchpoints`` are provided inline they are used directly;
    otherwise the server looks up stored journey data for the user.
    """
    tenant_id = _get_tenant_id(request)

    if body.touchpoints is not None:
        raw_touchpoints = body.touchpoints
    else:
        raw_touchpoints = _journey_store.get(tenant_id, body.user_id)

    if not raw_touchpoints:
        raise HTTPException(
            status_code=404,
            detail=f"No touchpoints found for user {body.user_id!r}",
        )

    result = await _resolver.resolve(
        user_id=body.user_id,
        event=body.event,
        touchpoints=raw_touchpoints,
        model_name=body.model,
    )

    metrics.increment("attribution_resolve_requests", labels={"model": result.model_used})

    return result.to_dict()


@router.post("/touchpoints", response_model=None)
@api_response
async def record_touchpoint(request: Request, body: TouchpointRequest):
    """Record a touchpoint in a user's journey."""
    tenant_id = _get_tenant_id(request)
    ts = body.timestamp or datetime.now(timezone.utc).isoformat()

    raw: dict[str, Any] = {
        "channel": body.channel,
        "source": body.source,
        "campaign": body.campaign,
        "event_type": body.event_type,
        "timestamp": ts,
        "properties": body.properties,
    }
    _journey_store.add(tenant_id, body.user_id, raw)

    logger.info(
        "Touchpoint recorded: tenant=%s user=%s channel=%s source=%s",
        tenant_id, body.user_id, body.channel, body.source,
    )
    metrics.increment("attribution_touchpoints_recorded")

    return {
        "user_id": body.user_id,
        "touchpoint_count": _journey_store.count(tenant_id, body.user_id),
        "recorded": True,
    }


@router.get("/journey/{user_id}", response_model=None)
@api_response
async def get_journey(request: Request, user_id: str):
    """Return all stored touchpoints for a user journey."""
    tenant_id = _get_tenant_id(request)
    touchpoints = _journey_store.get(tenant_id, user_id)
    return {
        "user_id": user_id,
        "touchpoint_count": len(touchpoints),
        "touchpoints": touchpoints,
    }


@router.delete("/journey/{user_id}", response_model=None)
@api_response
async def clear_journey(request: Request, user_id: str):
    """Clear all stored touchpoints for a user."""
    tenant_id = _get_tenant_id(request)
    removed = _journey_store.clear(tenant_id, user_id)
    return {
        "user_id": user_id,
        "removed": removed,
    }


@router.get("/models", response_model=None)
@api_response
async def list_models():
    """List all available attribution models."""
    return {
        "default_model": _config.default_model,
        "available_models": _resolver.list_models(),
    }
