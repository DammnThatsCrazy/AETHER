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

logger = get_logger("aether.service.ingestion.batch")
router = APIRouter(prefix="/v1", tags=["Ingestion"])

# ── Canonical event type registry (mirror of packages/shared/events.ts) ───────

CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({
    # Core analytics
    "track", "page", "screen", "heartbeat", "error", "performance", "experiment",
    # Journey lifecycle
    "journey_started", "journey_paused", "journey_resumed", "journey_continued",
    "journey_completed", "journey_abandoned", "journey_checkpoint",
    # Identity
    "identify",
    # Consent (always accepted regardless of consent state)
    "consent",
    # Commerce / access
    "conversion", "payment_initiated", "payment_completed", "payment_failed",
    "approval_requested", "approval_resolved",
    "entitlement_granted", "entitlement_revoked",
    "access_granted", "access_denied",
    # Wallet / on-chain
    "wallet", "transaction", "contract_action",
    # Agent — legacy
    "agent_task", "agent_decision", "a2h_interaction",
    # Agent — lifecycle (granular)
    "agent_registered", "agent_updated", "agent_authorized", "agent_deauthorized",
    "agent_capability_granted", "agent_capability_revoked",
    "agent_task_created", "agent_task_decomposed", "agent_task_started",
    "agent_task_completed", "agent_task_failed", "agent_tool_called",
    "agent_resource_requested", "agent_delegated_task", "agent_subagent_spawned",
    "agent_policy_evaluated", "agent_handoff", "agent_escalated_to_human",
    "agent_outcome_recorded",
    # x402 — legacy
    "x402_payment",
    # x402 — lifecycle (granular)
    "x402_resource_requested", "x402_payment_required", "x402_quote_received",
    "x402_authorization_requested", "x402_authorization_resolved",
    "x402_payment_intent_created", "x402_payment_submitted", "x402_payment_settled",
    "x402_payment_failed", "x402_payment_timeout", "x402_receipt_verified",
    "x402_access_granted", "x402_access_denied", "x402_refund_or_reversal",
    # reward enablement (A6) — eligibility events emitted by Aether, not the tenant
    "reward_action_queued", "reward_proof_generated",
    "reward_delivered", "reward_claim_submitted",
    # Agentic observability — account / MCP / tool
    "agentic_account_observed", "agentic_account_connected_observed",
    "agentic_account_disconnected_observed", "agent_budget_observed",
    "agent_budget_changed_observed", "agent_permission_observed",
    "agent_mcp_connection_observed", "agent_tool_observed",
    "agent_tool_invocation_observed", "agent_activity_observed",
    "agent_risk_signal_observed", "agent_notification_observed",
    # Agentic observability — Robinhood-style trading observation
    "agent_strategy_observed", "agent_trade_intent_observed",
    "agent_trade_order_observed", "agent_trade_fill_observed",
    "agent_trade_rejection_observed", "agent_position_observed",
    "agent_portfolio_snapshot_observed", "agent_performance_snapshot_observed",
    "agent_disconnect_observed",
    # Agentic observability — AgentMail-style communication observation
    "agent_inbox_observed", "agent_email_address_observed",
    "agent_thread_observed", "agent_message_received_observed",
    "agent_message_sent_observed", "agent_reply_observed",
    "agent_attachment_observed", "agent_attachment_parsed_observed",
    "agent_otp_detected_observed", "agent_invoice_detected_observed",
    "agent_receipt_detected_observed", "agent_calendar_intent_observed",
    "agent_support_route_observed", "agent_semantic_search_observed",
    "agent_data_extraction_observed",
    # x402 protocol observation family (from external observer perspective)
    "x402_resource_request_observed", "x402_challenge_observed",
    "x402_payment_requirement_observed", "x402_signature_observed",
    "x402_verification_observed", "x402_settlement_observed",
    "x402_resource_access_observed", "x402_resource_access_denied_observed",
    "x402_failure_observed", "x402_replay_risk_observed",
    "x402_provider_observed",
})

# Required consent purpose per event family (mirror of EVENT_CONSENT_PURPOSE)
EVENT_CONSENT_PURPOSE: dict[str, str] = {
    "track": "analytics", "page": "analytics", "screen": "analytics",
    "heartbeat": "analytics", "error": "analytics", "performance": "analytics",
    "journey_started": "analytics", "journey_paused": "analytics",
    "journey_resumed": "analytics", "journey_continued": "analytics",
    "journey_completed": "analytics", "journey_abandoned": "analytics",
    "journey_checkpoint": "analytics",
    "identify": "analytics",
    "experiment": "marketing", "conversion": "marketing",
    "consent": "analytics",
    "payment_initiated": "commerce", "payment_completed": "commerce",
    "payment_failed": "commerce", "approval_requested": "commerce",
    "approval_resolved": "commerce", "entitlement_granted": "commerce",
    "entitlement_revoked": "commerce", "access_granted": "commerce",
    "access_denied": "commerce",
    "wallet": "web3", "transaction": "web3", "contract_action": "web3",
    "agent_task": "agent", "agent_decision": "agent", "a2h_interaction": "agent",
    # Agent lifecycle
    "agent_registered": "agent", "agent_updated": "agent",
    "agent_authorized": "agent", "agent_deauthorized": "agent",
    "agent_capability_granted": "agent", "agent_capability_revoked": "agent",
    "agent_task_created": "agent", "agent_task_decomposed": "agent",
    "agent_task_started": "agent", "agent_task_completed": "agent",
    "agent_task_failed": "agent", "agent_tool_called": "agent",
    "agent_resource_requested": "agent", "agent_delegated_task": "agent",
    "agent_subagent_spawned": "agent", "agent_policy_evaluated": "agent",
    "agent_handoff": "agent", "agent_escalated_to_human": "agent",
    "agent_outcome_recorded": "agent",
    # x402
    "x402_payment": "commerce",
    "x402_resource_requested": "commerce", "x402_payment_required": "commerce",
    "x402_quote_received": "commerce", "x402_authorization_requested": "commerce",
    "x402_authorization_resolved": "commerce", "x402_payment_intent_created": "commerce",
    "x402_payment_submitted": "commerce", "x402_payment_settled": "commerce",
    "x402_payment_failed": "commerce", "x402_payment_timeout": "commerce",
    "x402_receipt_verified": "commerce", "x402_access_granted": "commerce",
    "x402_access_denied": "commerce", "x402_refund_or_reversal": "commerce",
    # reward enablement (A6)
    "reward_action_queued": "commerce", "reward_proof_generated": "commerce",
    "reward_delivered": "commerce", "reward_claim_submitted": "commerce",
    # Agentic observability — account / MCP / tool
    "agentic_account_observed": "agent", "agentic_account_connected_observed": "agent",
    "agentic_account_disconnected_observed": "agent", "agent_budget_observed": "agent",
    "agent_budget_changed_observed": "agent", "agent_permission_observed": "agent",
    "agent_mcp_connection_observed": "agent", "agent_tool_observed": "agent",
    "agent_tool_invocation_observed": "agent", "agent_activity_observed": "agent",
    "agent_risk_signal_observed": "agent", "agent_notification_observed": "agent",
    # Agentic observability — Robinhood-style trading observation
    "agent_strategy_observed": "agent", "agent_trade_intent_observed": "agent",
    "agent_trade_order_observed": "agent", "agent_trade_fill_observed": "agent",
    "agent_trade_rejection_observed": "agent", "agent_position_observed": "agent",
    "agent_portfolio_snapshot_observed": "agent", "agent_performance_snapshot_observed": "agent",
    "agent_disconnect_observed": "agent",
    # Agentic observability — AgentMail-style communication observation
    "agent_inbox_observed": "agent", "agent_email_address_observed": "agent",
    "agent_thread_observed": "agent", "agent_message_received_observed": "agent",
    "agent_message_sent_observed": "agent", "agent_reply_observed": "agent",
    "agent_attachment_observed": "agent", "agent_attachment_parsed_observed": "agent",
    "agent_otp_detected_observed": "agent", "agent_invoice_detected_observed": "agent",
    "agent_receipt_detected_observed": "agent", "agent_calendar_intent_observed": "agent",
    "agent_support_route_observed": "agent", "agent_semantic_search_observed": "agent",
    "agent_data_extraction_observed": "agent",
    # x402 protocol observation family
    "x402_resource_request_observed": "agent", "x402_challenge_observed": "agent",
    "x402_payment_requirement_observed": "agent", "x402_signature_observed": "agent",
    "x402_verification_observed": "agent", "x402_settlement_observed": "agent",
    "x402_resource_access_observed": "agent", "x402_resource_access_denied_observed": "agent",
    "x402_failure_observed": "agent", "x402_replay_risk_observed": "agent",
    "x402_provider_observed": "agent",
}

# Backend-side sensitive field patterns — scrub even if SDK missed them.
# These are pattern-matched against lower-cased property keys.
_SENSITIVE_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(p) for p in [
        r"private[_\s]?key", r"seed[_\s]?phrase", r"mnemonic",
        r"password", r"passwd", r"secret[_\s]?key?", r"\bsecret\b",
        r"pin\b", r"\bpin\b", r"card[_\s]?number", r"\bpan\b",
        r"\bcvv\b", r"\bcvc\b", r"cvv2",
        r"payment[_\s]?token", r"auth[_\s]?code",
        r"api[_\s]?key", r"access[_\s]?token", r"refresh[_\s]?token",
        r"bearer[_\s]?token", r"ssh[_\s]?key",
        r"social[_\s]?security", r"\bssn\b",
        r"bank[_\s]?account", r"routing[_\s]?number",
    ]
]

SCHEMA_VERSION = "1.0.0"

# ── Pydantic models ────────────────────────────────────────────────────────────

class EventContext(BaseModel):
    library: Optional[dict[str, str]] = None
    page: Optional[dict[str, Any]] = None
    device: Optional[dict[str, Any]] = None
    os: Optional[dict[str, Any]] = None
    network: Optional[dict[str, Any]] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    userAgent: Optional[str] = None
    ip: Optional[str] = None


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
    consents: list[str] = Field(
        default_factory=list,
        description="Consent scopes granted by the user for this batch (e.g. analytics, commerce, web3, agent)",
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

    granted_consents: frozenset[str] = frozenset(body.consents)

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
        import asyncio
        resolver = get_identity_resolver()
        for normalized in accepted_raw:
            asyncio.ensure_future(
                _resolve_identity_safe(resolver, normalized, tenant.tenant_id)
            )

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
            reason=f"unknown_event_type:{sdk_event.type}",
        )

    # 2a. Observe-only invariant: reject any event claiming AETHER executed
    if sdk_event.properties and sdk_event.properties.get("execution_by_aether") is True:
        metrics.increment("ingestion_validation_failed_total", labels={"reason": "execution_by_aether"})
        return EventResult(
            id=sdk_event.id,
            status="rejected",
            reason="execution_by_aether_must_be_false",
        )

    # 2b. Sensitive field scrubbing on properties (backend defense)
    if sdk_event.properties:
        scrubbed, had_sensitive = _scrub_sensitive_fields(sdk_event.properties)
        if had_sensitive:
            logger.warning(
                "Sensitive fields scrubbed in event %s (tenant=%s type=%s)",
                sdk_event.id, tenant_id, sdk_event.type,
            )
            metrics.increment("ingestion_sensitive_scrub_total")
            # Mutate in-place so downstream uses scrubbed payload
            sdk_event.properties = scrubbed

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
    """Map event type to family for routing."""
    _FAMILY_MAP: dict[str, str] = {
        "track": "core", "page": "core", "screen": "core", "heartbeat": "core",
        "error": "core", "performance": "core", "experiment": "core",
        "journey_started": "journey", "journey_paused": "journey",
        "journey_resumed": "journey", "journey_continued": "journey",
        "journey_completed": "journey", "journey_abandoned": "journey",
        "journey_checkpoint": "journey",
        "identify": "identity", "consent": "consent",
        "conversion": "commerce", "payment_initiated": "commerce",
        "payment_completed": "commerce", "payment_failed": "commerce",
        "approval_requested": "commerce", "approval_resolved": "commerce",
        "entitlement_granted": "commerce", "entitlement_revoked": "commerce",
        "access_granted": "commerce", "access_denied": "commerce",
        "wallet": "wallet", "transaction": "wallet", "contract_action": "wallet",
        "agent_task": "agent", "agent_decision": "agent", "a2h_interaction": "agent",
        # agent lifecycle granular
        "agent_registered": "agent", "agent_updated": "agent",
        "agent_authorized": "agent", "agent_deauthorized": "agent",
        "agent_capability_granted": "agent", "agent_capability_revoked": "agent",
        "agent_task_created": "agent", "agent_task_decomposed": "agent",
        "agent_task_started": "agent", "agent_task_completed": "agent",
        "agent_task_failed": "agent", "agent_tool_called": "agent",
        "agent_resource_requested": "agent", "agent_delegated_task": "agent",
        "agent_subagent_spawned": "agent", "agent_policy_evaluated": "agent",
        "agent_handoff": "agent", "agent_escalated_to_human": "agent",
        "agent_outcome_recorded": "agent",
        # agentic observability — account/MCP/tool
        "agentic_account_observed": "agent", "agentic_account_connected_observed": "agent",
        "agentic_account_disconnected_observed": "agent", "agent_budget_observed": "agent",
        "agent_budget_changed_observed": "agent", "agent_permission_observed": "agent",
        "agent_mcp_connection_observed": "agent", "agent_tool_observed": "agent",
        "agent_tool_invocation_observed": "agent", "agent_activity_observed": "agent",
        "agent_risk_signal_observed": "agent", "agent_notification_observed": "agent",
        # agentic observability — Robinhood-style trading observation
        "agent_strategy_observed": "agent", "agent_trade_intent_observed": "agent",
        "agent_trade_order_observed": "agent", "agent_trade_fill_observed": "agent",
        "agent_trade_rejection_observed": "agent", "agent_position_observed": "agent",
        "agent_portfolio_snapshot_observed": "agent", "agent_performance_snapshot_observed": "agent",
        "agent_disconnect_observed": "agent",
        # agentic observability — AgentMail-style communication observation
        "agent_inbox_observed": "agent", "agent_email_address_observed": "agent",
        "agent_thread_observed": "agent", "agent_message_received_observed": "agent",
        "agent_message_sent_observed": "agent", "agent_reply_observed": "agent",
        "agent_attachment_observed": "agent", "agent_attachment_parsed_observed": "agent",
        "agent_otp_detected_observed": "agent", "agent_invoice_detected_observed": "agent",
        "agent_receipt_detected_observed": "agent", "agent_calendar_intent_observed": "agent",
        "agent_support_route_observed": "agent", "agent_semantic_search_observed": "agent",
        "agent_data_extraction_observed": "agent",
        # x402 legacy
        "x402_payment": "x402",
        # x402 lifecycle granular
        "x402_payment_initiated": "x402", "x402_payment_authorized": "x402",
        "x402_authorization_requested": "x402", "x402_authorization_resolved": "x402",
        "x402_payment_intent_created": "x402", "x402_payment_submitted": "x402",
        "x402_payment_settled": "x402", "x402_payment_failed": "x402",
        "x402_payment_timeout": "x402", "x402_receipt_verified": "x402",
        "x402_access_granted": "x402", "x402_access_denied": "x402",
        "x402_refund_or_reversal": "x402",
        # x402 protocol observation
        "x402_resource_request_observed": "x402", "x402_challenge_observed": "x402",
        "x402_payment_requirement_observed": "x402", "x402_signature_observed": "x402",
        "x402_verification_observed": "x402", "x402_settlement_observed": "x402",
        "x402_resource_access_observed": "x402", "x402_resource_access_denied_observed": "x402",
        "x402_failure_observed": "x402", "x402_replay_risk_observed": "x402",
        "x402_provider_observed": "x402",
        # reward
        "reward_action_queued": "reward", "reward_proof_generated": "reward",
        "reward_delivered": "reward", "reward_claim_submitted": "reward",
    }
    return _FAMILY_MAP.get(event_type, "core")


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
    props: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """
    Recursively scrub keys matching sensitive patterns.
    Returns (scrubbed_dict, had_sensitive_fields).
    """
    out: dict[str, Any] = {}
    had_sensitive = False
    for k, v in props.items():
        k_lower = k.lower()
        is_sensitive = any(p.search(k_lower) for p in _SENSITIVE_KEY_PATTERNS)
        if is_sensitive:
            out[k] = "[REDACTED]"
            had_sensitive = True
        elif isinstance(v, dict):
            scrubbed_v, child_sensitive = _scrub_sensitive_fields(v)
            out[k] = scrubbed_v
            if child_sensitive:
                had_sensitive = True
        else:
            out[k] = v
    return out, had_sensitive
