"""Unit tests for Suggestion Intelligence models (Pydantic validation)."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from pydantic import ValidationError

from services.suggestions.models import (
    Suggestion,
    SuggestionClass,
    SuggestionCreate,
    SuggestionPriority,
    SuggestionSource,
    SuggestionStatus,
    SuggestionSubject,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_create(**overrides) -> dict:
    base = {
        "tenant_id": "tenant_abc",
        "subject": {"kind": "entity", "id": "ent_1"},
        "source": SuggestionSource.RULE.value,
        "suggestion_class": SuggestionClass.DATA_QUALITY.value,
        "title": "Test Suggestion",
        "summary": "A test summary",
        "what": "What is happening",
        "why": "Why it matters",
        "impact": "Impact description",
        "confidence_score": 0.8,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SuggestionStatus enum
# ---------------------------------------------------------------------------

def test_suggestion_status_has_15_values():
    values = [s.value for s in SuggestionStatus]
    assert len(values) == 15, f"Expected 15 statuses, got {len(values)}: {values}"


def test_suggestion_status_contains_expected_values():
    expected = {
        "detected", "oriented", "suggested", "review_required",
        "approved", "rejected", "suppressed", "executing", "executed",
        "delivered", "measured", "learned", "closed", "expired", "failed",
    }
    actual = {s.value for s in SuggestionStatus}
    assert actual == expected


# ---------------------------------------------------------------------------
# SuggestionClass enum
# ---------------------------------------------------------------------------

def test_suggestion_class_has_17_values():
    values = [c.value for c in SuggestionClass]
    assert len(values) == 17, f"Expected 17 classes, got {len(values)}: {values}"


def test_suggestion_class_contains_expected_values():
    expected = {
        "customer_success", "data_quality", "sdk_health", "sdk_drift",
        "identity", "graph_health", "profile360", "campaign", "retargeting",
        "revenue", "reliability", "security", "governance", "agent_operations",
        "notification", "investigation", "general_intelligence",
    }
    actual = {c.value for c in SuggestionClass}
    assert actual == expected


# ---------------------------------------------------------------------------
# SuggestionPriority enum
# ---------------------------------------------------------------------------

def test_suggestion_priority_has_p0_p1_p2_p3_info():
    values = {p.value for p in SuggestionPriority}
    assert values == {"P0", "P1", "P2", "P3", "info"}


# ---------------------------------------------------------------------------
# SuggestionCreate validation
# ---------------------------------------------------------------------------

def test_suggestion_create_accepts_valid_payload():
    create = SuggestionCreate.model_validate(_minimal_create())
    assert create.tenant_id == "tenant_abc"
    assert create.confidence_score == 0.8


def test_suggestion_create_rejects_title_over_200_chars():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(title="x" * 201))


def test_suggestion_create_accepts_title_at_200_chars():
    create = SuggestionCreate.model_validate(_minimal_create(title="x" * 200))
    assert len(create.title) == 200


def test_suggestion_create_rejects_summary_over_500_chars():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(summary="y" * 501))


def test_suggestion_create_rejects_confidence_below_zero():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(confidence_score=-0.1))


def test_suggestion_create_rejects_confidence_above_one():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(confidence_score=1.1))


def test_suggestion_create_accepts_boundary_confidence_scores():
    low = SuggestionCreate.model_validate(_minimal_create(confidence_score=0.0))
    high = SuggestionCreate.model_validate(_minimal_create(confidence_score=1.0))
    assert low.confidence_score == 0.0
    assert high.confidence_score == 1.0


# ---------------------------------------------------------------------------
# Suggestion score fields clamped to [0.0, 1.0]
# ---------------------------------------------------------------------------

def test_suggestion_impact_score_clamped():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(impact_score=1.5))


def test_suggestion_urgency_score_clamped():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(urgency_score=-0.1))


def test_suggestion_risk_score_clamped():
    with pytest.raises(ValidationError):
        SuggestionCreate.model_validate(_minimal_create(risk_score=2.0))


# ---------------------------------------------------------------------------
# SuggestionSubject
# ---------------------------------------------------------------------------

def test_suggestion_subject_requires_kind_and_id():
    with pytest.raises(ValidationError):
        SuggestionSubject.model_validate({"kind": "entity"})


def test_suggestion_subject_accepts_valid_kinds():
    for kind in ["entity", "tenant", "organization", "graph", "profile",
                 "journey", "campaign", "sdk", "provider", "agent",
                 "alert", "investigation", "system"]:
        sub = SuggestionSubject.model_validate({"kind": kind, "id": "test_id"})
        assert sub.kind == kind
