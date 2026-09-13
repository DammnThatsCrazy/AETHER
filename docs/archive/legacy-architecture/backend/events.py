"""
Aether Shared — @aether/events
Event schema definitions, producer/consumer wrappers, dead-letter handling.
Used by: Ingestion, Identity, Analytics, ML Serving, Agent.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from shared.logger.logger import get_logger

logger = get_logger("aether.events")


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
        )


# ═══════════════════════════════════════════════════════════════════════════
# PRODUCER (abstract — swap implementation for Kafka vs SNS)
# ═══════════════════════════════════════════════════════════════════════════

class EventProducer:
    """
    Publishes events to the event bus.
    Stub implementation — logs events in memory.
    Replace with aiokafka.AIOKafkaProducer or boto3 SNS client.
    """

    def __init__(self):
        self._published: list[Event] = []

    async def publish(self, event: Event):
        logger.info(
            f"Publishing event {event.event_id} to {event.topic.value}"
        )
        self._published.append(event)
        # --- PRODUCTION ---
        # await self._kafka_producer.send(event.topic.value, event.serialize().encode())

    async def publish_batch(self, events: list[Event]):
        for event in events:
            await self.publish(event)


# ═══════════════════════════════════════════════════════════════════════════
# CONSUMER (abstract)
# ═══════════════════════════════════════════════════════════════════════════

class EventConsumer:
    """
    Subscribes to topics and processes events.
    Stub — in production use aiokafka.AIOKafkaConsumer or SQS poller.
    """

    def __init__(self):
        self._handlers: dict[Topic, list[Callable]] = {}

    def subscribe(self, topic: Topic, handler: Callable):
        self._handlers.setdefault(topic, []).append(handler)
        logger.info(f"Subscribed handler to {topic.value}")

    async def process(self, event: Event):
        handlers = self._handlers.get(event.topic, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Handler failed for event {event.event_id}: {e}"
                )
                await self._send_to_dlq(event, str(e))

    async def _send_to_dlq(self, event: Event, error: str):
        logger.warning(
            f"Sending event {event.event_id} to dead-letter queue: {error}"
        )
        # --- PRODUCTION ---
        # Publish to DEAD_LETTER topic with error metadata
