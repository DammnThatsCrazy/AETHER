"""Unit tests verifying tenant isolation across the suggestion layer."""

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
    OodaPhase,
    Suggestion,
    SuggestionClass,
    SuggestionPriority,
    SuggestionQuery,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSubject,
)
from services.suggestions.repository import SuggestionRepository
from services.suggestions.service import SuggestionService
from shared.common.common import NotFoundError


def _run(coro):
    return asyncio.run(coro)


def _make_suggestion(tenant_id: str) -> Suggestion:
    now = "2026-01-01T00:00:00Z"
    return Suggestion(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id="ent_1"),
        source=SuggestionSource.RULE,
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


def _make_tenant(tenant_id: str, user_id: str = "user_1") -> MagicMock:
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    tenant.user_id = user_id
    return tenant


def _fresh_repo() -> SuggestionRepository:
    repo = SuggestionRepository()
    if hasattr(repo, "_store"):
        repo._store.clear()
    return repo


def _make_service(repo: SuggestionRepository) -> SuggestionService:
    producer = MagicMock()
    producer.produce = AsyncMock()
    cache = MagicMock()
    graph = MagicMock()
    return SuggestionService(repo=repo, producer=producer, cache=cache, graph=graph)


# ---------------------------------------------------------------------------
# Repository layer: tenant isolation
# ---------------------------------------------------------------------------

def test_repository_get_with_wrong_tenant_returns_none():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))

    result = _run(repo.get(suggestion.id, "tenant_b"))
    assert result is None


def test_repository_get_with_correct_tenant_returns_record():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))

    result = _run(repo.get(suggestion.id, "tenant_a"))
    assert result is not None
    assert result["id"] == suggestion.id


def test_repository_list_with_wrong_tenant_returns_empty():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))

    query = SuggestionQuery(tenant_id="tenant_b")
    results = _run(repo.list(query))
    assert results == []


def test_repository_list_only_returns_own_tenant_records():
    repo = _fresh_repo()
    for _ in range(2):
        _run(repo.create(_make_suggestion(tenant_id="tenant_a")))
    _run(repo.create(_make_suggestion(tenant_id="tenant_b")))

    query = SuggestionQuery(tenant_id="tenant_a")
    results = _run(repo.list(query))
    assert len(results) == 2
    assert all(r["tenant_id"] == "tenant_a" for r in results)


def test_repository_get_or_fail_with_wrong_tenant_raises():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    _run(repo.create(suggestion))

    with pytest.raises(NotFoundError):
        _run(repo.get_or_fail(suggestion.id, "tenant_b"))


# ---------------------------------------------------------------------------
# Service layer: tenant isolation
# ---------------------------------------------------------------------------

def test_service_get_suggestion_with_wrong_tenant_raises_not_found():
    suggestion_id = str(uuid.uuid4())
    # repo.get returns None when the tenant doesn't match
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)

    svc = _make_service(repo)
    tenant_b = _make_tenant("tenant_b")

    with pytest.raises(NotFoundError):
        _run(svc.get_suggestion(suggestion_id, tenant_b))


def test_service_get_suggestion_with_correct_tenant_returns_record():
    record = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant_a",
        "status": "detected",
    }
    repo = MagicMock()
    repo.get = AsyncMock(return_value=record)

    svc = _make_service(repo)
    tenant_a = _make_tenant("tenant_a")
    result = _run(svc.get_suggestion(record["id"], tenant_a))
    assert result["id"] == record["id"]


def test_service_create_suggestion_rejects_wrong_tenant_in_body():
    from services.suggestions.models import SuggestionCreate
    from shared.common.common import ForbiddenError

    repo = MagicMock()
    svc = _make_service(repo)

    # Create payload has tenant_a but authenticated tenant is tenant_b
    create = SuggestionCreate(
        tenant_id="tenant_a",
        subject=SuggestionSubject(kind="entity", id="ent_1"),
        source=SuggestionSource.RULE,
        suggestion_class=SuggestionClass.DATA_QUALITY,
        title="Test",
        summary="Summary",
        what="What",
        why="Why",
        impact="Impact",
        confidence_score=0.8,
    )
    tenant_b = _make_tenant("tenant_b")

    with pytest.raises(ForbiddenError):
        _run(svc.create_suggestion(create, tenant_b))


# ---------------------------------------------------------------------------
# Repository summary: tenant isolation
# ---------------------------------------------------------------------------

def test_repository_summary_only_counts_own_tenant():
    repo = _fresh_repo()
    for _ in range(3):
        _run(repo.create(_make_suggestion(tenant_id="tenant_a")))
    for _ in range(2):
        _run(repo.create(_make_suggestion(tenant_id="tenant_b")))

    summary_a = _run(repo.summary("tenant_a"))
    summary_b = _run(repo.summary("tenant_b"))

    assert summary_a.total == 3
    assert summary_b.total == 2


# ---------------------------------------------------------------------------
# find_by_source_ref: tenant isolation
# ---------------------------------------------------------------------------

def test_find_by_source_ref_does_not_cross_tenants():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    suggestion.source = SuggestionSource.RECOMMENDATION_ENGINE
    suggestion.source_ref = {"service": "recommendation_engine", "id": "rec_001"}
    _run(repo.create(suggestion))

    # Attempt lookup from tenant_b
    result = _run(repo.find_by_source_ref(
        tenant_id="tenant_b",
        source="recommendation_engine",
        source_id="rec_001",
    ))
    assert result is None


def test_find_by_source_ref_succeeds_for_correct_tenant():
    repo = _fresh_repo()
    suggestion = _make_suggestion(tenant_id="tenant_a")
    suggestion.source = SuggestionSource.RECOMMENDATION_ENGINE
    suggestion.source_ref = {"service": "recommendation_engine", "id": "rec_002"}
    _run(repo.create(suggestion))

    result = _run(repo.find_by_source_ref(
        tenant_id="tenant_a",
        source="recommendation_engine",
        source_id="rec_002",
    ))
    assert result is not None
    assert result["id"] == suggestion.id
