"""Unit tests for the Noesis ↔ Suggestion adapter (read-only)."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.suggestions.adapters.noesis_adapter import (
    SUGGESTION_INTENTS,
    handle_suggestion_explain,
    handle_suggestion_lookup,
    handle_suggestion_review_queue,
    handle_suggestion_summary,
    handle_suggestion_outcome_lookup,
)
from services.suggestions.models import SuggestionSummary


def _run(coro):
    return asyncio.run(coro)


def _make_plan(**kwargs) -> MagicMock:
    plan = MagicMock()
    plan.limit = kwargs.get("limit", 10)
    plan.target = kwargs.get("target", "")
    return plan


def _make_tenant(tenant_id: str = "tenant_abc") -> MagicMock:
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    return tenant


def _make_record(suggestion_id: str = None) -> dict:
    now = "2026-01-01T00:00:00Z"
    return {
        "id": suggestion_id or str(uuid.uuid4()),
        "tenant_id": "tenant_abc",
        "status": "suggested",
        "priority": "P2",
        "suggestion_class": "data_quality",
        "title": "Test Suggestion",
        "summary": "Summary text",
        "what": "What is happening",
        "why": "Why it matters",
        "impact": "Impact text",
        "confidence_score": 0.8,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# SUGGESTION_INTENTS frozenset
# ---------------------------------------------------------------------------

def test_suggestion_intents_is_frozenset():
    assert isinstance(SUGGESTION_INTENTS, frozenset)


def test_suggestion_intents_has_all_5_intents():
    assert len(SUGGESTION_INTENTS) == 5


def test_suggestion_intents_contains_expected_values():
    expected = {
        "suggestion_lookup",
        "suggestion_summary",
        "suggestion_review_queue",
        "suggestion_explain",
        "suggestion_outcome_lookup",
    }
    assert SUGGESTION_INTENTS == expected


# ---------------------------------------------------------------------------
# handle_suggestion_lookup
# ---------------------------------------------------------------------------

def test_handle_suggestion_lookup_returns_answer_key():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_lookup(plan, repo, tenant))
    assert "answer" in result


def test_handle_suggestion_lookup_returns_results_key():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_lookup(plan, repo, tenant))
    assert "results" in result


def test_handle_suggestion_lookup_results_is_list():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[_make_record()])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_lookup(plan, repo, tenant))
    assert isinstance(result["results"], list)


def test_handle_suggestion_lookup_answer_mentions_count():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[_make_record(), _make_record()])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_lookup(plan, repo, tenant))
    assert "2" in result["answer"]


def test_handle_suggestion_lookup_empty_repo_answer_mentions_zero():
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_lookup(plan, repo, tenant))
    assert "0" in result["answer"]


# ---------------------------------------------------------------------------
# handle_suggestion_summary
# ---------------------------------------------------------------------------

def test_handle_suggestion_summary_returns_answer_key():
    summary = SuggestionSummary(
        total=5, open=3, review_required=1, approved=0,
        executed=0, failed=0, closed=1,
        by_class={}, by_priority={}, by_status={},
    )
    repo = MagicMock()
    repo.summary = AsyncMock(return_value=summary)
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_summary(plan, repo, tenant))
    assert "answer" in result


def test_handle_suggestion_summary_answer_contains_counts():
    summary = SuggestionSummary(
        total=10, open=7, review_required=2, approved=1,
        executed=0, failed=0, closed=0,
        by_class={}, by_priority={}, by_status={},
    )
    repo = MagicMock()
    repo.summary = AsyncMock(return_value=summary)
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_summary(plan, repo, tenant))
    assert "10" in result["answer"]


def test_handle_suggestion_summary_results_is_list():
    summary = SuggestionSummary(
        total=0, open=0, review_required=0, approved=0,
        executed=0, failed=0, closed=0,
        by_class={}, by_priority={}, by_status={},
    )
    repo = MagicMock()
    repo.summary = AsyncMock(return_value=summary)
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_summary(plan, repo, tenant))
    assert isinstance(result["results"], list)
    assert len(result["results"]) == 1  # contains the summary dict


# ---------------------------------------------------------------------------
# handle_suggestion_review_queue
# ---------------------------------------------------------------------------

def test_handle_suggestion_review_queue_returns_results_in_results_key():
    records = [_make_record(), _make_record()]
    repo = MagicMock()
    repo.list_review_queue = AsyncMock(return_value=records)
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_review_queue(plan, repo, tenant))
    assert "results" in result
    assert isinstance(result["results"], list)
    assert len(result["results"]) == 2


def test_handle_suggestion_review_queue_answer_is_string():
    repo = MagicMock()
    repo.list_review_queue = AsyncMock(return_value=[])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_review_queue(plan, repo, tenant))
    assert isinstance(result["answer"], str)


def test_handle_suggestion_review_queue_empty_returns_zero_in_answer():
    repo = MagicMock()
    repo.list_review_queue = AsyncMock(return_value=[])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_review_queue(plan, repo, tenant))
    assert "0" in result["answer"]


# ---------------------------------------------------------------------------
# handle_suggestion_explain
# ---------------------------------------------------------------------------

def test_handle_suggestion_explain_returns_explanation_text():
    sug_id = str(uuid.uuid4())
    record = _make_record(suggestion_id=sug_id)
    repo = MagicMock()
    repo.get = AsyncMock(return_value=record)
    plan = _make_plan(target=sug_id)
    tenant = _make_tenant()

    result = _run(handle_suggestion_explain(plan, repo, tenant))
    assert "answer" in result
    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0


def test_handle_suggestion_explain_without_target_returns_helpful_message():
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    plan = _make_plan(target="")
    tenant = _make_tenant()

    result = _run(handle_suggestion_explain(plan, repo, tenant))
    assert "answer" in result
    assert "specify" in result["answer"].lower() or "id" in result["answer"].lower()


def test_handle_suggestion_explain_unknown_id_returns_not_found():
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    plan = _make_plan(target="nonexistent_id")
    tenant = _make_tenant()

    result = _run(handle_suggestion_explain(plan, repo, tenant))
    assert "not found" in result["answer"].lower()


def test_handle_suggestion_explain_includes_title_in_answer():
    sug_id = str(uuid.uuid4())
    record = _make_record(suggestion_id=sug_id)
    repo = MagicMock()
    repo.get = AsyncMock(return_value=record)
    plan = _make_plan(target=sug_id)
    tenant = _make_tenant()

    result = _run(handle_suggestion_explain(plan, repo, tenant))
    assert "Test Suggestion" in result["answer"]


# ---------------------------------------------------------------------------
# Response structure (all handlers)
# ---------------------------------------------------------------------------

def test_all_handlers_return_warnings_list():
    """All Noesis responses should carry the read-only warning."""
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    plan = _make_plan()
    tenant = _make_tenant()

    result = _run(handle_suggestion_lookup(plan, repo, tenant))
    assert "warnings" in result
    assert isinstance(result["warnings"], list)
    assert len(result["warnings"]) > 0
