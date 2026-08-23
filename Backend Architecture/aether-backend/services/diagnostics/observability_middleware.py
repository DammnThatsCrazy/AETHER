"""Auto-record ``observability_traces`` middleware (agent 3B — observability closure).

Closes the Phase-0 gap for ``observability_traces``: the durable store was only
written by the manual ``POST /v1/diagnostics/observability/traces`` route, so a
request that never called that route left no trace record behind. This module
adds an HTTP middleware that auto-records a trace for every authenticated,
non-observability request — a real "observer in the loop" writer, the same
durable + idempotent store as :mod:`services.diagnostics.trace_writer`.

It is also a trace-propagation boundary: on request entry it continues the W3C
``traceparent`` header (or mints a fresh one) onto ``request.state.traceparent``
(main's ``shared.observability`` has no async-context traceparent setter), so
the auto-recorded trace record carries that ``traceparent`` in its metadata.

This module is the re-home target for the branch's ``trace_writer.py`` seam
(record_observability_trace / record_request_trace) and the branch's
reliability heartbeat writers (record_service_heartbeat /
record_worker_heartbeat + the WorkerSupervisor bridge): those symbols were
dropped from the port, and their canonical homes here are this module backed by
:mod:`services.diagnostics.observability_routes` (the ``observability_traces``
store + ``traces:<tenant_id>`` key) and main's
``services.reliability.service.service_registry`` respectively.

Observation-only, fail-open by construction:

  * The middleware never mutates request/response behavior.
  * A store failure is logged, never raised (instrumentation cannot break the
    instrumented boundary).
  * Public / docs / metrics / observability-trace paths are skipped, and only
    requests with an authenticated tenant are recorded — so no per-request spam
    for unauthenticated probes, and no self-recursion.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from services.diagnostics.observability_routes import _trace_key, _trace_store
from shared.logger.logger import get_logger
from shared.observability import (
    child_traceparent,
    otel_enabled,
)

logger = get_logger("aether.service.diagnostics.observability_middleware")

#: Paths that are never auto-recorded: health/docs/metrics are probe noise, and
#: the observability trace surface itself must not record its own reads/writes
#: (self-recursion would double-count every trace page view).
_SKIP_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/v1/diagnostics/observability/traces",
    "/v1/diagnostics/observability/metrics",
    "/v1/diagnostics/observability/summary",
)

#: Methods that never carry a meaningful request span (CORS preflight, etc.).
_SKIP_METHODS = frozenset({"OPTIONS", "HEAD"})


def _bind_request_traceparent(request: Request) -> None:
    """Continue the inbound W3C ``traceparent`` header onto the request state.

    A strict no-op when the seam is disabled (``otel_enabled()`` False) — the
    seam's ``child_traceparent`` returns ``None`` and we clear rather than bind.
    The bound value rides on ``request.state.traceparent`` (main has no
    async-context traceparent setter), so ``_record`` reads the SAME value.
    """
    header = request.headers.get("traceparent")
    bound = child_traceparent(header) if header else None
    request.state.traceparent = bound if otel_enabled() else None


class ObservabilityTraceMiddleware(BaseHTTPMiddleware):
    """Auto-record one ``observability_traces`` entry per observed request.

    Wire via: ``app.add_middleware(ObservabilityTraceMiddleware)`` after auth
    middleware (needs ``request.state.tenant``). Because it depends on the
    existing auth stack, mounting it in the shared middleware chain ordering is
    the integration pass's job — see the wiring notes on
    :func:`register_observability_middleware`.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        if request.method in _SKIP_METHODS or request.url.path.startswith(_SKIP_PREFIXES):
            return await call_next(request)

        tenant = getattr(request.state, "tenant", None)
        tenant_id = getattr(tenant, "tenant_id", "") if tenant is not None else ""
        if not tenant_id:
            # No authenticated tenant → nothing to key the trace record on.
            # Still bind the traceparent so downstream hops propagate it, but
            # skip the auto-record (no per-request spam for public probes).
            _bind_request_traceparent(request)
            return await call_next(request)

        _bind_request_traceparent(request)
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or f"auto:{tenant_id}:{time.perf_counter_ns()}"
        )
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — record the failure, re-raise
            self._record(
                tenant_id, request, request_id, started,
                status="error", error=f"{type(exc).__name__}: {exc}",
            )
            raise
        status_code = getattr(response, "status_code", 200)
        status = "error" if status_code >= 500 else "ok"
        self._record(tenant_id, request, request_id, started, status=status)
        return response

    def _record(
        self,
        tenant_id: str,
        request: Request,
        request_id: str,
        started: float,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        """Best-effort durable write — never raised (fail-open instrumentation)."""
        traceparent = getattr(request.state, "traceparent", None)
        metadata: dict[str, Any] = {}
        if traceparent:
            metadata["traceparent"] = traceparent
        # Fire-and-forget on the loop: a slow store must never gate the
        # response. The writer is idempotent on request_id, so a lost task at
        # shutdown merely loses one record (acceptable for a trace log). An
        # observed task failure is logged, never raised into the request.
        task = asyncio.create_task(
            self._record_async(
                tenant_id,
                request_id=request_id,
                endpoint=request.url.path,
                duration_ms=(time.perf_counter() - started) * 1000,
                status=status,
                error=error,
                metadata=metadata,
            )
        )
        task.add_done_callback(_log_record_failure)

    @staticmethod
    async def _record_async(
        tenant_id: str,
        *,
        request_id: str,
        endpoint: str,
        duration_ms: float,
        status: str,
        error: str | None,
        metadata: dict[str, Any],
    ) -> None:
        await record_observability_trace(
            tenant_id,
            request_id=request_id,
            service="backend",
            endpoint=endpoint,
            duration_ms=duration_ms,
            status=status,
            error=error,
            metadata=metadata,
        )


def _log_record_failure(task: asyncio.Task) -> None:
    """Sink for a fire-and-forget auto-record that failed (fail-open)."""
    if task.cancelled() or task.exception() is None:
        return
    logger.warning("observability_trace auto-record failed: %s", task.exception())


def register_observability_middleware(app: Any) -> None:
    """Mount the auto-record trace middleware on a FastAPI app.

    Ordering note for the integration pass: add AFTER the auth middleware (the
    dispatch needs ``request.state.tenant``), e.g. immediately after
    ``register_middleware(app)`` in ``main.py``.
    """
    app.add_middleware(ObservabilityTraceMiddleware)


# ═══════════════════════════════════════════════════════════════════════════
# observability_traces production writer (re-homed from branch trace_writer.py)
# ═══════════════════════════════════════════════════════════════════════════
# The branch's ``services/diagnostics/trace_writer.py`` is not ported; its two
# callable writers re-home here, backed by the SAME durable store the
# diagnostics route surfaces (:data:`services.diagnostics.observability_routes.
# _trace_store`) and keyed EXACTLY like the route (``traces:<tenant_id>``), so a
# record written from any async boundary is indistinguishable from one posted to
# ``POST /v1/diagnostics/observability/traces``. Fail-open: a store failure is
# logged, never re-raised, so instrumentation cannot break the observed path.

#: Valid statuses, matching the route's ``TraceRecord`` pattern.
_TRACE_STATUSES = frozenset({"ok", "error", "timeout", "cancelled"})


async def record_observability_trace(
    tenant_id: str,
    *,
    request_id: str,
    service: str,
    endpoint: str,
    duration_ms: float,
    status: str,
    error: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    timestamp: Optional[str] = None,
    store: Optional[Any] = None,
) -> dict:
    """Durably append one observability trace record (idempotent writer).

    Callable from any async boundary — a worker cycle, a background task, a
    request handler — without request/auth plumbing. ``request_id`` is the
    idempotency key: a crash/retry that re-emits the same request_id is a no-op.

    Returns the stored record.
    """
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if status not in _TRACE_STATUSES:
        raise ValueError(f"status must be one of {sorted(_TRACE_STATUSES)}")
    if not request_id:
        raise ValueError("request_id is required to record an observability trace")
    if not service:
        raise ValueError("service is required to record an observability trace")

    store = store or _trace_store
    record: dict[str, Any] = {
        "request_id": request_id,
        "service": service,
        "endpoint": endpoint,
        "duration_ms": duration_ms,
        "status": status,
        "error": error,
        "metadata": dict(metadata or {}),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id or "public",
    }
    key = _trace_key(tenant_id or "public")

    # Idempotency: the same request_id must never produce two trace lines.
    try:
        existing = await store.get_list(key, limit=1000)
    except Exception:  # pragma: no cover - best-effort instrumentation
        existing = []
    if any(t.get("request_id") == request_id for t in existing):
        return record

    try:
        await store.append_list(key, record)
    except Exception as exc:  # pragma: no cover - fail-open instrumentation
        logger.warning("observability trace append failed: %s", exc)
    return record


_seq = 0
_lock = asyncio.Lock()


async def _next_seq() -> int:
    global _seq
    async with _lock:
        _seq += 1
        return _seq


async def record_request_trace(
    tenant_id: str,
    *,
    service: str,
    endpoint: str,
    duration_ms: float,
    status: str,
    request_id: Optional[str] = None,
    error: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict:
    """Record a request-scoped trace, minting a deterministic request_id when
    the caller did not provide one (process-local monotonic counter)."""
    request_id = request_id or f"auto:{service}:{endpoint}:{await _next_seq()}"
    return await record_observability_trace(
        tenant_id,
        request_id=request_id,
        service=service,
        endpoint=endpoint,
        duration_ms=duration_ms,
        status=status,
        error=error,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Reliability heartbeat seam (re-homed from branch reliability/service.py)
# ═══════════════════════════════════════════════════════════════════════════
# The branch extended ``services.reliability.service`` with production heartbeat
# writers and a WorkerSupervisor -> registry bridge. Main's reliability service
# already owns the ``service_registry`` singleton and the
# ``ServiceHealthRegistry.heartbeat`` / ``set_status`` / ``record_successful_job``
# primitives, so the seam re-homes onto THAT registry as thin validating
# facades rather than re-porting branch code.

async def record_service_heartbeat(
    service_key: str,
    *,
    latency_ms: float | None = None,
    error_rate: float | None = None,
) -> dict[str, Any]:
    """Durably record one heartbeat for a service (production writer).

    Idempotent by nature: heartbeats are a current-state projection (the
    ``last_heartbeat_at`` is advanced in place), never an append-only trail, so
    a supervisor crash/restart that re-emits the same cycle cannot duplicate a
    row. Writes through main's ``services.reliability.service.service_registry``.
    """
    if not service_key:
        raise ValueError("service_key is required to record a heartbeat")
    from services.reliability.service import service_registry

    return await service_registry.heartbeat(
        service_key, latency_ms=latency_ms, error_rate=error_rate,
    )


async def record_worker_heartbeat(
    worker_key: str,
    *,
    latency_ms: float | None = None,
    error_rate: float | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Durably record one heartbeat for a worker process/loop (production writer).

    ``worker_key`` is a namespaced process identifier (e.g. ``worker:interop:scan``).
    The record is created on first heartbeat if the worker is not a declared
    service definition (the registry ``_update`` seeds on demand) — so the
    reliability surface observes every supervised worker, not only the statically
    declared services.
    """
    if not worker_key:
        raise ValueError("worker_key is required to record a heartbeat")
    record = await record_service_heartbeat(
        worker_key, latency_ms=latency_ms, error_rate=error_rate,
    )
    if status and status != record.get("status"):
        from services.reliability.service import service_registry

        await service_registry.set_status(worker_key, status)
        record["status"] = status
    return record


#: WorkerSupervisor.state() token → reliability ServiceHealthStatus verdict.
_SUPERVISOR_STATE_STATUS = {
    "running": "healthy",
    "restarting": "healthy",
    "failed": "critical",
    "stopped": "degraded",
    "disabled": "unknown",
}


def worker_heartbeat_key(name: str, role: str | None) -> str:
    """Namespaced reliability registry key for one supervised worker."""
    return f"worker:{role or 'unattributed'}:{name}"


async def bridge_worker_supervisor_heartbeats(
    supervisor: Any = None,
) -> dict[str, dict[str, Any]]:
    """Fold live WorkerSupervisor state into the reliability registry.

    For every supervised worker, records a heartbeat under
    ``worker:<role>:<name>`` with an honest status verdict and, when the worker
    has a recent successful cycle (``last_success_at``), advances
    ``last_successful_job_at`` on the same record. Fail-open: an unbounded
    (None) supervisor or a ``status()`` that raises is observed as silence —
    the registry rows simply do not advance — never an error, never a
    fabricated healthy.

    Returns the per-worker registry records so callers/tests can assert on them.
    """
    if supervisor is None:
        from shared.supervisor_handle import get_worker_supervisor

        supervisor = get_worker_supervisor()
    try:
        status = supervisor.status() if supervisor is not None else {}
    except Exception as exc:  # noqa: BLE001 — a broken status read is silence
        logger.warning("worker_heartbeat_bridge status() failed: %s", exc)
        return {}

    records: dict[str, dict[str, Any]] = {}
    for name, info in status.items():
        worker_key = worker_heartbeat_key(name, info.get("role"))
        state = info.get("state") or "unknown"
        verdict = _SUPERVISOR_STATE_STATUS.get(state, "unknown")
        records[worker_key] = await record_worker_heartbeat(
            worker_key, status=verdict,
        )
        if info.get("last_success_at"):
            from services.reliability.service import service_registry

            await service_registry.record_successful_job(worker_key)
    return records
