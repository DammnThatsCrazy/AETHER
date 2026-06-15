"""Unit tests for the Recommendation Engine ↔ Suggestion adapter."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.suggestions.adapters.recommendation_adapter import (
    create_suggestion_from_recommendation,
    execute_recommendation_via_suggestion,
    find_or_create_from_recommendation,
)
from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionStatus,
)


def _run(coro):
    return asyncio.run(coro)


def _make_rec(**overrides) -> dict:
    base = {
        "recommendation_id": str(uuid.uuid4()),
        "entity_id": "ent_abc123",
        "display_name": "Test Entity",
        "platform": "email",
        "channel": "email",
        "campaign_id": "camp_001",
        "retarget_score": 0.85,
        "urgency_score": 0.6,
        "created_at": "2026-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _make_approved_suggestion(suggestion_id: str = None, execution_eligible: bool = True) -> dict:
    return {
        "id": suggestion_id or str(uuid.uuid4()),
        "tenant_id": "tenant_abc",
        "status": SuggestionStatus.APPROVED.value,
        "title": "Retarget suggestion",
        "source": SuggestionSource.RECOMMENDATION_ENGINE.value,
        "source_ref": {"service": "recommendation_engine", "id": "rec_001"},
        "execution_eligible": execution_eligible,
        "delivery_eligible": False,
        "audit_trail": [],
    }


# ---------------------------------------------------------------------------
# create_suggestion_from_recommendation()
# ---------------------------------------------------------------------------

def test_create_from_rec_returns_suggestion_create():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert isinstance(result, SuggestionCreate)


def test_create_from_rec_maps_entity_id_to_subject_id():
    rec = _make_rec(entity_id="ent_specific_123")
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.subject.id == "ent_specific_123"


def test_create_from_rec_sets_source_to_recommendation_engine():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.source == SuggestionSource.RECOMMENDATION_ENGINE


def test_create_from_rec_sets_class_to_retargeting():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.suggestion_class == SuggestionClass.RETARGETING


def test_create_from_rec_maps_retarget_score_to_confidence():
    rec = _make_rec(retarget_score=0.9)
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.confidence_score == 0.9


def test_create_from_rec_maps_tenant_id():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_xyz")
    assert result.tenant_id == "tenant_xyz"


def test_create_from_rec_maps_urgency_score():
    rec = _make_rec(urgency_score=0.75)
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.urgency_score == 0.75


def test_create_from_rec_is_reversible():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.reversible is True


def test_create_from_rec_has_low_risk_score():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.risk_score == 0.1


def test_create_from_rec_sets_source_ref_with_rec_id():
    rec = _make_rec(recommendation_id="rec_specific")
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.source_ref is not None
    assert result.source_ref["id"] == "rec_specific"
    assert result.source_ref["service"] == "recommendation_engine"


def test_create_from_rec_has_evidence_with_model_output():
    rec = _make_rec()
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert len(result.evidence) >= 1
    assert result.evidence[0]["type"] == "model_output"


def test_create_from_rec_falls_back_user_id_when_no_entity_id():
    rec = _make_rec()
    del rec["entity_id"]
    rec["user_id"] = "user_fallback"
    result = create_suggestion_from_recommendation(rec, "tenant_abc")
    assert result.subject.id == "user_fallback"


# ---------------------------------------------------------------------------
# find_or_create_from_recommendation() — idempotency
# ---------------------------------------------------------------------------

def test_find_or_create_returns_existing_when_rec_id_found():
    rec = _make_rec(recommendation_id="rec_existing")
    existing = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant_abc",
        "status": "detected",
        "source_ref": {"service": "recommendation_engine", "id": "rec_existing"},
    }
    repo = MagicMock()
    repo.find_by_source_ref = AsyncMock(return_value=existing)

    svc = MagicMock()
    svc._repo = repo

    result = _run(find_or_create_from_recommendation(rec, "tenant_abc", svc))
    assert result["id"] == existing["id"]
    # Should NOT call create_suggestion
    svc.create_suggestion.assert_not_called()


def test_find_or_create_creates_new_when_rec_id_not_found():
    rec = _make_rec(recommendation_id="rec_new")
    new_suggestion = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant_abc",
        "status": "detected",
    }
    repo = MagicMock()
    repo.find_by_source_ref = AsyncMock(return_value=None)

    svc = MagicMock()
    svc._repo = repo
    svc.create_suggestion = AsyncMock(return_value=new_suggestion)

    result = _run(find_or_create_from_recommendation(rec, "tenant_abc", svc))
    svc.create_suggestion.assert_called_once()
    assert result["id"] == new_suggestion["id"]


def test_find_or_create_idempotent_same_rec_id_returns_same_suggestion():
    rec_id = "rec_idempotent"
    rec = _make_rec(recommendation_id=rec_id)
    existing = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant_abc",
        "status": "detected",
        "source_ref": {"service": "recommendation_engine", "id": rec_id},
    }
    repo = MagicMock()
    repo.find_by_source_ref = AsyncMock(return_value=existing)

    svc = MagicMock()
    svc._repo = repo

    result1 = _run(find_or_create_from_recommendation(rec, "tenant_abc", svc))
    result2 = _run(find_or_create_from_recommendation(rec, "tenant_abc", svc))
    assert result1["id"] == result2["id"]


# ---------------------------------------------------------------------------
# execute_recommendation_via_suggestion()
# ---------------------------------------------------------------------------

def test_execute_rec_skips_if_not_approved():
    suggestion = _make_approved_suggestion()
    suggestion["status"] = "suggested"  # not approved

    svc = MagicMock()
    result = _run(execute_recommendation_via_suggestion(suggestion, svc))
    assert result == suggestion


def test_execute_rec_skips_if_not_execution_eligible():
    suggestion = _make_approved_suggestion(execution_eligible=False)

    svc = MagicMock()
    result = _run(execute_recommendation_via_suggestion(suggestion, svc))
    assert result == suggestion


def test_execute_rec_transitions_to_executed_when_eligible():
    suggestion = _make_approved_suggestion(execution_eligible=True)
    executed = {**suggestion, "status": SuggestionStatus.EXECUTED.value}

    svc = MagicMock()
    svc._repo = MagicMock()
    svc._producer = MagicMock()

    with patch(
        "services.suggestions.adapters.recommendation_adapter.apply_transition",
        AsyncMock(return_value=executed),
    ) as mock_trans:
        with patch(
            "services.suggestions.adapters.recommendation_adapter.emit_suggestion_event",
            AsyncMock(),
        ):
            result = _run(execute_recommendation_via_suggestion(suggestion, svc))

    mock_trans.assert_called_once()
    assert result["status"] == SuggestionStatus.EXECUTED.value
