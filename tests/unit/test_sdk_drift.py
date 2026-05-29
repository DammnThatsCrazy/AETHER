"""
Tests for SDK Drift Detection Engine.
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
def drift_detector(monkeypatch):
    with service_module_context(monkeypatch):
        import importlib
        import services.sdk_drift.service as svc_mod
        importlib.reload(svc_mod)
        svc_mod._sdk_drift_detector = None
        detector = svc_mod.get_sdk_drift_detector()
        yield detector, svc_mod


def make_heartbeat_dict(**kwargs) -> dict:
    defaults = {
        "tenant_id": "tenant-test",
        "sdk_id": "sdk-001",
        "sdk_version": "7.0.0",
        "platform": "web",
        "queue_depth": 5,
        "retry_count": 0,
        "dropped_events": 0,
        "ingestion_success_rate": 1.0,
        "schema_hash": "expected-hash-7-0-0",
        "auth_valid": True,
        "consent_valid": True,
    }
    defaults.update(kwargs)
    return defaults


# ── Schema drift ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schema_drift_detected(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(schema_hash="wrong-hash-xyz")

    incident = await detector.check_schema_drift(hb)
    assert incident is not None
    assert incident.drift_type == "schema_drift"
    assert incident.severity == "critical"
    assert "wrong-hash-xyz" in incident.description


@pytest.mark.asyncio
async def test_no_schema_drift_correct_hash(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(schema_hash="expected-hash-7-0-0")

    incident = await detector.check_schema_drift(hb)
    assert incident is None


@pytest.mark.asyncio
async def test_schema_drift_skipped_unknown_version(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(sdk_version="99.0.0", schema_hash="anything")

    incident = await detector.check_schema_drift(hb)
    assert incident is None


# ── Stale SDK ──────────────────────────────────────────────────────────────────

def test_stale_sdk_detected_old_version(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(sdk_version="5.9.9")

    incident = detector.check_stale_sdk(hb)
    assert incident is not None
    assert incident.drift_type == "stale_sdk"
    assert incident.severity == "warning"


def test_stale_sdk_not_flagged_current_version(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(sdk_version="7.0.0")

    incident = detector.check_stale_sdk(hb)
    assert incident is None


def test_stale_sdk_exact_minimum_version(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(sdk_version="6.0.0")

    incident = detector.check_stale_sdk(hb)
    assert incident is None


# ── Replay storm ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_storm_detected_high_rate(drift_detector):
    detector, _ = drift_detector

    counter_key = "replay_rate:tenant-test:sdk-replay"
    await detector._counter_store.set(
        counter_key,
        {"rate": 490, "sdk_id": "sdk-replay", "tenant_id": "tenant-test"},
    )

    hb = make_heartbeat_dict(sdk_id="sdk-replay", retry_count=15, queue_depth=10)
    incident = await detector.check_replay_storm(hb)

    assert incident is not None
    assert incident.drift_type == "replay_storm"
    assert incident.severity == "critical"


@pytest.mark.asyncio
async def test_replay_storm_not_triggered_low_rate(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(sdk_id="sdk-safe-replay", retry_count=0, queue_depth=2)

    incident = await detector.check_replay_storm(hb)
    assert incident is None


# ── Payload anomaly ────────────────────────────────────────────────────────────

def test_payload_anomaly_detected_high_drop_rate(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(queue_depth=10, dropped_events=50, ingestion_success_rate=0.1)

    incident = detector.check_payload_anomaly(hb)
    assert incident is not None
    assert incident.drift_type == "payload_anomaly"


def test_payload_anomaly_not_triggered_low_drop_rate(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict(queue_depth=100, dropped_events=5)

    incident = detector.check_payload_anomaly(hb)
    assert incident is None


# ── Healthy SDK — no incidents ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_drift_on_healthy_sdk(drift_detector):
    detector, _ = drift_detector
    hb = make_heartbeat_dict()

    with patch.object(detector, "_publish_drift_event", new=AsyncMock()):
        incidents = await detector.run_all_checks(hb)

    assert incidents == []


# ── Version comparison ─────────────────────────────────────────────────────────

def test_version_lt_comparisons(drift_detector):
    detector, _ = drift_detector
    assert detector._version_lt("5.9.9", "6.0.0") is True
    assert detector._version_lt("6.0.0", "6.0.0") is False
    assert detector._version_lt("7.0.0", "6.0.0") is False
    assert detector._version_lt("6.0.0", "6.0.1") is True
