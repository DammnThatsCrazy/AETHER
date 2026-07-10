"""Router-level integration tests for the Job Center API.

Exercises services/jobs/routes.py and services/jobs/kyber_routes.py through
a real FastAPI app + TestClient (HTTP layer, path ordering, pydantic
validation, AetherError → status-code mapping), with the auth middleware
replaced by a header-driven fake tenant — the same approach as the other
router integration tests in this suite.

AETHER_ENV=local → in-memory repository backend.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-job-center-api-tests")

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.common.common import AetherError  # noqa: E402

from repositories.jobs_repo import get_jobs_repository, reset_jobs_memory  # noqa: E402
from services.jobs import kyber_routes, routes  # noqa: E402
from services.jobs.handlers import JobOutcome, register_handler  # noqa: E402
from services.jobs.models import JobStatus  # noqa: E402

TENANT_A = "tenant-api-a"
TENANT_B = "tenant-api-b"

# ── Test job types (registered once per process) ─────────────────────────────

try:
    @register_handler("reports.generate", tenant_invocable=True)
    async def _reports_generate(payload, ctx):  # pragma: no cover — never executed here
        return JobOutcome(status="succeeded", result={})

    @register_handler("internal.compaction")  # registered but NOT tenant-invocable
    async def _internal_compaction(payload, ctx):  # pragma: no cover
        return JobOutcome(status="succeeded", result={})
except ValueError:
    pass  # already registered on this worker (module re-import)


# ── Fake auth (mirrors the shape middleware puts on request.state.tenant) ────

class FakeTenant:
    def __init__(self, tenant_id: str, operator: bool = False):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.permissions = ["kyber:operator"] if operator else ["read", "write"]

    def require_permission(self, permission: str) -> None:
        return None

    def require_any_permission(self, *permissions: str) -> None:
        return None

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        tenant_id = request.headers.get("x-test-tenant", TENANT_A)
        operator = request.headers.get("x-test-operator") == "1"
        request.state.tenant = FakeTenant(tenant_id, operator=operator)
        return await call_next(request)

    @app.exception_handler(AetherError)
    async def aether_error_handler(request: Request, exc: AetherError):
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(routes.router)
    app.include_router(kyber_routes.router)
    return app


@pytest.fixture()
def client():
    reset_jobs_memory()
    with TestClient(_build_app()) as c:
        yield c
    reset_jobs_memory()


def _operator_headers():
    return {"x-test-operator": "1"}


def _run(coro):
    """Run repo coroutines from sync tests (TestClient owns its own loop, so
    tests stay sync and drive the repository via a private asyncio.run)."""
    return asyncio.run(coro)


# ── Enqueue + reads ──────────────────────────────────────────────────────────

def test_enqueue_and_get_job(client):
    resp = client.post("/v1/jobs", json={
        "job_type": "reports.generate",
        "payload": {"report": "monthly"},
        "idempotency_key": "rep-1",
    })
    assert resp.status_code == 200, resp.text
    job = resp.json()["data"]
    assert job["status"] == JobStatus.QUEUED.value
    assert job["replayed"] is False
    assert job["payload"] == {"report": "monthly"}

    # replay with the same key
    replay = client.post("/v1/jobs", json={
        "job_type": "reports.generate",
        "payload": {"report": "monthly"},
        "idempotency_key": "rep-1",
    }).json()["data"]
    assert replay["replayed"] is True
    assert replay["id"] == job["id"]

    got = client.get(f"/v1/jobs/{job['id']}")
    assert got.status_code == 200
    assert got.json()["data"]["id"] == job["id"]

    listed = client.get("/v1/jobs").json()["data"]
    assert listed["job_count"] == 1

    summary = client.get("/v1/jobs/summary").json()["data"]
    assert summary["by_status"]["queued"] == 1
    assert summary["total"] == 1


def test_enqueue_unknown_job_type_is_400(client):
    resp = client.post("/v1/jobs", json={"job_type": "nope.never", "payload": {}})
    assert resp.status_code == 400


def test_enqueue_non_tenant_invocable_type_is_403(client):
    resp = client.post("/v1/jobs", json={"job_type": "internal.compaction", "payload": {}})
    assert resp.status_code == 403


def test_get_missing_job_is_404_and_cross_tenant_is_hidden(client):
    assert client.get("/v1/jobs/job_doesnotexist").status_code == 404

    job = client.post("/v1/jobs", json={"job_type": "reports.generate", "payload": {}}).json()["data"]
    other = client.get(f"/v1/jobs/{job['id']}", headers={"x-test-tenant": TENANT_B})
    assert other.status_code == 404
    other_list = client.get("/v1/jobs", headers={"x-test-tenant": TENANT_B}).json()["data"]
    assert other_list["job_count"] == 0


# ── Cancel / retry / events ──────────────────────────────────────────────────

def test_cancel_queued_job_and_events_timeline(client):
    job = client.post("/v1/jobs", json={"job_type": "reports.generate", "payload": {}}).json()["data"]

    cancelled = client.post(f"/v1/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == JobStatus.CANCELLED.value

    # cancelling a terminal job conflicts
    assert client.post(f"/v1/jobs/{job['id']}/cancel").status_code == 409

    events = client.get(f"/v1/jobs/{job['id']}/events").json()["data"]
    types = [e["event_type"] for e in events["events"]]
    assert types == ["job.queued", "job.cancelled"]

    # tenant B cannot read A's timeline
    other = client.get(
        f"/v1/jobs/{job['id']}/events", headers={"x-test-tenant": TENANT_B}
    )
    assert other.status_code == 404


def test_retry_failed_job(client):
    job = client.post("/v1/jobs", json={"job_type": "reports.generate", "payload": {}}).json()["data"]

    # not failed yet → conflict
    assert client.post(f"/v1/jobs/{job['id']}/retry").status_code == 409

    _run(get_jobs_repository().finish(job["id"], JobStatus.FAILED.value, error="boom"))
    retried = client.post(f"/v1/jobs/{job['id']}/retry")
    assert retried.status_code == 200
    data = retried.json()["data"]
    assert data["status"] == JobStatus.QUEUED.value
    assert data["attempts"] == 0


# ── Schedules CRUD (and route-shadowing regression) ──────────────────────────

def test_schedule_crud_roundtrip(client):
    created = client.post("/v1/jobs/schedules", json={
        "name": "nightly report",
        "job_type": "reports.generate",
        "cron_expression": "0 2 * * *",
        "timezone": "America/New_York",
        "misfire_policy": "fire_once",
        "overlap_policy": "skip",
        "payload": {"report": "nightly"},
    })
    assert created.status_code == 200, created.text
    schedule = created.json()["data"]
    assert schedule["next_run_at"] is not None
    assert schedule["enabled"] is True

    # /v1/jobs/schedules must be the schedules list, not a job lookup for
    # job_id == "schedules" (registration-order regression guard).
    listed = client.get("/v1/jobs/schedules")
    assert listed.status_code == 200
    assert listed.json()["data"]["schedule_count"] == 1

    got = client.get(f"/v1/jobs/schedules/{schedule['id']}")
    assert got.status_code == 200
    assert got.json()["data"]["name"] == "nightly report"

    patched = client.patch(
        f"/v1/jobs/schedules/{schedule['id']}",
        json={"cron_expression": "0 3 * * *", "enabled": False},
    )
    assert patched.status_code == 200
    data = patched.json()["data"]
    assert data["cron_expression"] == "0 3 * * *"
    assert data["enabled"] is False

    deleted = client.delete(f"/v1/jobs/schedules/{schedule['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/v1/jobs/schedules/{schedule['id']}").status_code == 404


def test_schedule_validation_errors(client):
    bad_cron = client.post("/v1/jobs/schedules", json={
        "name": "x", "job_type": "reports.generate", "cron_expression": "banana",
    })
    assert bad_cron.status_code == 400

    bad_tz = client.post("/v1/jobs/schedules", json={
        "name": "x", "job_type": "reports.generate",
        "cron_expression": "0 2 * * *", "timezone": "Mars/Olympus_Mons",
    })
    assert bad_tz.status_code == 400

    bad_policy = client.post("/v1/jobs/schedules", json={
        "name": "x", "job_type": "reports.generate",
        "cron_expression": "0 2 * * *", "misfire_policy": "explode",
    })
    assert bad_policy.status_code == 400

    non_invocable = client.post("/v1/jobs/schedules", json={
        "name": "x", "job_type": "internal.compaction", "cron_expression": "0 2 * * *",
    })
    assert non_invocable.status_code == 403


def test_schedules_are_tenant_scoped(client):
    schedule = client.post("/v1/jobs/schedules", json={
        "name": "mine", "job_type": "reports.generate", "cron_expression": "0 2 * * *",
    }).json()["data"]

    headers = {"x-test-tenant": TENANT_B}
    assert client.get(f"/v1/jobs/schedules/{schedule['id']}", headers=headers).status_code == 404
    assert client.delete(f"/v1/jobs/schedules/{schedule['id']}", headers=headers).status_code == 404
    assert client.get("/v1/jobs/schedules", headers=headers).json()["data"]["schedule_count"] == 0


# ── Kyber operator routes ────────────────────────────────────────────────────

def test_kyber_routes_reject_non_operators(client):
    job = client.post("/v1/jobs", json={"job_type": "reports.generate", "payload": {}}).json()["data"]
    assert client.get("/v1/kyber/jobs/timeline").status_code == 403
    assert client.post(f"/v1/kyber/jobs/{job['id']}/requeue").status_code == 403


def test_kyber_timeline_is_cross_tenant(client):
    client.post("/v1/jobs", json={"job_type": "reports.generate", "payload": {}})
    client.post(
        "/v1/jobs", json={"job_type": "reports.generate", "payload": {}},
        headers={"x-test-tenant": TENANT_B},
    )

    resp = client.get("/v1/kyber/jobs/timeline", headers=_operator_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    tenants = {e["tenant_id"] for e in data["events"]}
    assert tenants == {TENANT_A, TENANT_B}

    scoped = client.get(
        "/v1/kyber/jobs/timeline",
        headers=_operator_headers(),
        params={"tenant_id": TENANT_B},
    ).json()["data"]
    assert {e["tenant_id"] for e in scoped["events"]} == {TENANT_B}


def test_kyber_requeue_failed_job(client):
    job = client.post("/v1/jobs", json={"job_type": "reports.generate", "payload": {}}).json()["data"]

    # queued job is not requeueable
    conflict = client.post(f"/v1/kyber/jobs/{job['id']}/requeue", headers=_operator_headers())
    assert conflict.status_code == 409

    _run(get_jobs_repository().finish(job["id"], JobStatus.FAILED.value, error="boom"))
    resp = client.post(f"/v1/kyber/jobs/{job['id']}/requeue", headers=_operator_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == JobStatus.QUEUED.value
    assert data["attempts"] == 0

    missing = client.post("/v1/kyber/jobs/job_missing/requeue", headers=_operator_headers())
    assert missing.status_code == 404
