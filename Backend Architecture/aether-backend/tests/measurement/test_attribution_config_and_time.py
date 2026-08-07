"""Attribution reliability tests — config durability (G) and event-time (H).

G: the model-config API wrote a module-global dict while the engine read the
   attribution_model_configs table nothing wrote, so an acknowledged config was
   invisible to the executor. Both sides now go through AttributionRunRepository,
   which shares one store in local mode (and the typed table in production).

H: a conversion with a missing/invalid event timestamp silently became
   datetime.now(), widening the lookback window and over-crediting. The engine
   now rejects the run; the resolver refuses to attribute and excludes
   invalid-timestamp touchpoints instead of stamping them with now().
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.measurement.engine.attribution_engine import AttributionEngine
from services.measurement.repositories.attribution_run_repo import (
    AttributionRunRepository,
    _reset_local_attribution,
)
from services.attribution.resolver import AttributionResolver


def _run(coro):
    # A fresh loop each call — asyncio.get_event_loop() raises "no current event
    # loop" under pytest-asyncio + xdist once a prior async test closed the loop.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# G — attribution model config durability / bridge
# ─────────────────────────────────────────────────────────────────────────────

def _build_attr_app() -> FastAPI:
    from services.measurement.routes.attribution import router

    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _eh(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _tenant(request: Request, call_next):
        request.state.tenant = SimpleNamespace(tenant_id="test-tenant")
        return await call_next(request)

    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_repo_create_then_get_model_config_bridge():
    _reset_local_attribution()
    repo = AttributionRunRepository()
    saved = await repo.create_model_config({
        "tenant_id": "tenant-a", "name": "cfg", "model_type": "linear",
    })
    cfg_id = saved["model_config_id"]

    # A DIFFERENT instance (as the engine holds) must see the same config.
    found = await AttributionRunRepository().get_model_config("tenant-a", cfg_id)
    assert found is not None
    assert found["model_type"] == "linear"
    # And it is not visible to another tenant.
    assert await repo.get_model_config("tenant-b", cfg_id) is None


def test_api_created_config_is_visible_to_engine_repo():
    _reset_local_attribution()
    client = TestClient(_build_attr_app())

    resp = client.post("/v1/attribution/configurations", json={
        "name": "primary", "model_type": "last_touch",
    })
    assert resp.status_code == 200, resp.text
    cfg_id = resp.json()["data"]["model_config_id"]

    # The engine reads config via AttributionRunRepository.get_model_config — the
    # exact path that previously returned None because the API wrote elsewhere.
    found = _run(AttributionRunRepository().get_model_config("test-tenant", cfg_id))
    assert found is not None
    assert found["model_type"] == "last_touch"

    listing = client.get("/v1/attribution/configurations")
    assert listing.status_code == 200
    ids = [c["model_config_id"] for c in listing.json()["data"]]
    assert cfg_id in ids


# ─────────────────────────────────────────────────────────────────────────────
# H — event-time integrity
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_model_config_uuid_case_insensitive():
    # Regression: the local lookup must match Postgres's case-insensitive UUID
    # equality, so an upper/mixed-case UUID string still resolves.
    _reset_local_attribution()
    repo = AttributionRunRepository()
    saved = await repo.create_model_config({
        "tenant_id": "tenant-a", "name": "cfg", "model_type": "linear",
    })
    found = await AttributionRunRepository().get_model_config(
        "tenant-a", saved["model_config_id"].upper()
    )
    assert found is not None
    assert found["model_type"] == "linear"


@pytest.mark.asyncio
async def test_resolver_refuses_on_empty_string_conversion_timestamp():
    # Regression: a PRESENT-but-empty timestamp is provided-and-invalid → refuse
    # (not treated as absent → now()).
    resolver = AttributionResolver()
    result = await resolver.resolve(
        user_id="u-1",
        event={"timestamp": ""},
        touchpoints=[{"channel": "a", "timestamp": "2026-01-01T00:00:00Z"}],
    )
    assert result.model_used == "none"
    assert result.credits == []


@pytest.mark.asyncio
async def test_engine_rejects_invalid_conversion_timestamp(monkeypatch):
    _reset_local_attribution()
    engine = AttributionEngine()

    async def _fake_get(tenant_id, conversion_id):
        return {
            "conversion_id": conversion_id, "tenant_id": tenant_id,
            "occurred_at": "not-a-date", "attribution_eligible": True,
            "profile_id": "p-1",
        }

    monkeypatch.setattr(engine._conversion_repo, "get", _fake_get)

    # The run is rejected (not silently anchored to now()).
    with pytest.raises(ValueError, match="invalid_conversion_timestamp"):
        await engine.run_for_conversion("tenant-a", "conv-1")


def test_parse_touchpoints_excludes_invalid_or_missing_timestamp():
    raw = [
        {"channel": "a", "timestamp": "2026-01-01T00:00:00Z"},
        {"channel": "b", "timestamp": "not-a-date"},
        {"channel": "c"},  # missing timestamp
    ]
    tps = AttributionResolver._parse_touchpoints(raw)
    assert [t.channel for t in tps] == ["a"]


@pytest.mark.asyncio
async def test_resolver_refuses_on_invalid_conversion_timestamp():
    resolver = AttributionResolver()
    result = await resolver.resolve(
        user_id="u-1",
        event={"timestamp": "not-a-date"},  # provided but unparseable → refuse
        touchpoints=[{"channel": "a", "timestamp": "2026-01-01T00:00:00Z"}],
    )
    assert result.model_used == "none"
    assert result.credits == []
