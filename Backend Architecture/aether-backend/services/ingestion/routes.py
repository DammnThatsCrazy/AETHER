"""
Aether Service — Ingestion
Event validation, normalization, and queuing from SDK, API feeds, and Agent.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, ForbiddenError, utc_now
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_producer
from repositories.lake import BronzeRepository

logger = get_logger("aether.service.ingestion")
router = APIRouter(prefix="/v1/ingest", tags=["Ingestion"])


# ── Request / Response Models ─────────────────────────────────────────

class SDKEvent(BaseModel):
    event_type: str = Field(..., description="e.g. page_view, click, custom")
    session_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[str] = None
    user_id: Optional[str] = None
    device_id: Optional[str] = None


class BatchEventsRequest(BaseModel):
    events: list[SDKEvent] = Field(..., min_length=1, max_length=500)


class APIFeedEvent(BaseModel):
    source: str = Field(..., description="e.g. dune, strategy, custom_api")
    entity_type: str
    data: dict[str, Any]
    external_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Deterministic provider record ID used for idempotency",
    )
    # Optional per-subject (S-class) escalation: a feed is normally T-class
    # (tenant back-office attests rights). When a caller also declares the
    # subject + purpose, the feed runs the same server-receipt consent gate as
    # the batch path (via the shared ingress facade) and a denial is a 403.
    subject_id: Optional[str] = Field(
        default=None,
        description="Optional subject id; presence (with purpose) escalates the "
        "feed to a per-subject server-consent check",
    )
    anonymous_id: Optional[str] = Field(default=None)
    purpose: Optional[str] = Field(
        default=None,
        description="Optional consent purpose; presence (with a subject) escalates "
        "the feed to a per-subject server-consent check",
    )


# ── Routes ────────────────────────────────────────────────────────────

@router.post("/events", deprecated=True)
async def ingest_single_event(
    event: SDKEvent,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Deprecated: use POST /v1/batch instead.

    Retained as a server-to-server alias with full validation and tenant scoping.
    SDKs MUST use /v1/batch. Converged (WS-B2) onto the canonical V1 spine: the
    legacy wire event is normalized to a canonical BaseEvent and routed through
    services.ingestion.batch.ingest_events, so validation / consent / scrub /
    Bronze-durable / idempotency / publish semantics match /v1/batch.
    """
    # Convergence closes the missing-auth gap: aliases now require WRITE like
    # /v1/batch and /feed (permission checked before translation/kill-flag).
    from shared.auth.auth import Permissions
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    from config.settings import settings
    if settings.deprecated_ingest_aliases.kill_enabled:
        raise HTTPException(
            status_code=410,
            detail={
                "message": "POST /v1/ingest/events is deprecated and retired; "
                           "use POST /v1/batch",
                "replacement": "POST /v1/batch",
                "deprecated": True,
            },
        )

    from pydantic import ValidationError
    from services.ingestion.batch import BaseEvent, EventContext, ingest_events
    from services.ingestion.validation import RequestPrivacySignals

    try:
        canonical = _alias_event_to_canonical(
            event, BaseEvent=BaseEvent, EventContext=EventContext
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"POST /v1/ingest/events: invalid event payload: {exc}",
            },
        )

    resp = await ingest_events(
        [canonical],
        tenant_id=tenant.tenant_id,
        request_privacy=RequestPrivacySignals.from_headers(request.headers),
        server_context=None,
        granted_consents=frozenset(),
        sent_at=None,
        producer=producer,
    )
    result = resp.events[0]
    return APIResponse(
        data={"event_id": result.id, "status": result.status}
    ).to_dict()


@router.post("/events/batch", deprecated=True)
async def ingest_batch_events(
    batch: BatchEventsRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Deprecated: use POST /v1/batch instead.

    Retained as a server-to-server alias. SDKs MUST use /v1/batch. Converged
    (WS-B2): every event is normalized to a canonical BaseEvent and routed
    through services.ingestion.batch.ingest_events, matching /v1/batch
    semantics. Accepted events are Bronze-durable before the bus publish.
    """
    # Convergence closes the missing-auth gap: aliases now require WRITE like
    # /v1/batch and /feed (permission checked before translation/kill-flag).
    from shared.auth.auth import Permissions
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    from config.settings import settings
    if settings.deprecated_ingest_aliases.kill_enabled:
        raise HTTPException(
            status_code=410,
            detail={
                "message": "POST /v1/ingest/events/batch is deprecated and retired; "
                           "use POST /v1/batch",
                "replacement": "POST /v1/batch",
                "deprecated": True,
            },
        )

    from pydantic import ValidationError
    from services.ingestion.batch import BaseEvent, EventContext, ingest_events
    from services.ingestion.validation import RequestPrivacySignals

    try:
        canonical_events = [
            _alias_event_to_canonical(
                e, BaseEvent=BaseEvent, EventContext=EventContext
            )
            for e in batch.events
        ]
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"POST /v1/ingest/events/batch: invalid event payload: {exc}",
            },
        )

    resp = await ingest_events(
        canonical_events,
        tenant_id=tenant.tenant_id,
        request_privacy=RequestPrivacySignals.from_headers(request.headers),
        server_context=None,
        granted_consents=frozenset(),
        sent_at=None,
        producer=producer,
    )
    accepted_event_ids = [r.id for r in resp.events if r.status == "accepted"]
    return APIResponse(
        data={"accepted": len(accepted_event_ids), "event_ids": accepted_event_ids}
    ).to_dict()


def _alias_event_to_canonical(
    event: SDKEvent, *,
    BaseEvent,
    EventContext,
):
    """Translate a deprecated-alias wire event onto the canonical BaseEvent model.

    The server generates the event id — per-request retry-dedup is not possible
    on this alias; client dedup requires POST /v1/batch. The legacy wire has no
    anonymous concept, so anonymousId mirrors the session id. Canonical Silver's
    touchpoint_projector reads context.device.id, so a legacy device_id maps onto
    context.device.id when present. Non-canonical legacy types (page_view / click
    / custom, ...) are no longer silently published: the canonical validator now
    rejects them per-event with unknown_event_type — the intended WS-B2
    enforcement. A supplied timestamp that fails ISO parsing raises pydantic
    ValidationError here; the handlers convert it to HTTP 400.
    """
    context = (
        EventContext(device={"id": event.device_id})
        if event.device_id
        else EventContext()
    )
    return BaseEvent(
        id=str(uuid.uuid4()),
        type=(event.event_type or "").lower().strip(),
        sessionId=event.session_id,
        anonymousId=event.session_id,
        userId=event.user_id,
        properties=event.properties or {},
        context=context,
        timestamp=event.timestamp or utc_now().isoformat(),
    )


@router.post("/feed")
async def ingest_api_feed(
    feed_event: APIFeedEvent,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Ingest data from external API feeds (Dune, Strategy, etc.).

    external_id is required for idempotency — the same (source, external_id)
    pair from the same tenant is deduplicated.
    """
    from shared.auth.auth import Permissions
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    received_at = utc_now().isoformat()

    # WS-B3 ingress consent (T class). scrub_sensitive_fields + strip of any
    # client-asserted canonical entity ids + the tenant data-policy decision are
    # the MANDATORY T-class minimization layer and run UNCONDITIONALLY before any
    # durable Bronze write — they are never gated by the per-path flag (scrub
    # never rejects and data-policy is default-allow, so this is a pure
    # convergence). Only the per-subject (S) server-receipt escalation is a
    # per-path toggle: when a caller ALSO declares subject+purpose (the optional
    # APIFeedEvent fields) AND the feed S-gate is enabled, the same facade runs
    # the server-consent check (itself gated by the authoritative flag). Denials
    # are 403s — the feed is idempotent, so reject-and-retry is correct (no
    # quarantine).
    from config.settings import settings
    from services.ingestion.validation import (
        evaluate_ingress_decision,
        format_ingress_rejection,
        scrub_sensitive_fields,
        strip_canonical_entity_id,
    )

    data, _ = scrub_sensitive_fields(feed_event.data)
    data = strip_canonical_entity_id(data)
    purpose = (feed_event.purpose or "").strip() or None
    subject = (feed_event.subject_id or "").strip() or None
    anon = (feed_event.anonymous_id or "").strip() or None
    if not settings.ingress_consent.feed_ingress_consent_enforcement_enabled:
        # S-class escalation disabled for the feed path: fall back to the
        # unconditional T-class decision (data-policy only, no server-receipt).
        purpose = subject = anon = None
    allowed, reason_code, decisions = await evaluate_ingress_decision(
        tenant_id=tenant.tenant_id,
        subject_id=subject,
        anonymous_id=anon,
        purpose=purpose,
        fingerprint_obj=data,
    )
    if not allowed:
        metrics.increment(
            "ingestion_feed_consent_blocked_total",
            labels={"reason": reason_code or "unknown"},
        )
        raise ForbiddenError(
            f"ingress_consent_denied:{format_ingress_rejection(reason_code, decisions)}"
        )

    payload = {
        "source": feed_event.source,
        "entity_type": feed_event.entity_type,
        "external_id": feed_event.external_id,
        "data": data,
        "tenant_id": tenant.tenant_id,
        "received_at": received_at,
        "schema_version": "1.0",
    }

    # Durable Bronze write for idempotency and recovery
    bronze = BronzeRepository("feeds")
    result, is_new = await bronze.ingest(
        source=feed_event.source,
        source_tag=f"feed:{feed_event.source}",
        provider_record_id=feed_event.external_id,
        payload=payload,
        schema_version="1.0",
        entity_id=feed_event.external_id,
        entity_type=feed_event.entity_type,
        tenant_id=tenant.tenant_id,
    )
    is_duplicate = not is_new

    if is_duplicate:
        metrics.increment("api_feeds_duplicate", labels={"source": feed_event.source})
        return APIResponse(
            data={"status": "duplicate", "source": feed_event.source, "external_id": feed_event.external_id}
        ).to_dict()

    await producer.publish(Event(
        topic=Topic.API_FEED_RAW,
        tenant_id=tenant.tenant_id,
        source_service="ingestion.feed",
        payload=payload,
    ))

    metrics.increment("api_feeds_ingested", labels={"source": feed_event.source})
    metrics.increment("event_ingested", labels={"source": "feed"})
    return APIResponse(
        data={"status": "accepted", "source": feed_event.source, "external_id": feed_event.external_id}
    ).to_dict()


# ── Internal Helpers ──────────────────────────────────────────────────

def _validate_and_normalize(
    event: SDKEvent, tenant_id: str, request: Optional[Request] = None,
) -> dict:
    """Validate event fields and normalize to canonical schema."""
    if not event.event_type:
        raise BadRequestError("event_type is required")

    # IP Enrichment (GeoLite2)
    ip_data = _enrich_ip(request) if request else {}

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
        "ip_enrichment": ip_data,
    }


def _enrich_ip(request: Request) -> dict:
    """Extract and enrich IP from request headers using MaxMind GeoLite2.

    Checks Cloudflare, X-Forwarded-For, then falls back to the ASGI client
    host. Performs GeoIP lookup with graceful fallback when the database
    is unavailable.
    """
    ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    if not ip:
        return {}

    ip_hash = hashlib.sha256(ip.encode()).hexdigest()

    base = {
        "ip_hash": ip_hash,
        "ip_range": ".".join(ip.split(".")[:3]) + ".0/24" if "." in ip else "",
        "country_code": "",
        "region": "",
        "city": "",
        "latitude": 0.0,
        "longitude": 0.0,
        "timezone": "",
        "asn": 0,
        "isp": "",
        "is_vpn": False,
        "is_proxy": False,
        "is_tor": False,
        "is_datacenter": False,
    }

    geo = _geo_lookup(ip)
    base.update(geo)
    return base


# ── MaxMind GeoLite2 Adapter ─────────────────────────────────────────

import ipaddress
import os

_GEOIP_DB_PATH = os.getenv("GEOIP_DB_PATH", "/usr/share/GeoIP/GeoLite2-City.mmdb")
_GEOIP_ASN_PATH = os.getenv("GEOIP_ASN_DB_PATH", "/usr/share/GeoIP/GeoLite2-ASN.mmdb")

# Lazy-loaded readers
_city_reader = None
_asn_reader = None
_geoip_available = None

# Known private/reserved ranges
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# Known datacenter/VPN ASNs (top providers)
_DATACENTER_ASNS = {
    14061,  # DigitalOcean
    16509,  # Amazon AWS
    15169,  # Google Cloud
    8075,   # Microsoft Azure
    13335,  # Cloudflare
    20473,  # Vultr
    63949,  # Linode
    14618,  # Amazon AWS (alt)
}


def _init_geoip() -> bool:
    """Lazily initialize MaxMind readers. Returns True if available."""
    global _city_reader, _asn_reader, _geoip_available

    if _geoip_available is not None:
        return _geoip_available

    try:
        import maxminddb
        if os.path.exists(_GEOIP_DB_PATH):
            _city_reader = maxminddb.open_database(_GEOIP_DB_PATH)
            logger.info("GeoIP city database loaded: %s", _GEOIP_DB_PATH)
        if os.path.exists(_GEOIP_ASN_PATH):
            _asn_reader = maxminddb.open_database(_GEOIP_ASN_PATH)
            logger.info("GeoIP ASN database loaded: %s", _GEOIP_ASN_PATH)
        _geoip_available = _city_reader is not None
    except ImportError:
        logger.warning("maxminddb package not installed — GeoIP enrichment disabled")
        _geoip_available = False
    except Exception as exc:
        logger.warning("Failed to load GeoIP database: %s", exc)
        _geoip_available = False

    return _geoip_available


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _PRIVATE_RANGES)
    except ValueError:
        return False


def _geo_lookup(ip_str: str) -> dict:
    """Perform GeoIP lookup with graceful fallback.

    Returns a dict of geo fields. On any failure, returns empty values
    (never raises). Private/reserved IPs return immediately with empty geo.
    """
    result: dict = {}

    # Skip private IPs — they have no geo data
    if _is_private_ip(ip_str):
        return result

    # Validate IP format
    try:
        ipaddress.ip_address(ip_str)
    except ValueError:
        logger.debug("Invalid IP address for geo lookup: %s", ip_str[:20])
        return result

    if not _init_geoip():
        return result

    # City/Country lookup
    if _city_reader is not None:
        try:
            city_data = _city_reader.get(ip_str)
            if city_data:
                country = city_data.get("country", {})
                subdivision = city_data.get("subdivisions", [{}])[0] if city_data.get("subdivisions") else {}
                city = city_data.get("city", {})
                location = city_data.get("location", {})

                result["country_code"] = country.get("iso_code", "")
                result["region"] = subdivision.get("names", {}).get("en", "")
                result["city"] = city.get("names", {}).get("en", "")
                result["latitude"] = location.get("latitude", 0.0)
                result["longitude"] = location.get("longitude", 0.0)
                result["timezone"] = location.get("time_zone", "")
        except Exception as exc:
            logger.debug("GeoIP city lookup failed for %s: %s", ip_str[:20], exc)

    # ASN lookup
    if _asn_reader is not None:
        try:
            asn_data = _asn_reader.get(ip_str)
            if asn_data:
                asn_number = asn_data.get("autonomous_system_number", 0)
                result["asn"] = asn_number
                result["isp"] = asn_data.get("autonomous_system_organization", "")
                result["is_datacenter"] = asn_number in _DATACENTER_ASNS
        except Exception as exc:
            logger.debug("GeoIP ASN lookup failed for %s: %s", ip_str[:20], exc)

    return result
