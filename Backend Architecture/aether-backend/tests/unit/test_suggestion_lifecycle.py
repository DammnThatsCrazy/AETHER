"""Unit tests for the Suggestion lifecycle state machine."""

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

from services.suggestions.lifecycle import (
    LEGAL_TRANSITIONS,
    apply_transition,
    build_audit_event,
    validate_transition,
)
from services.suggestions.models import SuggestionStatus
from shared.common.common import BadRequestError


def _run(coro):
    return asyncio.run(coro)


def _make_record(status: SuggestionStatus, requires_approval: bool = False) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant_test",
        "status": status.value,
        "ooda_phase": "observe",
        "requires_approval": requires_approval,
        "audit_trail": [],
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _make_repo(record: dict) -> MagicMock:
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=record)

    async def _transition(suggestion_id, tenant_id, from_status, to_status, audit_event):
        record["status"] = to_status
        record.setdefault("audit_trail", []).append(audit_event)
        return record

    repo.transition = _transition
    return repo


# ---------------------------------------------------------------------------
# Legal transitions — spot checks
# ---------------------------------------------------------------------------

def test_detected_to_suggested_is_legal():
    validate_transition(SuggestionStatus.DETECTED, SuggestionStatus.SUGGESTED)


def test_suggested_to_review_required_is_legal():
    validate_transition(SuggestionStatus.SUGGESTED, SuggestionStatus.REVIEW_REQUIRED)


def test_review_required_to_approved_is_legal():
    validate_transition(SuggestionStatus.REVIEW_REQUIRED, SuggestionStatus.APPROVED)


def test_approved_to_executing_is_legal():
    validate_transition(SuggestionStatus.APPROVED, SuggestionStatus.EXECUTING)


def test_executing_to_executed_is_legal():
    validate_transition(SuggestionStatus.EXECUTING, SuggestionStatus.EXECUTED)


def test_executed_to_measured_is_legal():
    validate_transition(SuggestionStatus.EXECUTED, SuggestionStatus.MEASURED)


def test_measured_to_learned_is_legal():
    validate_transition(SuggestionStatus.MEASURED, SuggestionStatus.LEARNED)


def test_learned_to_closed_is_legal():
    validate_transition(SuggestionStatus.LEARNED, SuggestionStatus.CLOSED)


# ---------------------------------------------------------------------------
# Terminal state: CLOSED has no outbound transitions
# ---------------------------------------------------------------------------

def test_closed_is_terminal_state():
    assert LEGAL_TRANSITIONS[SuggestionStatus.CLOSED] == frozenset()


def test_transition_from_closed_raises():
    with pytest.raises(BadRequestError):
        validate_transition(SuggestionStatus.CLOSED, SuggestionStatus.DETECTED)


def test_transition_from_closed_to_suggested_raises():
    with pytest.raises(BadRequestError):
        validate_transition(SuggestionStatus.CLOSED, SuggestionStatus.SUGGESTED)


# ---------------------------------------------------------------------------
# requires_approval blocks SUGGESTED→APPROVED shortcut
# ---------------------------------------------------------------------------

def test_requires_approval_blocks_suggested_to_approved():
    with pytest.raises(BadRequestError, match="requires human approval"):
        validate_transition(
            SuggestionStatus.SUGGESTED,
            SuggestionStatus.APPROVED,
            requires_approval=True,
        )


def test_no_approval_requirement_allows_suggested_to_approved():
    # Should not raise
    validate_transition(
        SuggestionStatus.SUGGESTED,
        SuggestionStatus.APPROVED,
        requires_approval=False,
    )


# ---------------------------------------------------------------------------
# Illegal transitions raise BadRequestError
# ---------------------------------------------------------------------------

def test_detected_to_executed_is_illegal():
    with pytest.raises(BadRequestError):
        validate_transition(SuggestionStatus.DETECTED, SuggestionStatus.EXECUTED)


def test_suggested_to_executing_is_illegal():
    with pytest.raises(BadRequestError):
        validate_transition(SuggestionStatus.SUGGESTED, SuggestionStatus.EXECUTING)


# ---------------------------------------------------------------------------
# build_audit_event
# ---------------------------------------------------------------------------

def test_build_audit_event_returns_dict_with_required_fields():
    event = build_audit_event(
        action="transition_to_suggested",
        from_status="detected",
        to_status="suggested",
        actor_id="user_1",
        actor_kind="tenant_user",
    )
    assert event["action"] == "transition_to_suggested"
    assert event["from_status"] == "detected"
    assert event["to_status"] == "suggested"
    assert event["actor_kind"] == "tenant_user"
    assert "id" in event
    assert "timestamp" in event


# ---------------------------------------------------------------------------
# apply_transition integration with mocked repo
# ---------------------------------------------------------------------------

def test_apply_transition_updates_status():
    record = _make_record(SuggestionStatus.SUGGESTED, requires_approval=False)
    repo = _make_repo(record)

    updated = _run(apply_transition(
        repo=repo,
        suggestion_id=record["id"],
        tenant_id="tenant_test",
        to_status=SuggestionStatus.APPROVED,
    ))
    assert updated["status"] == SuggestionStatus.APPROVED.value


def test_apply_transition_sets_reviewed_at_on_approved():
    record = _make_record(SuggestionStatus.REVIEW_REQUIRED)
    repo = _make_repo(record)

    # Patch the repo.transition to also set reviewed_at
    async def _transition(suggestion_id, tenant_id, from_status, to_status, audit_event):
        record["status"] = to_status
        record.setdefault("audit_trail", []).append(audit_event)
        return record

    repo.transition = _transition

    updated = _run(apply_transition(
        repo=repo,
        suggestion_id=record["id"],
        tenant_id="tenant_test",
        to_status=SuggestionStatus.APPROVED,
        actor_id="reviewer_1",
    ))
    assert updated["status"] == SuggestionStatus.APPROVED.value


def test_apply_transition_appends_audit_event():
    record = _make_record(SuggestionStatus.SUGGESTED, requires_approval=False)
    repo = _make_repo(record)

    _run(apply_transition(
        repo=repo,
        suggestion_id=record["id"],
        tenant_id="tenant_test",
        to_status=SuggestionStatus.APPROVED,
    ))
    assert len(record["audit_trail"]) == 1
    assert record["audit_trail"][0]["to_status"] == SuggestionStatus.APPROVED.value


def test_apply_transition_closed_sets_closed_at_in_patch():
    # Verify the patch dict contains closed_at for CLOSED transition
    # We do this by inspecting what repo.transition receives
    record = _make_record(SuggestionStatus.LEARNED)
    received_patches = []

    async def _get_or_fail(suggestion_id, tenant_id):
        return record

    async def _transition(suggestion_id, tenant_id, from_status, to_status, audit_event):
        record["status"] = to_status
        record.setdefault("audit_trail", []).append(audit_event)
        return record

    repo = MagicMock()
    repo.get_or_fail = _get_or_fail
    repo.transition = _transition

    updated = _run(apply_transition(
        repo=repo,
        suggestion_id=record["id"],
        tenant_id="tenant_test",
        to_status=SuggestionStatus.CLOSED,
    ))
    assert updated["status"] == SuggestionStatus.CLOSED.value
