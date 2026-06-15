"""Unit tests for the Suggestion priority scorer."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.suggestions.models import (
    SuggestionClass,
    SuggestionPriority,
    SuggestionSource,
    SuggestionSubject,
)
from services.suggestions.scorer import (
    CLASS_FLOOR,
    REVERSIBILITY_PENALTY,
    compute_priority_score,
    compute_scores,
    map_to_priority,
)
from services.suggestions.models import SuggestionCreate


# ---------------------------------------------------------------------------
# compute_priority_score — range and value
# ---------------------------------------------------------------------------

def test_compute_priority_score_returns_float_in_range():
    score = compute_priority_score(
        impact=0.7,
        confidence=0.8,
        urgency=0.6,
        evidence_quality=0.7,
        tenant_value=0.5,
        risk=0.3,
        reversible=True,
    )
    assert 0.0 <= score <= 1.0


def test_compute_priority_score_high_inputs_yield_high_score():
    score = compute_priority_score(
        impact=1.0,
        confidence=1.0,
        urgency=1.0,
        evidence_quality=1.0,
        tenant_value=1.0,
        risk=0.0,
        reversible=True,
    )
    assert score > 0.80


def test_compute_priority_score_zero_inputs_yield_low_score():
    score = compute_priority_score(
        impact=0.0,
        confidence=0.0,
        urgency=0.0,
        evidence_quality=0.0,
        tenant_value=0.0,
        risk=0.0,
        reversible=True,
    )
    assert score == 0.0


def test_compute_priority_score_clamped_at_zero_with_high_risk():
    score = compute_priority_score(
        impact=0.0,
        confidence=0.0,
        urgency=0.0,
        evidence_quality=0.0,
        tenant_value=0.0,
        risk=1.0,
        reversible=False,
    )
    assert score == 0.0  # clamped at 0.0


# ---------------------------------------------------------------------------
# Reversibility penalty
# ---------------------------------------------------------------------------

def test_irreversible_penalized_more_than_reversible():
    score_reversible = compute_priority_score(
        impact=0.6,
        confidence=0.6,
        urgency=0.6,
        evidence_quality=0.6,
        tenant_value=0.6,
        risk=0.5,
        reversible=True,
    )
    score_irreversible = compute_priority_score(
        impact=0.6,
        confidence=0.6,
        urgency=0.6,
        evidence_quality=0.6,
        tenant_value=0.6,
        risk=0.5,
        reversible=False,
    )
    assert score_reversible > score_irreversible


def test_reversibility_penalty_values():
    assert REVERSIBILITY_PENALTY[True] < REVERSIBILITY_PENALTY[False]
    assert REVERSIBILITY_PENALTY[None] == 0.30


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_compute_priority_score_is_deterministic():
    kwargs = dict(
        impact=0.7, confidence=0.65, urgency=0.8,
        evidence_quality=0.7, tenant_value=0.5, risk=0.3, reversible=True,
    )
    first = compute_priority_score(**kwargs)
    second = compute_priority_score(**kwargs)
    assert first == second


# ---------------------------------------------------------------------------
# Class floor enforcement
# ---------------------------------------------------------------------------

def test_security_class_forced_to_minimum_p1():
    # Give it a score that would map to P3 or INFO
    score = map_to_priority(0.1, SuggestionClass.SECURITY, risk_score=None)
    order = [SuggestionPriority.P0, SuggestionPriority.P1, SuggestionPriority.P2,
             SuggestionPriority.P3, SuggestionPriority.INFO]
    assert order.index(score) <= order.index(SuggestionPriority.P1)


def test_reliability_class_forced_to_minimum_p1():
    score = map_to_priority(0.1, SuggestionClass.RELIABILITY, risk_score=None)
    order = [SuggestionPriority.P0, SuggestionPriority.P1, SuggestionPriority.P2,
             SuggestionPriority.P3, SuggestionPriority.INFO]
    assert order.index(score) <= order.index(SuggestionPriority.P1)


def test_class_floor_for_security_is_p1():
    assert CLASS_FLOOR[SuggestionClass.SECURITY] == SuggestionPriority.P1


def test_class_floor_for_reliability_is_p1():
    assert CLASS_FLOOR[SuggestionClass.RELIABILITY] == SuggestionPriority.P1


def test_high_risk_score_forces_at_least_p1():
    # Score would be P3 without the risk floor
    priority = map_to_priority(0.3, SuggestionClass.DATA_QUALITY, risk_score=0.9)
    order = [SuggestionPriority.P0, SuggestionPriority.P1, SuggestionPriority.P2,
             SuggestionPriority.P3, SuggestionPriority.INFO]
    assert order.index(priority) <= order.index(SuggestionPriority.P1)


def test_data_quality_class_no_forced_floor():
    # DATA_QUALITY has no floor — low score stays INFO
    priority = map_to_priority(0.05, SuggestionClass.DATA_QUALITY, risk_score=None)
    assert priority == SuggestionPriority.INFO


# ---------------------------------------------------------------------------
# compute_scores integration
# ---------------------------------------------------------------------------

def _make_create(**overrides) -> SuggestionCreate:
    base = {
        "tenant_id": "t1",
        "subject": SuggestionSubject(kind="entity", id="e1"),
        "source": SuggestionSource.RULE,
        "suggestion_class": SuggestionClass.DATA_QUALITY,
        "title": "Test",
        "summary": "Summary",
        "what": "What",
        "why": "Why",
        "impact": "Impact",
        "confidence_score": 0.8,
    }
    base.update(overrides)
    return SuggestionCreate(**base)


def test_compute_scores_returns_priority_score_in_range():
    create = _make_create()
    scores = compute_scores(create)
    assert 0.0 <= scores["priority_score"] <= 1.0


def test_compute_scores_includes_required_keys():
    create = _make_create()
    scores = compute_scores(create)
    for key in ["impact_score", "urgency_score", "evidence_quality_score",
                "tenant_value_score", "reversibility_score", "priority_score", "priority"]:
        assert key in scores, f"Missing key: {key}"


def test_compute_scores_returns_priority_enum():
    create = _make_create()
    scores = compute_scores(create)
    assert isinstance(scores["priority"], SuggestionPriority)
