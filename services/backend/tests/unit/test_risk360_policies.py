"""Risk360 Phase-5 risk-policy registry tests (policies.py).

Verifies the registry style (frozen rows + lookup that raises listing ids), the
positive-weights/unregistered-dimension guards, and the honest aggregation rule:
an unobserved dimension contributes NOTHING to the aggregate (never a coerced
zero that drags a risk score toward ALLOW), and an all-missing vector fails
closed to the policy default instead of inventing a number.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.risk360.contracts import (  # noqa: E402
    EpistemicStatus,
    RiskComponent,
    RiskVector,
    ValueState,
)
from services.risk360.policies import (  # noqa: E402
    DEFAULT_POLICY_ID,
    RiskPolicy,
    policy,
    weighted_aggregate_score,
)
from shared.computation.policies import DecisionPolicy, DecisionThreshold, PolicyOutcome  # noqa: E402


def _make_policy(weights=None):
    thresholds = (
        DecisionThreshold(upper=0.25, outcome=PolicyOutcome.ALLOW),
        DecisionThreshold(lower=0.25, upper=0.65, outcome=PolicyOutcome.REVIEW),
        DecisionThreshold(lower=0.65, outcome=PolicyOutcome.BLOCK),
    )
    decision = DecisionPolicy(
        policy_id="test.risk",
        policy_version="1",
        display_name="test",
        thresholds=list(thresholds),
        default_outcome=PolicyOutcome.REVIEW,
        owner="risk",
        fail_closed=True,
    )
    return RiskPolicy(
        policy_id="test.risk",
        policy_version="1",
        display_name="test policy",
        dimension_weights=weights or {"identity": 2.0, "fraud": 2.0},
        policy=decision,
    )


def _component(dimension, score=None, state=None):
    state = state or (ValueState.ESTIMATED if score is not None else ValueState.MISSING_INPUTS)
    return RiskComponent(
        dimension=dimension,
        state=state,
        score=score,
        claim_state=EpistemicStatus.DERIVED if score is not None else EpistemicStatus.UNKNOWN,
    )


def test_seeded_registry_and_lookup_failure_lists_ids():
    row = policy(DEFAULT_POLICY_ID)
    assert row.policy_id == DEFAULT_POLICY_ID
    with pytest.raises(KeyError, match="risk360.standard"):
        policy("risk360.nope")


def test_nonpositive_and_unregistered_weights_are_rejected():
    with pytest.raises(ValueError, match="positive"):
        _make_policy(weights={"identity": 0.0})
    with pytest.raises(ValueError, match="unregistered"):
        _make_policy(weights={"identity": 2.0, "not_a_dim": 1.0})


def test_aggregate_ignores_missing_dimensions():
    vector = RiskVector(
        components=[_component("identity", score=0.8), _component("fraud")]
    )
    # only identity contributes (2.0 weight) — fraud is missing, never a 0
    aggregate = _make_policy().aggregate_score(vector)
    assert aggregate == pytest.approx(0.8)


def test_all_missing_vector_aggregates_to_none_and_fails_closed():
    row = _make_policy()
    vector = RiskVector(components=[_component("identity")])
    aggregate, outcome = row.decide(vector)
    assert aggregate is None
    assert outcome == PolicyOutcome.REVIEW  # fail-closed default, no invented number


def test_weighted_aggregate_over_only_scored_dimensions():
    scores = {"identity": 0.5, "fraud": 1.0}
    weights = {"identity": 1.0, "fraud": 3.0}
    # fraud (weight 3) dominates; the missing third dimension plays no part
    assert weighted_aggregate_score(weights, scores) == pytest.approx(0.875)


def test_weighted_aggregate_no_scored_dimensions_returns_none():
    assert weighted_aggregate_score({"identity": 2.0}, {}) is None
