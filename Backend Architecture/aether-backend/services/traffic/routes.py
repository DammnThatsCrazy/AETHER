"""
Aether Backend — Automatic Traffic Source Tracking Service

Automatically creates and manages "virtual links" for all detected traffic sources.
No pre-created links required — everything is dynamically generated and aggregated.

Routes:
    POST /v1/track/traffic-source    Report a detected traffic source from SDK
    POST /v1/track/events            Track events with traffic source attribution
    GET  /v1/analytics/sources       Get aggregated traffic source analytics
    GET  /v1/analytics/sources/{id}  Get single traffic source details
    GET  /v1/analytics/channels      Get channel-level breakdown
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from shared.decorators import require_api_key_raw
from .classifier import SourceClassifier

logger = logging.getLogger("aether.traffic")

_classifier = SourceClassifier()

router = APIRouter(prefix="/v1", tags=["traffic"])


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class SourceInfo(BaseModel):
    source: str
    medium: str
    campaign: Optional[str] = None
    content: Optional[str] = None
    term: Optional[str] = None
    traffic_type: str = "unknown"
    referrer_domain: Optional[str] = None
    referrer_url: Optional[str] = None
    referrer_path: Optional[str] = None
    landing_page: str = "/"
    click_ids: dict[str, str] = Field(default_factory=dict)
    is_new_user: bool = True
    confidence: float = 0.0


class TrafficSourceRequest(BaseModel):
    session_id: str
    source: SourceInfo
    timestamp: str
    user_agent: Optional[str] = None
    screen_resolution: Optional[str] = None
    language: Optional[str] = None
    timezone_str: Optional[str] = None


class TrafficEventRequest(BaseModel):
    type: str                        # pageView, conversion, custom
    session_id: str
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)


class TrafficSourceResponse(BaseModel):
    id: str
    source: str
    medium: str
    campaign: Optional[str] = None
    traffic_type: str
    first_seen: str
    last_seen: str
    total_sessions: int
    total_page_views: int
    total_conversions: int
    total_revenue: float


class ChannelBreakdown(BaseModel):
    channel: str
    sessions: int
    page_views: int
    conversions: int
    revenue: float
    conversion_rate: float
    sources: list[TrafficSourceResponse]


# =============================================================================
# IN-MEMORY STORE (production: DynamoDB / PostgreSQL)
# =============================================================================

class TrafficStore:
    """Thread-safe in-memory store for traffic source data."""

    def __init__(self) -> None:
        self.sources: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}

    def get_or_create_source(self, api_key: str, info: SourceInfo) -> dict[str, Any]:
        key = self._source_key(api_key, info)
        if key not in self.sources:
            self.sources[key] = {
                "id": f"src_{uuid4().hex[:12]}",
                "api_key": api_key,
                "source": info.source,
                "medium": info.medium,
                "campaign": info.campaign,
                "content": info.content,
                "term": info.term,
                "traffic_type": info.traffic_type,
                "referrer_domain": info.referrer_domain,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "total_sessions": 0,
                "total_page_views": 0,
                "total_conversions": 0,
                "total_revenue": 0.0,
            }
        source = self.sources[key]
        source["last_seen"] = datetime.now(timezone.utc).isoformat()
        return source

    def record_session(
        self, source_id: str, session_id: str, info: SourceInfo, api_key: str,
        user_agent: str | None, request: TrafficSourceRequest,
    ) -> None:
        self.sessions[session_id] = {
            "id": session_id,
            "api_key": api_key,
            "traffic_source_id": source_id,
            "started_at": request.timestamp,
            "last_activity": request.timestamp,
            "is_new_user": info.is_new_user,
            "entry_page": info.landing_page,
            "landing_url": info.landing_page,
            "user_agent": user_agent,
            "screen_resolution": request.screen_resolution,
            "language": request.language,
            "timezone": request.timezone_str,
            "converted": False,
            "conversion_amount": 0.0,
        }
        # Increment session count on source
        key = self._source_key(api_key, info)
        if key in self.sources:
            self.sources[key]["total_sessions"] += 1

    def record_page_view(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        source_id = session["traffic_source_id"]
        for src in self.sources.values():
            if src["id"] == source_id:
                src["total_page_views"] += 1
                break
        session["last_activity"] = datetime.now(timezone.utc).isoformat()

    def record_conversion(self, session_id: str, amount: float) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        source_id = session["traffic_source_id"]
        for src in self.sources.values():
            if src["id"] == source_id:
                src["total_conversions"] += 1
                src["total_revenue"] += amount
                break
        session["converted"] = True
        session["conversion_amount"] = amount
        session["last_activity"] = datetime.now(timezone.utc).isoformat()

    def get_sources(self, api_key: str) -> list[dict[str, Any]]:
        return [s for s in self.sources.values() if s.get("api_key") == api_key]

    def get_source_by_id(self, source_id: str, api_key: str) -> dict[str, Any] | None:
        for src in self.sources.values():
            if src["id"] == source_id and src.get("api_key") == api_key:
                return src
        return None

    def _source_key(self, api_key: str, info: SourceInfo) -> str:
        raw = f"{api_key}::{info.source}::{info.medium}::{info.campaign or ''}"
        return hashlib.md5(raw.lower().encode()).hexdigest()


_store = TrafficStore()


# =============================================================================
# ROUTES
# =============================================================================

@router.post("/track/traffic-source")
async def report_traffic_source(
    body: TrafficSourceRequest,
    api_key: str = Depends(require_api_key_raw),
) -> dict[str, Any]:
    """
    Called by the client SDK on every new session to report the detected source.
    Classifies raw signals into source/medium/channel, then creates or updates
    the virtual traffic source entry and records the session.
    """
    # Classify raw traffic signals into source/medium/channel
    classified = _classifier.classify(
        referrer=body.source.referrer_url or "",
        referrer_domain=body.source.referrer_domain or "",
        utm_source=body.source.source if body.source.source not in ("(direct)", "", "unknown") else None,
        utm_medium=body.source.medium if body.source.medium not in ("(none)", "", "unknown") else None,
        utm_campaign=body.source.campaign,
        click_ids=body.source.click_ids,
        landing_page=body.source.landing_page,
    )

    # Override raw values with classified results
    body.source.source = classified.source
    body.source.medium = classified.medium
    body.source.traffic_type = classified.channel
    body.source.confidence = classified.confidence

    source = _store.get_or_create_source(api_key, body.source)
    _store.record_session(
        source_id=source["id"],
        session_id=body.session_id,
        info=body.source,
        api_key=api_key,
        user_agent=body.user_agent,
        request=body,
    )

    logger.info(
        "Traffic source reported: %s/%s (type=%s, session=%s)",
        body.source.source, body.source.medium, body.source.traffic_type, body.session_id,
    )

    return {
        "success": True,
        "traffic_source_id": source["id"],
        "session_id": body.session_id,
        "is_new_source": source["total_sessions"] == 1,
    }


@router.post("/track/events")
async def track_event(
    body: TrafficEventRequest,
    api_key: str = Depends(require_api_key_raw),
) -> dict[str, Any]:
    """Track page views, conversions, and custom events with source attribution."""
    event_id = str(uuid4())

    if body.type == "pageView":
        _store.record_page_view(body.session_id)
    elif body.type == "conversion":
        amount = body.data.get("amount", 0.0)
        _store.record_conversion(body.session_id, float(amount))

    return {"success": True, "event_id": event_id}


@router.get("/analytics/sources")
async def get_traffic_sources(
    api_key: str = Depends(require_api_key_raw),
) -> dict[str, Any]:
    """Get all traffic sources with aggregated stats."""
    sources = _store.get_sources(api_key)
    total_sessions = sum(s["total_sessions"] for s in sources)
    total_conversions = sum(s["total_conversions"] for s in sources)
    total_revenue = sum(s["total_revenue"] for s in sources)

    return {
        "total_sources": len(sources),
        "total_sessions": total_sessions,
        "total_conversions": total_conversions,
        "total_revenue": total_revenue,
        "overall_conversion_rate": (total_conversions / max(total_sessions, 1)) * 100,
        "sources": [
            TrafficSourceResponse(
                id=s["id"],
                source=s["source"],
                medium=s["medium"],
                campaign=s.get("campaign"),
                traffic_type=s["traffic_type"],
                first_seen=s["first_seen"],
                last_seen=s["last_seen"],
                total_sessions=s["total_sessions"],
                total_page_views=s["total_page_views"],
                total_conversions=s["total_conversions"],
                total_revenue=s["total_revenue"],
            ).model_dump()
            for s in sorted(sources, key=lambda x: x["total_sessions"], reverse=True)
        ],
    }


@router.get("/analytics/sources/{source_id}")
async def get_traffic_source_detail(
    source_id: str,
    api_key: str = Depends(require_api_key_raw),
) -> dict[str, Any]:
    """Get detailed info for a single traffic source."""
    source = _store.get_source_by_id(source_id, api_key)
    if not source:
        raise HTTPException(status_code=404, detail="Traffic source not found")
    return TrafficSourceResponse(**{
        k: source[k]
        for k in TrafficSourceResponse.model_fields
    }).model_dump()


@router.get("/analytics/channels")
async def get_channel_breakdown(
    api_key: str = Depends(require_api_key_raw),
) -> dict[str, Any]:
    """Get traffic data aggregated by channel (traffic_type)."""
    sources = _store.get_sources(api_key)
    channels: dict[str, dict[str, Any]] = {}

    for src in sources:
        ch = src["traffic_type"]
        if ch not in channels:
            channels[ch] = {
                "channel": ch, "sessions": 0, "page_views": 0,
                "conversions": 0, "revenue": 0.0, "sources": [],
            }
        channels[ch]["sessions"] += src["total_sessions"]
        channels[ch]["page_views"] += src["total_page_views"]
        channels[ch]["conversions"] += src["total_conversions"]
        channels[ch]["revenue"] += src["total_revenue"]
        channels[ch]["sources"].append(
            TrafficSourceResponse(
                id=src["id"], source=src["source"], medium=src["medium"],
                campaign=src.get("campaign"), traffic_type=src["traffic_type"],
                first_seen=src["first_seen"], last_seen=src["last_seen"],
                total_sessions=src["total_sessions"], total_page_views=src["total_page_views"],
                total_conversions=src["total_conversions"], total_revenue=src["total_revenue"],
            ).model_dump()
        )

    for ch in channels.values():
        ch["conversion_rate"] = round(
            (ch["conversions"] / max(ch["sessions"], 1)) * 100, 2,
        )

    return {
        "channels": sorted(channels.values(), key=lambda x: x["sessions"], reverse=True),
    }
