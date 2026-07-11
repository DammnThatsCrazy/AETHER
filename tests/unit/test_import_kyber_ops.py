"""Import Engine — Kyber operator surface + per-tenant concurrency cap.

Proves the cross-tenant operator routes see every tenant's imports (Kyber is the
internal console), the failed-import requeue resets and re-enqueues a commit,
and a tenant cannot pile up unbounded in-flight imports.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from services.imports import kyber_routes as kr  # noqa: E402
from services.imports import service as svc  # noqa: E402


@contextmanager
def raises_named(*names: str):
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        yield excinfo
    got = type(excinfo.value).__name__
    assert got in names, f"expected one of {names}, got {got}: {excinfo.value}"


@pytest.fixture()
def clean():
    from repositories.import_files import get_import_file_repository
    from repositories.imports_repo import get_imports_repository

    r = get_imports_repository()
    for attr in ("sessions", "schemas", "mappings", "templates", "validations",
                 "row_errors", "commits", "rollbacks"):
        getattr(r, attr)._store.clear()
    get_import_file_repository()._store.clear()
    return r


class _Actor:
    actor_id = "operator-1"


class _Req:
    def __init__(self):
        self.state = type("S", (), {})()


# ── operator surface ─────────────────────────────────────────────────────────


async def test_timeline_is_cross_tenant(clean):
    await svc.create_import("tenant-a", created_by="a")
    await svc.create_import("tenant-b", created_by="b")
    body = await kr.imports_timeline(_Req(), actor=_Actor(), limit=100)
    tenants = {s["tenant_id"] for s in body["data"]["sessions"]}
    assert {"tenant-a", "tenant-b"} <= tenants


async def test_detail_any_tenant(clean):
    session = await svc.create_import("tenant-a")
    body = await kr.import_detail(session["id"], _Req(), actor=_Actor())
    assert body["data"]["session"]["id"] == session["id"]
    assert body["data"]["commit_count"] == 0


async def test_detail_missing_404(clean):
    with raises_named("NotFoundError"):
        await kr.import_detail("nope", _Req(), actor=_Actor())


async def test_requeue_resets_failed_and_enqueues(clean):
    session = await svc.create_import("tenant-a")
    await clean.set_status("tenant-a", session["id"], "failed")
    body = await kr.requeue_import(session["id"], _Req(), actor=_Actor())
    assert body["data"]["job"]["job_type"] == "import.commit"
    refreshed = await clean.get_session("tenant-a", session["id"])
    assert refreshed["status"] == "approved"


async def test_requeue_rejects_non_failed(clean):
    session = await svc.create_import("tenant-a")  # status 'created'
    with raises_named("ConflictError"):
        await kr.requeue_import(session["id"], _Req(), actor=_Actor())


# ── concurrency cap ──────────────────────────────────────────────────────────


async def test_concurrent_import_cap(clean, monkeypatch):
    monkeypatch.setattr(svc, "MAX_CONCURRENT_IMPORTS", 2)
    a = await svc.create_import("tenant-cap")
    await svc.create_import("tenant-cap")
    with raises_named("ConflictError"):
        await svc.create_import("tenant-cap")
    # Cancelling one frees a slot (terminal states don't count).
    await svc.cancel_import("tenant-cap", a["id"])
    freed = await svc.create_import("tenant-cap")
    assert freed["status"] == "created"
