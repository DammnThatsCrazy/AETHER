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
from datetime import datetime
from typing import Any, Literal, Optional, Sequence

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from config.settings import settings
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
from services.ingestion.bronze_bulk import (
    BronzeSDKEvent,
    OutboxEvent,
    ingest_many,
)
from services.ingestion.ingestion_observability import (
    record_degraded,
    record_stage,
)
from services.ingestion.sdk_version_tiers import (
    classify_sdk_version,
    sdk_version_advisory,
    sdk_version_ingress_blocked,
)
from services.ingestion.sequence_integrity import analyze_batch_sequences
from services.ingestion.validation import (
    EventValidationResult,
    RequestPrivacySignals,
    build_normalized_payload as _validated_normalized_payload,
    format_rejection,
    get_event_family as _validated_event_family,
    validate_event,
)
# Capability-family metering seam (§7): durable evidence + meter for
# reconciliation at the canonical ingestion choke point.
from services.metering_evidence.families import meter_family_usage  # noqa: E402

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
REJECT_DEPLOYMENT_CONTEXT = "deployment_context_invalid"

# SDK-supplied canonical IDs are never trusted — identity resolution is
# backend-owned (see packages/shared/agent-deployment.ts). Keys matching
# these names (case/format-insensitive) are stripped from properties/context.
_CANONICAL_ENTITY_KEYS = frozenset({"canonical_entity_id", "canonicalentityid"})

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
    # Temporal provenance (optional evidence; server computes the authoritative
    # envelope — see services/ingestion/temporal_enforcement.py).
    utcOffsetMinutes: Optional[int] = None
    timeZoneSource: Optional[str] = None
    clockSource: Optional[str] = None
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
    acquisitionEvidence: Optional[dict[str, Any]] = None
    privacy: Optional[dict[str, Any]] = None
    sampling: Optional[dict[str, Any]] = None
    sequence: Optional[dict[str, Any]] = None

    # Canonical envelope context v1 (packages/shared/events.ts). All optional +
    # additive at the MODEL layer; the SDKs stamp `surface` (and, progressively,
    # the rest) on every event. `extra="forbid"` above means these MUST be
    # declared or real SDK batches 422 at ingest. Backend persists them in the
    # opaque context JSONB; first-class promotion (e.g. surface attribution)
    # happens downstream. Requiredness is enforced separately and staged:
    # when settings.ingestion_v2.envelope_required_fields_enforced is on
    # (default in staging/production), release-critical events missing
    # sequence/schemaVersion/surface are rejected per-event with
    # `envelope_missing:<field>` (services/ingestion/validation.py) rather
    # than failing the whole batch here.
    schemaVersion: Optional[str] = None
    surface: Optional[str] = None
    application: Optional[dict[str, Any]] = None
    operatingSystem: Optional[dict[str, Any]] = None
    semanticInput: Optional[dict[str, Any]] = None
    semanticHints: Optional[dict[str, Any]] = None
    dataQuality: Optional[dict[str, Any]] = None

    # Distributed tracing (flat legacy keys + nested canonical `correlation`)
    correlationId: Optional[str] = None
    causationId: Optional[str] = None
    traceId: Optional[str] = None
    correlation: Optional[dict[str, Any]] = None

    # External Agent Telemetry Plane V1 — AgentDeploymentContext
    # (packages/shared/agent-deployment.ts). Validated flag-gated in
    # _process_single_event; both key styles accepted from SDKs.
    agentDeployment: Optional[dict[str, Any]] = None
    agent_deployment: Optional[dict[str, Any]] = None


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

    # ── V2 canary dispatch (PR 5 / FT-5-INGESTION-V2) ─────────────────────────
    # Flag-gated, default OFF. When enabled globally, or when this tenant is in
    # the canary list, route to the transactional typed-Bronze + outbox path.
    # The V1 path below is left entirely unchanged for every other tenant.
    request_privacy = RequestPrivacySignals.from_headers(getattr(request, "headers", {}))
    server_context = _build_server_context(request, tenant.tenant_id)
    iv2 = settings.ingestion_v2
    if iv2.enabled or tenant.tenant_id in iv2.canary_tenants:
        return await _ingest_batch_v2(
            body=body,
            tenant=tenant,
            request_privacy=request_privacy,
            server_context=server_context,
        )

    response = await ingest_events(
        events=body.batch,
        tenant_id=tenant.tenant_id,
        request_privacy=request_privacy,
        server_context=server_context,
        granted_consents=frozenset(body.consents or []),
        sent_at=body.sentAt,
        producer=producer,
    )
    # The /v1/batch handler keeps returning the plain BatchResponse dict
    # (ingest_events returns the model); ingest_events is the shared spine the
    # deprecated aliases also converge onto.
    return response.model_dump()


# ── Canonical V1 ingestion spine ─────────────────────────────────────────────
# Shared by the /v1/batch V1 path and the deprecated /v1/ingest/events aliases
# (converged onto it via routes.py). Behavior is the pre-existing V1 body
# unchanged: per-event validate_event → _process_single_event →
# _apply_temporal_enforcement → observation-envelope flag block → durable
# Bronze write (sdk_events) BEFORE bus publish → identity fire-and-forget →
# Redis set_nx idempotency claim AFTER Bronze → release-on-publish-failure →
# producer.publish_batch → tally → sequence-integrity meters → family meter —
# with the same meters / logger messages in the same order.

async def ingest_events(
    events: Sequence[BaseEvent], *,
    tenant_id: str,
    request_privacy: RequestPrivacySignals,
    server_context: dict | None,
    granted_consents: frozenset[str],
    sent_at: str | None,          # None → temporal enforcement uses received_at
    producer: EventProducer,
) -> BatchResponse:
    """Canonical V1 ingestion spine over a sequence of SDK events.

    Computes the batch envelope (batch_id / received_at / registry) internally,
    exactly as the /v1/batch handler did, and runs the full invariant ordering
    for every event. ``sent_at`` of None (the deprecated aliases carry no send
    time) makes temporal enforcement use ``received_at`` as its baseline.
    """
    received_dt = utc_now()
    received_at = received_dt.isoformat()
    # Deprecated aliases carry no send time — fall back to the server receive
    # time as the temporal-enforcement baseline (identical to the old /v1/batch
    # path whenever the caller did supply body.sentAt).
    sent_at_effective = sent_at if sent_at is not None else received_at
    batch_id = str(uuid.uuid4())
    registry = get_registry()

    results: list[EventResult] = []
    accepted_events: list[Event] = []
    accepted_raw: list[dict] = []

    metrics.increment("ingestion_batch_received_total", labels={"tenant_id": tenant_id})

    for sdk_event in events:
        # WS-E funnel telemetry: every observation that reaches the spine is
        # RECEIVED (flag-gated; no-op while observability is OFF).
        record_stage(
            tenant_id=tenant_id,
            event_id=sdk_event.id,
            event_type=sdk_event.type,
            stage="received",
            status="observed",
            path="sdk",
        )
        # WS-E Invariant #18: enforce-mode SDK version-tier blocking. Inert by
        # default (flag OFF / mode != enforce / blocked-after date not reached).
        if sdk_version_ingress_blocked(sdk_event.context.library):
            reason = _sdk_version_block_reason(sdk_event.context.library)
            results.append(EventResult(id=sdk_event.id, status="rejected", reason=reason))
            continue

        validation = await validate_event(
            sdk_event=sdk_event,
            tenant_id=tenant_id,
            batch_id=batch_id,
            received_at=received_at,
            granted_consents=granted_consents,
            request_privacy=request_privacy,
        )
        result = await _process_single_event(
            sdk_event=sdk_event,
            tenant_id=tenant_id,
            batch_id=batch_id,
            received_at=received_at,
            cache=registry.cache,
            granted_consents=granted_consents,
            request_privacy=request_privacy,
            validation=validation,
        )
        result = _apply_temporal_enforcement(
            sdk_event=sdk_event,
            result=result,
            normalized=validation.normalized_event,
            tenant_id=tenant_id,
            sent_at=sent_at_effective,
            received_at_dt=received_dt,
        )
        results.append(result)
        if result.status == "accepted":
            normalized = validation.normalized_event
            if normalized is None:  # pragma: no cover - typed invariant
                raise RuntimeError("accepted validation missing normalized event")
            # WS-E Invariant #18: advisory SDK version-tier label on the
            # normalized payload (additive; only when the compat flag is ON).
            _advisory = sdk_version_advisory(sdk_event.context.library)
            if _advisory is not None:
                normalized["sdk_tier"] = _advisory
            if server_context is not None:
                normalized["server_context"] = server_context
            if settings.observation_envelope.enabled:
                # WS-A5/WS-B1 flag-gated adoption (default OFF). Builds the
                # canonical Envelope-B observation for this accepted SDK event
                # through the SDK adapter (services/ingestion/adapters/sdk.py),
                # then — when the WS-B1 gateway flag is also ON — validates and
                # stamps it through the universal ingestion gateway
                # (services/ingestion/gateway.py). Persisted additively as
                # normalized["observation_envelope"]; consumers keep reading the
                # flat dict until WS-B converges every adapter onto Envelope B.
                # Any mapping/validation failure degrades to the flat path, so
                # the flags can never take ingestion down.
                try:
                    from services.ingestion.adapters.sdk import SdkIngressAdapter
                    from services.ingestion.gateway import validate_and_stamp

                    adapter = SdkIngressAdapter()
                    envelope = adapter.build_observation_envelope(normalized)
                    if envelope is not None:
                        if settings.ingress_gateway.enabled:
                            result = validate_and_stamp(
                                envelope.to_bronze_additive(),
                                adapter=adapter,
                                tenant_id=tenant_id,
                            )
                            if result.accepted:
                                normalized["observation_envelope"] = result.envelope
                            else:
                                # Gateway rejected this envelope (schema / type /
                                # family / tenant). The A-side event is already
                                # accepted — degrade to the flat dict.
                                logger.warning(
                                    "observation_envelope gateway-rejected for batch "
                                    "%s event_id=%s reason=%s",
                                    batch_id,
                                    normalized.get("event_id"),
                                    result.reasons,
                                )
                                metrics.increment(
                                    "ingestion_observation_envelope_gateway_rejected_total",
                                    labels={"tenant_id": tenant_id},
                                )
                                # WS-E funnel: flag fail-open degrade (accepted A-side,
                                # envelope rejected → flat dict). No-op while OFF.
                                record_degraded(
                                    tenant_id=tenant_id,
                                    event_id=normalized.get("event_id"),
                                )
                        else:
                            normalized["observation_envelope"] = envelope.to_bronze_additive()
                    else:
                        metrics.increment(
                            "ingestion_observation_envelope_skipped_total",
                            labels={"tenant_id": tenant_id},
                        )
                except Exception as exc:
                    logger.warning(
                        "observation_envelope build failed for batch %s event_id=%s: %s",
                        batch_id,
                        normalized.get("event_id"),
                        exc,
                        exc_info=True,
                    )
                    metrics.increment(
                        "ingestion_observation_envelope_build_failed_total",
                        labels={"tenant_id": tenant_id},
                    )
            accepted_events.append(Event(
                topic=Topic.SDK_EVENTS_VALIDATED,
                tenant_id=tenant_id,
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
                    tenant_id=tenant_id,
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
                _resolve_identity_safe(resolver, normalized, tenant_id)
            )

            def _log_task_exc(
                t: "_asyncio.Task",
                _tid: str = tenant_id,
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
        idempotency_key = _make_idempotency_key(tenant_id, raw["event_id"], SCHEMA_VERSION)
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
                labels={"tenant_id": tenant_id},
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
    _emit_sequence_integrity_meters(events, tenant_id)

    logger.info(
        "Batch %s processed: accepted=%d duplicates=%d rejected=%d tenant=%s",
        batch_id, n_accepted, n_duplicates, n_rejected, tenant_id,
    )

    # WS-E funnel: final per-event VALIDATED disposition + durable BRONZE for
    # accepted events (flag-gated; no-op while ingestion observability is OFF).
    for _res in results:
        record_stage(
            tenant_id=tenant_id, event_id=_res.id, stage="validated",
            status=_res.status, path="sdk",
        )
        if _res.status == "accepted":
            record_stage(
                tenant_id=tenant_id, event_id=_res.id, stage="bronze",
                status="accepted", path="sdk",
            )

    # Family seam: durable meter + evidence for accepted ingestion only
    # (advisory — no entitlement gate; metering never breaks the request).
    if n_accepted > 0:
        await meter_family_usage(
            "ingestion", tenant_id, event_id=batch_id,
            quantity=n_accepted, enforce=False, raise_on_metering_error=False,
        )

    return BatchResponse(
        accepted=n_accepted,
        duplicates=n_duplicates,
        rejected=n_rejected,
        events=results,
        batchId=batch_id,
        receivedAt=received_at,
    )


# ── V2 path (PR 5): transactional typed Bronze + outbox ───────────────────────

async def _ingest_batch_v2(
    body: BatchRequest,
    tenant,
    request_privacy: RequestPrivacySignals = RequestPrivacySignals(),
    server_context: Optional[dict] = None,
) -> dict:
    """Transactional /v1/batch path.

    Authenticate/validate/scrub/consent are handled exactly as V1 (reusing the
    same registry + scrub + consent helpers), then all accepted events are
    written — typed Bronze rows plus their transactional-outbox rows — in ONE
    transaction via ``ingest_many``. Database uniqueness is the idempotency
    source of truth (no Redis, no per-event create_task, no in-request publish;
    the outbox relay worker that drains ``event_outbox`` is PR 6). The response
    is the exact ``BatchResponse`` schema V1 returns, so V1/V2 are interchangeable.
    """
    received_dt = utc_now()
    received_at = received_dt.isoformat()
    batch_id = str(uuid.uuid4())

    metrics.increment("ingestion_batch_received_total", labels={"tenant_id": tenant.tenant_id})
    metrics.increment("ingestion_v2_batch_received_total", labels={"tenant_id": tenant.tenant_id})

    granted_consents: frozenset[str] = frozenset(body.consents or [])

    results: list[EventResult] = []
    candidates: list[BronzeSDKEvent] = []
    candidate_outbox: list[OutboxEvent] = []
    candidate_positions: list[int] = []  # results index for each candidate
    candidate_deployments: list[Optional[str]] = []

    for sdk_event in body.batch:
        # WS-E funnel telemetry: RECEIVED (flag-gated; no-op while OFF).
        record_stage(
            tenant_id=tenant.tenant_id,
            event_id=sdk_event.id,
            event_type=sdk_event.type,
            stage="received",
            status="observed",
            path="sdk",
        )
        # WS-E Invariant #18: enforce-mode SDK version-tier blocking (inert by
        # default — flag OFF / mode != enforce / blocked-after date not reached).
        if sdk_version_ingress_blocked(sdk_event.context.library):
            results.append(EventResult(
                id=sdk_event.id,
                status="rejected",
                reason=_sdk_version_block_reason(sdk_event.context.library),
            ))
            continue

        validation = await validate_event(
            sdk_event=sdk_event,
            tenant_id=tenant.tenant_id,
            batch_id=batch_id,
            received_at=received_at,
            granted_consents=granted_consents,
            request_privacy=request_privacy,
        )
        if not validation.allowed:
            results.append(EventResult(
                id=sdk_event.id,
                status="rejected",
                reason=format_rejection(validation, sdk_event),
            ))
            continue

        # Placeholder — final accepted/duplicate resolved by the bulk ingest.
        results.append(EventResult(id=sdk_event.id, status="accepted"))

        normalized = validation.normalized_event
        if normalized is None:  # pragma: no cover - typed invariant
            raise RuntimeError("accepted validation missing normalized event")

        temporal_result = _apply_temporal_enforcement(
            sdk_event=sdk_event,
            result=results[-1],
            normalized=normalized,
            tenant_id=tenant.tenant_id,
            sent_at=body.sentAt,
            received_at_dt=received_dt,
        )
        results[-1] = temporal_result
        if temporal_result.status != "accepted":
            continue
        # WS-E Invariant #18: advisory SDK version-tier label (additive; only
        # when the compat flag is ON).
        _advisory = sdk_version_advisory(sdk_event.context.library)
        if _advisory is not None:
            normalized["sdk_tier"] = _advisory
        if server_context is not None:
            normalized["server_context"] = server_context

        entity_id = normalized.get("user_id") or normalized.get("anonymous_id", "")
        candidates.append(BronzeSDKEvent(
            tenant_id=tenant.tenant_id,
            event_id=sdk_event.id,
            schema_version=SCHEMA_VERSION,
            batch_id=batch_id,
            event_type=sdk_event.type,
            event_family=_get_event_family(sdk_event.type),
            event_timestamp=sdk_event.timestamp,
            received_at=received_at,
            session_id=sdk_event.sessionId,
            anonymous_id=sdk_event.anonymousId,
            user_id=sdk_event.userId,
            entity_id=entity_id,
            payload=normalized,
            source="sdk",
            source_tag=f"batch:{batch_id}",
        ))
        candidate_outbox.append(OutboxEvent(
            tenant_id=tenant.tenant_id,
            event_id=sdk_event.id,
            topic=Topic.SDK_EVENTS_VALIDATED.value,
            partition_key=(entity_id or sdk_event.sessionId),
            payload=normalized,
        ))
        candidate_positions.append(len(results) - 1)
        candidate_deployments.append(validation.deployment_id)

    if candidates:
        try:
            bulk = await ingest_many(candidates, candidate_outbox)
        except Exception as exc:
            logger.error(
                "V2 bulk ingest failed for batch %s: %s", batch_id, exc, exc_info=True
            )
            metrics.increment("ingestion_bronze_write_failed_total")
            raise ServiceUnavailableError(
                "Ingestion temporarily unavailable — please retry"
            )
        # bulk.statuses is aligned to candidate input order; map back to results.
        for pos, status, deployment_id in zip(
            candidate_positions, bulk.statuses, candidate_deployments
        ):
            normalized_status = "accepted" if status == "accepted" else "duplicate"
            results[pos] = EventResult(id=results[pos].id, status=normalized_status)
            if deployment_id and normalized_status == "accepted":
                from services.agent.deployments import record_event_outcome
                await record_event_outcome(
                    tenant.tenant_id, deployment_id, "accepted"
                )

    n_accepted = sum(1 for r in results if r.status == "accepted")
    n_duplicates = sum(1 for r in results if r.status == "duplicate")
    n_rejected = sum(1 for r in results if r.status == "rejected")

    metrics.increment(
        "ingestion_event_accepted_total",
        value=n_accepted,
        labels={"tenant_id": tenant.tenant_id},
    )
    metrics.increment("ingestion_event_duplicate_total", value=n_duplicates)
    metrics.increment("ingestion_event_rejected_total", value=n_rejected)
    _emit_sequence_integrity_meters(body.batch, tenant.tenant_id)

    logger.info(
        "Batch %s processed (v2): accepted=%d duplicates=%d rejected=%d tenant=%s",
        batch_id, n_accepted, n_duplicates, n_rejected, tenant.tenant_id,
    )

    # WS-E funnel: final per-event VALIDATED disposition + durable BRONZE for
    # accepted events (flag-gated; no-op while ingestion observability is OFF).
    for _res in results:
        record_stage(
            tenant_id=tenant.tenant_id, event_id=_res.id, stage="validated",
            status=_res.status, path="sdk",
        )
        if _res.status == "accepted":
            record_stage(
                tenant_id=tenant.tenant_id, event_id=_res.id, stage="bronze",
                status="accepted", path="sdk",
            )

    # Family seam: durable meter + evidence for accepted ingestion only
    # (advisory — no entitlement gate; metering never breaks the request).
    if n_accepted > 0:
        await meter_family_usage(
            "ingestion", tenant.tenant_id, event_id=batch_id,
            quantity=n_accepted, enforce=False, raise_on_metering_error=False,
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
    request_privacy: RequestPrivacySignals = RequestPrivacySignals(),
    validation: Optional[EventValidationResult] = None,
) -> EventResult:
    """Consume canonical validation, then apply V1 cache idempotency only."""

    decision = validation or await validate_event(
        sdk_event=sdk_event,
        tenant_id=tenant_id,
        batch_id=batch_id,
        received_at=received_at,
        granted_consents=granted_consents,
        request_privacy=request_privacy,
    )
    if not decision.allowed:
        return EventResult(
            id=sdk_event.id,
            status="rejected",
            reason=format_rejection(decision, sdk_event),
        )

    idempotency_key = _make_idempotency_key(
        tenant_id, sdk_event.id, SCHEMA_VERSION
    )
    cache_key = f"aether:idempotency:{idempotency_key}"
    if await _check_idempotency(cache, cache_key):
        metrics.increment("ingestion_event_duplicate_total")
        return EventResult(id=sdk_event.id, status="duplicate")

    if decision.deployment_id:
        from services.agent.deployments import record_event_outcome
        await record_event_outcome(
            tenant_id, decision.deployment_id, "accepted"
        )

    return EventResult(id=sdk_event.id, status="accepted")


def _build_server_context(request: Request, tenant_id: str) -> Optional[dict]:
    """Server-derived network context (flag-gated, default off — zero cost).

    Computed once per batch; the raw IP never leaves the enricher. Enrichment
    failures produce explicit states and never reject events.
    """
    if not settings.context_intelligence.enrichment_enabled:
        return None
    from services.ingestion.context_enricher import enrich_request_context

    try:
        headers = getattr(request, "headers", {}) or {}
        client = getattr(request, "client", None)
        context = enrich_request_context(
            tenant_id=tenant_id,
            at=utc_now(),
            peer_ip=getattr(client, "host", None) if client else None,
            forwarded_for=headers.get("X-Forwarded-For"),
            cf_connecting_ip=headers.get("CF-Connecting-IP"),
        )
        metrics.increment(
            "ingestion_context_enrichment_total",
            labels={"tenant_id": tenant_id, "state": context.enrichment_state},
        )
        return context.as_payload()
    except Exception as exc:  # enrichment must never break ingestion
        logger.warning("Context enrichment failed (event continues): %s", exc)
        return None


def _apply_temporal_enforcement(
    sdk_event: BaseEvent,
    result: EventResult,
    normalized: Optional[dict],
    tenant_id: str,
    sent_at: Optional[str],
    received_at_dt: "datetime",
) -> EventResult:
    """Temporal mode ladder (off → shadow → warn → enforce) for one event.

    ``off`` returns immediately (zero cost). Active modes compute the
    server-authoritative temporal envelope identically — shadow only meters,
    warn also surfaces reasons, enforce applies reject/quarantine dispositions.
    The envelope rides the normalized payload (``temporal`` key) into Bronze.
    """
    mode = settings.temporal_integrity.mode_for_tenant(tenant_id)
    if mode == "off":
        return result

    from services.ingestion.temporal_enforcement import enforce_temporal

    ctx = sdk_event.context
    decision = enforce_temporal(
        event_timestamp=sdk_event.timestamp,
        event_family=_get_event_family(sdk_event.type),
        context_timezone=ctx.timezone,
        context_offset_minutes=ctx.utcOffsetMinutes,
        context_tz_source=ctx.timeZoneSource,
        context_clock_source=ctx.clockSource,
        context_locale=ctx.locale,
        sent_at=sent_at,
        received_at=received_at_dt,
    )

    state = decision.envelope.temporal_state if decision.envelope else "invalid"
    metrics.increment(
        "ingestion_temporal_state_total",
        labels={"tenant_id": tenant_id, "state": state, "mode": mode},
    )
    for code in decision.reason_codes:
        metrics.increment(
            "ingestion_temporal_reason_total",
            labels={"tenant_id": tenant_id, "reason": code},
        )

    if decision.envelope is not None and normalized is not None:
        normalized["temporal"] = decision.envelope.model_dump_bronze()

    if result.status != "accepted":
        return result
    if mode == "enforce" and decision.blocked:
        metrics.increment(
            "ingestion_temporal_blocked_total",
            labels={"tenant_id": tenant_id, "disposition": decision.disposition},
        )
        return EventResult(
            id=sdk_event.id,
            status="rejected",
            reason=f"temporal_{decision.disposition}:" + ",".join(decision.reason_codes),
        )
    if mode == "warn" and decision.reason_codes:
        return EventResult(
            id=sdk_event.id,
            status="accepted",
            reason="temporal_warning:" + ",".join(decision.reason_codes),
        )
    return result


def _emit_sequence_integrity_meters(batch: list[BaseEvent], tenant_id: str) -> None:
    """Meter in-batch sequence gaps/duplicates (stateless, metrics only).

    Runs once per accepted batch over every event the client sent — rejected
    or duplicate events still carried ``context.sequence.event``, and the
    counter is a property of the client's stream, so excluding them would
    manufacture false gaps. Findings never change event dispositions.
    """
    findings = analyze_batch_sequences([
        {"sessionId": e.sessionId, "context": {"sequence": e.context.sequence}}
        for e in batch
    ])
    for finding in findings:
        if finding.kind == "gap":
            metrics.increment(
                "ingestion_sequence_gap_total",
                labels={"tenant_id": tenant_id},
            )
        else:
            metrics.increment(
                "ingestion_sequence_duplicate_total",
                labels={"tenant_id": tenant_id},
            )


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
    """Compatibility wrapper over the canonical validation normalizer."""
    return _validated_normalized_payload(
        sdk_event=sdk_event,
        tenant_id=tenant_id,
        batch_id=batch_id,
        received_at=received_at,
    )


def _get_event_family(event_type: str) -> str:
    """Compatibility wrapper over the generated-registry family lookup."""
    return _validated_event_family(event_type)


def _sdk_version_block_reason(library: Optional[dict[str, Any]]) -> str:
    """Rejection reason for enforce-mode SDK version-tier blocking."""
    band = classify_sdk_version(
        (library or {}).get("version"), (library or {}).get("name")
    )
    label = (band.label or band.id).lower().replace(" ", "-")
    return f"sdk_version_blocked:{band.id}:{label}"


def _strip_canonical_entity_id(obj: Any) -> Any:
    """Recursively drop SDK-supplied canonical entity IDs from a payload.

    Identity resolution is backend-owned; a client-asserted canonical ID is
    never trusted (regardless of feature flags).
    """
    if isinstance(obj, dict):
        return {
            k: _strip_canonical_entity_id(v)
            for k, v in obj.items()
            if k.lower().replace("-", "_") not in _CANONICAL_ENTITY_KEYS
        }
    if isinstance(obj, list):
        return [_strip_canonical_entity_id(item) for item in obj]
    return obj


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
