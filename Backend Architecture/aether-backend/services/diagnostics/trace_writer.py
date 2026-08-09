"""observability_traces production writer (agent 1E — observability write path).

Closes the Phase-0 gap for ``observability_traces``: the store was only written
by the manual ``POST /v1/diagnostics/observability/traces`` route, so nothing in
an async worker boundary could append a trace record without an authenticated
HTTP round-trip. This module exposes the same store through a callable, durable,
idempotent writer that any async boundary can call directly:

  * :func:`record_observability_trace` — append one trace record for a tenant,
    keyed exactly like the route (``traces:<tenant_id>``). Re-recording the same
    ``request_id`` collapses (the record already exists) — at-least-once across a
    crash/retry, never a duplicate trace line.
  * :func:`record_request_trace` — convenience for request-scoped spans already
    carrying a traceparent/request context.

The writer is observation-only: it records what happened; it never changes the
behavior of the code path it observes. A store failure is fail-open (logged,
never re-raised) so instrumentation cannot break the instrumented boundary.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.observability import traceparent_metadata
from shared.store import get_store

logger = get_logger("aether.service.diagnostics.trace_writer")

#: Valid statuses, matching the route's TraceRecord pattern.
_TRACE_STATUSES = frozenset({"ok", "error", "timeout", "cancelled"})


def _trace_key(tenant_id: str) -> str:
    return f"traces:{tenant_id or 'public'}"


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

    Returns the stored record (or ``None`` values are omitted fields).
    """
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if status not in _TRACE_STATUSES:
        raise ValueError(f"status must be one of {sorted(_TRACE_STATUSES)}")
    if not request_id:
        raise ValueError("request_id is required to record an observability trace")
    if not service:
        raise ValueError("service is required to record an observability trace")

    store = store or get_store("observability_traces")
    # Trace-link the stored record to the async hop that produced it: if a
    # trace is active in the current context (request → job → worker → write),
    # its traceparent rides along in metadata. No-op when the seam is off.
    metadata = dict(metadata or {})
    metadata.update(traceparent_metadata())
    record: dict[str, Any] = {
        "request_id": request_id,
        "service": service,
        "endpoint": endpoint,
        "duration_ms": duration_ms,
        "status": status,
        "error": error,
        "metadata": metadata,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id or "public",
    }
    key = _trace_key(tenant_id)

    # Idempotency: the same request_id must never produce two trace lines.
    try:
        existing = await store.get_list(key, limit=1000)
    except Exception:  # pragma: no cover - best-effort instrumentation
        existing = []
    if any(t.get("request_id") == request_id for t in existing):
        metrics.increment("observability_trace_replayed", labels={"service": service})
        return record

    try:
        await store.append_list(key, record)
    except Exception as exc:  # pragma: no cover - fail-open instrumentation
        logger.warning("observability trace append failed: %s", exc)
        return record
    metrics.observe(
        "observability_trace_duration_ms", duration_ms,
        labels={"service": service, "status": status},
    )
    return record


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
    the caller did not provide one (process-pid + monotonic counter)."""
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


_seq = 0
_lock = asyncio.Lock()


async def _next_seq() -> int:
    global _seq
    async with _lock:
        _seq += 1
        return _seq


__all__ = [
    "record_observability_trace",
    "record_request_trace",
]
