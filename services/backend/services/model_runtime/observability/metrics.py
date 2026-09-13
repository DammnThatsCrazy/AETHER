"""ADR-008 D8 observability — canonical metric names and runtime recorder.

The harness ships counters for model-runtime calls, tokens, latency, cost,
provider errors, verification outcomes, circuit-breaker state, routing
decisions, budget overruns, and credential rejections. Staging/production fail
closed: recording is best-effort, never raises for backend failures, and never
exposes request content, tenant data, or credentials.

Metric labels are restricted to non-sensitive identifiers (provider, model,
mode, status, error_type, booleans). Provider request bodies, tenant data, and
secrets never appear in metric names or labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class MetricNames:
    """Canonical metric name strings emitted by the model-runtime harness.

    Every recorder method increments one of these exact names; consumers and
    dashboards key off these strings. Frozen so the canonical values can never
    be mutated at runtime.
    """

    CALLS: ClassVar[str] = "model_runtime_calls"
    TOKENS_INPUT: ClassVar[str] = "model_runtime_tokens_input"
    TOKENS_OUTPUT: ClassVar[str] = "model_runtime_tokens_output"
    LATENCY_MS: ClassVar[str] = "model_runtime_latency_ms"
    COST_USD: ClassVar[str] = "model_runtime_cost_usd"
    PROVIDER_ERRORS: ClassVar[str] = "model_runtime_provider_errors"
    VERIFICATION_FAILURES: ClassVar[str] = "model_runtime_verification_failures"
    VERIFICATION_PASSES: ClassVar[str] = "model_runtime_verification_passes"
    CIRCUIT_OPEN: ClassVar[str] = "model_runtime_circuit_open"
    CIRCUIT_CLOSED: ClassVar[str] = "model_runtime_circuit_closed"
    ROUTES: ClassVar[str] = "model_runtime_routes"
    BUDGET_EXCEEDED: ClassVar[str] = "model_runtime_budget_exceeded"
    CREDENTIAL_REJECTIONS: ClassVar[str] = "model_runtime_credential_rejections"


class RuntimeMetricsRecorder:
    """Records harness metrics through a backend with the ``increment`` surface.

    Defaults to the shared ``metrics`` helper from ``shared.logger.logger``,
    imported lazily so this module stays importable in every environment. When
    the shared backend cannot be loaded the recorder falls back to a no-op
    :class:`NullMetricsRecorder` so metrics never break the hot path.

    All increments are labels-safe and secret-free: labels carry only
    provider/model/mode/status/error_type/boolean identifiers. Recorded values
    are non-negative; negative token/cost (and latency) inputs raise
    ``ValueError``.
    """

    def __init__(self, metrics_backend=None) -> None:
        """Bind a backend; ``None`` resolves the shared ``metrics`` helper."""
        if metrics_backend is not None:
            self._backend = metrics_backend
        else:
            self._backend = self._default_backend()

    @staticmethod
    def _default_backend():
        """Lazily load the shared metrics helper; fall back to a no-op."""
        try:
            from shared.logger.logger import metrics
        except Exception:  # pragma: no cover - backend absent (disabled paths)
            return NullMetricsRecorder()
        return metrics

    def record_call(self, provider: str, model: str, *, status: str) -> None:
        """Count one model-runtime call."""
        self._backend.increment(
            MetricNames.CALLS,
            labels={"provider": provider, "model": model, "status": status},
        )

    def record_tokens(
        self, provider: str, input_tokens: int, output_tokens: int
    ) -> None:
        """Accumulate input/output token counters (negative values rejected)."""
        self._require_non_negative(input_tokens, name="input_tokens")
        self._require_non_negative(output_tokens, name="output_tokens")
        self._backend.increment(
            MetricNames.TOKENS_INPUT,
            value=input_tokens,
            labels={"provider": provider},
        )
        self._backend.increment(
            MetricNames.TOKENS_OUTPUT,
            value=output_tokens,
            labels={"provider": provider},
        )

    def record_latency(self, provider: str, latency_ms: float) -> None:
        """Accumulate the latency counter in milliseconds."""
        self._require_non_negative(latency_ms, name="latency_ms")
        self._backend.increment(
            MetricNames.LATENCY_MS,
            value=latency_ms,
            labels={"provider": provider},
        )

    def record_cost(self, provider: str, cost_usd: float) -> None:
        """Accumulate cost in USD, rounded to 6 decimals (negative rejected)."""
        self._require_non_negative(cost_usd, name="cost_usd")
        self._backend.increment(
            MetricNames.COST_USD,
            value=round(cost_usd, 6),
            labels={"provider": provider},
        )

    def record_provider_error(self, provider: str, error_type: str) -> None:
        """Count a provider-side error."""
        self._backend.increment(
            MetricNames.PROVIDER_ERRORS,
            labels={"provider": provider, "error_type": error_type},
        )

    def record_verification(self, passed: bool) -> None:
        """Count a verification pass or failure."""
        if passed:
            self._backend.increment(MetricNames.VERIFICATION_PASSES)
        else:
            self._backend.increment(MetricNames.VERIFICATION_FAILURES)

    def record_circuit(self, open: bool) -> None:
        """Record circuit-breaker state transitions (open/closed)."""
        if open:
            self._backend.increment(MetricNames.CIRCUIT_OPEN)
        else:
            self._backend.increment(MetricNames.CIRCUIT_CLOSED)

    def record_route(self, mode: str, *, entitled: bool, fallback: bool) -> None:
        """Count a routing decision with mode/entitlement/fallback labels."""
        self._backend.increment(
            MetricNames.ROUTES,
            labels={
                "mode": str(mode),
                "entitled": str(bool(entitled)),
                "fallback": str(bool(fallback)),
            },
        )

    def record_budget_exceeded(self, provider: str) -> None:
        """Count a per-tenant budget rejection."""
        self._backend.increment(
            MetricNames.BUDGET_EXCEEDED, labels={"provider": provider}
        )

    def record_credential_rejection(self, provider: str) -> None:
        """Count a credential rejection for a provider."""
        self._backend.increment(
            MetricNames.CREDENTIAL_REJECTIONS, labels={"provider": provider}
        )

    @staticmethod
    def _require_non_negative(value, *, name: str) -> None:
        """Reject negative recorded values (tokens/cost/latency)."""
        if value < 0:
            raise ValueError(f"{name} must be non-negative, got {value!r}")


class NullMetricsRecorder:
    """No-op recorder: the same surface as :class:`RuntimeMetricsRecorder`.

    Used for tests and disabled paths. Never raises and records nothing, even
    when handed negative values or an invalid backend. Serves as the default
    backend when the shared metrics helper is unavailable.
    """

    def __init__(self, metrics_backend=None) -> None:
        # A backend may be supplied for drop-in construction; it is ignored.
        self._backend = metrics_backend

    def increment(self, name: str, value=1, labels=None) -> None:
        """No-op increment (matches the shared ``metrics`` helper surface)."""
        return None

    def record_call(self, provider: str, model: str, *, status: str) -> None:
        """No-op."""
        return None

    def record_tokens(
        self, provider: str, input_tokens: int, output_tokens: int
    ) -> None:
        """No-op."""
        return None

    def record_latency(self, provider: str, latency_ms: float) -> None:
        """No-op."""
        return None

    def record_cost(self, provider: str, cost_usd: float) -> None:
        """No-op."""
        return None

    def record_provider_error(self, provider: str, error_type: str) -> None:
        """No-op."""
        return None

    def record_verification(self, passed: bool) -> None:
        """No-op."""
        return None

    def record_circuit(self, open: bool) -> None:
        """No-op."""
        return None

    def record_route(self, mode: str, *, entitled: bool, fallback: bool) -> None:
        """No-op."""
        return None

    def record_budget_exceeded(self, provider: str) -> None:
        """No-op."""
        return None

    def record_credential_rejection(self, provider: str) -> None:
        """No-op."""
        return None


__all__ = [
    "MetricNames",
    "NullMetricsRecorder",
    "RuntimeMetricsRecorder",
]
