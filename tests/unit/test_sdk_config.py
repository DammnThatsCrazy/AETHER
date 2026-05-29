"""
Tests for SDK Remote Config & Auto-Update Service.
Uses module-level stubs so tests run without FastAPI/cryptography installed.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit._sdk_test_helpers import inject_shared_stubs, BACKEND_ROOT


@contextmanager
def service_module_context(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    monkeypatch.setenv("SDK_CONFIG_SECRET", "test-secret-abc123")

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
def config_service(monkeypatch):
    with service_module_context(monkeypatch):
        import importlib
        import services.sdk_config.service as svc_mod
        importlib.reload(svc_mod)
        svc_mod._sdk_config_service = None
        svc = svc_mod.get_sdk_config_service()
        yield svc, svc_mod


async def publish_test_manifest(svc, rollout_percentage: int = 100):
    with patch.object(svc, "_publish_config_event", new=AsyncMock()):
        return await svc.publish_manifest(
            tenant_id="tenant-test",
            min_sdk_version="6.0.0",
            schema_version="7.0.0",
            features={"analytics": True, "web3": False},
            endpoints={"ingest": "https://ingest.aether.xyz"},
            flags={"heartbeat_interval_seconds": 60},
            rollout_percentage=rollout_percentage,
        )


# ── Signing & verification ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manifest_signing_produces_signature(config_service):
    svc, _ = config_service
    manifest = await publish_test_manifest(svc)

    assert manifest.signature != ""
    assert len(manifest.signature) == 64  # SHA-256 hex


@pytest.mark.asyncio
async def test_manifest_signature_verification_valid(config_service):
    svc, _ = config_service
    manifest = await publish_test_manifest(svc)

    valid = svc.verify_signature(manifest.canonical_payload(), manifest.signature)
    assert valid is True


@pytest.mark.asyncio
async def test_manifest_signature_verification_tampered(config_service):
    svc, _ = config_service
    manifest = await publish_test_manifest(svc)

    valid = svc.verify_signature(manifest.canonical_payload(), "deadbeef" * 8)
    assert valid is False


# ── Version incrementing ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manifest_version_increments_on_publish(config_service):
    svc, _ = config_service
    m1 = await publish_test_manifest(svc)
    m2 = await publish_test_manifest(svc)

    assert int(m2.manifest_version) == int(m1.manifest_version) + 1


# ── Rollout gating ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollout_100_pct_delivers_to_all(config_service):
    svc, _ = config_service
    await publish_test_manifest(svc, rollout_percentage=100)

    manifest = await svc.get_manifest("tenant-test", "sdk-any-id", "7.0.0")
    assert manifest is not None


@pytest.mark.asyncio
async def test_cohort_bucket_is_deterministic(config_service):
    svc, _ = config_service
    b1 = svc._cohort_bucket("tenant-test", "sdk-abc")
    b2 = svc._cohort_bucket("tenant-test", "sdk-abc")
    assert b1 == b2
    assert 0 <= b1 <= 99


@pytest.mark.asyncio
async def test_rollout_0_pct_outside_cohort_gets_previous(config_service):
    svc, _ = config_service

    # First: stable manifest at 100%
    await publish_test_manifest(svc, rollout_percentage=100)

    # Second: canary at 0% — all instances are "outside" the cohort
    canary = await publish_test_manifest(svc, rollout_percentage=0)

    # Any SDK should get the previous (stable) manifest
    manifest = await svc.get_manifest("tenant-test", "sdk-outside", "7.0.0")
    assert manifest is not None
    # The manifest returned should NOT be the canary (version should differ)
    assert manifest.manifest_version != canary.manifest_version


# ── Rollback ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_restores_previous_manifest(config_service):
    svc, _ = config_service
    m1 = await publish_test_manifest(svc)
    _m2 = await publish_test_manifest(svc)

    restored = await svc.rollback_manifest("tenant-test")
    assert restored is not None
    assert restored.manifest_version == m1.manifest_version


@pytest.mark.asyncio
async def test_rollback_returns_none_with_no_history(config_service):
    svc, _ = config_service
    result = await svc.rollback_manifest("tenant-no-history")
    assert result is None


# ── Kafka publish ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manifest_publish_fires_kafka_event(config_service):
    svc, _ = config_service

    with patch.object(svc, "_publish_config_event", new=AsyncMock()) as mock_publish:
        await svc.publish_manifest(
            tenant_id="tenant-test",
            min_sdk_version="6.0.0",
            schema_version="7.0.0",
            features={},
            endpoints={},
            flags={},
            rollout_percentage=100,
        )

    mock_publish.assert_called_once()
    assert mock_publish.call_args[0][0] == "tenant-test"


# ── Rollout status ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollout_status_reflects_published_manifest(config_service):
    svc, _ = config_service
    await publish_test_manifest(svc, rollout_percentage=50)
    status = await svc.get_rollout_status("tenant-test")

    assert status["tenant_id"] == "tenant-test"
    assert status["current_rollout_pct"] == 50
    assert status["current_version"] is not None
