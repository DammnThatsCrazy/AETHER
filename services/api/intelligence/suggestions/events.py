"""Suggestion event emission helpers.

Wraps the EventProducer to publish Suggestion lifecycle events. Errors in
event emission are logged as warnings — they must never corrupt persisted state.
"""

from __future__ import annotations

import uuid
from typing import Optional

from shared.events.events import Event, EventProducer, Topic
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.suggestions.events")

# ---------------------------------------------------------------------------
# Event name → Topic mapping
# ---------------------------------------------------------------------------

_EVENT_TO_TOPIC: dict[str, Topic] = {
    "suggestion.detected":        Topic.SUGGESTION_DETECTED,
    "suggestion.oriented":        Topic.SUGGESTION_ORIENTED,
    "suggestion.created":         Topic.SUGGESTION_CREATED,
    "suggestion.review_required": Topic.SUGGESTION_REVIEW_REQUIRED,
    "suggestion.approved":        Topic.SUGGESTION_APPROVED,
    "suggestion.rejected":        Topic.SUGGESTION_REJECTED,
    "suggestion.suppressed":      Topic.SUGGESTION_SUPPRESSED,
    "suggestion.executing":       Topic.SUGGESTION_EXECUTING,
    "suggestion.executed":        Topic.SUGGESTION_EXECUTED,
    "suggestion.delivered":       Topic.SUGGESTION_DELIVERED,
    "suggestion.outcome_recorded": Topic.SUGGESTION_OUTCOME_RECORDED,
    "suggestion.closed":          Topic.SUGGESTION_CLOSED,
    "suggestion.failed":          Topic.SUGGESTION_FAILED,
    "suggestion.expired":         Topic.SUGGESTION_EXPIRED,
}


async def emit_suggestion_event(
    producer: EventProducer,
    event_type: str,
    suggestion: dict,
    correlation_id: Optional[str] = None,
) -> None:
    """Emit a lifecycle event for a Suggestion.

    Errors are caught and logged as warnings so that event delivery failures
    never roll back a successfully persisted suggestion state transition.
    """
    topic = _EVENT_TO_TOPIC.get(event_type)
    if topic is None:
        logger.warning(f"Unknown suggestion event type: {event_type!r} — skipping emit")
        return

    try:
        event = Event(
            topic=topic,
            tenant_id=suggestion.get("tenant_id", ""),
            event_id=str(uuid.uuid4()),
            timestamp=utc_now().isoformat(),
            source_service="suggestions",
            correlation_id=correlation_id or "",
            payload={
                "suggestion_id": suggestion.get("id"),
                "tenant_id": suggestion.get("tenant_id"),
                "status": suggestion.get("status"),
                "ooda_phase": suggestion.get("ooda_phase"),
                "suggestion_class": suggestion.get("suggestion_class"),
                "priority": suggestion.get("priority"),
                "source": suggestion.get("source"),
                "subject_kind": (suggestion.get("subject") or {}).get("kind"),
                "subject_id": (suggestion.get("subject") or {}).get("id"),
            },
        )
        await producer.publish(event)
        logger.debug(f"Emitted {event_type!r} for suggestion {suggestion.get('id')!r}")
    except Exception as exc:
        logger.warning(
            f"Failed to emit {event_type!r} for suggestion "
            f"{suggestion.get('id')!r}: {exc}"
        )
