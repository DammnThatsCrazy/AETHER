"""Suggestion dispatcher — routes approved suggestions to the correct execution mode.

Dispatch modes:
  notify_only                    → deliver via NotificationIntelligence
  legacy_recommendation_execute  → delegate to RecommendationExecutor
  no_op                         → mark DELIVERED, record outcome, done

Idempotent: if the suggestion is already EXECUTED or DELIVERED, the dispatcher
returns the current state without re-executing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from shared.auth.auth import TenantContext
from shared.common.common import BadRequestError, utc_now
from shared.logger.logger import get_logger

from .events import emit_suggestion_event
from .lifecycle import apply_transition
from .models import SuggestionSource, SuggestionStatus

if TYPE_CHECKING:
    from .service import SuggestionService

logger = get_logger("aether.suggestions.dispatcher")

_IDEMPOTENT_STATUSES = frozenset({
    SuggestionStatus.EXECUTED.value,
    SuggestionStatus.DELIVERED.value,
    SuggestionStatus.CLOSED.value,
})

# Sources that support legacy recommendation execution
_RECOMMENDATION_SOURCES: frozenset[str] = frozenset({
    SuggestionSource.RECOMMENDATION_ENGINE.value,
})

# Sources that support notification delivery
_NOTIFICATION_SOURCES: frozenset[str] = frozenset({
    SuggestionSource.NOTIFICATION_INTELLIGENCE.value,
    SuggestionSource.DATA_QUALITY.value,
    SuggestionSource.SDK_HEALTH.value,
    SuggestionSource.SDK_DRIFT.value,
    SuggestionSource.GRAPH.value,
    SuggestionSource.GOVERNANCE.value,
    SuggestionSource.RELIABILITY.value,
})


def _resolve_dispatch_mode(suggestion: dict) -> str:
    source = suggestion.get("source", "")
    if source in _RECOMMENDATION_SOURCES and suggestion.get("execution_eligible"):
        return "legacy_recommendation_execute"
    if source in _NOTIFICATION_SOURCES and suggestion.get("delivery_eligible"):
        return "notify_only"
    return "no_op"


async def dispatch(
    suggestion: dict,
    tenant_context: TenantContext,
    service: "SuggestionService",
    execution_enabled: bool = False,
) -> dict:
    """Execute or deliver an approved suggestion via the appropriate mode.

    Guards:
    - suggestion.status must be APPROVED
    - execution gate checked for execution modes
    - idempotent: re-entering EXECUTED/DELIVERED is a no-op
    """
    suggestion_id = suggestion["id"]
    tenant_id = suggestion["tenant_id"]
    current_status = suggestion.get("status")

    if current_status in _IDEMPOTENT_STATUSES:
        logger.info(f"Dispatch idempotent: suggestion {suggestion_id!r} is already {current_status!r}")
        return suggestion

    if current_status != SuggestionStatus.APPROVED.value:
        raise BadRequestError(
            f"Dispatch requires APPROVED status, got {current_status!r}"
        )

    mode = _resolve_dispatch_mode(suggestion)
    logger.info(f"Dispatching suggestion {suggestion_id!r} mode={mode!r}")

    try:
        if mode == "legacy_recommendation_execute":
            if not execution_enabled:
                raise BadRequestError(
                    "Execution is disabled. Set AETHER_SUGGESTIONS_EXECUTION_ENABLED=true."
                )
            # Delegate to recommendation adapter (lazy import to avoid circular dep)
            from services.suggestions.adapters.recommendation_adapter import (
                execute_recommendation_via_suggestion,
            )
            updated = await execute_recommendation_via_suggestion(suggestion, service)

        elif mode == "notify_only":
            # Deliver via notification adapter
            from services.suggestions.adapters.notification_adapter import (
                deliver_suggestion_via_notification,
            )
            updated = await deliver_suggestion_via_notification(suggestion, service)

        else:
            # no_op: mark delivered and record outcome
            updated = await service.deliver_suggestion(suggestion_id, tenant_context)

    except BadRequestError:
        raise
    except Exception as exc:
        logger.warning(f"Dispatch failed for {suggestion_id!r}: {exc}")
        try:
            updated = await apply_transition(
                repo=service._repo,
                suggestion_id=suggestion_id,
                tenant_id=tenant_id,
                to_status=SuggestionStatus.FAILED,
                actor_kind="system",
                notes=f"Dispatch error: {exc}",
            )
            await emit_suggestion_event(service._producer, "suggestion.failed", updated)
        except Exception as inner:
            logger.warning(f"FAILED transition also errored: {inner}")
            updated = suggestion
        return updated

    return updated
