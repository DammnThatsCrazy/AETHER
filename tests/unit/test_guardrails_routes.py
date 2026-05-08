"""Tests for /v1/guardrails."""

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
def gr_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.diagnostics.guardrails_routes")
        importlib.reload(mod)
        mod._policy_store._data.clear()
        mod._policy_store._lists.clear()
        mod._decision_store._data.clear()
        mod._decision_store._lists.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    tenant = SimpleNamespace(tenant_id=tenant_id, require_permission=lambda perm: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.mark.asyncio
async def test_create_and_get_policy(gr_routes):
    body = gr_routes.PolicyCreate(kind="rate_limit", name="ingest", config={"qps": 10})
    res = await gr_routes.create_policy(body, make_request())
    pid = res["data"]["policy_id"]
    fetched = await gr_routes.get_policy(pid, make_request())
    assert fetched["data"]["kind"] == "rate_limit"
    assert fetched["data"]["config"]["qps"] == 10


@pytest.mark.asyncio
async def test_create_invalid_kind(gr_routes):
    body = gr_routes.PolicyCreate(kind="bogus", name="x")
    with pytest.raises(Exception) as exc:
        await gr_routes.create_policy(body, make_request())
    assert "Invalid kind" in str(exc.value)


@pytest.mark.asyncio
async def test_list_policies_filtered(gr_routes):
    await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="rate_limit", name="a", enabled=True),
        make_request(),
    )
    await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="pii_detector", name="b", enabled=False),
        make_request(),
    )
    res_kind = await gr_routes.list_policies(make_request(), kind="rate_limit")
    assert res_kind["data"]["count"] == 1
    res_enabled = await gr_routes.list_policies(make_request(), enabled=False)
    assert res_enabled["data"]["count"] == 1


@pytest.mark.asyncio
async def test_update_policy_merges_config(gr_routes):
    create = await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="rate_limit", name="a", config={"qps": 10}),
        make_request(),
    )
    pid = create["data"]["policy_id"]
    update = await gr_routes.update_policy(
        pid, gr_routes.PolicyUpdate(config={"burst": 5}, enabled=False), make_request()
    )
    assert update["data"]["config"] == {"qps": 10, "burst": 5}
    assert update["data"]["enabled"] is False


@pytest.mark.asyncio
async def test_delete_policy(gr_routes):
    create = await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="kill_switch", name="ks"), make_request()
    )
    pid = create["data"]["policy_id"]
    await gr_routes.delete_policy(pid, make_request())
    with pytest.raises(Exception):
        await gr_routes.get_policy(pid, make_request())


@pytest.mark.asyncio
async def test_record_decision_requires_existing_policy(gr_routes):
    body = gr_routes.DecisionRecord(policy_id="ghost", outcome="deny")
    with pytest.raises(Exception) as exc:
        await gr_routes.record_decision(body, make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_decision_invalid_outcome(gr_routes):
    create = await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="rate_limit", name="a"), make_request()
    )
    pid = create["data"]["policy_id"]
    body = gr_routes.DecisionRecord(policy_id=pid, outcome="bogus")
    with pytest.raises(Exception) as exc:
        await gr_routes.record_decision(body, make_request())
    assert "Invalid outcome" in str(exc.value)


@pytest.mark.asyncio
async def test_decisions_filtered_by_outcome(gr_routes):
    create = await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="rate_limit", name="a"), make_request()
    )
    pid = create["data"]["policy_id"]
    await gr_routes.record_decision(
        gr_routes.DecisionRecord(policy_id=pid, outcome="allow"), make_request()
    )
    await gr_routes.record_decision(
        gr_routes.DecisionRecord(policy_id=pid, outcome="deny"), make_request()
    )
    res = await gr_routes.list_decisions(make_request(), outcome="deny")
    assert res["data"]["count"] == 1


@pytest.mark.asyncio
async def test_status_rollup(gr_routes):
    await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="rate_limit", name="a", enabled=True),
        make_request(),
    )
    await gr_routes.create_policy(
        gr_routes.PolicyCreate(kind="rate_limit", name="b", enabled=False),
        make_request(),
    )
    res = await gr_routes.status(make_request())
    assert res["data"]["policy_count"] == 2
    assert res["data"]["policies_by_kind"]["rate_limit"] == 2
    assert res["data"]["enabled_by_kind"]["rate_limit"] == 1
