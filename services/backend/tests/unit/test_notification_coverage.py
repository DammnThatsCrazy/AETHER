"""Producer-coverage registry: honest state machine + never-falsely-healthy roll-up."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

from shared.common.common import utc_now
from services.notification_intelligence import coverage as cov
from services.notification_intelligence.coverage import (
    CoverageState,
    ProducerSpec,
    evaluate_coverage,
)
from services.notification_intelligence import routes as ni_routes


NOW = utc_now()


def _iso(seconds_ago: int) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _report(specs, emits):
    return evaluate_coverage(tuple(specs), emits, now=NOW)


def test_state_per_freshness_window():
    spec = ProducerSpec("p", "d", required=True, max_staleness_seconds=100)
    assert _report([spec], {"p": _iso(50)}).producers[0].state == CoverageState.HEALTHY
    assert _report([spec], {"p": _iso(150)}).producers[0].state == CoverageState.DEGRADED
    assert _report([spec], {"p": _iso(500)}).producers[0].state == CoverageState.STALE


def test_never_observed_is_unavailable_if_required_else_unknown():
    req = ProducerSpec("r", "d", required=True)
    opt = ProducerSpec("o", "d", required=False)
    rep = _report([req, opt], {})
    by = {c.producer_id: c.state for c in rep.producers}
    assert by["r"] == CoverageState.UNAVAILABLE
    assert by["o"] == CoverageState.UNKNOWN


def test_no_baseline_is_never_healthy():
    # No required producer declared → overall can never be 'healthy'.
    specs = [ProducerSpec("a", "d"), ProducerSpec("b", "d")]
    rep = _report(specs, {"a": _iso(1), "b": _iso(1)})
    assert rep.overall_state == CoverageState.COVERAGE_INCOMPLETE


def test_required_healthy_rolls_up_healthy():
    spec = ProducerSpec("p", "d", required=True, max_staleness_seconds=100)
    assert _report([spec], {"p": _iso(10)}).overall_state == CoverageState.HEALTHY


def test_required_unavailable_forces_coverage_incomplete():
    healthy = ProducerSpec("h", "d", required=True, max_staleness_seconds=100)
    missing = ProducerSpec("m", "d", required=True)
    rep = _report([healthy, missing], {"h": _iso(10)})
    assert rep.overall_state == CoverageState.COVERAGE_INCOMPLETE


def test_required_stale_rolls_up_stale():
    spec = ProducerSpec("p", "d", required=True, max_staleness_seconds=100)
    assert _report([spec], {"p": _iso(1000)}).overall_state == CoverageState.STALE


def test_static_state_bypasses_freshness():
    disabled = ProducerSpec("d", "d", required=True, static_state=CoverageState.DISABLED_INTENTIONALLY)
    blocked = ProducerSpec("b", "d", required=True, static_state=CoverageState.EXTERNALLY_BLOCKED)
    rep = _report([disabled, blocked], {})
    states = {c.producer_id: c.state for c in rep.producers}
    assert states["d"] == CoverageState.DISABLED_INTENTIONALLY
    assert states["b"] == CoverageState.EXTERNALLY_BLOCKED
    # A lawful non-emission does not by itself make coverage incomplete.
    assert rep.overall_state == CoverageState.HEALTHY


def test_unregistered_observed_surfaced():
    rep = _report([ProducerSpec("known", "d")], {"known": _iso(1), "mystery": _iso(1)})
    assert "mystery" in rep.unregistered_observed


def test_heartbeat_roundtrip_and_registry_report():
    cov.reset_heartbeats()
    try:
        assert cov.heartbeat_snapshot() == {}
        cov.record_producer_emit("identity")
        cov.record_producer_emit("")  # empty → no-op
        snap = cov.heartbeat_snapshot()
        assert "identity" in snap and "" not in snap
        report = cov.build_coverage_report()
        # identity is a registered producer → observed healthy; overall is never
        # 'healthy' because the seeded registry declares no required producer.
        ident = next(c for c in report.producers if c.producer_id == "identity")
        assert ident.state == CoverageState.HEALTHY
        assert report.overall_state == CoverageState.COVERAGE_INCOMPLETE
    finally:
        cov.reset_heartbeats()


def test_coverage_endpoint_returns_report():
    cov.reset_heartbeats()
    try:
        req = SimpleNamespace(state=SimpleNamespace(tenant=SimpleNamespace(
            require_permission=lambda p: None)))
        out = asyncio.run(ni_routes.producer_coverage(req))
        assert out["data"]["overall_state"] == "coverage_incomplete"
        assert isinstance(out["data"]["producers"], list)
    finally:
        cov.reset_heartbeats()
