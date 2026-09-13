"""Unit tests for SuggestionService (mocked dependencies)."""

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

from services.suggestions.models import (
    SuggestionActionRequest,
    SuggestionClass,
    SuggestionPolicyDecision,
    SuggestionPriority,
    SuggestionRejectRequest,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSubject,
    SuggestionSummary,
)
from services.suggestions.service import SuggestionService
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError


def _run(coro):
    return asyncio.run(coro)


def _make_tenant(tenant_id: str = "tenant_abc", user_id: str = "user_1") -> MagicMock:
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    tenant.user_id = user_id
    return tenant


def _make_suggestion_record(
    suggestion_id: str = None,
    tenant_id: str = "tenant_abc",
    status: str = "detected",
    requires_approval: bool = False,
    execution_eligible: bool = False,
    delivery_eligible: bool = True,
) -> dict:
    now = "2026-01-01T00:00:00Z"
    return {
        "id": suggestion_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "status": status,
        "ooda_phase": "observe",
        "suggestion_class": SuggestionClass.DATA_QUALITY.value,
        "priority": SuggestionPriority.P3.value,
        "source": SuggestionSource.RULE.value,
        "title": "Test Suggestion",
        "summary": "A test summary",
        "what": "What",
        "why": "Why",
        "impact": "Impact",
        "confidence_score": 0.8,
        "requires_approval": requires_approval,
        "execution_eligible": execution_eligible,
        "delivery_eligible": delivery_eligible,
        "audit_trail": [],
        "created_at": now,
        "updated_at": now,
    }


def _make_policy_decision() -> SuggestionPolicyDecision:
    return SuggestionPolicyDecision(
        decision_id=str(uuid.uuid4()),
        allowed=True,
        requires_approval=False,
        policies=["default_suggestion_policy"],
        evaluated_at="2026-01-01T00:00:00Z",
    )


def _make_service(
    repo: MagicMock = None,
    producer: MagicMock = None,
) -> SuggestionService:
    repo = repo or MagicMock()
    producer = producer or MagicMock()
    cache = MagicMock()
    graph = MagicMock()
    return SuggestionService(repo=repo, producer=producer, cache=cache, graph=graph)


def _make_create_payload(**overrides):
    from services.suggestions.models import SuggestionCreate
    base = {
        "tenant_id": "tenant_abc",
        "subject": SuggestionSubject(kind="entity", id="ent_1"),
        "source": SuggestionSource.RULE,
        "suggestion_class": SuggestionClass.DATA_QUALITY,
        "title": "Test Suggestion",
        "summary": "A test summary",
        "what": "What is happening",
        "why": "Why it matters",
        "impact": "Impact description",
        "confidence_score": 0.8,
    }
    base.update(overrides)
    return SuggestionCreate(**base)


# ---------------------------------------------------------------------------
# create_suggestion()
# ---------------------------------------------------------------------------

def test_create_suggestion_raises_forbidden_for_tenant_mismatch():
    svc = _make_service()
    create = _make_create_payload(tenant_id="tenant_abc")
    tenant = _make_tenant(tenant_id="tenant_different")
    with pytest.raises(ForbiddenError):
        _run(svc.create_suggestion(create, tenant))


def test_create_suggestion_calls_repo_create():
    record = _make_suggestion_record()
    repo = MagicMock()
    repo.create = AsyncMock(return_value=record)

    producer = MagicMock()
    producer.produce = AsyncMock()

    svc = _make_service(repo=repo, producer=producer)
    create = _make_create_payload()
    tenant = _make_tenant()

    with patch("services.suggestions.service.evaluate_suggestion_policy", AsyncMock(return_value=_make_policy_decision())):
        with patch("services.suggestions.service.emit_suggestion_event", AsyncMock()):
            result = _run(svc.create_suggestion(create, tenant))

    repo.create.assert_called_once()
    assert result["id"] == record["id"]


def test_create_suggestion_calls_compute_scores():
    record = _make_suggestion_record()
    repo = MagicMock()
    repo.create = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    create = _make_create_payload()
    tenant = _make_tenant()

    with patch("services.suggestions.service.compute_scores") as mock_scores:
        mock_scores.return_value = {
            "impact_score": 0.8,
            "urgency_score": 0.5,
            "evidence_quality_score": 0.7,
            "tenant_value_score": 0.5,
            "reversibility_score": 0.8,
            "priority_score": 0.65,
            "priority": SuggestionPriority.P2,
        }
        with patch("services.suggestions.service.evaluate_suggestion_policy", AsyncMock(return_value=_make_policy_decision())):
            with patch("services.suggestions.service.emit_suggestion_event", AsyncMock()):
                _run(svc.create_suggestion(create, tenant))
    mock_scores.assert_called_once()


def test_create_suggestion_emits_event():
    record = _make_suggestion_record()
    repo = MagicMock()
    repo.create = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    create = _make_create_payload()
    tenant = _make_tenant()

    with patch("services.suggestions.service.evaluate_suggestion_policy", AsyncMock(return_value=_make_policy_decision())):
        with patch("services.suggestions.service.emit_suggestion_event", AsyncMock()) as mock_emit:
            _run(svc.create_suggestion(create, tenant))
    mock_emit.assert_called_once()


# ---------------------------------------------------------------------------
# get_suggestion()
# ---------------------------------------------------------------------------

def test_get_suggestion_returns_record_for_correct_tenant():
    record = _make_suggestion_record(tenant_id="tenant_abc")
    repo = MagicMock()
    repo.get = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    tenant = _make_tenant(tenant_id="tenant_abc")
    result = _run(svc.get_suggestion(record["id"], tenant))
    assert result["id"] == record["id"]


def test_get_suggestion_raises_not_found_when_repo_returns_none():
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)

    svc = _make_service(repo=repo)
    tenant = _make_tenant()
    with pytest.raises(NotFoundError):
        _run(svc.get_suggestion("nonexistent_id", tenant))


def test_get_suggestion_enforces_tenant_id_match():
    # repo.get returns None when tenant doesn't match (repo enforces this)
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)

    svc = _make_service(repo=repo)
    tenant = _make_tenant(tenant_id="tenant_wrong")
    with pytest.raises(NotFoundError):
        _run(svc.get_suggestion("some_id", tenant))


# ---------------------------------------------------------------------------
# approve_suggestion()
# ---------------------------------------------------------------------------

def test_approve_suggestion_calls_apply_transition():
    record = _make_suggestion_record(status="review_required")
    updated = {**record, "status": "approved"}
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    tenant = _make_tenant()
    body = SuggestionActionRequest(actor_id="user_1", notes="LGTM")

    with patch("services.suggestions.service.apply_transition", AsyncMock(return_value=updated)) as mock_trans:
        with patch("services.suggestions.service.emit_suggestion_event", AsyncMock()):
            result = _run(svc.approve_suggestion(record["id"], body, tenant))

    mock_trans.assert_called_once()
    call_kwargs = mock_trans.call_args.kwargs
    assert call_kwargs["to_status"] == SuggestionStatus.APPROVED


def test_approve_suggestion_raises_for_wrong_status():
    # Only review_required or suggested can be approved
    record = _make_suggestion_record(status="detected")
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    tenant = _make_tenant()
    body = SuggestionActionRequest()

    with pytest.raises(BadRequestError):
        _run(svc.approve_suggestion(record["id"], body, tenant))


def test_approve_suggestion_from_suggested_is_allowed():
    record = _make_suggestion_record(status="suggested", requires_approval=False)
    updated = {**record, "status": "approved"}
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    tenant = _make_tenant()
    body = SuggestionActionRequest()

    with patch("services.suggestions.service.apply_transition", AsyncMock(return_value=updated)):
        with patch("services.suggestions.service.emit_suggestion_event", AsyncMock()):
            result = _run(svc.approve_suggestion(record["id"], body, tenant))
    assert result["status"] == "approved"


# ---------------------------------------------------------------------------
# reject_suggestion()
# ---------------------------------------------------------------------------

def test_reject_suggestion_requires_reason():
    # SuggestionRejectRequest requires reason field
    with pytest.raises(Exception):
        SuggestionRejectRequest()  # missing required reason


def test_reject_suggestion_calls_apply_transition_with_rejected_status():
    record = _make_suggestion_record(status="review_required")
    updated = {**record, "status": "rejected"}
    repo = MagicMock()
    repo.get_or_fail = AsyncMock(return_value=record)

    svc = _make_service(repo=repo)
    tenant = _make_tenant()
    body = SuggestionRejectRequest(reason="Not relevant")

    with patch("services.suggestions.service.apply_transition", AsyncMock(return_value=updated)) as mock_trans:
        with patch("services.suggestions.service.emit_suggestion_event", AsyncMock()):
            _run(svc.reject_suggestion(record["id"], body, tenant))

    mock_trans.assert_called_once()
    call_kwargs = mock_trans.call_args.kwargs
    assert call_kwargs["to_status"] == SuggestionStatus.REJECTED


# ---------------------------------------------------------------------------
# summarize()
# ---------------------------------------------------------------------------

def test_summarize_returns_suggestion_summary():
    summary = SuggestionSummary(
        total=10, open=5, review_required=2, approved=1,
        executed=1, failed=0, closed=1,
        by_class={"data_quality": 10},
        by_priority={"P3": 10},
        by_status={"detected": 5, "closed": 1},
    )
    repo = MagicMock()
    repo.summary = AsyncMock(return_value=summary)

    svc = _make_service(repo=repo)
    tenant = _make_tenant()
    result = _run(svc.summarize(tenant))
    assert isinstance(result, SuggestionSummary)
    assert result.total == 10
    assert result.open == 5


def test_summarize_passes_tenant_id_to_repo():
    summary = SuggestionSummary(
        total=0, open=0, review_required=0, approved=0,
        executed=0, failed=0, closed=0,
        by_class={}, by_priority={}, by_status={},
    )
    repo = MagicMock()
    repo.summary = AsyncMock(return_value=summary)

    svc = _make_service(repo=repo)
    tenant = _make_tenant(tenant_id="tenant_abc")
    _run(svc.summarize(tenant))
    repo.summary.assert_called_once_with("tenant_abc", filters=None)


# ---------------------------------------------------------------------------
# query_suggestions()
# ---------------------------------------------------------------------------

def test_query_suggestions_raises_forbidden_for_tenant_mismatch():
    from services.suggestions.models import SuggestionQuery
    repo = MagicMock()
    svc = _make_service(repo=repo)
    tenant = _make_tenant(tenant_id="tenant_abc")
    query = SuggestionQuery(tenant_id="tenant_xyz")
    with pytest.raises(ForbiddenError):
        _run(svc.query_suggestions(query, tenant))


def test_query_suggestions_returns_list_and_count():
    from services.suggestions.models import SuggestionQuery
    records = [_make_suggestion_record(), _make_suggestion_record()]
    repo = MagicMock()
    repo.list = AsyncMock(return_value=records)

    svc = _make_service(repo=repo)
    tenant = _make_tenant(tenant_id="tenant_abc")
    query = SuggestionQuery(tenant_id="tenant_abc")
    results, total = _run(svc.query_suggestions(query, tenant))
    assert len(results) == 2
    assert total == 2
