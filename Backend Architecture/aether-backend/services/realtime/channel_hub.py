"""Channel-aware pub/sub hub for multi-channel WebSocket subscriptions.

Maps internal Event topics → RealtimeChannel values, assigns monotonic cursors,
and fans out pre-serialised RealtimeEventMessage JSON to per-channel queues.

Kept separate from hub.py (entity-level SSE hub) so neither touches the other.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional

from shared.events.events import Event, EventConsumer, Topic
from shared.logger.logger import get_logger

logger = get_logger("aether.realtime.channel_hub")

# Topics the channel hub cares about — superset of the entity hub.
_CHANNEL_TOPICS: tuple[Topic, ...] = (
    Topic.PROFILE_UPDATED,
    Topic.IDENTITY_RESOLVED,
    Topic.IDENTITY_MERGED,
    Topic.ENTITY_CREATED,
    Topic.ENTITY_UPDATED,
    Topic.ENTITY_IDENTIFIER_LINKED,
    Topic.ENTITY_IDENTIFIER_UNLINKED,
    Topic.ENTITY_MEMBERSHIP_ADDED,
    Topic.FLOW_WALLET_LINKED,
    Topic.AGENT_EXECUTION_STARTED,
    Topic.AGENT_EXECUTION_COMPLETED,
    Topic.AGENT_EXECUTION_FAILED,
    Topic.AGENT_EXECUTION_RECOVERED,
    Topic.AGENT_HIRED,
    Topic.AGENT_TASK_STARTED,
    Topic.AGENT_TASK_COMPLETED,
    Topic.AGENT_DECISION_MADE,
    Topic.AGENT_STATE_SNAPSHOT,
    Topic.AGENT_ESCALATION_RAISED,
    Topic.BEHAVIOR_PROFILE_UPDATED,
    Topic.INVESTIGATION_CASE_CREATED,
    Topic.INVESTIGATION_CASE_UPDATED,
    Topic.INVESTIGATION_STATUS_CHANGED,
    Topic.GOVERNANCE_DECISION_EVALUATED,
    Topic.EVENT_REPLAY_SUBMITTED,
    Topic.EVENT_REPLAY_COMPLETED,
    Topic.EVENT_REPLAY_CANCELLED,
    Topic.ML_EXTRACTION_ALERT_OPENED,
    Topic.ML_EXTRACTION_CLUSTER_ESCALATED,
    Topic.ML_EXTRACTION_IDENTITY_RESOLVED,
)

# Keyword → RealtimeChannel mapping (checked in order; first match wins).
_CHANNEL_MAP: list[tuple[str, str]] = [
    ("alert", "tenant.alerts"),
    ("cluster", "cluster.membership"),
    ("agent.execution", "agent.coordination"),
    ("agent.task", "agent.coordination"),
    ("agent.decision", "agent.coordination"),
    ("agent.state", "agent.coordination"),
    ("agent.escalation", "agent.coordination"),
    ("agent.hired", "agent.coordination"),
    ("agent", "agent.coordination"),
    ("wallet", "web3.wallets"),
    ("flow.wallet", "web3.wallets"),
    ("investigation", "investigation.workspace"),
    ("governance", "governance.audit"),
    ("event.replay", "tenant.events"),
    ("behavior", "journey.timeline"),
    ("journey", "journey.timeline"),
    ("identity", "entity.profile"),
    ("profile", "entity.profile"),
    ("entity.identifier", "entity.relationships"),
    ("entity.membership", "entity.relationships"),
    ("entity", "entity.profile"),
]


def _topic_to_channel(topic_value: str) -> str:
    for keyword, channel in _CHANNEL_MAP:
        if keyword in topic_value:
            return channel
    return "tenant.events"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChannelHub:
    """Multi-channel pub/sub hub keyed by (tenant_id, channel)."""

    def __init__(self) -> None:
        self._subs: dict[tuple[str, str], set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._wired = False
        self._seq = 0

    def _next_cursor(self) -> str:
        self._seq += 1
        return f"{int(time.monotonic_ns() // 1_000_000)}:{self._seq}"

    async def attach(self, consumer: EventConsumer) -> None:
        if self._wired:
            return
        for topic in _CHANNEL_TOPICS:
            try:
                consumer.subscribe(topic, self._on_event)
            except Exception as exc:  # pragma: no cover
                logger.warning("ChannelHub: failed to subscribe topic %s: %s", topic, exc)
        self._wired = True
        logger.info("ChannelHub attached to %d topics", len(_CHANNEL_TOPICS))

    MAX_SUBSCRIBERS_PER_CHANNEL = 500

    async def subscribe(
        self, tenant_id: str, channels: list[str]
    ) -> dict[str, asyncio.Queue]:
        queues: dict[str, asyncio.Queue] = {}
        async with self._lock:
            for ch in channels:
                bucket = self._subs.setdefault((tenant_id, ch), set())
                if len(bucket) >= self.MAX_SUBSCRIBERS_PER_CHANNEL:
                    logger.warning("ChannelHub: subscriber limit reached for (%s, %s)", tenant_id, ch)
                    continue
                q: asyncio.Queue = asyncio.Queue(maxsize=256)
                bucket.add(q)
                queues[ch] = q
        return queues

    async def unsubscribe(
        self, tenant_id: str, queues: dict[str, asyncio.Queue]
    ) -> None:
        async with self._lock:
            for ch, q in queues.items():
                bucket = self._subs.get((tenant_id, ch))
                if bucket and q in bucket:
                    bucket.remove(q)
                    if not bucket:
                        self._subs.pop((tenant_id, ch), None)

    async def _on_event(self, event: Event) -> None:
        if not event.tenant_id:
            return
        topic_val = event.topic.value if event.topic else ""
        channel = _topic_to_channel(topic_val)

        cursor = self._next_cursor()
        envelope_payload = {
            "id": event.event_id,
            "type": topic_val or "track",
            "tenantId": event.tenant_id,
            "occurredAt": event.timestamp or _utc_iso(),
            "ingestedAt": _utc_iso(),
            "schemaVersion": event.version or "1.0",
            "source": "realtime",
            "replayable": False,
            "payload": event.payload or {},
        }
        msg = json.dumps({"action": "event", "channel": channel, "cursor": cursor, "event": envelope_payload})
        tenant_events_msg = None  # only built if needed

        async with self._lock:
            to_notify: list[asyncio.Queue] = []
            # Deliver to specific-channel subscribers
            ch_bucket = self._subs.get((event.tenant_id, channel))
            if ch_bucket:
                to_notify.extend(ch_bucket)
            # Deliver to catch-all "tenant.events" subscribers (different channel → different cursor obj)
            if channel != "tenant.events":
                all_bucket = self._subs.get((event.tenant_id, "tenant.events"))
                if all_bucket:
                    if tenant_events_msg is None:
                        tenant_events_msg = json.dumps({
                            "action": "event",
                            "channel": "tenant.events",
                            "cursor": self._next_cursor(),
                            "event": envelope_payload,
                        })
                    to_notify.extend(all_bucket)

        for q in to_notify:
            text = msg if q in (self._subs.get((event.tenant_id, channel)) or set()) else (tenant_events_msg or msg)
            try:
                q.put_nowait(text)
            except asyncio.QueueFull:
                logger.warning("ChannelHub queue full, dropping event for slow client")


_channel_hub: Optional[ChannelHub] = None


def get_channel_hub() -> ChannelHub:
    global _channel_hub
    if _channel_hub is None:
        _channel_hub = ChannelHub()
    return _channel_hub
