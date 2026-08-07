"""Fraud score *semantics* regressions (Section 16).

These lock in three properties of the fraud scoring surface:

1. The handcrafted 0-1 "confidence" and the 0-100 signal scores are labeled as
   UNCALIBRATED heuristics — they must never be silently treated as calibrated
   probabilities of fraud.
2. Structurally-correlated / duplicate signals are damped, not naively
   additively double-counted (shared IP + shared device + shared wallet all
   co-occur for a single household / NAT / device farm; duplicate hits of the
   same signal type collapse).
3. The signal-weight scheme is versioned and that version is carried on the
   persisted decision, so any stored score is traceable to its formula.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.fraud.evaluation import (
    SIGNAL_WEIGHTS_VERSION,
    FraudEvaluationService,
    compute_signal_risk_score,
)
from services.fraud.signals import SignalResult
from services.fraud_networks.scoring import (
    CONFIDENCE_WEIGHTS_VERSION,
    UncalibratedConfidence,
    score_confidence,
)

# Legacy naive weight: each distinct signal type independently added 10 points.
_NAIVE_PER_SIGNAL = 10.0


# ── 1. Uncalibrated labeling ─────────────────────────────────────────────────

def test_score_confidence_is_labeled_uncalibrated_not_probability():
    """score_confidence must advertise that it is NOT a calibrated probability."""
    conf = score_confidence(
        evidence_count=10,
        signal_overlap=3,
        member_count=5,
        has_circular_transfer=True,
        has_shared_device=True,
    )
    # Still a float for all existing numeric consumers (routes.py stores it).
    assert isinstance(conf, float)
    assert 0.0 <= conf <= 1.0

    # ...but explicitly annotated as an uncalibrated heuristic.
    assert isinstance(conf, UncalibratedConfidence)
    assert conf.calibrated is False
    assert conf.kind == "uncalibrated_heuristic"
    assert conf.score_kind == "uncalibrated_heuristic"
    assert conf.weights_version == CONFIDENCE_WEIGHTS_VERSION

    # The docstring must warn it is not a probability of fraud.
    doc = (score_confidence.__doc__ or "").lower()
    assert "not" in doc and "calibrated" in doc
    assert "probability" in doc


def test_signal_result_score_is_labeled_uncalibrated():
    """Handcrafted 0-100 signal scores are heuristics, not probabilities."""
    result = SignalResult(name="bot_detection", score=75.0, weight=0.2)
    assert result.calibrated is False
    assert result.score_kind == "uncalibrated_heuristic"


# ── 2. Correlated / duplicate signals must not linearly double-count ──────────

def test_duplicate_signal_hits_do_not_stack():
    """50 shared-IP hits are one structural fact — they must not add 50x weight."""
    one_hit = compute_signal_risk_score(["shared_ip"])
    fifty_hits = compute_signal_risk_score(["shared_ip"] * 50)
    assert fifty_hits == one_hit  # duplicates collapse, no hit-count inflation


def test_correlated_signal_family_is_damped_not_linear():
    """shared IP + device + wallet co-occur structurally: damp, don't sum fully."""
    single = compute_signal_risk_score(["shared_ip"])
    trio = compute_signal_risk_score(["shared_ip", "shared_device", "shared_wallet"])

    naive_trio = 3 * _NAIVE_PER_SIGNAL  # what the old len(signals)*10 produced
    # Correlated siblings add *something* (still more suspicious than one)...
    assert trio > single
    # ...but strictly less than the naive additive sum — no double-counting.
    assert trio < naive_trio


def test_independent_signal_families_still_add_fully():
    """Genuinely independent evidence must still accumulate at full weight."""
    combined = compute_signal_risk_score(["shared_ip", "reward_farming"])
    # Two different families => two full base contributions, no damping.
    assert combined == pytest.approx(2 * _NAIVE_PER_SIGNAL)


def test_layering_family_damped_but_circular_bonus_preserved():
    """circular_transfer + split_merge are one topology; circular keeps its bonus."""
    both = compute_signal_risk_score(["circular_transfer", "split_merge"])
    # base 10 + damped sibling (< 10) + circular bonus 25, and still < the naive
    # (10 + 10 + 25 = 45) additive value.
    assert both < 45.0
    assert both > 25.0  # circular bonus is retained


# ── 3. Weight scheme is versioned and persisted ──────────────────────────────

def test_signal_weights_version_is_present_and_stringy():
    assert isinstance(SIGNAL_WEIGHTS_VERSION, str)
    assert SIGNAL_WEIGHTS_VERSION  # non-empty


def _service_with_empty_repos() -> FraudEvaluationService:
    """A service whose repositories all return empty result sets (no signals)."""
    svc = FraudEvaluationService.__new__(FraudEvaluationService)
    empty = AsyncMock(return_value=[])
    for attr, methods in {
        "_sessions": ("list_for_entities",),
        "_wallets": ("find_many",),
        "_transfers": ("find_many",),
        "_delegations": ("find_many",),
        "_rewards": ("list_for_entities",),
        "_orders": ("list_for_entities",),
        "_refunds": ("list_for_entities",),
    }.items():
        mock = AsyncMock()
        for m in methods:
            setattr(mock, m, empty)
        setattr(svc, attr, mock)
    svc._decisions = AsyncMock()
    svc._decisions.get_current_for_subject = AsyncMock(return_value=None)
    svc._decisions.create = AsyncMock(return_value={})
    svc._decisions.supersede = AsyncMock(return_value={})
    return svc


@pytest.mark.asyncio
async def test_persisted_decision_carries_signal_weights_version():
    """A successfully evaluated decision records which weight scheme produced it."""
    svc = _service_with_empty_repos()
    decision = await svc.evaluate_subject(
        tenant_id="t-sem",
        subject_type="entity",
        subject_id="e-sem",
        entity_id="e-sem",
        force=True,
    )
    assert decision.evaluation_state == "evaluated"
    assert decision.metadata.get("signal_weights_version") == SIGNAL_WEIGHTS_VERSION
    assert decision.metadata.get("risk_score_kind") == "uncalibrated_heuristic"
    assert decision.model_versions.get("signal_weights") == SIGNAL_WEIGHTS_VERSION
