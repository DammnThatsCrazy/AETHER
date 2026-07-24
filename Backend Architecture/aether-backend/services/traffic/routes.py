"""
Aether Backend — Automatic Traffic Source Tracking Service

Automatically creates and manages "virtual links" for all detected traffic sources.
No pre-created links required — everything is dynamically generated and aggregated.

Routes:
    POST /v1/referral-links                 Create a controlled verified link
    GET  /v1/referral-links                 List tenant-scoped link metadata
    POST /v1/referral-links/{id}/revoke     Revoke a controlled verified link
    GET  /v1/r/{token}                      Verified source-link redirect (public)
    POST /v1/track/traffic-source    Report a detected traffic source from SDK
    POST /v1/track/events            Track events with traffic source attribution
    GET  /v1/analytics/sources       Get aggregated traffic source analytics
    GET  /v1/analytics/sources/{id}  Get single traffic source details
    GET  /v1/analytics/channels      Get channel-level breakdown
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from shared.auth.auth import Role, TenantContext
from shared.decorators import require_api_key, require_api_key_raw
from shared.logger.logger import metrics
from . import metrics as traffic_metrics
from .classifier import SourceClassifier
from .referral_links import VerifiedReferralLinkRepository

logger = logging.getLogger("aether.traffic")

_classifier = SourceClassifier()
_verified_referral_links = VerifiedReferralLinkRepository()

router = APIRouter(prefix="/v1", tags=["traffic"])


def _referral_link_access_allowed(tenant: TenantContext, permission: str) -> bool:
    """Keep browser/viewer keys outside the verified-evidence control plane."""

    if tenant.role in {Role.ADMIN, Role.EDITOR, Role.SERVICE}:
        return True
    return tenant.has_permission(permission)


async def _require_referral_link_read(
    tenant: TenantContext = Depends(require_api_key),
) -> TenantContext:
    if not (
        _referral_link_access_allowed(tenant, "referral_links:read")
        or _referral_link_access_allowed(tenant, "referral_links:write")
    ):
        raise HTTPException(status_code=403, detail="Referral-link read access required")
    return tenant


async def _require_referral_link_write(
    tenant: TenantContext = Depends(require_api_key),
) -> TenantContext:
    if not _referral_link_access_allowed(tenant, "referral_links:write"):
        raise HTTPException(status_code=403, detail="Referral-link write access required")
    return tenant


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


class VerifiedReferralLinkCreate(BaseModel):
    """Controlled source metadata bound to a one-time-disclosed opaque token."""

    placement_id: Optional[str] = Field(default=None, max_length=255)
    agent_id: Optional[str] = Field(default=None, max_length=255)
    campaign_id: Optional[str] = Field(default=None, max_length=255)
    ai_provider: Optional[str] = Field(default=None, max_length=128)
    ai_product: Optional[str] = Field(default=None, max_length=128)
    referral_mediation_type: str = Field(
        default="agent_mediated_referral", min_length=1, max_length=64
    )
    expires_at: Optional[datetime] = None
    # Canonical placement vocabulary — validated against the generated
    # traffic-source registry at repository create time.
    source: Optional[str] = Field(default=None, max_length=128)
    medium: Optional[str] = Field(default=None, max_length=128)
    channel_family: Optional[str] = Field(default=None, max_length=64)
    economic_class: Optional[str] = Field(default=None, max_length=64)
    source_class: Optional[str] = Field(default=None, max_length=64)
    destination_url: Optional[str] = Field(default=None, max_length=2048)
    valid_from: Optional[datetime] = None
    environment: Optional[str] = Field(default=None, max_length=64)
    max_uses: Optional[int] = Field(default=None, ge=1)
    metadata: Optional[dict[str, str]] = None


class VerifiedReferralLinkRevoke(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


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


def _deployment_environment() -> str:
    """Environment this API instance serves; links may bind to one environment."""

    return (os.environ.get("AETHER_ENVIRONMENT") or "production").strip().lower()


async def _audit_referral_link_event(
    *,
    actor_id: str,
    action: str,
    tenant_id: Optional[str],
    resource_id: Optional[str],
    outcome: str,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Best-effort tamper-evident audit trail; never blocks the request path."""

    try:
        from services.security.audit_ledger import AuditLedger

        await AuditLedger().record(
            actor_id=actor_id,
            actor_type="system" if actor_id == "public_redirect" else "tenant_user",
            event_type="verified_source_link",
            resource_type="verified_referral_link",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            resource_id=resource_id,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover — audit must not block traffic
        logger.warning("verified_source_link_audit_failed action=%s: %s", action, exc)


def _append_handoff_param(destination_url: str, handoff_token: str) -> str:
    """Append aether_ref=<handoff> to the link-owned destination URL only."""

    parsed = urlsplit(destination_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "aether_ref"
    ]
    query.append(("aether_ref", handoff_token))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )


# =============================================================================
# ROUTES
# =============================================================================

@router.post("/referral-links", status_code=201)
async def create_verified_referral_link(
    body: VerifiedReferralLinkCreate,
    tenant: TenantContext = Depends(_require_referral_link_write),
) -> dict[str, Any]:
    """Create a tenant-scoped verified referral link.

    ``referral_token`` is disclosed only in this response.  Store it in the
    controlled agent or placement and send it as the ``aether_ref`` query
    parameter; subsequent list responses never contain the token or its hash.
    """

    try:
        link, token = await _verified_referral_links.create(
            tenant.tenant_id,
            placement_id=body.placement_id,
            agent_id=body.agent_id,
            campaign_id=body.campaign_id,
            ai_provider=body.ai_provider,
            ai_product=body.ai_product,
            referral_mediation_type=body.referral_mediation_type,
            expires_at=body.expires_at,
            created_by=tenant.user_id,
            source=body.source,
            medium=body.medium,
            channel_family=body.channel_family,
            economic_class=body.economic_class,
            source_class=body.source_class,
            destination_url=body.destination_url,
            valid_from=body.valid_from,
            environment=body.environment,
            max_uses=body.max_uses,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _audit_referral_link_event(
        actor_id=str(tenant.user_id or tenant.tenant_id),
        action="create",
        tenant_id=tenant.tenant_id,
        resource_id=str(link["verified_referral_link_id"]),
        outcome="success",
        metadata={
            "placement_id": link.get("placement_id"),
            "source_class": link.get("source_class"),
            "environment": link.get("environment"),
        },
    )
    return {
        "link": link,
        "referral_token": token,
        "query_parameter": "aether_ref",
    }


@router.get("/referral-links")
async def list_verified_referral_links(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(_require_referral_link_read),
) -> dict[str, Any]:
    """List only the authenticated tenant's public referral-link metadata."""

    try:
        links = await _verified_referral_links.list(
            tenant.tenant_id, status=status, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "links": links,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(links),
        },
    }


@router.post("/referral-links/{verified_referral_link_id}/revoke")
async def revoke_verified_referral_link(
    verified_referral_link_id: str,
    body: VerifiedReferralLinkRevoke,
    tenant: TenantContext = Depends(_require_referral_link_write),
) -> dict[str, Any]:
    """Idempotently revoke a link owned by the authenticated tenant."""

    link = await _verified_referral_links.revoke(
        tenant.tenant_id,
        verified_referral_link_id,
        revoked_by=tenant.user_id,
        reason=body.reason,
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Verified referral link not found")
    await _audit_referral_link_event(
        actor_id=str(tenant.user_id or tenant.tenant_id),
        action="revoke",
        tenant_id=tenant.tenant_id,
        resource_id=str(link["verified_referral_link_id"]),
        outcome="success",
        metadata={"reason": body.reason},
    )
    return {"link": link}


@router.get("/r/{token}", include_in_schema=False)
async def redirect_verified_source_link(token: str, request: Request) -> RedirectResponse:
    """Public verified source-link redirect with server-observed proof.

    - Constant-time token-hash lookup; expiry/revocation/valid-from/
      environment/max-use enforcement all collapse into a uniform 404 so the
      endpoint never becomes a token-state oracle.
    - The visitor is ONLY ever redirected to the link's stored
      ``destination_url`` — request-supplied destinations are impossible.
    - Machine/scanner/link-preview user agents are recorded flagged
      ``is_machine`` and redirected WITHOUT a human handoff token.
    - Human requests mint a one-time ~15-minute handoff token (sha256-hashed
      at rest) appended as ``aether_ref`` for SDK pickup on the destination.
    """

    user_agent = request.headers.get("user-agent", "")
    _redirect_started = time.monotonic()
    try:
        result = await _verified_referral_links.resolve_redirect(
            token,
            environment=_deployment_environment(),
            user_agent=user_agent,
        )
    except Exception as exc:
        logger.warning("verified_source_link_redirect_error: %s", exc)
        metrics.increment(
            "verified_source_link_redirect_total", labels={"status": "error"}
        )
        traffic_metrics.record_redirect_latency(
            (time.monotonic() - _redirect_started) * 1000
        )
        raise HTTPException(status_code=404, detail="Not found") from exc

    if result is None:
        # Uniform not-found: unknown, expired, revoked, wrong-environment,
        # not-yet-valid, and exhausted tokens are indistinguishable.
        metrics.increment(
            "verified_source_link_redirect_total", labels={"status": "rejected"}
        )
        # An unresolvable token is also an invalid source-link signal (spec §16).
        traffic_metrics.record_invalid_source_link()
        traffic_metrics.record_redirect_latency(
            (time.monotonic() - _redirect_started) * 1000
        )
        raise HTTPException(status_code=404, detail="Not found")

    status = "machine" if result["is_machine"] else "verified"
    metrics.increment(
        "verified_source_link_redirect_total", labels={"status": status}
    )
    await _audit_referral_link_event(
        actor_id="public_redirect",
        action="verify",
        tenant_id=result["tenant_id"],
        resource_id=str(result["link"]["verified_referral_link_id"]),
        outcome="success",
        metadata={
            "use_id": result["use_id"],
            "ua_class": result["ua_class"],
            "is_machine": result["is_machine"],
        },
    )

    traffic_metrics.record_redirect_latency(
        (time.monotonic() - _redirect_started) * 1000
    )
    destination = result["destination_url"]
    if result["handoff_token"]:
        destination = _append_handoff_param(destination, result["handoff_token"])
    return RedirectResponse(url=destination, status_code=302)


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
