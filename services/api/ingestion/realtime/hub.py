"""
Realtime hub — in-process pub/sub keyed by (tenant_id, entity_id).

Subscribes to Profile 360 topics on the shared EventConsumer; clients
attach via SSE or WebSocket and receive only events that target their
entity. Single-pod fan-out is fine for current scale; switch to
Redis Streams when pods > 4 (documented as a follow-up).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from shared.events.events import Event, EventConsumer, Topic
from shared.logger.logger import get_logger

logger = get_logger("aether.realtime.hub")

# Topics worth fanning out for a Profile 360 client.
DEFAULT_TOPICS: tuple[Topic, ...] = (
    Topic.PROFILE_UPDATED,
    Topic.ENTITY_CREATED,
    Topic.ENTITY_UPDATED,
    Topic.ENTITY_IDENTIFIER_LINKED,
    Topic.ENTITY_IDENTIFIER_UNLINKED,
    Topic.DELEGATION_CREATED,
    Topic.DELEGATION_REVOKED,
    Topic.FLOW_TRANSFER,
    Topic.FLOW_WALLET_LINKED,
    Topic.AGENT_EXECUTION_STARTED,
    Topic.AGENT_EXECUTION_COMPLETED,
    Topic.AGENT_EXECUTION_FAILED,
    Topic.AGENT_EXECUTION_RECOVERED,
    Topic.BEHAVIOR_PROFILE_UPDATED,
)


def _entity_ids_in_event(event: Event) -> list[str]:
    """Pull every entity_id reference out of an event so we know who to notify."""
    ids: list[str] = []
    p = event.payload or {}
    for key in (
        "entity_id", "user_id", "agent_id",
        "owner_entity_id", "grantor_entity_id", "grantee_entity_id",
        "from_entity_id", "to_entity_id", "target_user_id",
        "organization_entity_id",
    ):
        v = p.get(key)
        if isinstance(v, str) and v:
            ids.append(v)
    if event.envelope is not None:
        for block in (event.envelope.actor, event.envelope.beneficiary):
            if isinstance(block, dict):
                v = block.get("entity_id")
                if isinstance(v, str) and v:
                    ids.append(v)
    return ids


class RealtimeHub:
    """In-process subscription registry. Singleton, attached at startup."""

    def __init__(self) -> None:
        # key = (tenant_id, entity_id) → set of asyncio Queues
        self._subs: dict[tuple[str, str], set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._wired = False

    async def attach(self, consumer: EventConsumer) -> None:
        """Subscribe to the relevant topics on the shared consumer."""
        if self._wired:
            return
        for t in DEFAULT_TOPICS:
            consumer.subscribe(t, self._on_event)
        self._wired = True
        logger.info("RealtimeHub attached to %d topics", len(DEFAULT_TOPICS))

    async def subscribe(self, tenant_id: str, entity_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs.setdefault((tenant_id, entity_id), set()).add(queue)
        return queue

    async def unsubscribe(self, tenant_id: str, entity_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            bucket = self._subs.get((tenant_id, entity_id))
            if bucket and queue in bucket:
                bucket.remove(queue)
                if not bucket:
                    self._subs.pop((tenant_id, entity_id), None)

    async def _on_event(self, event: Event) -> None:
        """Fan out an inbound event to any matching subscribers."""
        if not event.tenant_id:
            return
        targets = _entity_ids_in_event(event)
        if not targets:
            return
        msg = {
            "event_id": event.event_id,
            "topic": event.topic.value,
            "version": event.version,
            "timestamp": event.timestamp,
            "tenant_id": event.tenant_id,
            "payload": event.payload,
            "envelope": event.envelope.to_dict() if event.envelope else None,
        }
        text = json.dumps(msg)
        async with self._lock:
            queues_to_notify: list[asyncio.Queue] = []
            for entity_id in targets:
                bucket = self._subs.get((event.tenant_id, entity_id))
                if bucket:
                    queues_to_notify.extend(bucket)
        for q in queues_to_notify:
            try:
                q.put_nowait(text)
            except asyncio.QueueFull:
                # Drop on backpressure — client is slow; SSE will resync.
                logger.warning("Realtime queue full, dropping event for slow client")


_hub: Optional[RealtimeHub] = None


def get_hub() -> RealtimeHub:
    global _hub
    if _hub is None:
        _hub = RealtimeHub()
    return _hub
