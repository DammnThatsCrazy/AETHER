"""Noesis ↔ Suggestion adapter.

Provides READ-ONLY intent handlers for new suggestion-related Noesis intents.
Noesis MUST NOT approve, reject, execute, or mutate suggestions.
"""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.suggestions.adapters.noesis")

# Noesis intent → handler mapping
SUGGESTION_INTENTS = frozenset({
    "suggestion_lookup",
    "suggestion_summary",
    "suggestion_review_queue",
    "suggestion_explain",
    "suggestion_outcome_lookup",
})


async def handle_suggestion_lookup(
    plan: Any,
    repo: Any,
    tenant: Any,
) -> dict:
    """List suggestions for a subject or filter."""
    from services.suggestions.models import SuggestionQuery
    query = SuggestionQuery(
        tenant_id=tenant.tenant_id,
        limit=plan.limit or 10,
    )
    rows = await repo.list(query)
    count = len(rows)
    answer = f"Found {count} open suggestion{'s' if count != 1 else ''} for your tenant."
    if count > 0:
        top = rows[0]
        answer += (
            f" The highest-priority suggestion is: "{top.get('title', 'Untitled')}" "
            f"(priority {top.get('priority', 'P3')}, class {top.get('suggestion_class', 'unknown')})."
        )
    return _build_noesis_response(answer, rows[:5])


async def handle_suggestion_summary(
    plan: Any,
    repo: Any,
    tenant: Any,
) -> dict:
    """Return summary counts for the tenant."""
    summary = await repo.summary(tenant.tenant_id)
    answer = (
        f"Suggestion summary: {summary.total} total, "
        f"{summary.open} open, "
        f"{summary.review_required} awaiting review, "
        f"{summary.closed} closed."
    )
    return _build_noesis_response(answer, [summary.model_dump()])


async def handle_suggestion_review_queue(
    plan: Any,
    repo: Any,
    tenant: Any,
) -> dict:
    """List suggestions awaiting review."""
    rows = await repo.list_review_queue(tenant.tenant_id, limit=plan.limit or 10)
    count = len(rows)
    answer = (
        f"There {'is' if count == 1 else 'are'} {count} suggestion{'s' if count != 1 else ''} "
        "awaiting review. Approvals must be made through the review queue interface."
    )
    return _build_noesis_response(answer, rows)


async def handle_suggestion_explain(
    plan: Any,
    repo: Any,
    tenant: Any,
) -> dict:
    """Explain a specific suggestion (read-only)."""
    target_id = plan.target or ""
    if not target_id:
        return _build_noesis_response("Please specify a suggestion ID to explain.", [])

    record = await repo.get(target_id, tenant.tenant_id)
    if not record:
        return _build_noesis_response(f"Suggestion {target_id!r} not found.", [])

    answer = (
        f"Suggestion: {record.get('title', 'Untitled')}\n"
        f"Status: {record.get('status')}, Priority: {record.get('priority')}\n"
        f"What: {record.get('what', '')}\n"
        f"Why: {record.get('why', '')}\n"
        f"Impact: {record.get('impact', '')}"
    )
    return _build_noesis_response(answer, [record])


async def handle_suggestion_outcome_lookup(
    plan: Any,
    repo: Any,
    tenant: Any,
) -> dict:
    """Show outcome for a suggestion."""
    target_id = plan.target or ""
    if not target_id:
        return _build_noesis_response("Please specify a suggestion ID.", [])

    record = await repo.get(target_id, tenant.tenant_id)
    if not record:
        return _build_noesis_response(f"Suggestion {target_id!r} not found.", [])

    outcome = record.get("outcome")
    if not outcome:
        return _build_noesis_response(
            f"Suggestion {target_id!r} has no recorded outcome yet.", []
        )
    answer = (
        f"Outcome for suggestion {target_id!r}: "
        f"status={outcome.get('status')}, "
        f"feedback={outcome.get('tenant_feedback') or 'none'}."
    )
    return _build_noesis_response(answer, [{"suggestion_id": target_id, "outcome": outcome}])


def _build_noesis_response(answer: str, results: list) -> dict:
    return {
        "answer": answer,
        "intent": "suggestion_lookup",
        "mode": "deterministic",
        "confidence": 0.95,
        "results": results,
        "entities": [],
        "graph": {"nodes": [], "edges": [], "highlights": []},
        "actions": [],
        "warnings": ["Noesis is read-only. To approve, reject, or suppress a suggestion, use the review queue."],
    }
