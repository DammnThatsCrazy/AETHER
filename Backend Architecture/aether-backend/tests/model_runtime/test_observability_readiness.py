"""Commit 12-C: model-runtime readiness (deployment-gate projection).

Synchronous tests (``-n 0``), plain asserts only, well under the 300 ms
budget. Covers the ADR-008 D8/D9 semantics: config and unhealthy runtime
always fail closed; degraded stays ready with warn blockers; credential
absence is always reported and fails readiness only while the FailClosed gate
is enabled (D9 default OFF).
"""

from __future__ import annotations

from services.model_runtime.observability.readiness import (
    FailClosed,
    ReadinessState,
    RuntimeReadiness,
    describe,
)


class _StubHealth:
    """Fake RuntimeHealthProbe-like: a report object with status/providers/checks."""

    def __init__(self, status="ok", providers=(), checks=None):
        self.status = status
        self.providers = providers
        self.checks = checks if checks is not None else {}


# ── core gating ──────────────────────────────────────────────────────────────


def test_ok_and_config_ok_is_ready():
    state = RuntimeReadiness(_StubHealth(status="ok")).evaluate()
    assert state.ready is True
    assert state.blockers == ()
    assert state.checks["config"] is True
    assert state.checks["health"] is True
    assert state.checks["credentials"] is True


def test_unhealthy_is_not_ready_with_blocker():
    state = RuntimeReadiness(_StubHealth(status="unhealthy")).evaluate()
    assert state.ready is False
    assert "runtime unhealthy" in state.blockers
    assert state.checks["health"] is False


def test_degraded_is_ready_with_warn_blockers():
    health = _StubHealth(status="degraded", providers=["anthropic", "openai"])
    state = RuntimeReadiness(health).evaluate()
    assert state.ready is True
    assert state.checks["health"] is True
    assert "provider degraded: anthropic" in state.blockers
    assert "provider degraded: openai" in state.blockers


def test_degraded_dict_providers_only_marks_degraded():
    health = _StubHealth(
        status="degraded",
        providers={"anthropic": "ok", "openai": "degraded", "bedrock": "unhealthy"},
    )
    state = RuntimeReadiness(health).evaluate()
    assert state.ready is True
    assert "provider degraded: openai" in state.blockers
    assert "provider degraded: anthropic" not in state.blockers
    assert "provider degraded: bedrock" not in state.blockers


def test_config_not_ok_fail_closed():
    state = RuntimeReadiness(_StubHealth(status="ok"), config_ok=False).evaluate()
    assert state.ready is False
    assert "config not ok" in state.blockers
    assert state.checks["config"] is False


def test_config_not_ok_fail_closed_regardless_of_gate():
    # Configuration is never credential-gated: fail-closed even with the
    # FailClosed gate enabled and healthy credentials.
    state = RuntimeReadiness(
        _StubHealth(status="ok"),
        config_ok=False,
        credential_health=lambda: True,
        fail_closed=FailClosed(enabled=True),
    ).evaluate()
    assert state.ready is False
    assert "config not ok" in state.blockers


def test_unhealthy_fails_closed_even_with_gate_disabled():
    # Runtime health is never gated either: an unhealthy runtime blocks even
    # when the FailClosed credential gate is OFF.
    state = RuntimeReadiness(_StubHealth(status="unhealthy")).evaluate()
    assert state.ready is False


# ── credentials + FailClosed (D8/D9) ────────────────────────────────────────


def test_fail_closed_enabled_credential_false_not_ready():
    state = RuntimeReadiness(
        _StubHealth(status="ok"),
        credential_health=lambda: False,
        fail_closed=FailClosed(enabled=True),
    ).evaluate()
    assert state.ready is False
    assert "credential health failed" in state.blockers
    assert state.checks["credentials"] is False


def test_fail_closed_disabled_credential_false_reports_blocker_but_ready():
    state = RuntimeReadiness(
        _StubHealth(status="ok"),
        credential_health=lambda: False,
        fail_closed=FailClosed(),  # D9 default OFF
    ).evaluate()
    assert state.ready is True
    assert "credential health failed" in state.blockers
    assert state.checks["credentials"] is False


def test_default_gate_is_disabled():
    assert FailClosed().enabled is False
    assert FailClosed(enabled=True).enabled is True
    assert bool(FailClosed()) is False
    assert bool(FailClosed(enabled=True)) is True
    # RuntimeReadiness defaults to a disabled gate: credential absence is
    # reported but does not block traffic.
    state = RuntimeReadiness(
        _StubHealth(status="ok"), credential_health=lambda: False
    ).evaluate()
    assert state.ready is True
    assert "credential health failed" in state.blockers


def test_credential_health_true_is_ready_even_when_gate_enabled():
    state = RuntimeReadiness(
        _StubHealth(status="ok"),
        credential_health=lambda: True,
        fail_closed=FailClosed(enabled=True),
    ).evaluate()
    assert state.ready is True
    assert "credential health failed" not in state.blockers


def test_credential_health_exception_reported_and_gated():
    def boom():
        raise RuntimeError("resolver unavailable")

    state = RuntimeReadiness(
        _StubHealth(status="ok"),
        credential_health=boom,
        fail_closed=FailClosed(enabled=True),
    ).evaluate()
    assert state.ready is False
    assert "credential health failed" in state.blockers


# ── probe resolution (defensive interop with Commit 12-B) ───────────────────


def test_probe_method_form_resolves():
    class Probe:
        def __init__(self, status):
            self._status = status

        def check(self):
            return _StubHealth(status=self._status)

    assert RuntimeReadiness(Probe("ok")).is_ready() is True
    assert RuntimeReadiness(Probe("unhealthy")).is_ready() is False


def test_callable_probe_resolves():
    assert RuntimeReadiness(lambda: _StubHealth(status="ok")).is_ready() is True
    assert RuntimeReadiness(lambda: _StubHealth(status="unhealthy")).is_ready() is False


def test_missing_health_status_fails_closed():
    class Bare:
        pass

    state = RuntimeReadiness(Bare()).evaluate()
    assert state.ready is False
    assert "runtime unhealthy" in state.blockers


def test_async_probe_fails_closed_in_sync_gate():
    class AsyncProbe:
        async def check(self):
            return _StubHealth(status="ok")

    state = RuntimeReadiness(AsyncProbe()).evaluate()
    assert state.ready is False
    assert "runtime unhealthy" in state.blockers


# ── describe (audit-safe) ────────────────────────────────────────────────────


def test_describe_is_audit_safe():
    ready_state = ReadinessState(ready=True, blockers=(), checks={"config": True})
    desc = describe(ready_state)
    assert "ready=True" in desc
    assert "0" in desc  # blocker count
    assert "none" in desc  # first blocker placeholder

    unhealthy = ReadinessState(
        ready=False, blockers=("runtime unhealthy", "config not ok"), checks={}
    )
    desc2 = describe(unhealthy)
    assert "ready=False" in desc2
    assert "2" in desc2  # blocker count
    assert "runtime unhealthy" in desc2  # first blocker

    # Blocker reasons are terse/internal; never echo key material.
    assert "sk-" not in desc2
    assert "AKIA" not in desc2


# ── state shape / misc ───────────────────────────────────────────────────────


def test_is_ready_convenience():
    assert RuntimeReadiness(_StubHealth(status="ok")).is_ready() is True
    assert RuntimeReadiness(_StubHealth(status="unhealthy")).is_ready() is False
    assert RuntimeReadiness(_StubHealth(status="ok"), config_ok=False).is_ready() is False


def test_readiness_state_is_frozen():
    state = ReadinessState(ready=True, blockers=(), checks={})
    try:
        state.ready = False
    except Exception:
        pass
    else:
        raise AssertionError("ReadinessState should be frozen")
    assert state.ready is True


def test_checks_snapshot_normalizes_health_checks():
    health = _StubHealth(
        status="ok",
        checks={
            "database": {"status": "ok"},
            "migrations": "skipped",
            "workers": {"status": "failed"},
            "cache": True,
        },
    )
    state = RuntimeReadiness(health).evaluate()
    assert state.checks["database"] is True
    assert state.checks["migrations"] is True
    assert state.checks["workers"] is False
    assert state.checks["cache"] is True


def test_real_probe_false_required_extra_check_fails_readiness():
    # Commit 12-B interop: a real RuntimeHealthProbe whose required extra check
    # (e.g. database/migrations) is false must yield an aggregate status that
    # the readiness gate fails closed on — not ready even with providers
    # configured.
    from services.model_runtime.observability.health import (
        ProviderHealthCheck,
        RuntimeHealthProbe,
    )

    class _Provider:
        def __init__(self, name, configured):
            self.provider_name = name
            self._configured = configured

        def is_configured(self):
            return self._configured

    probe = RuntimeHealthProbe(
        ProviderHealthCheck({"anthropic": _Provider("anthropic", True)}),
        extra_checks={"runtime.database": False},
    )
    state = RuntimeReadiness(probe).evaluate()
    assert state.ready is False
    assert "runtime unhealthy" in state.blockers
    assert state.checks["health"] is False
    assert state.checks["runtime.database"] is False
