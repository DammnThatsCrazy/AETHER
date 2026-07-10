"""Integration tests for GET /ready and GET /v1/ready.

Local-mode app: builds a FastAPI app with the gateway router (mirroring how
other integration tests assemble minimal apps from routers), a connected
in-memory registry, and a WorkerSupervisor on app.state — /v1/ready must
return 200 with the migrations check skipped.

Non-local mode is exercised at the readiness_report(...) level with a
simulated failed required worker: the report must come back not-ready and
the workers check must surface the failure (advisory).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from config.settings import Environment, settings  # noqa: E402
from dependencies.providers import get_registry  # noqa: E402
from services.gateway.readiness import readiness_report  # noqa: E402
from services.gateway.routes import router as gateway_router  # noqa: E402
from services.runtime.supervisor import WorkerSpec, WorkerSupervisor  # noqa: E402


# ── local app: /v1/ready → 200 ───────────────────────────────────────────────


@pytest.fixture()
def local_client():
    assert settings.env == Environment.LOCAL, (
        "readiness integration tests must run with AETHER_ENV=local"
    )
    registry = get_registry()
    # In local mode these connect to in-memory backends (no external deps).
    asyncio.run(registry.cache.connect())
    asyncio.run(registry.producer.connect())

    app = FastAPI()
    app.include_router(gateway_router)
    app.state.worker_supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    return TestClient(app)


def test_v1_ready_returns_200_in_local(local_client):
    resp = local_client.get("/v1/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is True
    assert body["environment"] == "local"
    checks = body["checks"]
    for name in ("database", "migrations", "cache", "event_bus", "workers", "auth_config"):
        assert name in checks, f"missing readiness check: {name}"
    assert checks["migrations"]["status"] == "skipped"
    assert checks["auth_config"]["status"] == "skipped"
    assert checks["database"]["status"] == "ok"
    assert checks["cache"]["status"] == "ok"
    assert checks["event_bus"]["status"] == "ok"
    assert checks["workers"]["advisory"] is True


def test_unversioned_ready_alias_matches_v1(local_client):
    resp = local_client.get("/ready")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ready"] is True


def test_ready_response_contains_no_secret_material(local_client):
    body = local_client.get("/v1/ready").text.lower()
    assert "jwt_secret" not in body
    assert "change-me-in-production" not in body
    assert "traceback" not in body


# ── non-local report: failed required worker + not-ready ─────────────────────


def _non_local_settings():
    """Minimal settings view for readiness_report (staging, default secret)."""
    return SimpleNamespace(
        env=Environment.STAGING,
        auth=SimpleNamespace(jwt_secret="change-me-in-production"),
    )


class _StubHealthClient:
    def __init__(self, healthy: bool, mode: str = "stub") -> None:
        self._healthy = healthy
        self.mode = mode

    async def health_check(self) -> bool:
        return self._healthy


@pytest.mark.asyncio
async def test_readiness_report_not_ready_with_failed_required_worker_non_local():
    # Simulate a required worker that failed its first start. The supervisor
    # is started under LOCAL so start_all does not abort; the resulting
    # "failed" state is what a live staging process would report after
    # exhausting restarts.
    async def boom():
        raise RuntimeError("worker cannot start")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="notification_sla",
            factory=boom,
            required=True,
            max_restarts=0,
            backoff_base_s=0.001,
        )
    )
    await supervisor.start_all()
    for _ in range(200):
        if supervisor.status()["notification_sla"]["state"] == "failed":
            break
        await asyncio.sleep(0.005)
    await supervisor.stop_all()
    assert supervisor.status()["notification_sla"]["state"] == "failed"

    registry = SimpleNamespace(
        cache=_StubHealthClient(True), producer=_StubHealthClient(True)
    )
    ready, report = await readiness_report(registry, supervisor, _non_local_settings())

    assert ready is False
    assert report["ready"] is False
    assert report["environment"] == "staging"
    checks = report["checks"]

    # Non-local with no database pool: fail-closed.
    assert checks["database"]["status"] == "failed"
    # No pool → migrations check cannot run.
    assert checks["migrations"]["status"] == "skipped"
    # Default JWT secret is rejected outside local (value never echoed).
    assert checks["auth_config"]["status"] == "failed"
    assert "change-me-in-production" not in str(report)

    # The failed required worker is surfaced, but only advisorily.
    workers = checks["workers"]
    assert workers["advisory"] is True
    assert workers["status"] == "failed"
    assert workers["workers"]["notification_sla"]["state"] == "failed"
    assert workers["workers"]["notification_sla"]["required"] is True


@pytest.mark.asyncio
async def test_workers_check_is_advisory_only():
    """A failed worker alone must NOT flip readiness (advisory for now)."""

    async def boom():
        raise RuntimeError("crash")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(name="w", factory=boom, max_restarts=0, backoff_base_s=0.001)
    )
    await supervisor.start_all()
    for _ in range(200):
        if supervisor.status()["w"]["state"] == "failed":
            break
        await asyncio.sleep(0.005)
    await supervisor.stop_all()

    registry = SimpleNamespace(
        cache=_StubHealthClient(True), producer=_StubHealthClient(True)
    )
    local_settings = SimpleNamespace(
        env=Environment.LOCAL, auth=SimpleNamespace(jwt_secret="")
    )
    ready, report = await readiness_report(registry, supervisor, local_settings)

    assert report["checks"]["workers"]["status"] == "failed"
    assert report["checks"]["workers"]["advisory"] is True
    # Every non-advisory check passes in local, so overall readiness holds.
    assert ready is True
