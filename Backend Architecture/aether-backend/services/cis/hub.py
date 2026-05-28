"""
CIS Stream Hub — per-tenant asyncio.Queue registry for WebSocket event streaming.
Mirrors services/realtime/hub.py pattern.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.cis.hub")


class CISStreamHub:
    """Maintains a registry of asyncio.Queue per connected WebSocket, keyed by tenant_id."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    def subscribe(self, tenant_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._queues.setdefault(tenant_id, []).append(q)
        logger.debug(f"CISStreamHub: new subscriber for tenant={tenant_id}")
        return q

    def unsubscribe(self, tenant_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._queues.get(tenant_id, [])
        if q in queues:
            queues.remove(q)
        if not queues:
            self._queues.pop(tenant_id, None)

    async def broadcast(self, tenant_id: str, event: dict[str, Any]) -> None:
        for q in self._queues.get(tenant_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"CISStreamHub: queue full for tenant={tenant_id}, dropping event")

    @property
    def subscriber_count(self) -> int:
        return sum(len(qs) for qs in self._queues.values())
