"""AETHER model-runtime observability & operational controls (ADR-008 D8).

Public API for the observability subpackage: metrics, health, readiness,
circuit breaking, canaries, plus operational runbooks and incident
classification.

Sibling modules (metrics/health/readiness/circuit_breaker/canary) are owned by
Agents A-E and land in this same commit. They are imported guardedly so the
package loads cleanly during concurrent development and self-heals once each
sibling lands; before a sibling lands its names are bound to ``None``. Once all
siblings have landed these imports are equivalent to plain imports and could be
simplified to them with no behavior change.
"""

from services.model_runtime.observability.runbooks import (
    IncidentClassifier,
    Runbook,
    RunbookCatalog,
    recommend,
)

try:  # Agent A — observability/metrics.py
    from services.model_runtime.observability.metrics import (
        MetricNames,
        NullMetricsRecorder,
        RuntimeMetricsRecorder,
    )
except ImportError:  # pragma: no cover - not landed yet
    MetricNames = None
    RuntimeMetricsRecorder = None
    NullMetricsRecorder = None

try:  # Agent B — observability/health.py
    from services.model_runtime.observability.health import (
        ProviderHealth,
        ProviderHealthCheck,
        RuntimeHealth,
        RuntimeHealthProbe,
    )
except ImportError:  # pragma: no cover - not landed yet
    ProviderHealth = None
    RuntimeHealth = None
    ProviderHealthCheck = None
    RuntimeHealthProbe = None

try:  # Agent C — observability/readiness.py
    from services.model_runtime.observability.readiness import (
        FailClosed,
        ReadinessState,
        RuntimeReadiness,
    )
except ImportError:  # pragma: no cover - not landed yet
    ReadinessState = None
    RuntimeReadiness = None
    FailClosed = None

try:  # Agent D — observability/circuit_breaker.py
    from services.model_runtime.observability.circuit_breaker import (
        CircuitBreaker,
        CircuitRegistry,
        CircuitState,
    )
except ImportError:  # pragma: no cover - not landed yet
    CircuitState = None
    CircuitBreaker = None
    CircuitRegistry = None

try:  # Agent E — observability/canary.py
    from services.model_runtime.observability.canary import (
        CanaryMetrics,
        CanaryPolicy,
        CanarySelector,
        CanaryTracker,
    )
except ImportError:  # pragma: no cover - not landed yet
    CanaryPolicy = None
    CanarySelector = None
    CanaryTracker = None
    CanaryMetrics = None

__all__ = [
    # observability/metrics.py — Agent A
    "MetricNames",
    "RuntimeMetricsRecorder",
    "NullMetricsRecorder",
    # observability/health.py — Agent B
    "ProviderHealth",
    "RuntimeHealth",
    "ProviderHealthCheck",
    "RuntimeHealthProbe",
    # observability/readiness.py — Agent C
    "ReadinessState",
    "RuntimeReadiness",
    "FailClosed",
    # observability/circuit_breaker.py — Agent D
    "CircuitState",
    "CircuitBreaker",
    "CircuitRegistry",
    # observability/canary.py — Agent E
    "CanaryPolicy",
    "CanarySelector",
    "CanaryTracker",
    "CanaryMetrics",
    # observability/runbooks.py — Agent F (this package)
    "Runbook",
    "RunbookCatalog",
    "IncidentClassifier",
    "recommend",
]
