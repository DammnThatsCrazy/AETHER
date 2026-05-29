"""
Tests for SDK Health Monitoring Service.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.unit._sdk_test_helpers import inject_shared_stubs, BACKEND_ROOT


@contextmanager
def service_context(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")

    saved = dict(sys.modules)
    inject_shared_stubs()
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        if str(BACKEND_ROOT) in sys.path:
            sys.path.remove(str(BACKEND_ROOT))
        for key in list(sys.modules):
            if key not in saved:
                del sys.modules[key]


@pytest.fixture()
def sdk_health_service(monkeypatch):
    with service_context(monkeypatch):
        import importlib
        import services.sdk_health.service as svc_mod
        importlib.reload(svc_mod)
        svc_mod._sdk_health_service = None
        svc = svc_mod.get_sdk_health_service()
        yield svc, svc_mod


def make_heartbeat(svc_mod, **kwargs):
    defaults = dict(
        tenant_id="tenant-test",
        sdk_id="sdk-001",
        sdk_version="7.0.0",
        platform="web",
        app_version="1.0.0",
        queue_depth=5,
        retry_count=0,
        dropped_events=0,
        endpoint_latency_ms=50.0,
        ingestion_success_rate=1.0,
        schema_hash="schema-7.0.0",
        auth_valid=True,
        consent_valid=True,
        wallet_connected=False,
        config_version="1",
        rollout_cohort="default",
    )
    defaults.update(kwargs)
    return svc_mod.SDKHeartbeat(**defaults)


# ── Heartbeat ingestion ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_heartbeat_stores_to_redis(sdk_health_service):
    svc, svc_mod = sdk_health_service
    hb = make_heartbeat(svc_mod)

    with patch.object(svc, "_publish_heartbeat_event", new=AsyncMock()):
        with patch.object(svc, "_run_drift_checks_async", new=AsyncMock()):
            score = await svc.ingest_heartbeat(hb)

    stored = await svc._heartbeat_store.get(svc._heartbeat_key("tenant-test", "sdk-001"))
    assert stored is not None
    assert stored["sdk_id"] == "sdk-001"
    assert stored["platform"] == "web"
    assert score is not None
    assert score.sdk_id == "sdk-001"


@pytest.mark.asyncio
async def test_ingest_heartbeat_returns_health_score(sdk_health_service):
    svc, svc_mod = sdk_health_service
    hb = make_heartbeat(svc_mod)

    with patch.object(svc, "_publish_heartbeat_event", new=AsyncMock()):
        with patch.object(svc, "_run_drift_checks_async", new=AsyncMock()):
            score = await svc.ingest_heartbeat(hb)

    assert 0.0 <= score.composite <= 100.0
    assert score.status in ("healthy", "degraded", "unhealthy")
    assert score.tenant_id == "tenant-test"


# ── Health scoring ─────────────────────────────────────────────────────────────

def test_score_healthy_sdk(sdk_health_service):
    svc, svc_mod = sdk_health_service
    hb = make_heartbeat(
        svc_mod,
        queue_depth=0,
        dropped_events=0,
        endpoint_latency_ms=20.0,
        ingestion_success_rate=1.0,
        auth_valid=True,
        consent_valid=True,
    )
    score = svc._compute_score(hb)
    assert score.composite >= 80.0
    assert score.status == "healthy"


def test_score_degraded_sdk_high_latency(sdk_health_service):
    svc, svc_mod = sdk_health_service
    hb = make_heartbeat(
        svc_mod,
        endpoint_latency_ms=3000.0,
        ingestion_success_rate=0.7,
        retry_count=10,
    )
    score = svc._compute_score(hb)
    assert score.composite < 80.0


def test_score_unhealthy_sdk_high_drops(sdk_health_service):
    svc, svc_mod = sdk_health_service
    hb = make_heartbeat(
        svc_mod,
        queue_depth=10,
        dropped_events=90,
        ingestion_success_rate=0.1,
        auth_valid=False,
        retry_count=20,
    )
    score = svc._compute_score(hb)
    assert score.composite < 50.0
    assert score.status in ("degraded", "unhealthy")


def test_score_auth_invalid_penalty(sdk_health_service):
    svc, svc_mod = sdk_health_service
    healthy_hb = make_heartbeat(svc_mod, auth_valid=True)
    invalid_hb  = make_heartbeat(svc_mod, auth_valid=False)

    assert svc._compute_score(healthy_hb).composite > svc._compute_score(invalid_hb).composite


# ── Fleet status ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fleet_status_aggregation(sdk_health_service):
    svc, svc_mod = sdk_health_service

    for i in range(3):
        hb = make_heartbeat(svc_mod, sdk_id=f"sdk-{i:03d}", platform="web")
        with patch.object(svc, "_publish_heartbeat_event", new=AsyncMock()):
            with patch.object(svc, "_run_drift_checks_async", new=AsyncMock()):
                await svc.ingest_heartbeat(hb)

    fleet = await svc.get_fleet_status("tenant-test")
    assert fleet.tenant_id == "tenant-test"
    assert fleet.total_instances >= 3
    assert "web" in fleet.platforms


# ── Silent SDK detection ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_silent_sdks_flags_stale(sdk_health_service):
    svc, svc_mod = sdk_health_service

    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    await svc._heartbeat_store.set(
        svc._heartbeat_key("tenant-silent", "sdk-stale"),
        {"tenant_id": "tenant-silent", "sdk_id": "sdk-stale",
         "platform": "web", "sdk_version": "7.0.0", "reported_at": old_time},
    )

    silent = await svc.detect_silent_sdks("tenant-silent")
    assert "sdk-stale" in [s["sdk_id"] for s in silent]


@pytest.mark.asyncio
async def test_recent_sdk_not_flagged_silent(sdk_health_service):
    svc, svc_mod = sdk_health_service

    recent_time = datetime.now(timezone.utc).isoformat()
    await svc._heartbeat_store.set(
        svc._heartbeat_key("tenant-recent", "sdk-recent"),
        {"tenant_id": "tenant-recent", "sdk_id": "sdk-recent",
         "platform": "web", "sdk_version": "7.0.0", "reported_at": recent_time},
    )

    silent = await svc.detect_silent_sdks("tenant-recent")
    assert "sdk-recent" not in [s["sdk_id"] for s in silent]
