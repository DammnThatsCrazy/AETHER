"""Internal semantic-intelligence service port.

Both the public API routes and (from Phase A2) the validated-event worker call
this in-process port — never the HTTP API. It owns classification + durable
persistence + the read/aggregation surface, sitting over the pluggable store
(``get_store()`` → in-memory default, or the injected durable store).
"""

from __future__ import annotations

from typing import Any, Optional

from config.settings import settings
from services.consent.authority import evaluate_consent

from .eligibility import Eligibility
from .engine import (
    cascades_for_tenant,
    classify_event,
    entity_state,
    get_store,
)
from .models import ObservationStatus, SemanticObservation, SentimentObservation, SubjectType
from .providers import get_classifier_provider
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
        self,
        payload: dict[str, Any],
        tenant_id: str,
        *,
        eligibility: Optional[Eligibility] = None,
    ) -> tuple[SemanticObservation, list[SentimentObservation]]:
        """Classify an event payload and durably persist the results.

        The single write path shared by the API route and the worker (byte-
        identical observations regardless of entry point). Fail-closed on consent;
        eligibility routes structured vs text vs quarantine/abstain.
        """
        store = get_store()

        # 1. Consent — fail closed when authoritative enforcement is enabled.
        blocked = await self._consent_block(payload, tenant_id)
        if blocked is not None:
            obs = self._status_observation(
                payload, tenant_id, ObservationStatus.CONSENT_RESTRICTED, blocked
            )
            return await store.put_semantic(obs), []

        # 2. Eligibility routing (worker path supplies it; route path classifies directly).
        if eligibility is Eligibility.QUARANTINE:
            obs = self._status_observation(
                payload, tenant_id, ObservationStatus.QUARANTINED, "quarantined_unregistered"
            )
            return await store.put_semantic(obs), []
        if eligibility is Eligibility.TEXT:
            provider = get_classifier_provider(settings)
            if not provider.available():
                obs = self._status_observation(
                    payload,
                    tenant_id,
                    ObservationStatus.ABSTAINED,
                    provider.abstention_reason() or "provider_disabled",
                )
                return await store.put_semantic(obs), []

        # 3. Classify (deterministic, tool-less) + persist idempotently.
        obs, sentiments = classify_event(payload, tenant_id)
        stored_obs = await store.put_semantic(obs)
        stored_sentiments = [await store.put_sentiment(s) for s in sentiments]
        return stored_obs, stored_sentiments

    async def _consent_block(self, payload: dict[str, Any], tenant_id: str) -> Optional[str]:
        """Return a rejection reason if processing is unlawful, else None."""
        if not settings.consent_authority.authoritative_consent_enforcement_enabled:
            return None
        subject_id = payload.get("user_id") or payload.get("actor_ref")
        anonymous_id = payload.get("anonymous_id")
        purposes = payload.get("purposes") or ["analytics"]
        for purpose in purposes:
            allowed, reason = await evaluate_consent(tenant_id, subject_id, anonymous_id, purpose)
            if not allowed:
                return reason or "consent_denied"
        return None

    def _status_observation(
        self,
        payload: dict[str, Any],
        tenant_id: str,
        status: ObservationStatus,
        reason: str,
    ) -> SemanticObservation:
        """Build a content-free observation carrying only a terminal status.

        Used for consent-restricted / quarantined / provider-abstained events so
        the pipeline records that an event was seen without persisting content or
        an inferred interpretation.
        """
        actor_ref = str(payload.get("actor_ref") or payload.get("user_id") or "anonymous")
        subject = str(
            payload.get("primary_subject_ref")
            or payload.get("subject_ref")
            or payload.get("target_ref")
            or "unknown_subject"
        )
        return SemanticObservation(
            tenant_id=tenant_id,
            source_event_id=str(
                payload.get("source_event_id") or payload.get("event_id") or "event_unknown"
            ),
            source_type=str(payload.get("source_type") or payload.get("event_type") or "event"),
            actor_ref=actor_ref,
            actor_type=SubjectType.PROFILE,
            primary_subject_ref=subject,
            purposes=payload.get("purposes") or ["analytics"],
            consent_snapshot_id=payload.get("consent_snapshot_id"),
            classification_confidence=0.0,
            status=status,
            abstention_reason=reason,
        )

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

    async def enqueue_review(
        self,
        tenant_id: str,
        queue_type: str,
        *,
        subject_ref: Optional[str] = None,
        source_event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._review_queue.enqueue(
            tenant_id,
            queue_type,
            subject_ref=subject_ref,
            source_event_id=source_event_id,
            payload=payload,
        )

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
