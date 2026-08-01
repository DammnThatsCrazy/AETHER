"""Communications subsystem readiness (§21) — worker dependency + backlog truth."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


@pytest.mark.asyncio
async def test_local_is_ready():
    from services.comms.readiness import comms_subsystem_readiness
    out = await comms_subsystem_readiness(
        pool=None, worker_capabilities={}, is_local=True,
    )
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_comms_required_worker_failure_fails_readiness():
    from services.comms.readiness import comms_subsystem_readiness
    # stream-ingestion (comms projector) down and release-critical → comms fails.
    caps = {
        "stream-ingestion": {"available": False, "release_critical": True},
        "event-delivery": {"available": True, "release_critical": True},
    }
    out = await comms_subsystem_readiness(
        pool=None, worker_capabilities=caps, is_local=True,
    )
    assert out["status"] == "failed"
    assert "stream-ingestion" in out["worker_failures"]


@pytest.mark.asyncio
async def test_non_comms_or_non_critical_worker_does_not_fail_comms():
    from services.comms.readiness import comms_subsystem_readiness
    # A non-release-critical comms-adjacent capability being down must not fail.
    caps = {
        "stream-ingestion": {"available": False, "release_critical": False},
        "semantic-enrichment": {"available": False, "release_critical": True},
    }
    out = await comms_subsystem_readiness(
        pool=None, worker_capabilities=caps, is_local=True,
    )
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_backlog_degrades_not_fails():
    from services.comms.readiness import comms_subsystem_readiness

    class _FakePool:
        async def fetchrow(self, *_a, **_k):
            return {"pending": 999999, "oldest_age": 4200.0}

    out = await comms_subsystem_readiness(
        pool=_FakePool(), worker_capabilities={}, is_local=False,
    )
    assert out["status"] == "degraded"
    assert out["webhook_inbox_backlog"] == 999999


@pytest.mark.asyncio
async def test_storage_unreachable_fails():
    from services.comms.readiness import comms_subsystem_readiness

    class _BrokenPool:
        async def fetchrow(self, *_a, **_k):
            raise RuntimeError("connection reset")

    out = await comms_subsystem_readiness(
        pool=_BrokenPool(), worker_capabilities={}, is_local=False,
    )
    assert out["status"] == "failed"
