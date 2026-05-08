"""Tests for the agent feedback-loop introspection routes."""

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
def feedback_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.agent.feedback_routes")
        importlib.reload(mod)
        mod._loop_store._data.clear()
        mod._loop_store._lists.clear()
        mod._event_store._data.clear()
        mod._event_store._lists.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        require_permission=lambda perm: None,
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.mark.asyncio
async def test_upsert_and_get_loop(feedback_routes):
    body = feedback_routes.LoopSnapshot(
        auto_accept_threshold=0.9,
        discard_threshold=0.3,
        sample_count=42,
        approval_rate=0.78,
    )
    upsert = await feedback_routes.upsert_loop("web_crawler", body, make_request())
    assert upsert["data"]["worker_type"] == "web_crawler"
    assert upsert["data"]["sample_count"] == 42

    fetched = await feedback_routes.get_loop("web_crawler", make_request())
    assert fetched["data"]["auto_accept_threshold"] == 0.9


@pytest.mark.asyncio
async def test_upsert_rejects_inverted_thresholds(feedback_routes):
    body = feedback_routes.LoopSnapshot(
        auto_accept_threshold=0.3,
        discard_threshold=0.9,
    )
    with pytest.raises(Exception) as exc:
        await feedback_routes.upsert_loop("web_crawler", body, make_request())
    assert "auto_accept_threshold" in str(exc.value)


@pytest.mark.asyncio
async def test_get_loop_404(feedback_routes):
    with pytest.raises(Exception) as exc:
        await feedback_routes.get_loop("ghost", make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_list_loops_per_tenant(feedback_routes):
    body = feedback_routes.LoopSnapshot(auto_accept_threshold=0.8, discard_threshold=0.2)
    await feedback_routes.upsert_loop("web_crawler", body, make_request("t-001"))
    await feedback_routes.upsert_loop("api_scanner", body, make_request("t-001"))
    await feedback_routes.upsert_loop("web_crawler", body, make_request("t-002"))

    res = await feedback_routes.list_loops(make_request("t-001"))
    assert res["data"]["count"] == 2


@pytest.mark.asyncio
async def test_refit_records_event_and_updates_loop(feedback_routes):
    body = feedback_routes.LoopSnapshot(auto_accept_threshold=0.8, discard_threshold=0.2)
    await feedback_routes.upsert_loop("web_crawler", body, make_request())

    refit = await feedback_routes.record_refit(
        "web_crawler", make_request(), {"reason": "drift_detected"}
    )
    assert refit["data"]["event_type"] == "refit"

    loop = await feedback_routes.get_loop("web_crawler", make_request())
    assert loop["data"]["last_refit_at"] is not None


@pytest.mark.asyncio
async def test_refit_unknown_loop_404(feedback_routes):
    with pytest.raises(Exception) as exc:
        await feedback_routes.record_refit("ghost", make_request(), None)
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_events_listing(feedback_routes):
    body = feedback_routes.LoopSnapshot(auto_accept_threshold=0.8, discard_threshold=0.2)
    await feedback_routes.upsert_loop("web_crawler", body, make_request())
    await feedback_routes.record_refit("web_crawler", make_request(), None)
    await feedback_routes.record_refit("web_crawler", make_request(), None)

    res = await feedback_routes.list_events("web_crawler", make_request())
    assert res["data"]["count"] == 2
    assert all(e["event_type"] == "refit" for e in res["data"]["events"])


@pytest.mark.asyncio
async def test_metrics_snapshot_counts_refits(feedback_routes):
    body = feedback_routes.LoopSnapshot(
        auto_accept_threshold=0.85,
        discard_threshold=0.15,
        sample_count=100,
        approval_rate=0.6,
    )
    await feedback_routes.upsert_loop("entity_resolver", body, make_request())
    await feedback_routes.record_refit("entity_resolver", make_request(), None)

    res = await feedback_routes.get_metrics("entity_resolver", make_request())
    assert res["data"]["refit_count"] == 1
    assert res["data"]["sample_count"] == 100
    assert res["data"]["approval_rate"] == 0.6
