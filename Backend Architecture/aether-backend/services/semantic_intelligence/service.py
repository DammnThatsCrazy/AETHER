"""Internal semantic-intelligence service port.

Both the public API routes and (from Phase A2) the validated-event worker call
this in-process port — never the HTTP API. It owns classification + durable
persistence + the read/aggregation surface, sitting over the pluggable store
(``get_store()`` → in-memory default, or the injected durable store).
"""

from __future__ import annotations

from typing import Any, Optional

from .engine import (
    cascades_for_tenant,
    classify_event,
    entity_state,
    get_store,
)
from .models import SemanticObservation, SentimentObservation
from .repositories.review_queue_repo import SemanticReviewQueueRepository

_MODEL_VERSIONS = [
    "deterministic-semantic-classifier@1.0.0",
    "deterministic-sentiment-classifier@1.0.0",
]


class SemanticIntelligenceService:
    """Classification + durable persistence + read port for semantic intelligence."""

    def __init__(self, review_queue: Optional[SemanticReviewQueueRepository] = None) -> None:
        self._review_queue = review_queue or SemanticReviewQueueRepository()

    # ── write path ─────────────────────────────────────────────────────────────

    async def classify_and_persist(
        self, payload: dict[str, Any], tenant_id: str
    ) -> tuple[SemanticObservation, list[SentimentObservation]]:
        """Classify an event payload and durably persist the results.

        This is the single write path shared by the API route and the worker,
        guaranteeing byte-identical observations regardless of entry point.
        """
        obs, sentiments = classify_event(payload, tenant_id)
        store = get_store()
        stored_obs = await store.put_semantic(obs)
        stored_sentiments = [await store.put_sentiment(s) for s in sentiments]
        return stored_obs, stored_sentiments

    # ── read path ──────────────────────────────────────────────────────────────

    async def get_observation(
        self, tenant_id: str, observation_id: str
    ) -> Optional[SemanticObservation]:
        rows = await get_store().list_semantic(tenant_id)
        for obs in rows:
            if obs.observation_id == observation_id:
                return obs
        return None

    async def list_observations(
        self, tenant_id: str, subject: Optional[str] = None, *, limit: int = 50
    ) -> tuple[list[SemanticObservation], bool]:
        rows = await get_store().list_semantic(tenant_id, subject)
        return rows[:limit], len(rows) > limit

    async def entity_state(self, tenant_id: str, entity_ref: str):
        return await entity_state(tenant_id, entity_ref)

    async def list_sentiment(
        self, tenant_id: str, subject: Optional[str] = None, *, limit: int = 50
    ) -> tuple[list[SentimentObservation], bool]:
        rows = await get_store().list_sentiment(tenant_id, subject)
        return rows[:limit], len(rows) > limit

    async def timeline(
        self, tenant_id: str, entity_ref: str, *, limit: int = 50
    ) -> dict[str, Any]:
        store = get_store()
        semantic = await store.list_semantic(tenant_id, entity_ref)
        sentiment = await store.list_sentiment(tenant_id, entity_ref)
        return {
            "semantic": semantic[:limit],
            "sentiment": sentiment[:limit],
            "partial": len(semantic) > limit or len(sentiment) > limit,
        }

    async def narratives(self, tenant_id: str) -> list[str]:
        rows = await get_store().list_semantic(tenant_id)
        return sorted({n for r in rows for n in r.narrative_frames})

    async def cascades(self, tenant_id: str):
        return await cascades_for_tenant(tenant_id)

    async def campaign_observations(
        self, tenant_id: str, campaign_id: str
    ) -> list[SemanticObservation]:
        rows = await get_store().list_semantic(tenant_id)
        return [o for o in rows if o.campaign_id == campaign_id]

    async def campaign_sentiment(
        self, tenant_id: str, campaign_id: str
    ) -> list[SentimentObservation]:
        store = get_store()
        semantic_ids = {
            o.observation_id
            for o in await store.list_semantic(tenant_id)
            if o.campaign_id == campaign_id
        }
        return [
            s
            for s in await store.list_sentiment(tenant_id)
            if s.semantic_observation_id in semantic_ids
        ]

    # ── operator surface (honest, DB-sourced) ────────────────────────────────────

    async def fleet_health(self) -> dict[str, Any]:
        store = get_store()
        counts = await store.aggregate_counts()
        semantic = counts.get("semantic", {})
        total = int(semantic.get("total", 0) or 0)
        by_status = semantic.get("by_status", {})
        abstained = int(by_status.get("abstained", 0) or 0)
        quarantined = int(by_status.get("quarantined", 0) or 0)
        consent_restricted = int(by_status.get("consent_restricted", 0) or 0)
        return {
            "enabled_tenants": int(semantic.get("tenants", 0) or 0),
            "classified_observations": total,
            "sentiment_observations": int(counts.get("sentiment", {}).get("total", 0) or 0),
            "abstention_rate": (abstained / total) if total else 0,
            "quarantined_observations": quarantined,
            "consent_restricted_observations": consent_restricted,
            "model_versions": _MODEL_VERSIONS,
            "status_breakdown": by_status,
        }

    async def review_queue(
        self, tenant_id: str, queue_type: Optional[str] = None
    ) -> dict[str, Any]:
        items = await self._review_queue.list_open(tenant_id, queue_type)
        counts = await self._review_queue.counts(tenant_id)
        return {
            "items": items,
            "count": len(items),
            "counts_by_queue": counts,
        }


_service: Optional[SemanticIntelligenceService] = None


def get_semantic_service() -> SemanticIntelligenceService:
    """Lazy module singleton (mirrors consent/authority repository singletons)."""
    global _service
    if _service is None:
        _service = SemanticIntelligenceService()
    return _service


def set_semantic_service(service: SemanticIntelligenceService) -> None:
    """Test/DI hook to swap the active service."""
    global _service
    _service = service
