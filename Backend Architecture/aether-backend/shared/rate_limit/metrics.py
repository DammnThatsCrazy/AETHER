"""Aether Rate-Limit Metrics

Prometheus instrumentation for the burst limiter, feature gate, monthly
quota engine, and overage calculator. Falls back to a no-op shim when
prometheus_client is unavailable so importing never breaks tests.
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover — local dev without prometheus
    PROMETHEUS_AVAILABLE = False

    class _Noop:
        def labels(self, *_a: Any, **_k: Any) -> "_Noop":
            return self
        def inc(self, *_a: Any, **_k: Any) -> None: ...
        def set(self, *_a: Any, **_k: Any) -> None: ...
        def observe(self, *_a: Any, **_k: Any) -> None: ...

    def Counter(*_a, **_k):  # type: ignore[no-redef]
        return _Noop()
    def Gauge(*_a, **_k):  # type: ignore[no-redef]
        return _Noop()
    def Histogram(*_a, **_k):  # type: ignore[no-redef]
        return _Noop()


# --- Burst RPM ---
BURST_TOTAL = Counter(
    "aether_burst_rpm_total",
    "Burst RPM checks by tenant/plan/status (allowed|rejected)",
    ["tenant_id", "plan_tier", "status"],
)
BURST_REJECTED = Counter(
    "aether_burst_rpm_rejected_total",
    "Burst RPM rejections by tenant/plan",
    ["tenant_id", "plan_tier"],
)

# --- Feature Gate ---
GATE_TOTAL = Counter(
    "aether_feature_gate_total",
    "Feature gate checks by tenant/plan/service/status (allowed|blocked)",
    ["tenant_id", "plan_tier", "service", "status"],
)
GATE_BLOCKED = Counter(
    "aether_feature_gate_blocked_total",
    "Feature gate blocks broken down by minimum required plan",
    ["tenant_id", "plan_tier", "service", "required_plan"],
)

# --- Monthly Quota ---
QUOTA_USED = Gauge(
    "aether_quota_used_gauge",
    "Quota used in the current billing period",
    ["tenant_id", "plan_tier"],
)
QUOTA_REMAINING = Gauge(
    "aether_quota_remaining_gauge",
    "Quota remaining in the current billing period",
    ["tenant_id", "plan_tier"],
)
QUOTA_UTILIZATION = Gauge(
    "aether_quota_utilization_ratio",
    "Quota utilization ratio (used / limit), 0.0 - 1.0+",
    ["tenant_id", "plan_tier"],
)
OVERAGE_REQUESTS = Counter(
    "aether_overage_requests_total",
    "Overage requests by service",
    ["tenant_id", "plan_tier", "service"],
)

# --- Overage Cost (emitted by OverageCalculator) ---
OVERAGE_COST = Counter(
    "aether_overage_cost_dollars",
    "Overage cost in USD by service and active pricing option",
    ["tenant_id", "plan_tier", "service", "pricing_option"],
)

# --- Cross-cutting ---
MIDDLEWARE_LATENCY = Histogram(
    "aether_middleware_latency_seconds",
    "Middleware layer latency (auth|burst|gate|quota)",
    ["layer", "plan_tier"],
)
REDIS_FALLBACK = Counter(
    "aether_redis_fallback_total",
    "Redis fallback events by enforcement layer",
    ["layer"],
)
