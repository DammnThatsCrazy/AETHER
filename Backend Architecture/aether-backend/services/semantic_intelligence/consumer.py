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
            await get_semantic_service().classify_and_persist(
                sem_payload, tenant_id, eligibility=eligibility
            )
        except Exception:
            logger.exception("semantic classification failed for event %s", payload.get("event_id"))
            raise  # triggers DLQ in EventConsumer; persistence is idempotent on retry

    def register(self, consumer: Any) -> None:
        consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, self.on_validated_event)
