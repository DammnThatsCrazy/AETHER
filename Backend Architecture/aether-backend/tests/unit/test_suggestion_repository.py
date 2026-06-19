"""Unit tests for SuggestionRepository (in-memory mode via AETHER_ENV=local)."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest

from services.suggestions.models import (
    OodaPhase,
    Suggestion,
    SuggestionClass,
    SuggestionQuery,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSubject,
    SuggestionPriority,
)
from services.suggestions.repository import SuggestionRepository
from shared.common.common import NotFoundError


def _run(coro):
    return asyncio.run(coro)


def _make_suggestion(
    tenant_id: str = "tenant_a",
    source: SuggestionSource = SuggestionSource.RULE,
    source_ref: dict = None,
) -> Suggestion:
    now = "2026-01-01T00:00:00Z"
    return Suggestion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id="ent_1"),
        source=source,
        source_ref=source_ref,
        ooda_phase=OodaPhase.OBSERVE,
        suggestion_class=SuggestionClass.DATA_QUALITY,
        priority=SuggestionPriority.P3,
        status=SuggestionStatus.DETECTED,
        title="Test Suggestion",
        summary="Summary",
        what="What",
        why="Why",
        impact="Impact",
        confidence_score=0.8,
        created_at=now,
        updated_at=now,
    )


def _fresh_repo() -> SuggestionRepository:
    """Return a new repository instance with a cleared in-memory store."""
    repo = SuggestionRepository()
    # Clear in-memory store between tests if available
    if hasattr(repo, "_store"):
        repo._store.clear()
    return repo


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------

def test_create_returns_dict_with_id():
    repo = _fresh_repo()
    suggestion = _make_suggestion()
    result = _run(repo.create(suggestion))
    assert isinstance(result, dict)
    assert result.get("id") == suggestion.id


def test_create_stores_tenant_id():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_xyz")
    result = _run(repo.create(suggestion))
    assert result["tenant_id"] == "tenant_xyz"


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

def test_get_returns_created_suggestion():
    repo = _fresh_repo()
    suggestion = _make_suggestion()
    _run(repo.create(suggestion))
    record = _run(repo.get(suggestion.id, suggestion.tenant_id))
    assert record is not None
    assert record["id"] == suggestion.id


def test_get_with_wrong_tenant_returns_none():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))
    result = _run(repo.get(suggestion.id, "tenant_b"))
    assert result is None


def test_get_unknown_id_returns_none():
    repo = _fresh_repo()
    result = _run(repo.get("nonexistent_id", "tenant_a"))
    assert result is None


# ---------------------------------------------------------------------------
# get_or_fail()
# ---------------------------------------------------------------------------

def test_get_or_fail_raises_for_missing_suggestion():
    repo = _fresh_repo()
    with pytest.raises(NotFoundError):
        _run(repo.get_or_fail("missing_id", "tenant_a"))


def test_get_or_fail_raises_for_wrong_tenant():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))
    with pytest.raises(NotFoundError):
        _run(repo.get_or_fail(suggestion.id, "tenant_b"))


def test_get_or_fail_returns_record_for_correct_tenant():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))
    record = _run(repo.get_or_fail(suggestion.id, "tenant_a"))
    assert record["id"] == suggestion.id


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------

def test_list_returns_suggestions_for_matching_tenant():
    repo = _fresh_repo()
    for _ in range(3):
        _run(repo.create(_make_suggestion(tenant_id="tenant_a")))

    query = SuggestionQuery(tenant_id="tenant_a")
    results = _run(repo.list(query))
    assert len(results) == 3
    for r in results:
        assert r["tenant_id"] == "tenant_a"


def test_list_tenant_isolation_filters_other_tenants():
    repo = _fresh_repo()
    _run(repo.create(_make_suggestion(tenant_id="tenant_a")))
    _run(repo.create(_make_suggestion(tenant_id="tenant_b")))

    query = SuggestionQuery(tenant_id="tenant_a")
    results = _run(repo.list(query))
    assert all(r["tenant_id"] == "tenant_a" for r in results)


def test_list_with_wrong_tenant_returns_empty():
    repo = _fresh_repo()
    _run(repo.create(_make_suggestion(tenant_id="tenant_a")))

    query = SuggestionQuery(tenant_id="tenant_zzz")
    results = _run(repo.list(query))
    assert results == []


# ---------------------------------------------------------------------------
# find_by_source_ref()
# ---------------------------------------------------------------------------

def test_find_by_source_ref_returns_suggestion():
    repo = _fresh_repo()
    suggestion = _make_suggestion(
        tenant_id="tenant_a",
        source=SuggestionSource.RECOMMENDATION_ENGINE,
        source_ref={"service": "recommendation_engine", "id": "rec_abc123"},
    )
    _run(repo.create(suggestion))

    result = _run(
        repo.find_by_source_ref(
            tenant_id="tenant_a",
            source="recommendation_engine",
            source_id="rec_abc123",
        )
    )
    assert result is not None
    assert result["id"] == suggestion.id


def test_find_by_source_ref_returns_none_for_unknown_source_id():
    repo = _fresh_repo()
    query_result = _run(
        repo.find_by_source_ref(
            tenant_id="tenant_a",
            source="recommendation_engine",
            source_id="does_not_exist",
        )
    )
    assert query_result is None


def test_find_by_source_ref_respects_tenant_isolation():
    repo = _fresh_repo()
    suggestion = _make_suggestion(
        tenant_id="tenant_a",
        source=SuggestionSource.RECOMMENDATION_ENGINE,
        source_ref={"service": "recommendation_engine", "id": "rec_shared"},
    )
    _run(repo.create(suggestion))

    # Look up from a different tenant
    result = _run(
        repo.find_by_source_ref(
            tenant_id="tenant_b",
            source="recommendation_engine",
            source_id="rec_shared",
        )
    )
    assert result is None


# ---------------------------------------------------------------------------
# transition()
# ---------------------------------------------------------------------------

def test_transition_updates_status():
    repo = _fresh_repo()
    suggestion = _make_suggestion()
    created = _run(repo.create(suggestion))

    audit_event = {
        "id": str(uuid.uuid4()),
        "action": "transition_to_suggested",
        "actor_kind": "system",
        "from_status": "detected",
        "to_status": "suggested",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    updated = _run(repo.transition(
        suggestion_id=suggestion.id,
        tenant_id=suggestion.tenant_id,
        from_status="detected",
        to_status="suggested",
        audit_event=audit_event,
    ))
    assert updated["status"] == "suggested"


def test_transition_appends_audit_event():
    repo = _fresh_repo()
    suggestion = _make_suggestion()
    _run(repo.create(suggestion))

    audit_event = {
        "id": str(uuid.uuid4()),
        "action": "transition_to_suggested",
        "actor_kind": "system",
        "from_status": "detected",
        "to_status": "suggested",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    updated = _run(repo.transition(
        suggestion_id=suggestion.id,
        tenant_id=suggestion.tenant_id,
        from_status="detected",
        to_status="suggested",
        audit_event=audit_event,
    ))
    assert len(updated.get("audit_trail", [])) >= 1


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

def test_summary_returns_suggestion_summary():
    repo = _fresh_repo()
    from services.suggestions.models import SuggestionSummary
    _run(repo.create(_make_suggestion(tenant_id="tenant_sum")))
    summary = _run(repo.summary("tenant_sum"))
    assert isinstance(summary, SuggestionSummary)
    assert summary.total >= 1
