"""Auto-record ``observability_traces`` middleware (agent 3B — observability closure).

Closes the Phase-0 gap for ``observability_traces``: the durable store was only
written by the manual ``POST /v1/diagnostics/observability/traces`` route, so a
request that never called that route left no trace record behind. This module
adds an HTTP middleware that auto-records a trace for every authenticated,
non-observability request — a real "observer in the loop" writer, the same
durable + idempotent store as :mod:`services.diagnostics.trace_writer`.

It is also a trace-propagation boundary: on request entry it continues the W3C
``traceparent`` header (or mints a fresh one) into the current async context via
``shared.observability.continue_trace``, so every downstream hop that calls
:func:`shared.observability.inject_traceparent` continues the SAME trace; the
auto-recorded trace record then carries that ``traceparent`` in its metadata.

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
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from shared.logger.logger import get_logger
from shared.observability import (
    child_traceparent,
    current_traceparent,
    otel_enabled,
    set_current_traceparent,
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
    """Continue the inbound W3C ``traceparent`` header into the async context.

    A strict no-op when the seam is disabled (``otel_enabled()`` False) — the
    seam's ``child_traceparent`` returns ``None`` and we clear rather than bind.
    """
    header = request.headers.get("traceparent")
    bound = child_traceparent(header) if header else None
    if otel_enabled():
        set_current_traceparent(bound)


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
        traceparent = current_traceparent()
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
        from services.diagnostics.trace_writer import record_observability_trace

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
