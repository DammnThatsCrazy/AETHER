"""Semantic eligibility policy — skip / structured / text / quarantine / abstain.

Keyed off the canonical event registry (``CANONICAL_EVENT_TYPES`` / ``EVENT_FAMILY``)
so it stays in lockstep with the shared contract. Text classification is
allowlist-gated (only approved expressive inputs), matching the mono-prompt's
semantic-input eligibility requirement; everything else canonical is structured;
unregistered event types are quarantined; low-level telemetry is skipped.
"""

from __future__ import annotations

from enum import Enum

from services.ingestion.generated_registry import CANONICAL_EVENT_TYPES


class Eligibility(str, Enum):
    SKIP = "skip"
    STRUCTURED = "structured"
    TEXT = "text"
    QUARANTINE = "quarantine"
    ABSTAIN = "abstain"


# Low-level SDK telemetry / lifecycle noise — never semantically classified.
_SKIP_TYPES: frozenset[str] = frozenset(
    {
        "heartbeat",
        "error",
        "performance",
        "queue_health",
        "sdk_health",
        "flush",
        "app_backgrounded",
        "app_foregrounded",
    }
)

# Approved expressive text inputs (allowlist). Only these event types are eligible
# for model-backed text classification; arbitrary text is never classified.
_TEXT_ELIGIBLE_TYPES: frozenset[str] = frozenset(
    {
        "feedback_submitted",
        "review_created",
        "review_submitted",
        "survey_response_submitted",
        "search_submitted",
        "agent_message_received_observed",
        "agent_message_sent_observed",
        "agent_semantic_search_observed",
        "message_received_observed",
        "message_sent_observed",
        "message_replied_observed",
        "support_case_created",
        "support_case_escalated",
        "email_spam_complaint",
    }
)


def _has_text(payload: dict) -> bool:
    return bool(str(payload.get("content") or payload.get("text") or "").strip())


def classify_eligibility(event_type: str, payload: dict) -> tuple[Eligibility, str | None]:
    """Return the eligibility bucket + optional reason for a validated event."""
    if not event_type or event_type not in CANONICAL_EVENT_TYPES:
        return Eligibility.QUARANTINE, f"unregistered_event_type:{event_type or 'missing'}"
    if event_type in _SKIP_TYPES:
        return Eligibility.SKIP, "telemetry"
    if event_type in _TEXT_ELIGIBLE_TYPES:
        if not _has_text(payload):
            return Eligibility.ABSTAIN, "insufficient_content"
        return Eligibility.TEXT, None
    return Eligibility.STRUCTURED, None
