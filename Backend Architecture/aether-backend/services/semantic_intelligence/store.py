"""Durable semantic-sentiment store.

Implements the same async surface as the in-memory ``SemanticSentimentStore``
(``put_semantic`` / ``put_sentiment`` / ``list_semantic`` / ``list_sentiment`` /
``supersede`` / ``aggregate_counts``) but persists to the durable Silver fact
tables via :class:`SemanticFactRepository`. Injected at startup by ``main.py``
for non-local deployment profiles; local/CI keep the deterministic in-memory
store from ``engine.py``.
"""

from __future__ import annotations

from typing import Any, Optional

from .models import SemanticObservation, SentimentObservation
from .repositories.base_fact_repo import SemanticFactRepository

_OBSERVATIONS_TABLE = "silver_semantic_observations"
_SENTIMENT_TABLE = "silver_sentiment_observations"


def _observation_fact(obs: SemanticObservation) -> dict[str, Any]:
    return {
        "id": obs.observation_id,
        "tenant_id": obs.tenant_id,
        "source_event_id": obs.source_event_id,
        "subject_ref": obs.primary_subject_ref,
        "campaign_id": obs.campaign_id,
        "occurred_at": obs.occurred_at,
        "idempotency_key": obs.idempotency_key,
        "data": obs.model_dump(mode="json"),
    }


def _sentiment_fact(sent: SentimentObservation) -> dict[str, Any]:
    idem = f"sentiment:{sent.semantic_observation_id}:{sent.target_subject_ref}"
    data = sent.model_dump(mode="json")
    data["idempotency_key"] = idem
    return {
        "id": sent.sentiment_observation_id,
        "tenant_id": sent.tenant_id,
        "source_event_id": sent.source_event_id,
        "subject_ref": sent.target_subject_ref,
        "campaign_id": None,
        "occurred_at": sent.occurred_at,
        "idempotency_key": idem,
        "data": data,
    }


class DurableSemanticSentimentStore:
    """Postgres-backed (with in-memory fallback) semantic/sentiment store."""

    def __init__(self) -> None:
        self.observations = SemanticFactRepository(_OBSERVATIONS_TABLE)
        self.sentiment = SemanticFactRepository(_SENTIMENT_TABLE)

    async def put_semantic(self, obs: SemanticObservation) -> SemanticObservation:
        stored = await self.observations.upsert(_observation_fact(obs))
        data = stored.get("data", stored)
        return SemanticObservation(**data) if data else obs

    async def put_sentiment(self, obs: SentimentObservation) -> SentimentObservation:
        stored = await self.sentiment.upsert(_sentiment_fact(obs))
        data = stored.get("data", stored)
        return SentimentObservation(**data) if data else obs

    async def list_semantic(
        self, tenant_id: str, subject: Optional[str] = None
    ) -> list[SemanticObservation]:
        rows = await self.observations.list_by_tenant(tenant_id, subject, limit=2000)
        return sorted(
            (SemanticObservation(**r) for r in rows if r),
            key=lambda o: o.occurred_at,
        )

    async def list_sentiment(
        self, tenant_id: str, subject: Optional[str] = None
    ) -> list[SentimentObservation]:
        rows = await self.sentiment.list_by_tenant(tenant_id, subject, limit=2000)
        return sorted(
            (SentimentObservation(**r) for r in rows if r),
            key=lambda o: o.occurred_at,
        )

    async def supersede(
        self, tenant_id: str, idempotency_key: str, superseded_by: str
    ) -> bool:
        return await self.observations.supersede(tenant_id, idempotency_key, superseded_by)

    async def aggregate_counts(self, tenant_id: Optional[str] = None) -> dict[str, Any]:
        semantic = await self.observations.aggregate_counts(tenant_id)
        sentiment = await self.sentiment.aggregate_counts(tenant_id)
        return {"semantic": semantic, "sentiment": sentiment}
