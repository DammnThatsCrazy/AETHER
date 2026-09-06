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

from shared.backend_interpretation.flags import (
    outcome_truth_store_enabled,
    silver_temporal_envelope_enabled,
)
from shared.events.events import Event, EventConsumer, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from repositories.lake import BronzeRepository, SilverRepository
from services.ingestion.acquisition_privacy import sanitize_acquisition_payload
from services.ingestion.spine import (
    ObservationView,
    normalization_spine_enabled,
    to_observation_view,
)

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

    Relay-originated events (V2 transactional path) are skipped entirely:
    their typed Bronze row was persisted in the SAME transaction that
    enqueued the outbox row (bronze_bulk.ingest_many), and the V2 row id
    derivation differs from BronzeRepository's idempotency key — writing
    here would create an untyped duplicate under a different row id.
    """
    from services.ingestion.outbox_relay import RELAY_SOURCE_SERVICE

    if event.source_service == RELAY_SOURCE_SERVICE:
        metrics.increment("ingestion_bronze_relay_skip_total")
        return

    # Ingestion-level replay events (WS-B4) are skipped for the same reason:
    # the event's durable Bronze row already exists — it is exactly what the
    # replay re-delivered (original-time preservation, Invariant #15). Writing
    # here would mint a SECOND Bronze row for the same original event.
    from services.ingestion.replay import REPLAY_SOURCE_SERVICE

    if event.source_service == REPLAY_SOURCE_SERVICE:
        metrics.increment("ingestion_bronze_replay_skip_total")
        return

    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_id = payload.get("event_id", event.event_id)

    try:
        await _bronze.ingest(
            source="sdk",
            source_tag=payload.get("batch_id", ""),
            provider_record_id=event_id,
            payload=sanitize_acquisition_payload(payload),
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

    WS-B5: when the normalization-spine flag is ON the entity identity and
    occurrence reads go through :func:`to_observation_view` (so an additive
    envelope or an AetherEvent ``subject_id`` is reachable); when OFF every
    read is the legacy flat-key read (byte/row parity).
    """
    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_id = payload.get("event_id", event.event_id)
    event_type = payload.get("event_type", "")

    view = to_observation_view(payload) if normalization_spine_enabled() else None
    user_id = payload.get("user_id")
    anonymous_id = payload.get("anonymous_id")
    session_id = payload.get("session_id")
    last_event_at = payload.get("timestamp", "")
    if view is not None:
        if view.user_id is not None:
            user_id = view.user_id
        if view.anonymous_id is not None:
            anonymous_id = view.anonymous_id
        if view.session_id is not None:
            session_id = view.session_id
        if view.occurred_at is not None:
            last_event_at = view.occurred_at

    entity_id = user_id or anonymous_id or ""
    entity_type = "user"

    # Normalize to a stable Silver shape (no raw PII)
    normalized = {
        "last_event_type": event_type,
        "last_event_at": last_event_at,
        "last_session_id": session_id or "",
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
    }

    # Merge identity fields without exposing raw PII
    if user_id:
        normalized["user_id"] = user_id
    if anonymous_id:
        normalized["anonymous_id"] = anonymous_id

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
    the Silver projectors consume (type/messageId/context/properties).

    WS-B5: when the normalization-spine flag is ON the envelope is projected
    off :func:`to_observation_view`, so an AetherEvent dump gains its subject/
    occurrence instead of silently dropping them; when OFF (default) this is the
    legacy flat mapping, field-for-field (byte/row parity — the branch the
    existing Silver write-path tests assert).
    """
    if normalization_spine_enabled():
        return _project_sdk_envelope(to_observation_view(payload))
    return _legacy_sdk_envelope(payload)


def _legacy_sdk_envelope(payload: dict) -> dict:
    """The pre-spine flat mapping (kept verbatim so flag OFF is byte-identical)."""
    context = dict(payload.get("context") or {})
    # ``payload.tenant_id`` was bound from the authenticated ingestion context.
    # Never let an SDK-supplied context.tenantId override that authority when
    # rebuilding the projector envelope; doing so would permit cross-tenant
    # Silver facts and verified-referral lookups.
    context["tenantId"] = payload.get("tenant_id")
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


def _project_sdk_envelope(view: ObservationView) -> dict:
    """Project an observation view onto the Silver projector envelope.

    Mirrors ``_legacy_sdk_envelope`` field-for-field for the flat SDK/comms
    view so flag ON and OFF stay byte-parallel for legacy fixtures.
    """
    context = dict(view.context or {})
    # Tenant authority is preserved from the view's tenancy/tenant read (never
    # let a payload/context-supplied tenantId override it).
    context["tenantId"] = view.tenant_id
    return {
        "type": view.observation_type or "",
        "messageId": view.observation_id,
        "userId": view.user_id,
        "anonymousId": view.anonymous_id,
        "sessionId": view.session_id,
        "timestamp": view.occurred_at,
        "receivedAt": view.received_at,
        "properties": dict(view.payload_dict) if view.payload_dict else {},
        "context": context,
        "family": view.family or "",
    }


def _apply_silver_temporal(payload: dict, envelope: dict) -> dict:
    """WS-D item 5: carry the server-built temporal envelope to the Silver edge.

    Temporal enforcement (``enforce_temporal``) already rides the normalized
    Bronze payload as a ``temporal`` block when active; today the Silver
    projectors DROP it because they re-read the raw client ``timestamp``. When
    ``AETHER_SILVER_TEMPORAL_ENVELOPE_ENABLED`` is ON and the payload carries a
    server temporal block, its authoritative ``occurred_at`` replaces the raw
    client timestamp on the projector envelope so Silver facts are stamped with
    server time. OFF (default) is byte-for-byte unchanged.
    """
    if not silver_temporal_envelope_enabled():
        return envelope
    temporal = payload.get("temporal")
    if not isinstance(temporal, dict) or not temporal.get("occurred_at"):
        return envelope
    authoritative = dict(envelope)
    authoritative["temporal"] = temporal
    authoritative["timestamp"] = temporal["occurred_at"]
    return authoritative


async def _record_outcome_truth(
    tenant_id: str, payload: dict, results: list
) -> None:
    """WS-D item 3: mirror projected Silver outcome rows into the durable
    outcome-truth store with evidence lineage. Best-effort; failures log."""
    try:
        from services.measurement.outcome.truth_recorder import (
            record_from_silver_outcome,
        )
        from services.operational_intelligence.models import EntityRef

        for result in results or ():
            table = getattr(result, "table", None)
            if table != "silver_outcome_facts":
                continue
            for row in getattr(result, "rows", None) or []:
                subject_id = row.get("user_id") or row.get("actor_id")
                subject = (
                    EntityRef(kind="user", id=str(subject_id)) if subject_id else None
                )
                event_id = str(
                    row.get("source_event_id") or payload.get("event_id") or ""
                )
                await record_from_silver_outcome(
                    tenant_id=tenant_id,
                    row=row,
                    event_id=event_id,
                    subject=subject,
                )
    except Exception as exc:  # noqa: BLE001 - recorder must never fail projection
        logger.warning("outcome-truth record skipped: %s", exc)


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
    # WS-D item 5: when enabled, the server-built temporal envelope (if the
    # Bronze payload carries one) overrides the raw client timestamp so Silver
    # facts are stamped with server-authoritative time.
    envelope = _apply_silver_temporal(payload, envelope)
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
        # WS-D item 3: when the durable outcome-truth store is enabled, mirror
        # every projected outcome Silver row into the lineaged outcome-truth
        # store (best-effort — Bronze is durable and replay recovers missed
        # rows; a recorder failure never fails the projection).
        if outcome_truth_store_enabled():
            await _record_outcome_truth(tenant_id, payload, outcome.results)
    except Exception as exc:
        logger.error(
            "silver_fact_projector failed for event %s: %s",
            payload.get("event_id"), exc, exc_info=True,
        )
        return

    # Card-linked context on payment/commerce SDK events also lands in the
    # durable card_linked_flows store — the source of truth every card-linked
    # read surface queries. The Silver CardLinkedProjector above only writes
    # the analytical card_linked_flow_facts projection. Best-effort: Bronze is
    # durable and a replay recovers missed flows.
    await _ingest_card_linked_context(tenant_id, payload)

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


async def _ingest_card_linked_context(tenant_id: str, payload: dict) -> None:
    """Feed card-linked SDK context into the durable flow store (flag-gated)."""
    try:
        from config.settings import get_settings

        if not get_settings().card_linked_payment_rails.enabled:
            return
        from services.card_linked_payments.ingestion import (
            CARD_LINKED_SDK_EVENT_TYPES,
            get_ingestion_service,
        )

        event_type = payload.get("event_type", "")
        if event_type not in CARD_LINKED_SDK_EVENT_TYPES:
            return
        event = {
            "type": event_type,
            "event_id": payload.get("event_id"),
            "timestamp": payload.get("timestamp"),
            "user_id": payload.get("user_id"),
            "agent_id": payload.get("agent_id"),
            "canonical_entity_id": payload.get("canonical_entity_id"),
            "org_id": payload.get("org_id"),
            "properties": payload.get("properties") or {},
        }
        await get_ingestion_service().ingest_sdk_event(tenant_id, event)
    except Exception as exc:  # pragma: no cover — best-effort side channel
        logger.debug("card-linked SDK ingestion skipped: %s", exc)


def _comms_ingestion_enabled() -> bool:
    return os.getenv("AETHER_COMMS_INGESTION_ENABLED", "true").lower() != "false"


async def identity_signal_emitter(event: Event, producer: EventProducer) -> None:
    """
    Emit an identity resolution signal for identify/user events.

    Only emits for event types that carry strong identity signals:
    - identify: user_id + anonymous_id → IDENTITY_RESOLVED
    - wallet: wallet address → IDENTITY_RESOLVED

    Fingerprint-only signals are never used as high-confidence identity anchors.

    WS-B5: when the normalization-spine flag is ON the identity reads go
    through :func:`to_observation_view`, so an AetherEvent ``subject_id`` (or an
    additive envelope user subject) becomes reachable; when OFF every read is
    the legacy flat-key read.
    """
    payload = event.payload
    tenant_id = event.tenant_id or payload.get("tenant_id", "")
    event_type = payload.get("event_type", "")

    if event_type not in {"identify", "wallet"}:
        return

    view = to_observation_view(payload) if normalization_spine_enabled() else None
    user_id = payload.get("user_id")
    anonymous_id = payload.get("anonymous_id", "")
    session_id = payload.get("session_id", "")
    if view is not None:
        if view.user_id is not None:
            user_id = view.user_id
        if view.anonymous_id is not None:
            anonymous_id = view.anonymous_id
        if view.session_id is not None:
            session_id = view.session_id

    signal: dict = {
        "tenant_id": tenant_id,
        "anonymous_id": anonymous_id,
        "session_id": session_id,
        "source": "sdk",
        "confidence": 0.0,
    }

    if event_type == "identify" and user_id:
        signal["user_id"] = user_id
        signal["confidence"] = 0.95  # strong signal: explicit identification

    if event_type == "wallet":
        props = dict(payload.get("properties") or {})
        if not props and view is not None and view.payload_dict:
            props = dict(view.payload_dict)
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
