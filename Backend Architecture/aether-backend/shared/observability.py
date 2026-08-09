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


# =========================================================================
# W3C trace-context seam (AETHER_OTEL_ENABLED)
# =========================================================================
# This is deliberately a *seam*, not an OpenTelemetry integration: it
# generates and propagates W3C `traceparent` values so job/event hops share
# a trace id, and it is a no-op (None passthrough) unless AETHER_OTEL_ENABLED
# is set. Full OTel (SDK, exporters, spans) is a declared production_status
# blocker — this seam must not be mistaken for observability coverage.

import contextvars
import os
import re
import secrets
from typing import Mapping

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def otel_enabled() -> bool:
    return os.getenv("AETHER_OTEL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def new_traceparent() -> Optional[str]:
    """A fresh W3C traceparent, or None when the seam is disabled."""
    if not otel_enabled():
        return None
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


def child_traceparent(parent: Optional[str]) -> Optional[str]:
    """Continue `parent`'s trace with a new span id; fresh trace if absent/invalid."""
    if not otel_enabled():
        return None
    if parent:
        match = _TRACEPARENT_RE.match(parent.strip().lower())
        if match:
            return f"00-{match.group(1)}-{secrets.token_hex(8)}-01"
    return new_traceparent()


def parse_traceparent(header: Optional[str]) -> Optional[tuple[str, str]]:
    """(trace_id, span_id) from a W3C traceparent header, else None."""
    if not header:
        return None
    match = _TRACEPARENT_RE.match(header.strip().lower())
    if match is None:
        return None
    return match.group(1), match.group(2)


# =========================================================================
# In-process trace-continuation seam (contextvars)
# =========================================================================
# ``current_traceparent`` is the traceparent the *current* async context is
# executing under. Async boundaries that hand work off (a job enqueue, an
# outbox row, a worker cycle) read it to continue the trace into the next hop
# instead of minting a fresh one — that is what makes request → job → worker a
# single trace. Like the rest of this seam it is a strict no-op (None
# passthrough, nothing set) when AETHER_OTEL_ENABLED is off, so instrumented
# code adds no runtime behavior until the seam is switched on.

_TRACEPARENT_PAYLOAD_KEY = "_traceparent"

_current_traceparent: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_traceparent", default=None
)


def current_traceparent() -> Optional[str]:
    """The traceparent the current async context is running under, if any."""
    return _current_traceparent.get()


def set_current_traceparent(value: Optional[str]) -> Optional[str]:
    """Bind ``value`` to the current async context (None clears it)."""
    _current_traceparent.set(value)
    return value


def continue_trace(parent: Optional[str] = None) -> Optional[str]:
    """Advance the trace into a new span and bind it to the current context.

    ``parent`` wins when given; otherwise the current context's traceparent is
    continued (or a fresh trace started when neither exists).
    """
    tp = child_traceparent(parent if parent is not None else _current_traceparent.get())
    return set_current_traceparent(tp)


def begin_async_cycle() -> Optional[str]:
    """Start (or continue) a trace for a fresh async worker cycle.

    Background loops that are not launched from a request — a supervised worker
    cycle, the heartbeat bridge, the alert evaluator sweep — call this once per
    cycle so each iteration is a child span of the previous one when a trace is
    already active, or starts a fresh trace otherwise. ``continue_trace`` with
    no parent already does this; this alias documents the async-boundary intent
    and gives the fleet of async call sites one canonical entry point.
    """
    return continue_trace()


def inject_traceparent(payload: Optional[dict]) -> Optional[str]:
    """Stamp the payload with a traceparent for the next async boundary.

    A payload that already carries a ``_traceparent`` is left intact (it is the
    trace this hop continues). Otherwise the current context's trace is
    continued and bound to this context. Returns the stamped value, or None
    when the seam is disabled (payload untouched).
    """
    if payload is None or not isinstance(payload, dict):
        return None
    existing = payload.get(_TRACEPARENT_PAYLOAD_KEY)
    if existing:
        return existing
    tp = continue_trace()
    if tp is not None:
        payload[_TRACEPARENT_PAYLOAD_KEY] = tp
    return tp


def extract_traceparent(payload: Optional[Mapping]) -> Optional[str]:
    """Resume a trace from an inbound async payload.

    Reads ``_traceparent`` off ``payload``, derives a child span for the work
    done *here*, and binds it to the current context (so subsequent
    ``inject_traceparent`` hops continue the same trace). Returns the bound
    value, or None when the seam is disabled or no parent is present.
    """
    if not payload:
        return None
    parent = payload.get(_TRACEPARENT_PAYLOAD_KEY)
    if not parent:
        return None
    return continue_trace(parent=parent)


def traceparent_metadata() -> dict[str, str]:
    """The current trace id, as metadata safe to stamp on a durable record.

    Async boundaries that write an audit/trace/log line (the observability trace
    writer, the fleet-health aggregate, a worker heartbeat bridge) call this so
    the stored record is trace-linked to the hop that produced it. Returns an
    empty dict (nothing stamped) when the seam is disabled or no trace is
    active — a strict no-op, matching the rest of the seam.
    """
    tp = _current_traceparent.get()
    if not tp:
        return {}
    return {"traceparent": tp}
