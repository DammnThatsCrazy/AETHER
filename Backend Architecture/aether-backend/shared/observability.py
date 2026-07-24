"""
Aether Shared — Observability Instrumentation

Provides consistent trace propagation, structured logging, and metrics
collection across all backend services.

Usage in route handlers:
    from shared.observability import trace_request, emit_latency

    @router.post("/v1/something")
    async def handler(request: Request):
        ctx = trace_request(request)
        # ... business logic ...
        emit_latency("something_handler", ctx.elapsed_ms())
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.observability")


# =========================================================================
# Request Trace Context
# =========================================================================

@dataclass
class TraceContext:
    """Propagated context for distributed tracing."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    service: str = ""
    endpoint: str = ""
    start_time: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.start_time) * 1000

    def to_log_context(self) -> dict:
        """Fields safe to include in structured logs."""
        return {
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "service": self.service,
            "endpoint": self.endpoint,
        }


def trace_request(request, service: str = "backend") -> TraceContext:
    """Extract or create trace context from a FastAPI request."""
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID", str(uuid.uuid4()))
    )
    tenant_id = ""
    if hasattr(request.state, "tenant"):
        tenant_id = getattr(request.state.tenant, "tenant_id", "")

    return TraceContext(
        request_id=request_id,
        tenant_id=tenant_id,
        service=service,
        endpoint=request.url.path if hasattr(request, "url") else "",
    )


# =========================================================================
# Latency Histograms
# =========================================================================

# In-memory samples for local percentile computation.
# When prometheus_client is available, metrics.observe() also records
# to a Prometheus Histogram for /metrics export.
_latency_buckets: dict[str, list[float]] = {}
_MAX_SAMPLES = 1000


def emit_latency(operation: str, ms: float, labels: Optional[dict] = None) -> None:
    """Record an operation latency sample.

    Dual-writes to:
    1. Prometheus histogram (via MetricsCollector.observe) if available
    2. In-memory sample buffer for get_percentiles() API
    """
    metrics.observe(f"{operation}_latency_ms", ms, labels=labels or {})

    # Keep bounded in-memory samples for local percentile computation
    samples = _latency_buckets.setdefault(operation, [])
    samples.append(ms)
    if len(samples) > _MAX_SAMPLES:
        _latency_buckets[operation] = samples[-_MAX_SAMPLES:]


def get_percentiles(operation: str) -> dict:
    """Compute p50/p95/p99 for an operation."""
    samples = sorted(_latency_buckets.get(operation, []))
    if not samples:
        return {"p50": 0, "p95": 0, "p99": 0, "count": 0}

    n = len(samples)
    return {
        "p50": samples[int(n * 0.50)],
        "p95": samples[int(n * 0.95)] if n > 20 else samples[-1],
        "p99": samples[int(n * 0.99)] if n > 100 else samples[-1],
        "count": n,
        "mean": sum(samples) / n,
    }


# =========================================================================
# Service-Specific Counters
# =========================================================================

# GraphQL
def record_graphql_query(root_type: str, field_count: int, tenant_id: str) -> None:
    metrics.increment("graphql_queries_total", labels={"root_type": root_type})
    logger.info("graphql.query", extra={
        "root_type": root_type, "field_count": field_count, "tenant_id": tenant_id,
    })


def record_graphql_rejection(reason: str) -> None:
    metrics.increment("graphql_rejections_total", labels={"reason": reason})


# Export Jobs
def record_export_duration(format_: str, duration_ms: float, status: str) -> None:
    emit_latency("export_job", duration_ms, labels={"format": format_, "status": status})
    metrics.increment("export_jobs_total", labels={"format": format_, "status": status})


# Kafka
def record_kafka_publish(topic: str, success: bool) -> None:
    status = "success" if success else "failure"
    metrics.increment("kafka_publishes_total", labels={"topic": topic, "status": status})


# GeoIP
def record_geoip_lookup(hit: bool, fallback: bool = False) -> None:
    if hit:
        metrics.increment("geoip_lookups_hit")
    elif fallback:
        metrics.increment("geoip_lookups_fallback")
    else:
        metrics.increment("geoip_lookups_miss")


# =========================================================================
# Dashboard Metrics Summary
# =========================================================================

def metrics_summary() -> dict:
    """Generate a metrics summary for dashboards."""
    operations = list(_latency_buckets.keys())
    summary: dict = {
        "latency_percentiles": {
            op: get_percentiles(op) for op in operations
        },
    }
    # Traffic-intelligence counter family (spec §16). Lazy import keeps the
    # shared layer free of a services-layer import at module load.
    try:
        from services.traffic.metrics import traffic_metrics_summary

        summary["counters"] = traffic_metrics_summary()
    except Exception:  # pragma: no cover — dashboard must never fail hard
        pass
    return summary
