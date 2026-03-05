"""
Aether Shared — @aether/events
Event schema definitions, producer/consumer wrappers, dead-letter handling.
Used by: Ingestion, Identity, Analytics, ML Serving, Agent.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.events")

EventHandler = Callable[["Event"], Awaitable[None]]


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
# PRODUCER (abstract — swap implementation for Kafka vs SNS)
# ═══════════════════════════════════════════════════════════════════════════

class EventProducer:
    """
    Publishes events to the event bus with retry logic.
    Stub implementation — logs events in memory.
    Replace with aiokafka.AIOKafkaProducer or boto3 SNS client.
    """

    MAX_RETRIES = 3
    BASE_BACKOFF_S = 0.1

    def __init__(self) -> None:
        self._published: list[Event] = []
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("EventProducer connected (in-memory stub)")

    async def close(self) -> None:
        self._connected = False
        logger.info("EventProducer closed")

    async def publish(self, event: Event) -> None:
        """Publish a single event with retry."""
        for attempt in range(self.MAX_RETRIES):
            try:
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
        for event in events:
            await self.publish(event)

    @property
    def published_count(self) -> int:
        return len(self._published)

    async def health_check(self) -> bool:
        return self._connected or True  # Stub always healthy


# ═══════════════════════════════════════════════════════════════════════════
# CONSUMER (abstract)
# ═══════════════════════════════════════════════════════════════════════════

class EventConsumer:
    """
    Subscribes to topics and processes events with backpressure.
    Stub — in production use aiokafka.AIOKafkaConsumer or SQS poller.
    """

    MAX_CONCURRENT = 10
    MAX_HANDLER_RETRIES = 2

    def __init__(self) -> None:
        self._handlers: dict[Topic, list[EventHandler]] = {}
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._dlq: list[Event] = []

    def subscribe(self, topic: Topic, handler: EventHandler) -> None:
        self._handlers.setdefault(topic, []).append(handler)
        logger.info(f"Subscribed handler to {topic.value}")

    async def process(self, event: Event) -> None:
        """Process an event with concurrency limiting and retry."""
        async with self._semaphore:
            handlers = self._handlers.get(event.topic, [])
            for handler in handlers:
                try:
                    await handler(event)
                    metrics.increment("events_processed", labels={"topic": event.topic.value})
                except Exception as e:
                    logger.error(f"Handler failed for event {event.event_id}: {e}")
                    metrics.increment("events_handler_failed", labels={"topic": event.topic.value})
                    if event.retry_count < self.MAX_HANDLER_RETRIES:
                        event.retry_count += 1
                        logger.info(f"Retrying event {event.event_id} (attempt {event.retry_count})")
                        await self.process(event)
                    else:
                        await self._send_to_dlq(event, str(e))

    async def _send_to_dlq(self, event: Event, error: str) -> None:
        """Send failed events to dead-letter queue for manual review."""
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

    @property
    def dlq_depth(self) -> int:
        return len(self._dlq)
