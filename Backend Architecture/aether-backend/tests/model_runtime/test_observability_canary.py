"""Tests for deterministic canary routing and promotion tracking.

Covers ADR-008 D8 canary policy validation, deterministic (hash-based)
selector behavior, per-candidate outcome accumulation, and the promotion
gating thresholds. Runs under the ``-n 0`` (no xdist workers) test gate.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.model_runtime.observability.canary import (
    CanaryMetrics,
    CanaryPolicy,
    CanarySelector,
    CanaryTracker,
)


def _policy(**overrides):
    base = {
        "candidate_model": "claude-haiku-4-5-20251001",
        "candidate_provider": "anthropic",
    }
    base.update(overrides)
    return CanaryPolicy(**base)


# ---------------------------------------------------------------------------
# CanaryPolicy validation
# ---------------------------------------------------------------------------


def test_policy_accepts_valid_fraction():
    policy = _policy(traffic_fraction=0.05)
    assert policy.traffic_fraction == 0.05


def test_policy_rejects_zero_fraction():
    with pytest.raises(ValidationError):
        _policy(traffic_fraction=0.0)


def test_policy_rejects_negative_fraction():
    with pytest.raises(ValidationError):
        _policy(traffic_fraction=-0.1)


def test_policy_rejects_fraction_over_one():
    with pytest.raises(ValidationError):
        _policy(traffic_fraction=1.5)


def test_policy_defaults():
    policy = CanaryPolicy(candidate_model="m", candidate_provider="p")
    assert policy.traffic_fraction == 0.05
    assert policy.min_samples == 20
    assert policy.max_latency_ms is None
    assert policy.max_error_rate == 0.05
    assert policy.promote_after_samples == 100


# ---------------------------------------------------------------------------
# CanarySelector determinism
# ---------------------------------------------------------------------------


def test_selector_deterministic_for_same_inputs():
    selector = CanarySelector(_policy(traffic_fraction=0.05))
    assert selector.select("tenant-a", "trace-1") == selector.select("tenant-a", "trace-1")
    assert selector.select("tenant-b", "trace-2") == selector.select("tenant-b", "trace-2")


def test_selector_deterministic_across_instances():
    policy = _policy(traffic_fraction=0.2)
    first = CanarySelector(policy, seed="fixed-seed")
    second = CanarySelector(policy, seed="fixed-seed")
    for tenant, trace in (("t1", "r1"), ("t2", "r2"), ("t3", "r3"), ("t4", "r4")):
        assert first.select(tenant, trace) == second.select(tenant, trace)


def test_selector_varies_across_tenants():
    # A moderate fraction must split a population, not route everyone the same way.
    selector = CanarySelector(_policy(traffic_fraction=0.5))
    selected = {
        selector.select(f"tenant-{i}", "trace-x") for i in range(32)
    }
    assert True in selected
    assert False in selected


def test_selector_varies_across_traces():
    selector = CanarySelector(_policy(traffic_fraction=0.5))
    selected = {
        selector.select("tenant-x", f"trace-{i}") for i in range(32)
    }
    assert True in selected
    assert False in selected


def test_selector_seed_changes_selection():
    policy = _policy(traffic_fraction=0.5)
    seed_a = CanarySelector(policy, seed="seed-a")
    seed_b = CanarySelector(policy, seed="seed-b")
    pattern_a = tuple(seed_a.select(f"tenant-{i}", "trace") for i in range(32))
    pattern_b = tuple(seed_b.select(f"tenant-{i}", "trace") for i in range(32))
    assert pattern_a != pattern_b


def test_selector_fraction_zero_always_false():
    # construct() bypasses pydantic validation so the defensive guard can be
    # exercised directly; CanaryPolicy itself rejects traffic_fraction == 0.
    policy = CanaryPolicy.construct(
        candidate_model="m", candidate_provider="p", traffic_fraction=0.0
    )
    selector = CanarySelector(policy)
    assert selector.select("tenant", "trace") is False
    assert selector.select("other", "trace") is False
    assert selector.select("tenant", "other") is False


def test_selector_fraction_one_always_true():
    selector = CanarySelector(_policy(traffic_fraction=1.0))
    assert selector.select("tenant", "trace") is True
    assert selector.select("other", "x") is True


# ---------------------------------------------------------------------------
# CanaryTracker accumulation
# ---------------------------------------------------------------------------


def test_tracker_accumulates_metrics_correctly():
    tracker = CanaryTracker(_policy())
    candidate = tracker.candidate
    for _ in range(40):
        tracker.record(candidate, latency_ms=10.0, ok=True, verified=True)
    for _ in range(10):
        tracker.record(candidate, latency_ms=20.0, ok=False, verified=False)

    metrics = tracker.metrics()
    assert metrics.candidate == "claude-haiku-4-5-20251001@anthropic"
    assert metrics.samples == 50
    assert metrics.ok_count == 40
    assert metrics.error_rate == 0.2
    assert metrics.avg_latency_ms == 12.0  # (40 * 10 + 10 * 20) / 50
    assert metrics.verify_pass_rate == 0.8
    assert isinstance(metrics, CanaryMetrics)


def test_tracker_metrics_empty_before_any_records():
    tracker = CanaryTracker(_policy())
    metrics = tracker.metrics()
    assert metrics.candidate == "claude-haiku-4-5-20251001@anthropic"
    assert metrics.samples == 0
    assert metrics.ok_count == 0
    assert metrics.error_rate == 0.0
    assert metrics.avg_latency_ms == 0.0
    assert metrics.verify_pass_rate == 0.0
    assert metrics.promote is False


def test_tracker_accumulates_per_candidate():
    tracker = CanaryTracker(_policy())
    tracker.record("cand-a", latency_ms=1.0, ok=True, verified=True)
    tracker.record("cand-b", latency_ms=2.0, ok=False, verified=False)
    metric_a = tracker.metrics("cand-a")
    metric_b = tracker.metrics("cand-b")
    assert metric_a.samples == 1
    assert metric_a.ok_count == 1
    assert metric_a.error_rate == 0.0
    assert metric_a.verify_pass_rate == 1.0
    assert metric_b.samples == 1
    assert metric_b.ok_count == 0
    assert metric_b.error_rate == 1.0
    assert metric_b.verify_pass_rate == 0.0


# ---------------------------------------------------------------------------
# Promotion gating
# ---------------------------------------------------------------------------


def test_promote_true_when_all_thresholds_met():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(10):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    metrics = tracker.metrics()
    assert metrics.samples == 10
    assert metrics.error_rate == 0.0
    assert metrics.avg_latency_ms == 30.0
    assert metrics.verify_pass_rate == 1.0
    assert metrics.promote is True


def test_promote_false_when_samples_too_few():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(9):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    assert tracker.metrics().promote is False


def test_promote_false_when_error_rate_high():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(9):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    tracker.record(tracker.candidate, latency_ms=30.0, ok=False, verified=False)
    metrics = tracker.metrics()
    assert metrics.samples == 10
    assert metrics.error_rate == 0.1  # > 0.05
    assert metrics.promote is False


def test_promote_false_when_latency_high():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(10):
        tracker.record(tracker.candidate, latency_ms=60.0, ok=True, verified=True)
    metrics = tracker.metrics()
    assert metrics.samples == 10
    assert metrics.avg_latency_ms == 60.0  # > 50.0
    assert metrics.promote is False


def test_promote_false_when_verify_low():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(8):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    for _ in range(2):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=False)
    metrics = tracker.metrics()
    assert metrics.samples == 10
    assert metrics.error_rate == 0.0
    assert metrics.verify_pass_rate == 0.8  # < 0.9
    assert metrics.promote is False


def test_promote_boundary_verify_rate_exactly_nine_tenths():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(9):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=False)
    metrics = tracker.metrics()
    assert metrics.verify_pass_rate == 0.9  # >= 0.9 is sufficient
    assert metrics.promote is True


def test_promote_boundary_error_rate_equal_to_max():
    policy = _policy(promote_after_samples=10, max_error_rate=0.1, max_latency_ms=50.0)
    tracker = CanaryTracker(policy)
    for _ in range(9):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    tracker.record(tracker.candidate, latency_ms=30.0, ok=False, verified=False)
    metrics = tracker.metrics()
    assert metrics.error_rate == 0.1  # <= 0.1 is sufficient
    assert metrics.promote is True


def test_promote_boundary_latency_equal_to_max():
    policy = _policy(promote_after_samples=10, max_error_rate=0.05, max_latency_ms=30.0)
    tracker = CanaryTracker(policy)
    for _ in range(10):
        tracker.record(tracker.candidate, latency_ms=30.0, ok=True, verified=True)
    metrics = tracker.metrics()
    assert metrics.avg_latency_ms == 30.0  # <= max_latency_ms is sufficient
    assert metrics.promote is True


def test_promote_ignores_latency_when_no_limit():
    policy = _policy(promote_after_samples=5, max_error_rate=0.05, max_latency_ms=None)
    tracker = CanaryTracker(policy)
    for _ in range(5):
        tracker.record(tracker.candidate, latency_ms=9999.0, ok=True, verified=True)
    assert tracker.metrics().promote is True
