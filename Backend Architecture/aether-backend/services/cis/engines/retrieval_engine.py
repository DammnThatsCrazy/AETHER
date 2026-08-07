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


def _optional_float(value: Any) -> Optional[float]:
    """Coerce to float, preserving ``None`` (unknown) instead of fabricating 0.0."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    async def record(
        self, tenant_id: str, grounded: Optional[bool], synthetic_ratio: float
    ) -> None:
        key = self._stats_key(tenant_id)
        raw = await self._cache.get(key)
        stats = (
            json.loads(raw)
            if raw
            else {"grounded_count": 0, "grounding_known": 0, "total": 0, "synthetic_sum": 0.0}
        )
        # Back-compat for windows written before grounding_known was tracked.
        stats.setdefault("grounding_known", stats.get("total", 0))
        stats["total"] += 1
        # Only a *known* grounding signal moves the ratio. An unknown (None)
        # grounding is not evidence of "ungrounded" — folding it in as 0 would
        # silently fabricate the very absence the ml-serving layer disclosed.
        if grounded is not None:
            stats["grounding_known"] += 1
            stats["grounded_count"] += int(grounded)
        stats["synthetic_sum"] += synthetic_ratio
        # Keep rolling window
        if stats["total"] > _WINDOW_SIZE:
            scale = _WINDOW_SIZE / stats["total"]
            stats["grounded_count"] = int(stats["grounded_count"] * scale)
            stats["grounding_known"] = int(stats["grounding_known"] * scale)
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
        # Ratio is over observations where grounding was actually known; unknowns
        # neither help nor hurt it. Fall back to prior semantics when none known.
        known = stats.get("grounding_known", stats.get("total", 0))
        grounding_ratio = (
            stats.get("grounded_count", known) / known if known > 0 else 1.0
        )
        return {
            "grounding_ratio": grounding_ratio,
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
        # Preserve an unknown grounding signal as None (not a fabricated True).
        raw_grounded = p.get("grounded")
        grounded: Optional[bool] = None if raw_grounded is None else bool(raw_grounded)
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
            "confidence_score": _optional_float(
                p["confidence_score"] if "confidence_score" in p else p.get("confidence")
            ),
            "generation_hash": p.get("generation_hash", ""),
            "latency_ms": float(p.get("latency_ms", 0.0)),
            "grounded": None if grounded is None else int(grounded),
            "synthetic_ratio": synthetic_ratio,
            "source_service": "cis.retrieval_engine",
        }
        await self._ch.insert("cis_retrieval_traces", [row])

    async def get_window_stats(self, tenant_id: str) -> dict[str, float]:
        return await self._window.get_stats(tenant_id)
