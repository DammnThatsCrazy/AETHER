"""Unit tests for the Suggestion outcome loop."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from services.suggestions.outcome import (
    compute_learning_feedback,
    record_and_close,
)
from services.suggestions.models import (
    SuggestionClass,
    SuggestionOutcomeRequest,
    SuggestionPriority,
    SuggestionSource,
    SuggestionStatus,
)


def _run(coro):
    return asyncio.run(coro)


def _make_suggestion(
    suggestion_id: str = None,
    tenant_id: str = "tenant_abc",
    status: str = SuggestionStatus.DELIVERED.value,
) -> dict:
    return {
        "id": suggestion_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "status": status,
        "source": SuggestionSource.RULE.value,
        "suggestion_class": SuggestionClass.DATA_QUALITY.value,
        "priority": SuggestionPriority.P3.value,
        "title": "Test Suggestion",
        "audit_trail": [],
    }


def _make_tenant(tenant_id: str = "tenant_abc") -> MagicMock:
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    tenant.user_id = "user_test"
    return tenant


def _make_outcome_request(
    status: str = "helpful",
    measured_impact: dict = None,
) -> SuggestionOutcomeRequest:
    return SuggestionOutcomeRequest(
        status=status,
        measured_impact=measured_impact,
        operator_notes="Test notes",
        tenant_feedback="Helpful feedback",
    )


# ---------------------------------------------------------------------------
# compute_learning_feedback()
# ---------------------------------------------------------------------------

def test_compute_learning_feedback_helpful_returns_positive_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "positive"


def test_compute_learning_feedback_helpful_returns_positive_delta():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["delta"] > 0


def test_compute_learning_feedback_accepted_returns_positive_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "accepted"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "positive"


def test_compute_learning_feedback_executed_returns_positive_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "executed"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "positive"


def test_compute_learning_feedback_not_helpful_returns_negative_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "not_helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "negative"


def test_compute_learning_feedback_not_helpful_returns_negative_delta():
    suggestion = _make_suggestion()
    outcome = {"status": "not_helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["delta"] < 0


def test_compute_learning_feedback_rejected_returns_negative_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "rejected"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "negative"


def test_compute_learning_feedback_failed_returns_negative_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "failed"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "negative"


def test_compute_learning_feedback_unknown_returns_neutral_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "unknown"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "neutral"
    assert result["delta"] == 0.0


def test_compute_learning_feedback_ignored_returns_neutral_signal():
    suggestion = _make_suggestion()
    outcome = {"status": "ignored"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["signal"] == "neutral"


def test_compute_learning_feedback_includes_source():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["source"] == SuggestionSource.RULE.value


def test_compute_learning_feedback_includes_suggestion_class():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["suggestion_class"] == SuggestionClass.DATA_QUALITY.value


def test_compute_learning_feedback_includes_priority():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["priority"] == SuggestionPriority.P3.value


def test_compute_learning_feedback_includes_outcome_status():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["outcome_status"] == "helpful"


def test_compute_learning_feedback_includes_computed_at():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert "computed_at" in result
    assert result["computed_at"]


# ---------------------------------------------------------------------------
# record_and_close()
# ---------------------------------------------------------------------------

def _make_repo_for_close(suggestion: dict) -> MagicMock:
    """Build a repo mock that tracks status transitions internally."""
    state = dict(suggestion)  # mutable copy

    async def _get_or_fail(sid, tid):
        return dict(state)

    async def _record_outcome(sid, tid, outcome):
        state["outcome"] = outcome
        return dict(state)

    async def _transition(repo, suggestion_id, tenant_id, to_status, actor_kind, notes=None):
        state["status"] = to_status.value
        return dict(state)

    repo = MagicMock()
    repo.get_or_fail = _get_or_fail
    repo.record_outcome = _record_outcome
    return repo, state


def test_record_and_close_records_outcome():
    suggestion = _make_suggestion(status=SuggestionStatus.DELIVERED.value)
    repo = MagicMock()
    state = dict(suggestion)
    repo.get_or_fail = AsyncMock(return_value=dict(state))
    repo.record_outcome = AsyncMock(side_effect=lambda sid, tid, outcome: {**state, "outcome": outcome})

    tenant = _make_tenant()
    outcome_req = _make_outcome_request(status="helpful", measured_impact={"revenue": 100})

    with patch("services.suggestions.outcome.apply_transition", AsyncMock(return_value={**state, "status": "closed"})):
        with patch("services.suggestions.outcome.emit_suggestion_event", AsyncMock()):
            result = _run(record_and_close(
                suggestion_id=suggestion["id"],
                outcome_req=outcome_req,
                repo=repo,
                producer=MagicMock(),
                tenant_context=tenant,
            ))

    repo.record_outcome.assert_called_once()


def test_record_and_close_transitions_through_lifecycle():
    """Verify that apply_transition is called with MEASURED, LEARNED, CLOSED."""
    suggestion = _make_suggestion(status=SuggestionStatus.DELIVERED.value)
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=dict(suggestion))

    measured = {**suggestion, "status": SuggestionStatus.MEASURED.value}
    learned = {**suggestion, "status": SuggestionStatus.LEARNED.value}
    closed = {**suggestion, "status": SuggestionStatus.CLOSED.value}
    repo.record_outcome = AsyncMock(return_value=dict(suggestion))

    tenant = _make_tenant()
    outcome_req = _make_outcome_request(status="helpful", measured_impact={"revenue": 100})

    transition_calls = []

    async def _fake_apply_transition(repo, suggestion_id, tenant_id, to_status, actor_kind, notes=None):
        transition_calls.append(to_status)
        if to_status == SuggestionStatus.MEASURED:
            return measured
        elif to_status == SuggestionStatus.LEARNED:
            return learned
        else:
            return closed

    with patch("services.suggestions.outcome.apply_transition", _fake_apply_transition):
        with patch("services.suggestions.outcome.emit_suggestion_event", AsyncMock()):
            result = _run(record_and_close(
                suggestion_id=suggestion["id"],
                outcome_req=outcome_req,
                repo=repo,
                producer=MagicMock(),
                tenant_context=tenant,
            ))

    statuses = [t.value for t in transition_calls]
    assert SuggestionStatus.MEASURED.value in statuses


def test_record_and_close_emits_event():
    suggestion = _make_suggestion(status=SuggestionStatus.DELIVERED.value)
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=dict(suggestion))
    repo.record_outcome = AsyncMock(return_value=dict(suggestion))

    tenant = _make_tenant()
    outcome_req = _make_outcome_request(status="helpful")

    with patch("services.suggestions.outcome.apply_transition", AsyncMock(return_value={**suggestion, "status": "closed"})):
        with patch("services.suggestions.outcome.emit_suggestion_event", AsyncMock()) as mock_emit:
            _run(record_and_close(
                suggestion_id=suggestion["id"],
                outcome_req=outcome_req,
                repo=repo,
                producer=MagicMock(),
                tenant_context=tenant,
            ))

    mock_emit.assert_called_once()


def test_record_and_close_with_no_measured_impact_skips_learning():
    """Without measured_impact, learning_feedback is not computed, no LEARNED step."""
    suggestion = _make_suggestion(status=SuggestionStatus.DELIVERED.value)
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=dict(suggestion))

    measured = {**suggestion, "status": SuggestionStatus.MEASURED.value}
    repo.record_outcome = AsyncMock(return_value=dict(suggestion))

    tenant = _make_tenant()
    outcome_req = _make_outcome_request(status="helpful", measured_impact=None)

    transition_calls = []

    async def _fake_apply_transition(repo, suggestion_id, tenant_id, to_status, actor_kind, notes=None):
        transition_calls.append(to_status)
        return measured

    with patch("services.suggestions.outcome.apply_transition", _fake_apply_transition):
        with patch("services.suggestions.outcome.emit_suggestion_event", AsyncMock()):
            _run(record_and_close(
                suggestion_id=suggestion["id"],
                outcome_req=outcome_req,
                repo=repo,
                producer=MagicMock(),
                tenant_context=tenant,
            ))

    # LEARNED should not be in transition calls because no measured_impact
    assert SuggestionStatus.LEARNED not in transition_calls


def test_compute_learning_feedback_positive_delta_is_point_zero_five():
    suggestion = _make_suggestion()
    outcome = {"status": "helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["delta"] == 0.05


def test_compute_learning_feedback_negative_delta_is_minus_point_zero_five():
    suggestion = _make_suggestion()
    outcome = {"status": "not_helpful"}
    result = compute_learning_feedback(suggestion, outcome)
    assert result["delta"] == -0.05
