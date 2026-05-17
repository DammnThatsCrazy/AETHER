"""Tests for /v1/events replay job lifecycle."""

from __future__ import annotations

import asyncio
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
def mod(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        m = importlib.import_module("services.events.routes")
        importlib.reload(m)
        m._EVENTS.clear()
        yield m


def make_req(tenant_id: str = "t-001"):
    return SimpleNamespace(
        state=SimpleNamespace(
            tenant=SimpleNamespace(
                tenant_id=tenant_id,
                require_permission=lambda p: None,
            )
        )
    )


def _replay_body(mod, tenant_id="t-001", source_tag="bronze.events"):
    return mod.ReplayRequest(
        tenantId=tenant_id,
        sourceTag=source_tag,
        fromTime="2026-01-01T00:00:00Z",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_submit_replay_creates_queued_job(mod):
    job = asyncio.run(mod.submit_replay(_replay_body(mod), make_req()))
    assert job.status == "queued"
    assert job.totalReplayed == 0
    assert job.tenantId == "t-001"
    assert job.id is not None


def test_get_replay_job_returns_job(mod):
    created = asyncio.run(mod.submit_replay(_replay_body(mod), make_req()))
    fetched = asyncio.run(mod.get_replay_job(created.id, make_req(), tenantId="t-001"))
    assert fetched.id == created.id
    assert fetched.sourceTag == "bronze.events"


def test_get_replay_job_wrong_tenant_raises_404(mod):
    created = asyncio.run(mod.submit_replay(_replay_body(mod, tenant_id="t-001"), make_req("t-001")))
    with pytest.raises(Exception) as exc:
        asyncio.run(mod.get_replay_job(created.id, make_req("t-002"), tenantId="t-002"))
    assert "not found" in str(exc.value).lower()


def test_list_replay_jobs_by_tenant(mod):
    asyncio.run(mod.submit_replay(_replay_body(mod, tenant_id="t-001"), make_req("t-001")))
    asyncio.run(mod.submit_replay(_replay_body(mod, tenant_id="t-002"), make_req("t-002")))
    results = asyncio.run(mod.list_replay_jobs(make_req("t-001"), tenantId="t-001", limit=50))
    assert len(results) == 1
    assert results[0].tenantId == "t-001"


def test_cancel_replay_job_sets_cancelled(mod):
    created = asyncio.run(mod.submit_replay(_replay_body(mod), make_req()))
    cancelled = asyncio.run(mod.cancel_replay_job(created.id, make_req(), tenantId="t-001"))
    assert cancelled.status == "cancelled"
    assert cancelled.completedAt is not None
