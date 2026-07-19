"""Semantic projection worker.

Subscribes to ``SDK_EVENTS_VALIDATED`` and runs semantic classification IN-PROCESS
(never over HTTP) via :class:`SemanticIntelligenceService`. Eligibility routes
each event: skip (telemetry), structured, text, quarantine or abstain. This is
the wiring that makes semantics flow automatically from validated ingestion
instead of only on a manual API call.
"""

from __future__ import annotations

import re
from typing import Any

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger

from .eligibility import Eligibility, classify_eligibility
from .resolution import SemanticActorResolver, SemanticSubjectResolver
from .service import get_semantic_service

logger = get_logger("aether.semantic.consumer")

_CANONICAL_CAMPAIGN_RE = re.compile(
    r"^(camp_|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$)", re.I
)

# SDK event properties that commonly carry the semantic subject, in precedence
# order. A full SemanticSubjectResolver (cross-tenant validation, review queue)
# is a follow-up; this is deterministic best-effort extraction.
_SUBJECT_PROPERTY_KEYS = (
    "subject_ref",
    "product_id",
    "cart_id",
    "content_id",
    "offer_id",
    "agent_id",
    "wallet_id",
    "campaign_id",
)


def _first(payload: dict, props: dict, *keys: str) -> Any:
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
        if props.get(key) is not None:
            return props[key]
    return None


def _to_semantic_payload(event: Event) -> dict[str, Any]:
    payload = event.payload or {}
    props = payload.get("properties") or {}
    subject = _first(payload, props, *_SUBJECT_PROPERTY_KEYS)
    actor = payload.get("user_id") or payload.get("anonymous_id") or "anonymous"
    campaign_id = payload.get("campaign_id") or props.get("campaign_id")
    if campaign_id is not None and not _CANONICAL_CAMPAIGN_RE.match(str(campaign_id)):
        campaign_id = None  # non-canonical → drop (avoids invalid linkage)
    return {
        "source_event_id": payload.get("event_id") or event.event_id,
        "source_type": payload.get("event_type", "event"),
        "source_platform": (payload.get("context") or {}).get("platform"),
        "actor_ref": actor,
        "actor_type": "profile",
        "user_id": payload.get("user_id"),
        "anonymous_id": payload.get("anonymous_id"),
        "primary_subject_ref": str(subject) if subject is not None else "unknown_subject",
        "content": props.get("content") or props.get("text") or payload.get("content"),
        "language": props.get("language", "en"),
        "campaign_id": campaign_id,
        "purposes": payload.get("purposes") or ["analytics"],
        "consent_snapshot_id": (payload.get("context") or {}).get("consent_snapshot_id"),
        "occurred_at": payload.get("timestamp"),
        "session_id": payload.get("session_id"),
        "narrative_frames": props.get("narrative_frames", []),
    }


class SemanticEventConsumer:
    """Consumes validated SDK events and persists semantic observations."""

    def __init__(self, producer: Any = None) -> None:
        self._producer = producer
        self._subject_resolver = SemanticSubjectResolver()
        self._actor_resolver = SemanticActorResolver()

    async def on_validated_event(self, event: Event) -> None:
        payload = event.payload or {}
        tenant_id = event.tenant_id or payload.get("tenant_id", "")
        if not tenant_id:
            return
        event_type = payload.get("event_type", "")
        eligibility, _reason = classify_eligibility(event_type, {**payload, **(payload.get("properties") or {})})
        if eligibility is Eligibility.SKIP:
            return
        try:
            sem_payload = _to_semantic_payload(event)
            service = get_semantic_service()

            # Backend-owned subject/actor resolution over the RAW event payload
            # (SDKs never assign identity; the resolver, not the mapper, owns it).
            subject = await self._subject_resolver.resolve(payload, tenant_id)
            actor = await self._actor_resolver.resolve(payload, tenant_id)
            sem_payload["primary_subject_ref"] = subject.ref
            sem_payload["actor_ref"] = actor.ref
            sem_payload["subject_resolution_confidence"] = subject.confidence

            if subject.needs_review and subject.review_queue:
                await service.enqueue_review(
                    tenant_id,
                    subject.review_queue,
                    subject_ref=subject.ref,
                    source_event_id=sem_payload.get("source_event_id"),
                    payload={"method": subject.method, "event_type": event_type},
                )
            # A cross-tenant reference is quarantined, never classified against.
            if subject.review_queue == "cross_tenant_reference":
                eligibility = Eligibility.QUARANTINE

            await service.classify_and_persist(sem_payload, tenant_id, eligibility=eligibility)

            # Refresh durable Gold state (weighted reducer).
            if subject.ref != "unknown_subject" and eligibility is not Eligibility.QUARANTINE:
                from .reducers import (
                    recompute_campaign_impact,
                    recompute_entity_sentiment,
                    recompute_entity_state,
                )

                await recompute_entity_state(tenant_id, subject.ref)
                await recompute_entity_sentiment(tenant_id, subject.ref)
                campaign_id = sem_payload.get("campaign_id")
                if campaign_id:
                    await recompute_campaign_impact(tenant_id, campaign_id)
        except Exception:
            logger.exception("semantic classification failed for event %s", payload.get("event_id"))
            raise  # triggers DLQ in EventConsumer; persistence is idempotent on retry

    async def on_consent_updated(self, event: Event) -> None:
        """Consent revocation → restrict the subject's semantic data (fail-safe)."""
        payload = event.payload or {}
        tenant_id = event.tenant_id or payload.get("tenant_id", "")
        user_id = payload.get("user_id")
        if not tenant_id or not user_id:
            return
        # `granted` falsy (False / empty) is a revocation.
        if payload.get("granted"):
            return
        try:
            from .privacy import SemanticPrivacyHandler

            await SemanticPrivacyHandler().handle_restriction(tenant_id, str(user_id))
        except Exception:
            logger.exception("semantic consent restriction failed for %s", user_id)
            raise

    def register(self, consumer: Any) -> None:
        consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, self.on_validated_event)
        consumer.subscribe(Topic.CONSENT_UPDATED, self.on_consent_updated)
