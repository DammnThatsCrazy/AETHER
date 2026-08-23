"""Tests for model-runtime observability metrics (ADR-008 D8).

Uses a fake dict/record-based backend that captures ``(name, value, labels)``
increments. Plain asserts only — no pytest helpers, no external metrics
backend, no secrets in labels.
"""

from __future__ import annotations

from services.model_runtime.observability.metrics import (
    MetricNames,
    NullMetricsRecorder,
    RuntimeMetricsRecorder,
)


class FakeMetricsBackend:
    """Records (name, value, labels) increment calls for assertions."""

    def __init__(self) -> None:
        self.calls: list = []

    def increment(self, name, value=1, labels=None) -> None:
        self.calls.append((name, value, labels or {}))


def _calls_named(backend, name):
    """Return every recorded call matching ``name`` (list of tuples)."""
    return [call for call in backend.calls if call[0] == name]


def _labels_of(backend, name):
    """Return the labels dict of every recorded call matching ``name``."""
    return [call[2] for call in _calls_named(backend, name)]


def _raises_value_error(fn):
    """True when ``fn`` raises ValueError (plain-assert substitute)."""
    try:
        fn()
    except ValueError:
        return True
    return False


# ---------------------------------------------------------------------------
# Canonical metric names
# ---------------------------------------------------------------------------


def test_metric_names_are_canonical_strings():
    assert MetricNames.CALLS == "model_runtime_calls"
    assert MetricNames.TOKENS_INPUT == "model_runtime_tokens_input"
    assert MetricNames.TOKENS_OUTPUT == "model_runtime_tokens_output"
    assert MetricNames.LATENCY_MS == "model_runtime_latency_ms"
    assert MetricNames.COST_USD == "model_runtime_cost_usd"
    assert MetricNames.PROVIDER_ERRORS == "model_runtime_provider_errors"
    assert MetricNames.VERIFICATION_FAILURES == "model_runtime_verification_failures"
    assert MetricNames.VERIFICATION_PASSES == "model_runtime_verification_passes"
    assert MetricNames.CIRCUIT_OPEN == "model_runtime_circuit_open"
    assert MetricNames.CIRCUIT_CLOSED == "model_runtime_circuit_closed"
    assert MetricNames.ROUTES == "model_runtime_routes"
    assert MetricNames.BUDGET_EXCEEDED == "model_runtime_budget_exceeded"
    assert MetricNames.CREDENTIAL_REJECTIONS == "model_runtime_credential_rejections"


def test_metric_names_are_unique():
    values = [
        MetricNames.CALLS,
        MetricNames.TOKENS_INPUT,
        MetricNames.TOKENS_OUTPUT,
        MetricNames.LATENCY_MS,
        MetricNames.COST_USD,
        MetricNames.PROVIDER_ERRORS,
        MetricNames.VERIFICATION_FAILURES,
        MetricNames.VERIFICATION_PASSES,
        MetricNames.CIRCUIT_OPEN,
        MetricNames.CIRCUIT_CLOSED,
        MetricNames.ROUTES,
        MetricNames.BUDGET_EXCEEDED,
        MetricNames.CREDENTIAL_REJECTIONS,
    ]
    assert len(set(values)) == len(values)


# ---------------------------------------------------------------------------
# RuntimeMetricsRecorder — per-method name + labels
# ---------------------------------------------------------------------------


def test_record_call_emits_calls_with_labels():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_call("anthropic", "claude-sonnet-4-5", status="success")
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.CALLS
    assert value == 1
    assert labels == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "status": "success",
    }


def test_record_call_other_status_is_labeled():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_call("openai", "gpt-4o", status="error")
    assert _labels_of(backend, MetricNames.CALLS) == [
        {"provider": "openai", "model": "gpt-4o", "status": "error"}
    ]


def test_record_tokens_emits_input_and_output_counters():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_tokens("anthropic", 120, 80)
    assert len(backend.calls) == 2

    input_calls = _calls_named(backend, MetricNames.TOKENS_INPUT)
    output_calls = _calls_named(backend, MetricNames.TOKENS_OUTPUT)
    assert len(input_calls) == 1
    assert len(output_calls) == 1
    assert input_calls[0][1] == 120
    assert input_calls[0][2] == {"provider": "anthropic"}
    assert output_calls[0][1] == 80
    assert output_calls[0][2] == {"provider": "anthropic"}


def test_record_tokens_zero_is_accepted():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_tokens("anthropic", 0, 0)
    assert len(backend.calls) == 2


def test_record_latency_emits_latency_ms():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_latency("anthropic", 123.5)
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.LATENCY_MS
    assert value == 123.5
    assert labels == {"provider": "anthropic"}


def test_record_cost_rounds_to_6_decimals():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_cost("anthropic", 0.123456789)
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.COST_USD
    assert value == round(0.123456789, 6)
    assert labels == {"provider": "anthropic"}


def test_record_provider_error_emits_error_metric():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_provider_error("anthropic", "rate_limit")
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.PROVIDER_ERRORS
    assert labels == {"provider": "anthropic", "error_type": "rate_limit"}


def test_record_verification_passed_and_failed():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_verification(True)
    rec.record_verification(False)
    assert [call[0] for call in backend.calls] == [
        MetricNames.VERIFICATION_PASSES,
        MetricNames.VERIFICATION_FAILURES,
    ]
    assert _labels_of(backend, MetricNames.VERIFICATION_PASSES) == [{}]
    assert _labels_of(backend, MetricNames.VERIFICATION_FAILURES) == [{}]


def test_record_circuit_open_and_closed():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_circuit(True)
    rec.record_circuit(False)
    assert [call[0] for call in backend.calls] == [
        MetricNames.CIRCUIT_OPEN,
        MetricNames.CIRCUIT_CLOSED,
    ]


def test_record_route_emits_mode_entitled_fallback_labels():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_route("strict", entitled=True, fallback=False)
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.ROUTES
    assert labels == {
        "mode": "strict",
        "entitled": "True",
        "fallback": "False",
    }


def test_record_route_handles_fallback_true_and_unset_mode():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_route("balanced", entitled=False, fallback=True)
    assert _labels_of(backend, MetricNames.ROUTES) == [
        {"mode": "balanced", "entitled": "False", "fallback": "True"}
    ]


def test_record_budget_exceeded_emits_metric():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_budget_exceeded("openai")
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.BUDGET_EXCEEDED
    assert labels == {"provider": "openai"}


def test_record_credential_rejection_emits_metric():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_credential_rejection("openai")
    assert len(backend.calls) == 1
    name, value, labels = backend.calls[0]
    assert name == MetricNames.CREDENTIAL_REJECTIONS
    assert labels == {"provider": "openai"}


# ---------------------------------------------------------------------------
# Non-negative guards
# ---------------------------------------------------------------------------


def test_negative_tokens_and_cost_raise_value_error():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    assert _raises_value_error(lambda: rec.record_tokens("anthropic", -1, 10))
    assert _raises_value_error(lambda: rec.record_tokens("anthropic", 10, -1))
    assert _raises_value_error(lambda: rec.record_cost("anthropic", -0.01))
    # Rejected values must not be recorded.
    assert backend.calls == []


def test_negative_latency_raises_value_error():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    assert _raises_value_error(lambda: rec.record_latency("anthropic", -1.0))
    assert backend.calls == []


# ---------------------------------------------------------------------------
# NullMetricsRecorder
# ---------------------------------------------------------------------------


def test_null_recorder_never_raises_and_records_nothing():
    fake = FakeMetricsBackend()
    null = NullMetricsRecorder(metrics_backend=fake)
    null.record_call("anthropic", "claude-sonnet-4-5", status="success")
    null.record_tokens("anthropic", -1, 5)  # negative input: still no raise
    null.record_latency("anthropic", -1.0)  # negative input: still no raise
    null.record_cost("anthropic", -0.5)  # negative input: still no raise
    null.record_provider_error("anthropic", "rate_limit")
    null.record_verification(True)
    null.record_verification(False)
    null.record_circuit(True)
    null.record_circuit(False)
    null.record_route("strict", entitled=True, fallback=False)
    null.record_budget_exceeded("openai")
    null.record_credential_rejection("openai")
    null.increment("anything", 1, {"provider": "x"})
    assert fake.calls == []


def test_null_recorder_surface_matches_runtime_recorder():
    null = NullMetricsRecorder()
    for method in (
        "record_call",
        "record_tokens",
        "record_latency",
        "record_cost",
        "record_provider_error",
        "record_verification",
        "record_circuit",
        "record_route",
        "record_budget_exceeded",
        "record_credential_rejection",
    ):
        assert callable(getattr(null, method))


# ---------------------------------------------------------------------------
# Default backend (lazy shared metrics helper) and secret-free labels
# ---------------------------------------------------------------------------


def test_default_backend_resolves_and_records_without_raising():
    rec = RuntimeMetricsRecorder()  # no backend -> shared metrics / NullRecorder
    rec.record_call("anthropic", "claude-sonnet-4-5", status="success")
    rec.record_tokens("anthropic", 10, 20)
    rec.record_cost("anthropic", 0.001)
    # Must not raise regardless of which backend resolved.


def test_labels_contain_no_secrets():
    backend = FakeMetricsBackend()
    rec = RuntimeMetricsRecorder(metrics_backend=backend)
    rec.record_call("anthropic", "claude-sonnet-4-5", status="success")
    rec.record_tokens("anthropic", 10, 20)
    rec.record_latency("anthropic", 50.0)
    rec.record_cost("anthropic", 0.001)
    rec.record_provider_error("anthropic", "rate_limit")
    rec.record_verification(True)
    rec.record_circuit(False)
    rec.record_route("strict", entitled=True, fallback=False)
    rec.record_budget_exceeded("openai")
    rec.record_credential_rejection("openai")

    assert backend.calls, "expected metrics to be recorded"
    secret_markers = ("sk-", "AKIA", "Bearer")
    for _name, _value, labels in backend.calls:
        for label_key, label_value in labels.items():
            assert label_key in {"provider", "model", "status", "mode", "entitled", "fallback", "error_type"}
            for marker in secret_markers:
                assert marker not in str(label_value)
