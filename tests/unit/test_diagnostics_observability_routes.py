"""Tests for /v1/diagnostics/observability."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def obs_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.diagnostics.observability_routes")
        importlib.reload(mod)
        mod._trace_store._data.clear()
        mod._trace_store._lists.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    tenant = SimpleNamespace(tenant_id=tenant_id, require_permission=lambda perm: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.mark.asyncio
async def test_metrics_snapshot_returns_dict(obs_routes):
    res = await obs_routes.metrics_snapshot(make_request())
    assert "counters" in res["data"]
    assert "histograms" in res["data"]


@pytest.mark.asyncio
async def test_get_metric_filters_by_prefix(obs_routes):
    from shared.logger.logger import metrics
    metrics.increment("test_observability_alpha")
    metrics.increment("test_observability_alpha", labels={"k": "v"})
    metrics.increment("unrelated_counter")

    res = await obs_routes.get_metric("test_observability", make_request())
    assert all(k.startswith("test_observability") for k in res["data"]["counters"].keys())


@pytest.mark.asyncio
async def test_append_and_list_traces(obs_routes):
    body = obs_routes.TraceRecord(
        request_id="req-1",
        service="agent",
        endpoint="/v1/agent/tasks",
        duration_ms=42.0,
        status="ok",
    )
    await obs_routes.append_trace(body, make_request())

    body_err = obs_routes.TraceRecord(
        request_id="req-2",
        service="agent",
        endpoint="/v1/agent/tasks",
        duration_ms=120.0,
        status="error",
        error="boom",
    )
    await obs_routes.append_trace(body_err, make_request())

    res = await obs_routes.list_traces(make_request())
    assert res["data"]["count"] == 2


@pytest.mark.asyncio
async def test_list_traces_filtered_by_status(obs_routes):
    await obs_routes.append_trace(
        obs_routes.TraceRecord(request_id="r1", service="x", endpoint="/y", duration_ms=10.0, status="ok"),
        make_request(),
    )
    await obs_routes.append_trace(
        obs_routes.TraceRecord(request_id="r2", service="x", endpoint="/y", duration_ms=10.0, status="error"),
        make_request(),
    )
    res = await obs_routes.list_traces(make_request(), status="error")
    assert res["data"]["count"] == 1
    assert res["data"]["traces"][0]["status"] == "error"


@pytest.mark.asyncio
async def test_summary_computes_p95_and_error_rate(obs_routes):
    for i in range(10):
        await obs_routes.append_trace(
            obs_routes.TraceRecord(
                request_id=f"r-{i}",
                service="agent",
                endpoint="/x",
                duration_ms=float(i * 10),
                status="error" if i >= 8 else "ok",
            ),
            make_request(),
        )
    res = await obs_routes.summary(make_request())
    assert res["data"]["trace_sample_size"] == 10
    assert res["data"]["error_rate"] == 0.2
    assert res["data"]["p95_duration_ms"] >= res["data"]["p50_duration_ms"]
