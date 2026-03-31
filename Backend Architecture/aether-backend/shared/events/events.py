"""
Aether Shared — @aether/events
Event schema definitions, producer/consumer wrappers, dead-letter handling.
Used by: Ingestion, Identity, Analytics, ML Serving, Agent.

Backend selection:
- AETHER_ENV=local → in-memory event bus (no Kafka required)
- AETHER_ENV=staging/production → Kafka via aiokafka
  Set KAFKA_BOOTSTRAP_SERVERS env var.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.events")

EventHandler = Callable[["Event"], Awaitable[None]]

# Optional aiokafka import
try:
    from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    AIOKafkaProducer = None  # type: ignore[misc, assignment]
    AIOKafkaConsumer = None  # type: ignore[misc, assignment]
    KAFKA_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _kafka_bootstrap() -> str:
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")


# ═══════════════════════════════════════════════════════════════════════════
# EVENT TOPICS
# ═══════════════════════════════════════════════════════════════════════════

class Topic(str, Enum):
    # Ingestion
    SDK_EVENTS_RAW = "aether.sdk.events.raw"
    SDK_EVENTS_VALIDATED = "aether.sdk.events.validated"
    API_FEED_RAW = "aether.api.feed.raw"

    # Identity
    IDENTITY_RESOLVED = "aether.identity.resolved"
    IDENTITY_MERGED = "aether.identity.merged"
    PROFILE_UPDATED = "aether.profile.updated"

    # Analytics
    SESSION_SCORED = "aether.analytics.session.scored"
    ANOMALY_DETECTED = "aether.analytics.anomaly"

    # ML
    PREDICTION_GENERATED = "aether.ml.prediction"
    MODEL_UPDATED = "aether.ml.model.updated"

    # Agent
    AGENT_DISCOVERY = "aether.agent.discovery"
    AGENT_ENRICHMENT = "aether.agent.enrichment"

    # Campaign
    ATTRIBUTION_CALCULATED = "aether.campaign.attribution"

    # Consent
    CONSENT_UPDATED = "aether.consent.updated"
    DATA_SUBJECT_REQUEST = "aether.consent.dsr"

    # Identity Resolution
    RESOLUTION_EVALUATED = "aether.resolution.evaluated"
    RESOLUTION_AUTO_MERGED = "aether.resolution.auto_merged"
    RESOLUTION_FLAGGED = "aether.resolution.flagged"
    RESOLUTION_APPROVED = "aether.resolution.approved"
    RESOLUTION_REJECTED = "aether.resolution.rejected"
    FINGERPRINT_OBSERVED = "aether.identity.fingerprint.observed"
    IP_OBSERVED = "aether.identity.ip.observed"

    # Intelligence Graph — Agent Behavioral (L2)
    AGENT_TASK_STARTED = "aether.agent.task.started"
    AGENT_TASK_COMPLETED = "aether.agent.task.completed"
    AGENT_DECISION_MADE = "aether.agent.decision.made"
    AGENT_STATE_SNAPSHOT = "aether.agent.state.snapshot"
    AGENT_GROUND_TRUTH = "aether.agent.ground_truth"

    # Intelligence Graph — Agent-to-Human (A2H)
    AGENT_NOTIFICATION_SENT = "aether.agent.notification.sent"
    AGENT_RECOMMENDATION_MADE = "aether.agent.recommendation.made"
    AGENT_RESULT_DELIVERED = "aether.agent.result.delivered"
    AGENT_ESCALATION_RAISED = "aether.agent.escalation.raised"

    # Intelligence Graph — Commerce (L3a)
    PAYMENT_SENT = "aether.commerce.payment.sent"
    AGENT_HIRED = "aether.commerce.agent.hired"
    SERVICE_PURCHASED = "aether.commerce.service.purchased"  # Reserved — not yet published by any service
    FEE_ELIMINATED = "aether.commerce.fee.eliminated"  # Reserved — not yet published by any service

    # Intelligence Graph — On-Chain Actions (L0)
    ACTION_RECORDED = "aether.onchain.action.recorded"
    CONTRACT_DEPLOYED = "aether.onchain.contract.deployed"
    CONTRACT_CALLED = "aether.onchain.contract.called"

    # Intelligence Graph — x402 Payments (L3b)
    X402_PAYMENT_CAPTURED = "aether.x402.payment.captured"

    # Extraction Defense Mesh
    ML_EXTRACTION_REQUEST_SEEN = "aether.extraction.request.seen"
    ML_EXTRACTION_IDENTITY_RESOLVED = "aether.extraction.identity.resolved"
    ML_EXTRACTION_SIGNAL_COMPUTED = "aether.extraction.signal.computed"
    ML_EXTRACTION_SCORE_UPDATED = "aether.extraction.score.updated"
    ML_EXTRACTION_POLICY_APPLIED = "aether.extraction.policy.applied"
    ML_EXTRACTION_CANARY_HIT = "aether.extraction.canary.hit"
    ML_EXTRACTION_ALERT_OPENED = "aether.extraction.alert.opened"
    ML_EXTRACTION_CLUSTER_ESCALATED = "aether.extraction.cluster.escalated"

    # Dead letter
    DEAD_LETTER = "aether.dlq"


# ═══════════════════════════════════════════════════════════════════════════
# EVENT SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Event:
    topic: Topic
    payload: dict[str, Any]
    tenant_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_service: str = ""
    correlation_id: str = ""
    version: str = "1.0"
    retry_count: int = 0

    def serialize(self) -> str:
        return json.dumps({
            "event_id": self.event_id,
            "topic": self.topic.value,
            "version": self.version,
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "source_service": self.source_service,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "retry_count": self.retry_count,
        })

    @classmethod
    def deserialize(cls, raw: str) -> Event:
        data = json.loads(raw)
        return cls(
            event_id=data["event_id"],
            topic=Topic(data["topic"]),
            version=data.get("version", "1.0"),
            timestamp=data["timestamp"],
            tenant_id=data.get("tenant_id", ""),
            source_service=data.get("source_service", ""),
            correlation_id=data.get("correlation_id", ""),
            payload=data["payload"],
            retry_count=data.get("retry_count", 0),
        )


# ═══════════════════════════════════════════════════════════════════════════
# PRODUCER — auto-selects Kafka or in-memory
# ═══════════════════════════════════════════════════════════════════════════

class EventProducer:
    """
    Publishes events to the event bus with retry logic.

    Backend selection:
    - AETHER_ENV=local → in-memory list (for dev/testing)
    - AETHER_ENV=staging/production → Kafka via aiokafka
    """

    MAX_RETRIES = 3
    BASE_BACKOFF_S = 0.1

    def __init__(self) -> None:
        self._published: list[Event] = []
        self._connected = False
        self._kafka_producer: Optional[Any] = None
        self._mode = "uninitialized"

    async def connect(self) -> None:
        bootstrap = _kafka_bootstrap()
        if bootstrap and KAFKA_AVAILABLE:
            try:
                self._kafka_producer = AIOKafkaProducer(
                    bootstrap_servers=bootstrap,
                    value_serializer=lambda v: v.encode("utf-8"),
                    acks="all",
                    retries=3,
                    request_timeout_ms=30000,
                )
                await self._kafka_producer.start()
                self._mode = "kafka"
                logger.info(f"EventProducer connected (Kafka: {bootstrap})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(f"Kafka not reachable ({e}) — falling back to in-memory")
                    self._kafka_producer = None
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(
                        f"Kafka not reachable at {bootstrap}: {e}. "
                        "Set AETHER_ENV=local for in-memory fallback."
                    )
        elif _is_local_env():
            self._mode = "in-memory"
            logger.info("EventProducer connected (in-memory, local mode)")
        else:
            if not KAFKA_AVAILABLE:
                raise RuntimeError(
                    "aiokafka required for production: pip install aiokafka>=0.10"
                )
            raise RuntimeError(
                "KAFKA_BOOTSTRAP_SERVERS not set. Required in non-local environments."
            )
        self._connected = True

    async def close(self) -> None:
        if self._kafka_producer:
            await self._kafka_producer.stop()
            self._kafka_producer = None
        self._connected = False
        logger.info("EventProducer closed")

    async def publish(self, event: Event) -> None:
        """Publish a single event with retry."""
        if not self._connected:
            await self.connect()

        for attempt in range(self.MAX_RETRIES):
            try:
                if self._kafka_producer:
                    await self._kafka_producer.send_and_wait(
                        event.topic.value, event.serialize()
                    )
                else:
                    self._published.append(event)

                metrics.increment("events_published", labels={"topic": event.topic.value})
                logger.info(f"Published event {event.event_id} to {event.topic.value}")
                return
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(f"Failed to publish event {event.event_id} after {self.MAX_RETRIES} attempts: {e}")
                    metrics.increment("events_publish_failed", labels={"topic": event.topic.value})
                    raise
                backoff = self.BASE_BACKOFF_S * (2 ** attempt)
                logger.warning(f"Publish retry {attempt + 1} for {event.event_id}, backoff {backoff}s")
                await asyncio.sleep(backoff)

    async def publish_batch(self, events: list[Event]) -> None:
        """Publish a batch of events."""
        if self._kafka_producer:
            batch = self._kafka_producer.create_batch()
            for event in events:
                batch.append(
                    value=event.serialize().encode("utf-8"),
                    key=None,
                    timestamp=None,
                )
            for event in events:
                await self.publish(event)
        else:
            for event in events:
                await self.publish(event)

    @property
    def published_count(self) -> int:
        return len(self._published)

    async def health_check(self) -> bool:
        if not self._connected:
            return False
        if self._kafka_producer:
            try:
                partitions = await self._kafka_producer.partitions_for("__health")
                return True
            except Exception:
                return False
        return True  # In-memory mode is always healthy

    @property
    def mode(self) -> str:
        return self._mode


# ═══════════════════════════════════════════════════════════════════════════
# CONSUMER — auto-selects Kafka or in-memory
# ═══════════════════════════════════════════════════════════════════════════

class EventConsumer:
    """
    Subscribes to topics and processes events with backpressure.

    Backend:
    - AETHER_ENV=local → processes events in-memory via process()
    - AETHER_ENV=staging/production → Kafka consumer group via aiokafka
    """

    MAX_CONCURRENT = 10
    MAX_HANDLER_RETRIES = 2

    def __init__(self, group_id: str = "aether-backend") -> None:
        self._handlers: dict[Topic, list[EventHandler]] = {}
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._dlq: list[Event] = []
        self._kafka_consumer: Optional[Any] = None
        self._group_id = group_id
        self._running = False
        self._mode = "uninitialized"

    def subscribe(self, topic: Topic, handler: EventHandler) -> None:
        self._handlers.setdefault(topic, []).append(handler)
        logger.info(f"Subscribed handler to {topic.value}")

    async def start(self) -> None:
        """Start consuming from Kafka or stay in in-memory mode."""
        bootstrap = _kafka_bootstrap()
        topics = [t.value for t in self._handlers.keys()]
        if not topics:
            self._mode = "in-memory"
            logger.info("EventConsumer: no subscriptions, in-memory mode")
            return

        if bootstrap and KAFKA_AVAILABLE:
            try:
                self._kafka_consumer = AIOKafkaConsumer(
                    *topics,
                    bootstrap_servers=bootstrap,
                    group_id=self._group_id,
                    auto_offset_reset="earliest",
                    enable_auto_commit=True,
                    value_deserializer=lambda m: m.decode("utf-8"),
                )
                await self._kafka_consumer.start()
                self._mode = "kafka"
                self._running = True
                logger.info(f"EventConsumer started (Kafka: {bootstrap}, topics: {topics})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(f"Kafka consumer start failed ({e}) — in-memory mode")
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(f"Kafka consumer start failed: {e}")
        else:
            self._mode = "in-memory"
            logger.info("EventConsumer started (in-memory mode)")

    async def consume_loop(self) -> None:
        """Main consume loop for Kafka mode. Run as asyncio task."""
        if not self._kafka_consumer:
            return
        try:
            async for msg in self._kafka_consumer:
                try:
                    event = Event.deserialize(msg.value)
                    await self.process(event)
                except Exception as e:
                    logger.error(f"Error processing Kafka message: {e}")
        except Exception as e:
            logger.error(f"Kafka consume loop error: {e}")
        finally:
            self._running = False

    async def process(self, event: Event) -> None:
        """Process an event with concurrency limiting and retry."""
        async with self._semaphore:
            handlers = self._handlers.get(event.topic, [])
            for handler in handlers:
                success = False
                while not success:
                    try:
                        await handler(event)
                        metrics.increment("events_processed", labels={"topic": event.topic.value})
                        success = True
                    except Exception as e:
                        logger.error(f"Handler failed for event {event.event_id}: {e}")
                        metrics.increment("events_handler_failed", labels={"topic": event.topic.value})
                        if event.retry_count < self.MAX_HANDLER_RETRIES:
                            event.retry_count += 1
                            logger.info(f"Retrying event {event.event_id} (attempt {event.retry_count})")
                        else:
                            await self._send_to_dlq(event, str(e))
                            break

    async def _send_to_dlq(self, event: Event, error: str) -> None:
        """Send failed events to dead-letter queue."""
        dlq_event = Event(
            topic=Topic.DEAD_LETTER,
            tenant_id=event.tenant_id,
            source_service=event.source_service,
            correlation_id=event.correlation_id,
            payload={
                "original_topic": event.topic.value,
                "original_event_id": event.event_id,
                "original_payload": event.payload,
                "error": error,
                "retry_count": event.retry_count,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._dlq.append(dlq_event)
        metrics.increment("events_dead_lettered")
        logger.warning(f"Event {event.event_id} sent to DLQ: {error}")

    async def stop(self) -> None:
        self._running = False
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
            self._kafka_consumer = None
        logger.info("EventConsumer stopped")

    @property
    def dlq_depth(self) -> int:
        return len(self._dlq)

    @property
    def mode(self) -> str:
        return self._mode
