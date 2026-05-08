"""Tests for /v1/diagnostics/queues."""

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
def queue_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.diagnostics.queue_routes")
        importlib.reload(mod)
        mod._queue_store._data.clear()
        mod._queue_store._lists.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    tenant = SimpleNamespace(tenant_id=tenant_id, require_permission=lambda perm: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.mark.asyncio
async def test_publish_and_get_snapshot(queue_routes):
    body = queue_routes.QueueSnapshot(depth=42, throughput_per_minute=15.0)
    res = await queue_routes.publish_snapshot("ingestion", body, make_request())
    assert res["data"]["queue_name"] == "ingestion"
    assert res["data"]["depth"] == 42

    fetched = await queue_routes.get_queue("ingestion", make_request())
    assert fetched["data"]["throughput_per_minute"] == 15.0


@pytest.mark.asyncio
async def test_get_unknown_queue_404(queue_routes):
    with pytest.raises(Exception) as exc:
        await queue_routes.get_queue("ghost", make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_publish_empty_name_rejected(queue_routes):
    body = queue_routes.QueueSnapshot(depth=1)
    with pytest.raises(Exception) as exc:
        await queue_routes.publish_snapshot("   ", body, make_request())
    assert "must not be empty" in str(exc.value)


@pytest.mark.asyncio
async def test_summary_aggregates(queue_routes):
    await queue_routes.publish_snapshot(
        "ingestion",
        queue_routes.QueueSnapshot(depth=10, throughput_per_minute=5.0, error_rate=0.1),
        make_request(),
    )
    await queue_routes.publish_snapshot(
        "ml_serving",
        queue_routes.QueueSnapshot(depth=20, throughput_per_minute=8.0, error_rate=0.3, backpressure=True),
        make_request(),
    )

    summary = await queue_routes.summary(make_request())
    assert summary["data"]["total_depth"] == 30
    assert summary["data"]["total_throughput_per_minute"] == 13.0
    assert summary["data"]["queue_count"] == 2
    assert summary["data"]["backpressured_queues"] == ["ml_serving"]
    assert abs(summary["data"]["average_error_rate"] - 0.2) < 1e-9


@pytest.mark.asyncio
async def test_list_filters_by_tenant(queue_routes):
    body = queue_routes.QueueSnapshot(depth=1)
    await queue_routes.publish_snapshot("a", body, make_request("t-001"))
    await queue_routes.publish_snapshot("b", body, make_request("t-002"))
    res = await queue_routes.list_queues(make_request("t-001"))
    assert res["data"]["count"] == 1


@pytest.mark.asyncio
async def test_drop_snapshot(queue_routes):
    body = queue_routes.QueueSnapshot(depth=1)
    await queue_routes.publish_snapshot("temp", body, make_request())
    res = await queue_routes.drop_snapshot("temp", make_request())
    assert res["data"]["deleted"] is True

    with pytest.raises(Exception):
        await queue_routes.get_queue("temp", make_request())
