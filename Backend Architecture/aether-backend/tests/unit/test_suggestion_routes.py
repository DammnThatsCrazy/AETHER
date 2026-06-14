"""Smoke tests for Suggestion Intelligence FastAPI routes."""

from __future__ import annotations

import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.suggestions.models import (
    SuggestionClass,
    SuggestionPriority,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSummary,
)
from services.suggestions.routes import router


# ---------------------------------------------------------------------------
# App fixture — attach the suggestion router with a test middleware that
# injects a synthetic tenant context into request.state
# ---------------------------------------------------------------------------

def _make_record(
    suggestion_id: str = None,
    tenant_id: str = "tenant_abc",
    status: str = "review_required",
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
        "summary": "Summary",
        "what": "What",
        "why": "Why",
        "impact": "Impact",
        "confidence_score": 0.8,
        "requires_approval": False,
        "execution_eligible": False,
        "delivery_eligible": True,
        "audit_trail": [],
        "created_at": now,
        "updated_at": now,
    }


def _make_app(tenant_id: str = "tenant_abc") -> FastAPI:
    """Build a minimal FastAPI app with the suggestion router and stub auth."""
    app = FastAPI()

    @app.middleware("http")
    async def inject_tenant(request, call_next):
        tenant = MagicMock()
        tenant.tenant_id = tenant_id
        tenant.user_id = "user_test"
        tenant.require_permission = MagicMock()
        request.state.tenant = tenant
        return await call_next(request)

    app.include_router(router)
    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


@pytest.fixture
def suggestion_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GET /v1/suggestions — list
# ---------------------------------------------------------------------------

def test_list_suggestions_returns_200(client):
    mock_svc = MagicMock()
    mock_svc.query_suggestions = AsyncMock(return_value=([], 0))

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions")
    assert response.status_code == 200


def test_list_suggestions_response_has_data_key(client):
    mock_svc = MagicMock()
    mock_svc.query_suggestions = AsyncMock(return_value=([], 0))

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions")
    body = response.json()
    assert "data" in body


def test_list_suggestions_meta_includes_total(client):
    record = _make_record()
    mock_svc = MagicMock()
    mock_svc.query_suggestions = AsyncMock(return_value=([record], 1))

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions")
    body = response.json()
    assert body.get("meta", {}).get("total") == 1


# ---------------------------------------------------------------------------
# GET /v1/suggestions/{id} — fetch single
# ---------------------------------------------------------------------------

def test_get_suggestion_returns_404_for_unknown_id(client):
    from shared.common.common import NotFoundError
    mock_svc = MagicMock()
    mock_svc.get_suggestion = AsyncMock(side_effect=NotFoundError("not found"))

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions/unknown_id")
    assert response.status_code == 404


def test_get_suggestion_returns_200_for_known_id(client, suggestion_id):
    record = _make_record(suggestion_id=suggestion_id)
    mock_svc = MagicMock()
    mock_svc.get_suggestion = AsyncMock(return_value=record)

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get(f"/v1/suggestions/{suggestion_id}")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == suggestion_id


# ---------------------------------------------------------------------------
# POST /v1/suggestions/{id}/approve
# ---------------------------------------------------------------------------

def test_approve_suggestion_returns_200(client, suggestion_id):
    record = _make_record(suggestion_id=suggestion_id, status="approved")
    mock_svc = MagicMock()
    mock_svc.approve_suggestion = AsyncMock(return_value=record)

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"actor_id": "user_1"},
        )
    assert response.status_code == 200


def test_approve_suggestion_returns_data_with_status(client, suggestion_id):
    record = _make_record(suggestion_id=suggestion_id, status="approved")
    mock_svc = MagicMock()
    mock_svc.approve_suggestion = AsyncMock(return_value=record)

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"actor_id": "user_1"},
        )
    body = response.json()
    assert body["data"]["status"] == "approved"


# ---------------------------------------------------------------------------
# POST /v1/suggestions/{id}/reject
# ---------------------------------------------------------------------------

def test_reject_suggestion_returns_200(client, suggestion_id):
    record = _make_record(suggestion_id=suggestion_id, status="rejected")
    mock_svc = MagicMock()
    mock_svc.reject_suggestion = AsyncMock(return_value=record)

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.post(
            f"/v1/suggestions/{suggestion_id}/reject",
            json={"reason": "Not applicable"},
        )
    assert response.status_code == 200


def test_reject_suggestion_without_reason_returns_422(client, suggestion_id):
    with patch("services.suggestions.routes._get_service", return_value=MagicMock()):
        response = client.post(
            f"/v1/suggestions/{suggestion_id}/reject",
            json={},  # missing required 'reason' field
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/suggestions/summary
# ---------------------------------------------------------------------------

def test_get_summary_returns_200(client):
    summary = SuggestionSummary(
        total=5, open=3, review_required=1, approved=0,
        executed=0, failed=0, closed=1,
        by_class={"data_quality": 5},
        by_priority={"P3": 5},
        by_status={"detected": 3},
    )
    mock_svc = MagicMock()
    mock_svc.summarize = AsyncMock(return_value=summary)

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions/summary")
    assert response.status_code == 200


def test_get_summary_response_has_total(client):
    summary = SuggestionSummary(
        total=7, open=4, review_required=2, approved=1,
        executed=0, failed=0, closed=0,
        by_class={}, by_priority={}, by_status={},
    )
    mock_svc = MagicMock()
    mock_svc.summarize = AsyncMock(return_value=summary)

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions/summary")
    body = response.json()
    assert body["data"]["total"] == 7


# ---------------------------------------------------------------------------
# GET /v1/suggestions/review-queue
# ---------------------------------------------------------------------------

def test_get_review_queue_returns_200(client):
    mock_svc = MagicMock()
    mock_svc.review_queue = AsyncMock(return_value=[])

    with patch("services.suggestions.routes._get_service", return_value=mock_svc):
        response = client.get("/v1/suggestions/review-queue")
    assert response.status_code == 200
