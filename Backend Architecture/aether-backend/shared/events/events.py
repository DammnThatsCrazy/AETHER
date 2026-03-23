"""
Aether Shared — @aether/events
Event schema definitions, producer/consumer wrappers, dead-letter handling.
Used by: Ingestion, Identity, Analytics, ML Serving, Agent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.events")
EventHandler = Callable[["Event"], Awaitable[None]]


def _state_dir(component: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = base / "aether" / component
    path.mkdir(parents=True, exist_ok=True)
    return path


def _event_bus_db_path() -> Path:
    explicit = os.environ.get("AETHER_EVENT_BUS_DB_PATH")
    env = os.environ.get("AETHER_ENV", "local").lower()
    if explicit:
        path = Path(explicit)
    elif env == "local":
        path = _state_dir("events") / "event_bus.sqlite3"
    else:
        raise RuntimeError(
            "AETHER_EVENT_BUS_DB_PATH must be set in non-local environments to enable the durable event bus."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class Topic(str, Enum):
    SDK_EVENTS_RAW = "aether.sdk.events.raw"
    SDK_EVENTS_VALIDATED = "aether.sdk.events.validated"
    API_FEED_RAW = "aether.api.feed.raw"
    IDENTITY_RESOLVED = "aether.identity.resolved"
    IDENTITY_MERGED = "aether.identity.merged"
    PROFILE_UPDATED = "aether.profile.updated"
    SESSION_SCORED = "aether.analytics.session.scored"
    ANOMALY_DETECTED = "aether.analytics.anomaly"
    PREDICTION_GENERATED = "aether.ml.prediction"
    MODEL_UPDATED = "aether.ml.model.updated"
    AGENT_DISCOVERY = "aether.agent.discovery"
    AGENT_ENRICHMENT = "aether.agent.enrichment"
    ATTRIBUTION_CALCULATED = "aether.campaign.attribution"
    CONSENT_UPDATED = "aether.consent.updated"
    DATA_SUBJECT_REQUEST = "aether.consent.dsr"
    RESOLUTION_EVALUATED = "aether.resolution.evaluated"
    RESOLUTION_AUTO_MERGED = "aether.resolution.auto_merged"
    RESOLUTION_FLAGGED = "aether.resolution.flagged"
    RESOLUTION_APPROVED = "aether.resolution.approved"
    RESOLUTION_REJECTED = "aether.resolution.rejected"
    FINGERPRINT_OBSERVED = "aether.identity.fingerprint.observed"
    IP_OBSERVED = "aether.identity.ip.observed"
    AGENT_TASK_STARTED = "aether.agent.task.started"
    AGENT_TASK_COMPLETED = "aether.agent.task.completed"
    AGENT_DECISION_MADE = "aether.agent.decision.made"
    AGENT_STATE_SNAPSHOT = "aether.agent.state.snapshot"
    AGENT_GROUND_TRUTH = "aether.agent.ground_truth"
    AGENT_NOTIFICATION_SENT = "aether.agent.notification.sent"
    AGENT_RECOMMENDATION_MADE = "aether.agent.recommendation.made"
    AGENT_RESULT_DELIVERED = "aether.agent.result.delivered"
    AGENT_ESCALATION_RAISED = "aether.agent.escalation.raised"
    PAYMENT_SENT = "aether.commerce.payment.sent"
    AGENT_HIRED = "aether.commerce.agent.hired"
    SERVICE_PURCHASED = "aether.commerce.service.purchased"
    FEE_ELIMINATED = "aether.commerce.fee.eliminated"
    ACTION_RECORDED = "aether.onchain.action.recorded"
    CONTRACT_DEPLOYED = "aether.onchain.contract.deployed"
    CONTRACT_CALLED = "aether.onchain.contract.called"
    X402_PAYMENT_CAPTURED = "aether.x402.payment.captured"
    DEAD_LETTER = "aether.dlq"


@dataclass
class Event:
    topic: Topic
    payload: dict[str, Any]
    tenant_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
    def deserialize(cls, raw: str) -> "Event":
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


class _SQLiteEventBus:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_status_topic ON events(status, topic, id)"
            )

    def enqueue(self, event: Event) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO events(event_id, topic, payload, status, created_at, updated_at, error) VALUES (?, ?, ?, 'pending', ?, ?, '')",
                (event.event_id, event.topic.value, event.serialize(), now, now),
            )

    def next_event(self, topic: Topic) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE topic = ? AND status = 'pending' ORDER BY id LIMIT 1",
                (topic.value,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE events SET status = 'processing', updated_at = ? WHERE id = ?",
                (time.time(), row["id"]),
            )
            return row

    def mark_processed(self, record_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE events SET status = 'processed', updated_at = ? WHERE id = ?", (time.time(), record_id))

    def mark_dead_letter(self, record_id: int, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET status = 'dead_letter', updated_at = ?, error = ? WHERE id = ?",
                (time.time(), error, record_id),
            )

    def count(self, status: Optional[str] = None) -> int:
        with self._connect() as conn:
            if status:
                row = conn.execute("SELECT COUNT(*) AS c FROM events WHERE status = ?", (status,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()
            return int(row["c"])


class EventProducer:
    """Durable SQLite-backed event producer with retries and health checks."""

    MAX_RETRIES = 3
    BASE_BACKOFF_S = 0.1

    def __init__(self) -> None:
        self._bus = _SQLiteEventBus(_event_bus_db_path())
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("EventProducer connected to durable SQLite event bus")

    async def close(self) -> None:
        self._connected = False
        logger.info("EventProducer closed")

    async def publish(self, event: Event) -> None:
        for attempt in range(self.MAX_RETRIES):
            try:
                self._bus.enqueue(event)
                metrics.increment("events_published", labels={"topic": event.topic.value})
                return
            except Exception as exc:
                if attempt == self.MAX_RETRIES - 1:
                    metrics.increment("events_publish_failed", labels={"topic": event.topic.value})
                    raise
                await asyncio.sleep(self.BASE_BACKOFF_S * (2 ** attempt))
                logger.warning("Retrying publish for %s after error: %s", event.event_id, exc)

    async def publish_batch(self, events: list[Event]) -> None:
        for event in events:
            await self.publish(event)

    @property
    def published_count(self) -> int:
        return self._bus.count()

    async def health_check(self) -> bool:
        return self._connected and self._bus.count(status="dead_letter") >= 0


class EventConsumer:
    """Durable event consumer that processes queued events and maintains DLQ state."""

    MAX_CONCURRENT = 10
    MAX_HANDLER_RETRIES = 2

    def __init__(self) -> None:
        self._handlers: dict[Topic, list[EventHandler]] = {}
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._bus = _SQLiteEventBus(_event_bus_db_path())

    def subscribe(self, topic: Topic, handler: EventHandler) -> None:
        self._handlers.setdefault(topic, []).append(handler)
        logger.info("Subscribed handler to %s", topic.value)

    async def process(self, event: Event) -> None:
        async with self._semaphore:
            handlers = self._handlers.get(event.topic, [])
            for handler in handlers:
                last_error: Optional[Exception] = None
                for attempt in range(self.MAX_HANDLER_RETRIES + 1):
                    try:
                        await handler(event)
                        metrics.increment("events_processed", labels={"topic": event.topic.value})
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        event.retry_count += 1
                        metrics.increment("events_handler_failed", labels={"topic": event.topic.value})
                        if attempt < self.MAX_HANDLER_RETRIES:
                            await asyncio.sleep(0)
                if last_error is not None:
                    raise last_error

    async def pump_once(self, topic: Topic) -> bool:
        row = self._bus.next_event(topic)
        if row is None:
            return False
        event = Event.deserialize(row["payload"])
        try:
            await self.process(event)
            self._bus.mark_processed(row["id"])
        except Exception as exc:
            self._bus.mark_dead_letter(row["id"], str(exc))
            raise
        return True

    async def health_check(self) -> bool:
        return True
