"""Tests for the standalone scoring (extraction) routes."""

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
def scoring_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.agent.scoring_routes")
        importlib.reload(mod)
        mod._runs_store._data.clear()
        mod._runs_store._lists.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        require_permission=lambda perm: None,
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def make_request_body(routes, signals=None):
    return routes.ExtractionRequest(
        identity=routes.IdentityIn(api_key_id="key-1"),
        signals=signals or [],
        model_name="claude-sonnet-4",
        budget_utilization=0.4,
        canary_triggered=False,
        fraud_score=10.0,
    )


@pytest.mark.asyncio
async def test_list_models_returns_tiers(scoring_routes):
    res = await scoring_routes.list_models(make_request())
    assert "models" in res["data"]
    assert "tiers" in res["data"]
    assert any(m["model_name"] == "gpt-4" for m in res["data"]["models"])


@pytest.mark.asyncio
async def test_extract_persists_run(scoring_routes):
    body = make_request_body(scoring_routes)
    res = await scoring_routes.extract(body, make_request())
    run_id = res["data"]["run_id"]
    assert res["data"]["actor_key"] == "key-1"
    assert "score" in res["data"]
    assert "band" in res["data"]

    fetched = await scoring_routes.get_run(run_id, make_request())
    assert fetched["data"]["run_id"] == run_id


@pytest.mark.asyncio
async def test_extract_rejects_anonymous_identity(scoring_routes):
    body = scoring_routes.ExtractionRequest(
        identity=scoring_routes.IdentityIn(),
        model_name="claude-sonnet-4",
    )
    with pytest.raises(Exception) as exc:
        await scoring_routes.extract(body, make_request())
    assert "at least one" in str(exc.value)


@pytest.mark.asyncio
async def test_list_runs_filters_by_tenant_and_band(scoring_routes):
    await scoring_routes.extract(make_request_body(scoring_routes), make_request("t-001"))
    await scoring_routes.extract(make_request_body(scoring_routes), make_request("t-002"))
    res = await scoring_routes.list_runs(make_request("t-001"))
    assert res["data"]["count"] == 1
    assert res["data"]["runs"][0]["tenant_id"] == "t-001"


@pytest.mark.asyncio
async def test_canary_triggered_raises_score(scoring_routes):
    """Canary detection should produce a higher score than the same request without it.

    The scorer applies EMA smoothing so the raw 70.0 floor is mixed with prior
    state; we just assert the canary path produces a non-trivial score.
    """
    baseline_body = scoring_routes.ExtractionRequest(
        identity=scoring_routes.IdentityIn(api_key_id="key-2"),
        model_name="claude-opus-4",
        canary_triggered=False,
    )
    canary_body = scoring_routes.ExtractionRequest(
        identity=scoring_routes.IdentityIn(api_key_id="key-3"),
        model_name="claude-opus-4",
        canary_triggered=True,
    )
    baseline = await scoring_routes.extract(baseline_body, make_request())
    canary = await scoring_routes.extract(canary_body, make_request())
    assert canary["data"]["score"] > baseline["data"]["score"]
    assert canary["data"]["score"] > 0.0


@pytest.mark.asyncio
async def test_get_run_404(scoring_routes):
    with pytest.raises(Exception) as exc:
        await scoring_routes.get_run("missing", make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_policies_aggregation(scoring_routes):
    await scoring_routes.extract(make_request_body(scoring_routes), make_request())
    await scoring_routes.extract(make_request_body(scoring_routes), make_request())
    res = await scoring_routes.list_policies(make_request())
    assert res["data"]["total_runs"] == 2
    assert sum(p["count"] for p in res["data"]["policies"]) == 2


@pytest.mark.asyncio
async def test_signal_severity_validation(scoring_routes):
    with pytest.raises(Exception):
        scoring_routes.ExtractionRequest(
            identity=scoring_routes.IdentityIn(api_key_id="key-1"),
            signals=[scoring_routes.SignalIn(name="x", value=0.5, severity="bogus")],
        )
