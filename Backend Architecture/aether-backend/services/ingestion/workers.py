"""
Aether Service — Ingestion Workers

Kafka consumers that drive the Bronze → Silver → identity signal pipeline
for SDK events.  Workers are attached to the shared EventConsumer during
app startup via attach_ingestion_workers().

Worker topology:
  SDK_EVENTS_VALIDATED → sdk_bronze_writer → writes to bronze_sdk_events
                       → silver_normalizer  → writes to silver_sdk_events
                       → silver_fact_projector → SilverDispatcher fan-out →
                         silver fact tables (+ canonical activity, graph queue)
                       → identity_signal_emitter → publishes IDENTITY_RESOLVED

These workers never mutate graph/profile directly; they emit signals that
the Profile360 and identity-resolution services consume.
"""

from __future__ import annotations

import os

from shared.events.events import Event, EventConsumer, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from repositories.lake import BronzeRepository, SilverRepository

logger = get_logger("aether.service.ingestion.workers")

_bronze = BronzeRepository("sdk_events")
_silver = SilverRepository("sdk_events")

SCHEMA_VERSION = "1.0.0"


async def sdk_bronze_writer(event: Event) -> None:
    """
    Consume validated SDK events and write to Bronze tier.

    Idempotent — if the event was already written by the /v1/batch handler
    (durable pre-ACK write) the duplicate check in BronzeRepository.ingest()
    will skip it silently.  This covers the replay path where the
    Bronze write came first.
    """
    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_id = payload.get("event_id", event.event_id)

    try:
        await _bronze.ingest(
            source="sdk",
            source_tag=payload.get("batch_id", ""),
            provider_record_id=event_id,
            payload=payload,
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            entity_id=(
                payload.get("user_id")
                or payload.get("anonymous_id", "")
            ),
            entity_type="user",
            tenant_id=tenant_id,
        )
        metrics.increment("ingestion_bronze_write_latency_ms")  # real latency via instrumentation
        metrics.increment("sdk_bronze_written_total", labels={"tenant_id": tenant_id})
    except Exception as exc:
        logger.error(
            "sdk_bronze_writer failed for event %s: %s", event_id, exc, exc_info=True
        )
        raise  # triggers DLQ in EventConsumer


async def silver_normalizer(event: Event) -> None:
    """
    Consume validated SDK events and normalize into Silver tier.

    Silver is the entity-normalized view: one record per (entity, source)
    pair, merged from all SDK events.  Only a safe subset of fields is
    included — raw PII is never written to Silver.
    """
    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_id = payload.get("event_id", event.event_id)
    event_type = payload.get("event_type", "")

    entity_id = payload.get("user_id") or payload.get("anonymous_id", "")
    entity_type = "user"

    # Normalize to a stable Silver shape (no raw PII)
    normalized = {
        "last_event_type": event_type,
        "last_event_at": payload.get("timestamp", ""),
        "last_session_id": payload.get("session_id", ""),
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
    }

    # Merge identity fields without exposing raw PII
    if payload.get("user_id"):
        normalized["user_id"] = payload["user_id"]
    if payload.get("anonymous_id"):
        normalized["anonymous_id"] = payload["anonymous_id"]

    try:
        await _silver.upsert_record(
            entity_id=entity_id,
            entity_type=entity_type,
            source="sdk",
            source_tag=payload.get("batch_id", ""),
            normalized=normalized,
            bronze_id=event_id,
            tenant_id=tenant_id,
        )
        metrics.increment("ingestion_silver_written_total", labels={"tenant_id": tenant_id})
    except Exception as exc:
        logger.error(
            "silver_normalizer failed for event %s: %s", event_id, exc, exc_info=True
        )
        raise  # triggers DLQ in EventConsumer


def _bus_payload_to_sdk_envelope(payload: dict) -> dict:
    """Translate the normalized bus payload back to the SDK envelope shape
    the Silver projectors consume (type/messageId/context/properties)."""
    context = dict(payload.get("context") or {})
    context.setdefault("tenantId", payload.get("tenant_id"))
    return {
        "type": payload.get("event_type", ""),
        "messageId": payload.get("event_id"),
        "userId": payload.get("user_id"),
        "anonymousId": payload.get("anonymous_id"),
        "sessionId": payload.get("session_id"),
        "timestamp": payload.get("timestamp"),
        "receivedAt": payload.get("received_at"),
        "properties": payload.get("properties") or {},
        "context": context,
        "family": payload.get("event_family", ""),
    }


async def silver_fact_projector(event: Event) -> None:
    """Fan the validated event out to Silver fact projectors and persist rows.

    This is the durable Bronze → Silver fact path: the SilverDispatcher runs
    the ordered projector list (comms lifecycle first — ADR-C3), the writer
    persists each table idempotently, and communication events additionally
    trigger an asynchronous communication-state rebuild.

    Projection failures never raise: Bronze is already durable, and replaying
    the Bronze range recovers any missed facts.
    """
    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_type = payload.get("event_type", "")

    from services.silver.dispatcher import SilverDispatcher
    from services.comms.contracts import COMMUNICATION_EVENT_TYPES

    if event_type in COMMUNICATION_EVENT_TYPES and not _comms_ingestion_enabled():
        return

    dispatcher = SilverDispatcher()
    if not dispatcher.handles(event_type):
        return

    envelope = _bus_payload_to_sdk_envelope(payload)
    try:
        outcome = await dispatcher.project_with_outcome(envelope)
        if outcome.results:
            from services.silver.writer import SilverFactWriter
            written = await SilverFactWriter().persist(outcome.results)
            metrics.increment(
                "silver_facts_written_total", written,
                labels={"tenant_id": tenant_id, "event_type": event_type},
            )
        for failed in outcome.failed_projectors:
            metrics.increment(
                "silver_projection_dead_letters_total",
                labels={"tenant_id": tenant_id, "projector": failed},
            )
    except Exception as exc:
        logger.error(
            "silver_fact_projector failed for event %s: %s",
            payload.get("event_id"), exc, exc_info=True,
        )
        return

    # Communication events keep the per-entity state and journey fresh.
    # Rebuilds are coalesced: an event burst for one profile inside the
    # debounce window produces exactly one state recompute and one journey
    # recompile (Phase 15) instead of one per event.
    if event_type in COMMUNICATION_EVENT_TYPES:
        entity_id = payload.get("user_id") or payload.get("anonymous_id")
        props = payload.get("properties") or {}
        entity_id = props.get("recipient_entity_id") or props.get("profile_id") or entity_id
        if entity_id:
            try:
                from services.comms.rebuild_coalescer import get_rebuild_coalescer
                await get_rebuild_coalescer().request_rebuild(
                    tenant_id, str(entity_id),
                    channel=props.get("channel") or "email",
                    reason=event_type,
                )
            except Exception as exc:
                logger.warning("comms_rebuild_request_failed entity=%s: %s", entity_id, exc)


def _comms_ingestion_enabled() -> bool:
    return os.getenv("AETHER_COMMS_INGESTION_ENABLED", "true").lower() != "false"


async def identity_signal_emitter(event: Event, producer: EventProducer) -> None:
    """
    Emit an identity resolution signal for identify/user events.

    Only emits for event types that carry strong identity signals:
    - identify: user_id + anonymous_id → IDENTITY_RESOLVED
    - wallet: wallet address → IDENTITY_RESOLVED

    Fingerprint-only signals are never used as high-confidence identity anchors.
    """
    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_type = payload.get("event_type", "")

    if event_type not in {"identify", "wallet"}:
        return

    signal: dict = {
        "tenant_id": tenant_id,
        "anonymous_id": payload.get("anonymous_id", ""),
        "session_id": payload.get("session_id", ""),
        "source": "sdk",
        "confidence": 0.0,
    }

    if event_type == "identify" and payload.get("user_id"):
        signal["user_id"] = payload["user_id"]
        signal["confidence"] = 0.95  # strong signal: explicit identification

    if event_type == "wallet":
        props = payload.get("properties", {})
        wallet_addr = props.get("address") or props.get("wallet_address", "")
        if wallet_addr:
            signal["wallet_address"] = wallet_addr
            signal["confidence"] = 0.85

    if signal["confidence"] == 0.0:
        return

    try:
        await producer.publish(Event(
            topic=Topic.IDENTITY_RESOLVED,
            tenant_id=tenant_id,
            source_service="ingestion.workers",
            payload=signal,
        ))
    except Exception as exc:
        logger.warning("identity_signal_emitter publish failed: %s", exc)
        # Not a critical failure — identity resolution will catch up on replay


def attach_ingestion_workers(consumer: EventConsumer, producer: EventProducer) -> None:
    """
    Wire ingestion workers to the shared event consumer.
    Called from main.py lifespan during startup.
    """
    import functools

    # Bronze writer
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, sdk_bronze_writer)
    logger.info("Ingestion worker attached: sdk_bronze_writer → SDK_EVENTS_VALIDATED")

    # Silver normalizer
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, silver_normalizer)
    logger.info("Ingestion worker attached: silver_normalizer → SDK_EVENTS_VALIDATED")

    # Silver fact projector — multi-projector dispatch into silver fact tables
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, silver_fact_projector)
    logger.info("Ingestion worker attached: silver_fact_projector → SDK_EVENTS_VALIDATED")

    # Identity signal emitter (needs producer reference via partial)
    identity_handler = functools.partial(identity_signal_emitter, producer=producer)
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, identity_handler)
    logger.info("Ingestion worker attached: identity_signal_emitter → SDK_EVENTS_VALIDATED")
