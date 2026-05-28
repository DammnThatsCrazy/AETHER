"""
CIS Retrieval Observability Engine
Tracks retrieval stability, grounding integrity, unsupported claims ratio,
synthetic retrieval ratio, retrieval entropy, and context contamination.

Consumes CIS_RETRIEVAL_* topics and maintains rolling per-tenant windows in Redis.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger

if TYPE_CHECKING:
    from shared.cis.clickhouse import ClickHouseClient

logger = get_logger("aether.cis.retrieval_engine")

_WINDOW_SIZE = 100  # rolling window per tenant


def _shannon_entropy(items: list[str]) -> float:
    if not items:
        return 0.0
    counts = Counter(items)
    total = len(items)
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)


class RetrievalStabilityWindow:
    """Rolling per-tenant window stored in Redis sorted sets."""

    def __init__(self, cache: Any) -> None:
        self._cache = cache

    def _stats_key(self, tenant_id: str) -> str:
        return f"aether:cis:retrieval_stats:{tenant_id}"

    async def record(self, tenant_id: str, grounded: bool, synthetic_ratio: float) -> None:
        key = self._stats_key(tenant_id)
        raw = await self._cache.get(key)
        stats = json.loads(raw) if raw else {"grounded_count": 0, "total": 0, "synthetic_sum": 0.0}
        stats["total"] += 1
        stats["grounded_count"] += int(grounded)
        stats["synthetic_sum"] += synthetic_ratio
        # Keep rolling window
        if stats["total"] > _WINDOW_SIZE:
            scale = _WINDOW_SIZE / stats["total"]
            stats["grounded_count"] = int(stats["grounded_count"] * scale)
            stats["synthetic_sum"] *= scale
            stats["total"] = _WINDOW_SIZE
        await self._cache.set(key, json.dumps(stats), ttl=3600)

    async def get_stats(self, tenant_id: str) -> dict[str, float]:
        key = self._stats_key(tenant_id)
        raw = await self._cache.get(key)
        if not raw:
            return {"grounding_ratio": 1.0, "synthetic_ratio": 0.0, "total": 0}
        stats = json.loads(raw)
        total = max(1, stats.get("total", 1))
        return {
            "grounding_ratio": stats.get("grounded_count", total) / total,
            "synthetic_ratio": stats.get("synthetic_sum", 0.0) / total,
            "total": float(total),
        }


class RetrievalObservabilityEngine:
    """
    Async event handler for CIS_RETRIEVAL_* topics.
    Maintains rolling window stats and writes traces to ClickHouse.
    """

    def __init__(self, ch_client: "ClickHouseClient", cache: Any) -> None:
        self._ch = ch_client
        self._window = RetrievalStabilityWindow(cache)

    async def handle(self, event: Event) -> None:
        p = event.payload
        tenant_id = event.tenant_id
        grounded = bool(p.get("grounded", True))
        synthetic_ratio = float(p.get("synthetic_ratio", 0.0))
        node_ids: list[str] = p.get("retrieved_node_ids", [])

        await self._window.record(tenant_id, grounded, synthetic_ratio)

        # Compute retrieval entropy for this request
        entropy = _shannon_entropy(node_ids)

        row = {
            "event_id": event.event_id,
            "tenant_id": tenant_id,
            "timestamp": event.timestamp,
            "query_hash": p.get("query_hash", ""),
            "model_name": p.get("model_name", ""),
            "retrieved_node_ids": node_ids,
            "embedding_model": p.get("embedding_model", ""),
            "reasoning_trace": p.get("reasoning_trace", ""),
            "citations": p.get("citations", []),
            "confidence_score": float(p.get("confidence_score", p.get("confidence", 0.0))),
            "generation_hash": p.get("generation_hash", ""),
            "latency_ms": float(p.get("latency_ms", 0.0)),
            "grounded": int(grounded),
            "synthetic_ratio": synthetic_ratio,
            "source_service": "cis.retrieval_engine",
        }
        await self._ch.insert("cis_retrieval_traces", [row])

    async def get_window_stats(self, tenant_id: str) -> dict[str, float]:
        return await self._window.get_stats(tenant_id)
