"""Outcome loop — record, advance lifecycle, and derive learning feedback."""

from __future__ import annotations

from typing import Optional

from shared.auth.auth import TenantContext
from shared.common.common import utc_now
from shared.events.events import EventProducer
from shared.logger.logger import get_logger

from .events import emit_suggestion_event
from .lifecycle import apply_transition
from .models import SuggestionOutcomeRequest, SuggestionStatus
from .repository import SuggestionRepository

logger = get_logger("aether.suggestions.outcome")


def compute_learning_feedback(suggestion: dict, outcome: dict) -> dict:
    """Derive a learning signal from outcome status.

    Positive signal (helpful/accepted/executed) feeds back to the source
    and suggestion class. Negative signal (rejected/not_helpful/failed)
    reduces future weight for the same source+class pair.
    """
    outcome_status = outcome.get("status", "unknown")
    positive = {"helpful", "accepted", "executed"}
    negative = {"rejected", "not_helpful", "failed"}

    if outcome_status in positive:
        signal = "positive"
        delta = 0.05
    elif outcome_status in negative:
        signal = "negative"
        delta = -0.05
    else:
        signal = "neutral"
        delta = 0.0

    return {
        "signal": signal,
        "delta": delta,
        "source": suggestion.get("source"),
        "suggestion_class": suggestion.get("suggestion_class"),
        "priority": suggestion.get("priority"),
        "outcome_status": outcome_status,
        "computed_at": utc_now().isoformat(),
    }


async def record_and_close(
    suggestion_id: str,
    outcome_req: SuggestionOutcomeRequest,
    repo: SuggestionRepository,
    producer: EventProducer,
    tenant_context: TenantContext,
) -> dict:
    """Record an outcome, advance through MEASURED→LEARNED→CLOSED, emit event."""
    record = await repo.get_or_fail(suggestion_id, tenant_context.tenant_id)
    now = utc_now().isoformat()

    outcome = {
        "status": outcome_req.status,
        "measured_impact": outcome_req.measured_impact,
        "operator_notes": outcome_req.operator_notes,
        "tenant_feedback": outcome_req.tenant_feedback,
        "created_at": now,
        "created_by": outcome_req.created_by or getattr(tenant_context, "user_id", None),
    }

    if outcome_req.measured_impact:
        feedback = compute_learning_feedback(record, outcome)
        outcome["learning_feedback"] = feedback

    record = await repo.record_outcome(suggestion_id, tenant_context.tenant_id, outcome)

    current = SuggestionStatus(record.get("status", "delivered"))

    # Step to MEASURED if coming from EXECUTED or DELIVERED
    if current in (SuggestionStatus.EXECUTED, SuggestionStatus.DELIVERED):
        try:
            record = await apply_transition(
                repo=repo,
                suggestion_id=suggestion_id,
                tenant_id=tenant_context.tenant_id,
                to_status=SuggestionStatus.MEASURED,
                actor_kind="system",
                notes="Outcome recorded",
            )
            current = SuggestionStatus.MEASURED
        except Exception as exc:
            logger.debug(f"MEASURED transition skipped: {exc}")

    # Step to LEARNED if learning feedback was computed
    if current == SuggestionStatus.MEASURED and outcome.get("learning_feedback"):
        try:
            record = await apply_transition(
                repo=repo,
                suggestion_id=suggestion_id,
                tenant_id=tenant_context.tenant_id,
                to_status=SuggestionStatus.LEARNED,
                actor_kind="system",
                notes="Learning feedback computed",
            )
            current = SuggestionStatus.LEARNED
        except Exception as exc:
            logger.debug(f"LEARNED transition skipped: {exc}")

    # Step to CLOSED
    if current in (SuggestionStatus.MEASURED, SuggestionStatus.LEARNED):
        try:
            record = await apply_transition(
                repo=repo,
                suggestion_id=suggestion_id,
                tenant_id=tenant_context.tenant_id,
                to_status=SuggestionStatus.CLOSED,
                actor_kind="system",
                notes="Outcome loop complete",
            )
        except Exception as exc:
            logger.debug(f"CLOSED transition skipped: {exc}")

    await emit_suggestion_event(producer, "suggestion.outcome_recorded", record)
    return record
