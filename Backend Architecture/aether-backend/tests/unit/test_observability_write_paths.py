"""Observability write-path tests (agent 1E): the observability_traces
auto-record writer and the production reliability heartbeat writer.

Under test:

  * ``record_observability_trace`` appends a trace record to the same
    ``observability_traces`` store the diagnostics route surfaces, keyed exactly
    like the route (``traces:<tenant_id>``), and is IDEMPOTENT on ``request_id`` —
    a crash/retry that re-emits the same request collapses instead of
    duplicating (the crash-boundary guarantee for the trace writer).
  * Validation: a negative duration and an unknown status are rejected loudly.
  * ``record_service_heartbeat`` / ``record_worker_heartbeat`` write reliability
    records through the module-level ``service_registry`` singleton — idempotent
    current-state projection (a re-emitted heartbeat advances ``last_heartbeat_at``
    in place, never a second row).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.diagnostics.observability_middleware import (
    ObservabilityTraceMiddleware,
    record_observability_trace,
    record_request_trace,
    record_service_heartbeat,
    record_worker_heartbeat,
)
from services.reliability.service import service_registry
from shared.store import get_store


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    store = get_store("observability_traces")
    if hasattr(store, "_lists"):
        store._lists.clear()
    yield


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# observability_traces auto-record writer
# ═══════════════════════════════════════════════════════════════════════════

async def test_record_trace_appends_to_observability_traces_store():
    store = get_store("observability_traces")
    await record_observability_trace(
        "t-obs",
        request_id="req-1",
        service="interop-scan",
        endpoint="scan_cycle",
        duration_ms=12.5,
        status="ok",
        metadata={"provider": "wormhole"},
    )
    traces = await store.get_list("traces:t-obs")
    assert len(traces) == 1
    row = traces[0]
    assert row["request_id"] == "req-1"
    assert row["service"] == "interop-scan"
    assert row["endpoint"] == "scan_cycle"
    assert row["duration_ms"] == 12.5
    assert row["status"] == "ok"
    assert row["tenant_id"] == "t-obs"
    assert row["metadata"]["provider"] == "wormhole"


async def test_record_trace_is_idempotent_on_request_id():
    store = get_store("observability_traces")
    await record_observability_trace(
        "t-obs", request_id="req-dup", service="svc", endpoint="e",
        duration_ms=1.0, status="ok",
    )
    # Crash -> restart -> resume: the same request re-recorded must not duplicate.
    await record_observability_trace(
        "t-obs", request_id="req-dup", service="svc", endpoint="e",
        duration_ms=1.0, status="ok",
    )
    traces = await store.get_list("traces:t-obs")
    assert len(traces) == 1


async def test_record_trace_rejects_negative_duration():
    with pytest.raises(ValueError):
        await record_observability_trace(
            "t-obs", request_id="req-bad", service="svc", endpoint="e",
            duration_ms=-1.0, status="ok",
        )


async def test_record_trace_rejects_unknown_status():
    with pytest.raises(ValueError):
        await record_observability_trace(
            "t-obs", request_id="req-bad", service="svc", endpoint="e",
            duration_ms=1.0, status="exploded",
        )


async def test_record_request_trace_mints_request_id():
    store = get_store("observability_traces")
    await record_request_trace(
        "t-obs", service="kyber", endpoint="price_tick", duration_ms=3.0, status="ok",
    )
    await record_request_trace(
        "t-obs", service="kyber", endpoint="price_tick", duration_ms=3.0, status="ok",
    )
    traces = await store.get_list("traces:t-obs")
    assert len(traces) == 2
    # Distinct auto request_ids (both survive; only an identical request_id dedups).
    assert traces[0]["request_id"] != traces[1]["request_id"]


# ═══════════════════════════════════════════════════════════════════════════
# reliability heartbeat writers
# ═══════════════════════════════════════════════════════════════════════════

async def test_record_service_heartbeat_writes_reliability_record():
    rec = await record_service_heartbeat(
        "interop-scan-worker", latency_ms=45.0, error_rate=0.01,
    )
    assert rec["service_key"] == "interop-scan-worker"
    assert rec["last_heartbeat_at"] is not None
    assert rec["latency_ms"] == 45.0

    rows = await service_registry.list()
    matching = [r for r in rows if r.get("service_key") == "interop-scan-worker"]
    assert len(matching) == 1  # current-state projection: exactly one row


async def test_record_service_heartbeat_is_current_state_not_append_only():
    await record_service_heartbeat("svc-a", latency_ms=10.0)
    await record_service_heartbeat("svc-a", latency_ms=20.0)
    rows = await service_registry.list()
    matching = [r for r in rows if r.get("service_key") == "svc-a"]
    assert len(matching) == 1
    assert matching[0]["latency_ms"] == 20.0  # advanced in place, not a new row


async def test_record_worker_heartbeat_seeds_unknown_worker():
    rec = await record_worker_heartbeat(
        "worker:interop:scan", latency_ms=5.0, error_rate=0.0,
    )
    assert rec["service_key"] == "worker:interop:scan"
    rows = await service_registry.list()
    assert any(r.get("service_key") == "worker:interop:scan" for r in rows)


async def test_record_worker_heartbeat_sets_status():
    await record_worker_heartbeat("worker:rewards:reconcile", status="healthy")
    rows = await service_registry.list()
    matching = [r for r in rows if r.get("service_key") == "worker:rewards:reconcile"]
    assert matching and matching[0]["status"] == "healthy"


async def test_record_service_heartbeat_requires_key():
    with pytest.raises(ValueError):
        await record_service_heartbeat("")


# ═══════════════════════════════════════════════════════════════════════════
# ObservabilityTraceMiddleware (auto-record HTTP middleware)
# ═══════════════════════════════════════════════════════════════════════════

def _middleware_app(*, trace_first: bool):
    """Minimal FastAPI app: a stub auth middleware sets ``request.state.tenant``.

    ``trace_first=True`` places the trace middleware OUTERMOST (runs before
    auth) — the outcome of registering it "after" the auth middleware in code
    given Starlette's front-insert. ``trace_first=False`` leaves auth outermost
    (runs first), which is the ordering main.py actually wires.
    """
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/v1/echo")
    async def echo():
        return {"ok": True}

    async def fake_auth(request, call_next):
        request.state.tenant = SimpleNamespace(tenant_id="t-obs")
        return await call_next(request)

    # ``add_middleware`` inserts at the FRONT of the chain, so the LAST add is
    # the OUTERMOST middleware (runs first).
    if trace_first:
        app.middleware("http")(fake_auth)          # auth inner…
        app.add_middleware(ObservabilityTraceMiddleware)  # …trace outermost
    else:
        app.add_middleware(ObservabilityTraceMiddleware)  # trace inner…
        app.middleware("http")(fake_auth)          # …auth outermost (runs first)
    return app


async def test_observability_middleware_auto_records_authenticated_request():
    """Auth outermost → trace middleware sees request.state.tenant → one record."""
    from starlette.testclient import TestClient

    store = get_store("observability_traces")
    app = _middleware_app(trace_first=False)

    with TestClient(app) as client:
        resp = client.get("/v1/echo")
    assert resp.status_code == 200

    # The record is written by a fire-and-forget task on the portal loop; poll
    # briefly rather than assuming it has flushed before the response returns.
    traces: list = []
    for _ in range(100):
        traces = await store.get_list("traces:t-obs")
        if traces:
            break
        await asyncio.sleep(0.01)
    assert traces, "authenticated request should produce an auto-recorded trace"
    assert traces[0]["endpoint"] == "/v1/echo"
    assert traces[0]["status"] == "ok"
    assert traces[0]["tenant_id"] == "t-obs"


async def test_observability_middleware_skips_unauthenticated_request():
    """No tenant on request.state → no record (no per-request spam)."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    app = FastAPI()

    @app.get("/v1/echo")
    async def echo():
        return {"ok": True}

    app.add_middleware(ObservabilityTraceMiddleware)

    store = get_store("observability_traces")
    with TestClient(app) as client:
        resp = client.get("/v1/echo")
    assert resp.status_code == 200
    traces = await store.get_list("traces:t-obs")
    assert traces == []


async def test_observability_middleware_does_not_record_when_auth_runs_after():
    """Trace outermost (runs before auth) → tenant not yet set → no record.

    This is the regression guard for the wiring order: registering the trace
    middleware "after" the auth middleware in code (i.e. after
    ``register_middleware``) would put it outermost and silently disable
    auto-recording. main.py registers it BEFORE so auth runs first.
    """
    from starlette.testclient import TestClient

    store = get_store("observability_traces")
    app = _middleware_app(trace_first=True)

    with TestClient(app) as client:
        resp = client.get("/v1/echo")
    assert resp.status_code == 200
    traces = await store.get_list("traces:t-obs")
    assert traces == []
