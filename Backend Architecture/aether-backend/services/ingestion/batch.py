"""
Aether Service — POST /v1/batch
Canonical SDK ingestion endpoint for Web, iOS, Android, and React Native.

Contract source: docs/source-of-truth/INGESTION_CONTRACT.md

Auth: Bearer API key (Authorization: Bearer <api_key>)
     Must carry write permission.

Idempotency key: tenant_id:event_id:schema_version
  - Accepted events return status "accepted"
  - Duplicate events return status "duplicate" (no re-publish, no double-bill)
  - Invalid events return status "rejected" with reason

Durability: accepted events are written to durable Bronze tier BEFORE the
bus publish. If the bus publish fails the request returns 503 so the SDK can
retry.  The Bronze record is idempotent, so a retry is safe.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from repositories.lake import BronzeRepository
from shared.auth.auth import Permissions
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ServiceUnavailableError,
    utc_now,
)
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_producer, get_registry
from services.identity.routes import get_identity_resolver

from services.ingestion.generated_registry import (
    CANONICAL_EVENT_TYPES,
    EVENT_CONSENT_PURPOSE,
    EVENT_FAMILY,
)

logger = get_logger("aether.service.ingestion.batch")
router = APIRouter(prefix="/v1", tags=["Ingestion"])

# CANONICAL_EVENT_TYPES, EVENT_CONSENT_PURPOSE, EVENT_FAMILY imported above
# from services.ingestion.generated_registry — do not redefine here.

# Backend-side sensitive field patterns — scrub even if SDK missed them.
# Matched against all lower-cased dict keys, recursively.
_SENSITIVE_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"private[_\s]?key", r"seed[_\s]?phrase", r"mnemonic",
        r"password", r"passwd", r"passphrase",
        r"secret[_\s]?key?", r"\bsecret\b",
        r"\bpin\b", r"card[_\s]?number", r"\bpan\b",
        r"\bcvv\b", r"\bcvc\b", r"cvv2",
        r"payment[_\s]?token", r"auth[_\s]?code",
        r"api[_\s]?key", r"access[_\s]?token", r"refresh[_\s]?token",
        r"bearer[_\s]?token", r"ssh[_\s]?key", r"id[_\s]?token",
        r"social[_\s]?security", r"\bssn\b", r"\bein\b", r"\btin\b",
        r"bank[_\s]?account", r"routing[_\s]?number", r"iban",
        r"totp[_\s]?secret", r"otp[_\s]?secret", r"recovery[_\s]?code",
        r"client[_\s]?secret", r"webhook[_\s]?secret",
        r"form[_\s]?value", r"field[_\s]?value", r"input[_\s]?value",
        r"entered[_\s]?text", r"clipboard", r"keystroke",
        r"raw[_\s]?message", r"message[_\s]?body", r"email[_\s]?body",
    ]
]

# Stable per-event rejection reason codes (used in EventResult.reason)
REJECT_UNKNOWN_TYPE = "unknown_event_type"
REJECT_CONSENT_DENIED = "consent_denied"
REJECT_CONSENT_REQUIRED = "consent_required"
REJECT_EXECUTION_CLAIM = "execution_by_aether_must_be_false"

SCHEMA_VERSION = "1.0.0"

# ── Pydantic models ────────────────────────────────────────────────────────────

class EventContext(BaseModel):
    """Full SDK event context — mirrors EventContext in packages/shared/events.ts."""

    model_config = {"extra": "forbid"}

    # Core SDK fields
    library: Optional[dict[str, Any]] = None
    page: Optional[dict[str, Any]] = None
    device: Optional[dict[str, Any]] = None
    os: Optional[dict[str, Any]] = None
    network: Optional[dict[str, Any]] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    userAgent: Optional[str] = None
    ip: Optional[str] = None
    consent: Optional[dict[str, Any]] = None

    # Attribution / campaign
    campaign: Optional[dict[str, Any]] = None

    # Cross-device fingerprinting (personalization-gated)
    fingerprint: Optional[dict[str, Any]] = None

    # Journey continuity
    journey: Optional[dict[str, Any]] = None

    # B2B / multi-tenant binding
    tenantId: Optional[str] = None
    orgId: Optional[str] = None

    # Multi-actor identity
    actorId: Optional[str] = None
    actorKind: Optional[str] = None
    beneficiaryActorId: Optional[str] = None

    # Delegation
    delegationId: Optional[str] = None
    delegationScope: Optional[list[str]] = None

    # Identity-stitching signals
    identityConfidence: Optional[float] = None
    identitySignals: Optional[list[str]] = None

    # Exposure-aware attribution
    impressions: Optional[list[dict[str, Any]]] = None

    # Reward enablement (A6)
    rewardCampaignId: Optional[str] = None
    rewardRuleId: Optional[str] = None
    rewardIdempotencyKey: Optional[str] = None
    rewardWalletAddress: Optional[str] = None

    # Attribution / fraud / consent linkage
    attributionResultId: Optional[str] = None
    fraudDecisionId: Optional[str] = None
    consentSnapshotId: Optional[str] = None

    # Provenance and data lineage
    provenance: Optional[dict[str, Any]] = None
    semantic: Optional[dict[str, Any]] = None
    trafficSource: Optional[dict[str, Any]] = None
    privacy: Optional[dict[str, Any]] = None
    sampling: Optional[dict[str, Any]] = None
    sequence: Optional[dict[str, Any]] = None

    # Distributed tracing
    correlationId: Optional[str] = None
    causationId: Optional[str] = None
    traceId: Optional[str] = None


class BaseEvent(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, description="Client-generated unique event ID")
    type: str = Field(..., description="Canonical event type from EventType registry")
    timestamp: str = Field(..., description="ISO8601 event timestamp")
    sessionId: str = Field(..., min_length=1, max_length=256)
    anonymousId: str = Field(..., min_length=1, max_length=256)
    userId: Optional[str] = Field(default=None, max_length=256)
    properties: Optional[dict[str, Any]] = Field(default_factory=dict)
    context: EventContext = Field(default_factory=EventContext)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid ISO8601 timestamp: {v!r}")
        return v


class BatchRequest(BaseModel):
    batch: list[BaseEvent] = Field(..., min_length=1, max_length=500)
    sentAt: str = Field(..., description="ISO8601 batch send timestamp")
    consents: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional batch-level consent hint. Per-event context.consent snapshots "
            "are authoritative; this field is used as a fallback when per-event consent "
            "is absent."
        ),
    )
    context: Optional[dict[str, Any]] = None

    @field_validator("sentAt")
    @classmethod
    def validate_sent_at(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid ISO8601 sentAt: {v!r}")
        return v


class EventResult(BaseModel):
    id: str
    status: Literal["accepted", "duplicate", "rejected"]
    reason: Optional[str] = None


class BatchResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    events: list[EventResult]
    batchId: str
    receivedAt: str


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/batch", response_model=BatchResponse)
async def ingest_batch(
    request: Request,
    body: BatchRequest,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """
    Canonical SDK batch ingestion endpoint.

    Accepts 1–500 events per batch. Returns per-event status.
    Preserves client-generated event IDs for deduplication.

    Auth: Authorization: Bearer <api_key>  with write permission.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    received_at = utc_now().isoformat()
    batch_id = str(uuid.uuid4())
    registry = get_registry()

    results: list[EventResult] = []
    accepted_events: list[Event] = []
    accepted_raw: list[dict] = []

    metrics.increment("ingestion_batch_received_total", labels={"tenant_id": tenant.tenant_id})

    granted_consents: frozenset[str] = frozenset(body.consents or [])

    for sdk_event in body.batch:
        result = await _process_single_event(
            sdk_event=sdk_event,
            tenant_id=tenant.tenant_id,
            batch_id=batch_id,
            received_at=received_at,
            cache=registry.cache,
            granted_consents=granted_consents,
        )
        results.append(result)
        if result.status == "accepted":
            # Build normalized payload for bus and Bronze
            normalized = _build_normalized_payload(
                sdk_event=sdk_event,
                tenant_id=tenant.tenant_id,
                batch_id=batch_id,
                received_at=received_at,
            )
            accepted_events.append(Event(
                topic=Topic.SDK_EVENTS_VALIDATED,
                tenant_id=tenant.tenant_id,
                source_service="ingestion.batch",
                correlation_id=batch_id,
                payload=normalized,
            ))
            accepted_raw.append(normalized)

    # ── Durable Bronze write BEFORE bus publish ────────────────────────────
    # If Bronze write fails, we must not acknowledge the events.
    if accepted_raw:
        try:
            bronze = BronzeRepository("sdk_events")
            for normalized in accepted_raw:
                await bronze.ingest(
                    source="sdk",
                    source_tag=f"batch:{batch_id}",
                    provider_record_id=normalized["event_id"],
                    payload=normalized,
                    schema_version=SCHEMA_VERSION,
                    entity_id=normalized.get("user_id") or normalized.get("anonymous_id", ""),
                    entity_type="user",
                    tenant_id=tenant.tenant_id,
                )
        except Exception as exc:
            logger.error(
                "Bronze write failed for batch %s: %s", batch_id, exc, exc_info=True
            )
            metrics.increment("ingestion_bronze_write_failed_total")
            raise ServiceUnavailableError(
                "Ingestion temporarily unavailable — please retry"
            )

    # ── Identity resolution (fire-and-forget, non-blocking) ────────────────
    # Run after Bronze durability is confirmed. Resolution errors never fail
    # ingestion — events are already durable and recoverable via recompute.
    if accepted_raw:
        import asyncio as _asyncio
        resolver = get_identity_resolver()
        for normalized in accepted_raw:
            task = _asyncio.create_task(
                _resolve_identity_safe(resolver, normalized, tenant.tenant_id)
            )

            def _log_task_exc(
                t: "_asyncio.Task",
                _tid: str = tenant.tenant_id,
                _eid: str = normalized.get("event_id", ""),
            ) -> None:
                if t.cancelled():
                    return
                exc = t.exception()
                if exc:
                    logger.error(
                        "Identity resolution task failed event=%s tenant=%s: %s",
                        _eid, _tid, exc,
                    )

            task.add_done_callback(_log_task_exc)

    # ── Atomic idempotency claim AFTER Bronze write, BEFORE bus publish ───
    # Build a lookup from event_id → index in results so we can update in-place.
    event_id_to_result_idx: dict[str, int] = {}
    for idx, r in enumerate(results):
        event_id_to_result_idx[r.id] = idx

    claimed_keys: list[str] = []
    final_accepted_events: list[Event] = []
    final_accepted_raw: list[dict] = []

    for event, raw in zip(accepted_events, accepted_raw):
        idempotency_key = _make_idempotency_key(tenant.tenant_id, raw["event_id"], SCHEMA_VERSION)
        cache_key = f"aether:idempotency:{idempotency_key}"
        try:
            claimed = await registry.cache.set_nx(cache_key, "1", ttl=TTL.DAY)
        except Exception:
            claimed = True  # allow on cache error
        if claimed:
            claimed_keys.append(cache_key)
            final_accepted_events.append(event)
            final_accepted_raw.append(raw)
        else:
            # Concurrent request already claimed this key — mark as duplicate
            result_idx = event_id_to_result_idx.get(raw["event_id"])
            if result_idx is not None:
                results[result_idx] = EventResult(id=raw["event_id"], status="duplicate")
            metrics.increment("ingestion_event_duplicate_total")

    accepted_events = final_accepted_events
    accepted_raw = final_accepted_raw

    # ── Event bus publish ─────────────────────────────────────────────────
    if accepted_events:
        try:
            await producer.publish_batch(accepted_events)
            metrics.increment(
                "ingestion_event_accepted_total",
                value=len(accepted_events),
                labels={"tenant_id": tenant.tenant_id},
            )
        except Exception as exc:
            logger.error(
                "Event bus publish failed for batch %s: %s", batch_id, exc, exc_info=True
            )
            metrics.increment("ingestion_publish_failed_total")
            # Release claimed idempotency keys so the SDK can retry cleanly
            for key in claimed_keys:
                try:
                    await registry.cache.delete(key)
                except Exception:
                    pass
            # Bronze is already written — events are recoverable.
            # Do NOT return accepted to the client; let the SDK retry.
            raise ServiceUnavailableError(
                "Ingestion temporarily unavailable — please retry"
            )

    # ── Tally results ─────────────────────────────────────────────────────
    n_accepted = sum(1 for r in results if r.status == "accepted")
    n_duplicates = sum(1 for r in results if r.status == "duplicate")
    n_rejected = sum(1 for r in results if r.status == "rejected")

    metrics.increment("ingestion_event_duplicate_total", value=n_duplicates)
    metrics.increment("ingestion_event_rejected_total", value=n_rejected)

    logger.info(
        "Batch %s processed: accepted=%d duplicates=%d rejected=%d tenant=%s",
        batch_id, n_accepted, n_duplicates, n_rejected, tenant.tenant_id,
    )

    return BatchResponse(
        accepted=n_accepted,
        duplicates=n_duplicates,
        rejected=n_rejected,
        events=results,
        batchId=batch_id,
        receivedAt=received_at,
    ).model_dump()


# ── Per-event processing helpers ──────────────────────────────────────────────

async def _process_single_event(
    sdk_event: BaseEvent,
    tenant_id: str,
    batch_id: str,
    received_at: str,
    cache: CacheClient,
    granted_consents: frozenset[str] = frozenset(),
) -> EventResult:
    """Validate, check idempotency, and return per-event status."""

    # 1. Event type validation
    if sdk_event.type not in CANONICAL_EVENT_TYPES:
        metrics.increment("ingestion_validation_failed_total", labels={"reason": "unknown_type"})
        return EventResult(
            id=sdk_event.id,
            status="rejected",
            reason=f"{REJECT_UNKNOWN_TYPE}:{sdk_event.type}",
        )

    # 2. Observe-only invariant: reject any event claiming Aether executed
    if sdk_event.properties and sdk_event.properties.get("execution_by_aether") is True:
        metrics.increment("ingestion_validation_failed_total", labels={"reason": "execution_by_aether"})
        return EventResult(
            id=sdk_event.id,
            status="rejected",
            reason=REJECT_EXECUTION_CLAIM,
        )

    # 3. Sensitive field scrubbing on properties (recursive, backend defense)
    if sdk_event.properties:
        scrubbed, had_sensitive = _scrub_sensitive_fields(sdk_event.properties)
        if had_sensitive:
            logger.warning(
                "Sensitive fields scrubbed in event %s (tenant=%s type=%s)",
                sdk_event.id, tenant_id, sdk_event.type,
            )
            metrics.increment("ingestion_sensitive_scrub_total")
            sdk_event.properties = scrubbed

    # 4a. Per-event consent gate: check context.consent snapshot (authoritative)
    #     Only block when the per-event snapshot explicitly marks the purpose False.
    if sdk_event.type != "consent":
        required_purpose = EVENT_CONSENT_PURPOSE.get(sdk_event.type)
        if required_purpose and sdk_event.context:
            consent_obj = sdk_event.context.consent
            if consent_obj is not None and isinstance(consent_obj, dict):
                if consent_obj.get(required_purpose) is False:
                    metrics.increment(
                        "ingestion_consent_blocked_total",
                        labels={"purpose": required_purpose},
                    )
                    return EventResult(
                        id=sdk_event.id,
                        status="rejected",
                        reason=f"{REJECT_CONSENT_DENIED}:{required_purpose}",
                    )

    # 4b. Batch-level consent gate: fallback when no per-event snapshot is present.
    #     granted_consents is derived from BatchRequest.consents (optional hint).
    if sdk_event.type != "consent" and granted_consents:
        required_consent = EVENT_CONSENT_PURPOSE.get(sdk_event.type)
        if required_consent and required_consent not in granted_consents:
            metrics.increment(
                "ingestion_validation_failed_total",
                labels={"reason": "consent_missing"},
            )
            return EventResult(
                id=sdk_event.id,
                status="rejected",
                reason=f"{REJECT_CONSENT_REQUIRED}:{required_consent}",
            )

    # 4. Tenant-scoped idempotency check
    idempotency_key = _make_idempotency_key(tenant_id, sdk_event.id, SCHEMA_VERSION)
    cache_key = f"aether:idempotency:{idempotency_key}"

    is_duplicate = await _check_idempotency(cache, cache_key)
    if is_duplicate:
        metrics.increment("ingestion_event_duplicate_total")
        return EventResult(id=sdk_event.id, status="duplicate")

    return EventResult(id=sdk_event.id, status="accepted")


def _make_idempotency_key(tenant_id: str, event_id: str, schema_version: str) -> str:
    """Tenant-scoped idempotency key: prevents cross-tenant collision."""
    import hashlib
    raw = f"{tenant_id}:{event_id}:{schema_version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


async def _check_idempotency(cache: CacheClient, cache_key: str) -> bool:
    """
    Returns True if duplicate (key already exists), False if new.
    Does NOT claim the key — atomic claim happens after Bronze write via set_nx.
    Falls back to False (allow) if cache unavailable (best-effort dedup).
    """
    try:
        existing = await cache.get(cache_key)
        return bool(existing)
    except Exception as exc:
        logger.warning("Idempotency check failed (allowing event): %s", exc)
        return False


def _build_normalized_payload(
    sdk_event: BaseEvent,
    tenant_id: str,
    batch_id: str,
    received_at: str,
) -> dict:
    """Build the normalized payload written to Bronze and published to the bus."""
    return {
        "event_id": sdk_event.id,
        "tenant_id": tenant_id,
        "event_type": sdk_event.type,
        "event_family": _get_event_family(sdk_event.type),
        "session_id": sdk_event.sessionId,
        "anonymous_id": sdk_event.anonymousId,
        "user_id": sdk_event.userId,
        "properties": sdk_event.properties or {},
        "context": sdk_event.context.model_dump(exclude_none=True),
        "timestamp": sdk_event.timestamp,
        "received_at": received_at,
        "ingested_at": utc_now().isoformat(),
        "batch_id": batch_id,
        "schema_version": SCHEMA_VERSION,
        "source": "sdk",
    }


def _get_event_family(event_type: str) -> str:
    """Map event type to family using the generated registry."""
    return EVENT_FAMILY.get(event_type, "core")


async def _resolve_identity_safe(resolver, normalized: dict, tenant_id: str) -> None:
    """Run identity resolution without propagating exceptions to the ingestion path."""
    try:
        from services.identity.schemas import IdentityResolveRequest
        req = IdentityResolveRequest(
            event_id=normalized["event_id"],
            tenant_id=tenant_id,
            user_id=normalized.get("user_id"),
            anonymous_id=normalized.get("anonymous_id"),
            session_id=normalized.get("session_id"),
            properties=normalized.get("properties") or {},
            context=normalized.get("context") or {},
        )
        await resolver.resolve_event(req.model_dump(), tenant_id)
    except Exception as exc:
        logger.warning(
            "Identity resolution failed for event %s (tenant=%s): %s",
            normalized.get("event_id"), tenant_id, exc,
        )
        metrics.increment("identity_resolve_error_total")


def _scrub_sensitive_fields(
    obj: Any,
) -> tuple[Any, bool]:
    """
    Recursively scrub dict keys matching sensitive patterns.
    Also walks into lists. Returns (scrubbed_value, had_sensitive_fields).
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        had_sensitive = False
        for k, v in obj.items():
            k_lower = k.lower()
            is_sensitive = any(p.search(k_lower) for p in _SENSITIVE_KEY_PATTERNS)
            if is_sensitive:
                out[k] = "[REDACTED]"
                had_sensitive = True
            else:
                scrubbed_v, child_sensitive = _scrub_sensitive_fields(v)
                out[k] = scrubbed_v
                if child_sensitive:
                    had_sensitive = True
        return out, had_sensitive
    elif isinstance(obj, list):
        out_list: list[Any] = []
        had_sensitive = False
        for item in obj:
            scrubbed_item, child_sensitive = _scrub_sensitive_fields(item)
            out_list.append(scrubbed_item)
            if child_sensitive:
                had_sensitive = True
        return out_list, had_sensitive
    return obj, False
