"""Aether Rate-Limit Metrics

Prometheus instrumentation for the burst limiter, feature gate, monthly
quota engine, and overage calculator.

Registration is idempotent across module reloads: tests sometimes clear
sys.modules and re-import this module, which would otherwise hit
prometheus_client's duplicate-timeseries guard. We catch the duplicate
and look up the previously-registered collector.

Falls back to a no-op shim when prometheus_client is unavailable so
importing never breaks tests.
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover — local dev without prometheus
    PROMETHEUS_AVAILABLE = False

    class _Noop:
        def labels(self, *_a: Any, **_k: Any) -> "_Noop":
            return self
        def inc(self, *_a: Any, **_k: Any) -> None: ...
        def set(self, *_a: Any, **_k: Any) -> None: ...
        def observe(self, *_a: Any, **_k: Any) -> None: ...

    _NOOP = _Noop()
    REGISTRY = None  # type: ignore[assignment]

    def _make(*_a, **_k):
        return _NOOP


def _existing(metric_name: str) -> Any:
    """Return an already-registered collector that exposes `metric_name`.

    prometheus_client keys `_names_to_collectors` by every timeseries name
    a collector exposes (e.g. `_total`, `_created` for counters). Look up
    by both the bare and the `_total` form.
    """
    collectors = getattr(REGISTRY, "_names_to_collectors", {}) or {}
    return (
        collectors.get(metric_name)
        or collectors.get(f"{metric_name}_total")
    )


def _counter(name: str, doc: str, labels: list[str]) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NOOP
    try:
        return Counter(name, doc, labels)
    except ValueError:
        existing = _existing(name)
        if existing is not None:
            return existing
        raise


def _gauge(name: str, doc: str, labels: list[str]) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NOOP
    try:
        return Gauge(name, doc, labels)
    except ValueError:
        existing = _existing(name)
        if existing is not None:
            return existing
        raise


def _histogram(name: str, doc: str, labels: list[str]) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NOOP
    try:
        return Histogram(name, doc, labels)
    except ValueError:
        existing = _existing(name)
        if existing is not None:
            return existing
        raise


# --- Burst RPM ---
BURST_TOTAL = _counter(
    "aether_burst_rpm",
    "Burst RPM checks by tenant/plan/status (allowed|rejected)",
    ["tenant_id", "plan_tier", "status"],
)
BURST_REJECTED = _counter(
    "aether_burst_rpm_rejected",
    "Burst RPM rejections by tenant/plan",
    ["tenant_id", "plan_tier"],
)

# --- Feature Gate ---
GATE_TOTAL = _counter(
    "aether_feature_gate",
    "Feature gate checks by tenant/plan/service/status (allowed|blocked)",
    ["tenant_id", "plan_tier", "service", "status"],
)
GATE_BLOCKED = _counter(
    "aether_feature_gate_blocked",
    "Feature gate blocks broken down by minimum required plan",
    ["tenant_id", "plan_tier", "service", "required_plan"],
)

# --- Monthly Quota ---
QUOTA_USED = _gauge(
    "aether_quota_used_gauge",
    "Quota used in the current billing period",
    ["tenant_id", "plan_tier"],
)
QUOTA_REMAINING = _gauge(
    "aether_quota_remaining_gauge",
    "Quota remaining in the current billing period",
    ["tenant_id", "plan_tier"],
)
QUOTA_UTILIZATION = _gauge(
    "aether_quota_utilization_ratio",
    "Quota utilization ratio (used / limit), 0.0 - 1.0+",
    ["tenant_id", "plan_tier"],
)
OVERAGE_REQUESTS = _counter(
    "aether_overage_requests",
    "Overage requests by service",
    ["tenant_id", "plan_tier", "service"],
)

# --- Overage Cost (emitted by OverageCalculator) ---
OVERAGE_COST = _counter(
    "aether_overage_cost_dollars",
    "Overage cost in USD by service and active pricing option",
    ["tenant_id", "plan_tier", "service", "pricing_option"],
)

# --- Cross-cutting ---
MIDDLEWARE_LATENCY = _histogram(
    "aether_middleware_latency_seconds",
    "Middleware layer latency (auth|burst|gate|quota)",
    ["layer", "plan_tier"],
)
REDIS_FALLBACK = _counter(
    "aether_redis_fallback",
    "Redis fallback events by enforcement layer",
    ["layer"],
)
