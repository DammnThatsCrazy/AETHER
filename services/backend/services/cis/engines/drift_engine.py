"""
CIS Semantic Drift Engine
Detects embedding centroid migration, neighborhood instability,
semantic radius expansion, and graph entropy growth per tenant/cluster.

Consumes CIS_SEMANTIC_* Kafka topics and writes to ClickHouse.
Centroid state is maintained in Redis (EMA update).
"""

from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger

if TYPE_CHECKING:
    from shared.cis.clickhouse import ClickHouseClient

logger = get_logger("aether.cis.drift_engine")

_DRIFT_THRESHOLD = float(os.getenv("CIS_DRIFT_THRESHOLD", "0.25"))
_EMA_ALPHA = 0.05  # centroid exponential moving average factor


def _cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return 1.0 - dot / (na * nb)


def _ema_update(old: list[float], new: list[float], alpha: float) -> list[float]:
    if not old:
        return new
    return [alpha * n + (1 - alpha) * o for o, n in zip(old, new)]


class EmbeddingCentroidTracker:
    """Maintains per-tenant rolling centroids using EMA, stored in Redis."""

    def __init__(self, cache: Any) -> None:
        self._cache = cache

    def _key(self, tenant_id: str, cluster_id: str) -> str:
        return f"aether:cis:centroid:{tenant_id}:{cluster_id}"

    async def update(
        self, tenant_id: str, cluster_id: str, embedding: list[float]
    ) -> tuple[list[float], float]:
        """Update centroid and return (new_centroid, migration_distance)."""
        key = self._key(tenant_id, cluster_id)
        raw = await self._cache.get(key)
        old_centroid = json.loads(raw) if raw else []
        new_centroid = _ema_update(old_centroid, embedding, _EMA_ALPHA)
        await self._cache.set(key, json.dumps(new_centroid), ttl=86400)
        migration = _cosine_distance(old_centroid, new_centroid) if old_centroid else 0.0
        return new_centroid, migration


class DriftScoreComputer:
    """
    Computes composite drift score from four components:
      drift = 0.4 × centroid_migration
            + 0.3 × neighborhood_instability
            + 0.2 × semantic_radius
            + 0.1 × graph_entropy_delta
    """

    def compute(
        self,
        centroid_migration: float,
        neighborhood_instability: float,
        semantic_radius: float,
        graph_entropy_delta: float,
    ) -> float:
        score = (
            0.4 * centroid_migration +
            0.3 * neighborhood_instability +
            0.2 * semantic_radius +
            0.1 * abs(graph_entropy_delta)
        )
        return min(1.0, max(0.0, score))


class SemanticDriftEngine:
    """
    Async event handler for CIS_SEMANTIC_* topics.
    Computes drift scores and writes to ClickHouse.
    """

    def __init__(self, ch_client: "ClickHouseClient", cache: Any) -> None:
        self._ch = ch_client
        self._centroid_tracker = EmbeddingCentroidTracker(cache)
        self._scorer = DriftScoreComputer()
        self._producer: Optional[Any] = None

    def _get_producer(self) -> Any:
        if self._producer is None:
            from dependencies.providers import get_producer
            self._producer = get_producer()
        return self._producer

    async def handle(self, event: Event) -> None:
        p = event.payload
        tenant_id = event.tenant_id
        cluster_id = p.get("cluster_id", "default")

        centroid_migration = float(p.get("centroid_migration", 0.0))
        neighborhood_instability = float(p.get("neighborhood_instability", 0.0))
        semantic_radius = float(p.get("semantic_radius", 0.0))
        graph_entropy_delta = float(p.get("graph_entropy_delta", 0.0))

        # Recompute from raw embedding if provided
        embedding = p.get("embedding")
        if embedding and isinstance(embedding, list):
            try:
                _, centroid_migration = await self._centroid_tracker.update(
                    tenant_id, cluster_id, embedding
                )
            except Exception as e:
                logger.debug(f"Centroid update failed: {e}")

        composite = self._scorer.compute(
            centroid_migration, neighborhood_instability,
            semantic_radius, graph_entropy_delta,
        )
        triggered = composite > _DRIFT_THRESHOLD

        row = {
            "event_id": event.event_id,
            "tenant_id": tenant_id,
            "cluster_id": cluster_id,
            "timestamp": event.timestamp,
            "centroid_migration": centroid_migration,
            "neighborhood_instability": neighborhood_instability,
            "semantic_radius": semantic_radius,
            "graph_entropy_delta": graph_entropy_delta,
            "composite_drift_score": composite,
            "triggered_alert": int(triggered),
            "node_count": int(p.get("node_count", 0)),
            "source_service": "cis.drift_engine",
        }
        await self._ch.insert("cis_semantic_drift_metrics", [row])

        if triggered:
            try:
                await self._get_producer().publish(Event(
                    topic=Topic.CIS_SEMANTIC_DRIFT_DETECTED,
                    tenant_id=tenant_id,
                    source_service="cis.drift_engine",
                    payload={
                        "cluster_id": cluster_id,
                        "composite_drift_score": composite,
                        "centroid_migration": centroid_migration,
                        "threshold": _DRIFT_THRESHOLD,
                    },
                ))
            except Exception as e:
                logger.debug(f"Drift alert event emit failed: {e}")
            logger.warning(
                f"Semantic drift alert: tenant={tenant_id} cluster={cluster_id} "
                f"score={composite:.3f} > threshold={_DRIFT_THRESHOLD}"
            )
