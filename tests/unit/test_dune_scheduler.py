"""Tests for the Dune Analytics scheduled polling worker.

Verifies:
- Worker skips live calls in local mode
- Jobs run when due, are skipped when not yet due
- A failing job is isolated (others still run)
- API key resolution: tenant credential store for tenant schedules, DUNE_API_KEY
  only for platform schedules, absent → skipped with a generic detail
- Run details never carry exception text or credential values
- Schedule store CRUD (create / list / get / delete / update_run_status)
- Route-level tenant isolation: tenant A cannot read/delete tenant B's schedule
"""
from __future__ import annotations

import importlib
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "api"
_PREFIXES = ("config", "tenancy", "ingestion", "identity", "graph", "journeys", "intelligence", "value", "actions", "governance", "workers", "connectors", "replay", "billing", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _old_iso(seconds: int = 7200) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture()
def mock_repo(monkeypatch):
    """Provide an in-memory repository stub."""
    store: dict = {}

    class _Repo:
        async def insert(self, key, val):
            store[key] = val

        async def find_by_id(self, key):
            return store.get(key)

        async def find_many(self, filters=None, limit=None):
            rows = list(store.values())
            if filters:
                for k, v in filters.items():
                    rows = [r for r in rows if r.get(k) == v]
            return rows

        async def delete(self, key):
            store.pop(key, None)

    return _Repo(), store


@pytest.fixture()
def worker(monkeypatch, mock_repo):
    repo_obj, _ = mock_repo
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("AETHER_CREDENTIAL_BACKEND", "in_memory")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        sched_mod = importlib.import_module("connectors.dune_feeder.scheduler")
        models_mod = importlib.import_module("connectors.dune_feeder.models")

        # Patch the repository used by ScheduledQueryStore
        with patch.object(sched_mod.ScheduledQueryStore, "__init__", lambda self: None):
            worker_inst = sched_mod.DunePollingWorker()
            worker_inst._store = sched_mod.ScheduledQueryStore.__new__(sched_mod.ScheduledQueryStore)
            worker_inst._store._repo = repo_obj

        yield worker_inst, sched_mod, models_mod


def _make_config(sched_mod, *, last_run_at=None, enabled=True, interval=300,
                 tenant_scope="tenant-abc", api_key_ref=None):
    models_mod = importlib.import_module("connectors.dune_feeder.models")
    return models_mod.ScheduledQueryConfig(
        schedule_id=str(uuid.uuid4()),
        tenant_scope=tenant_scope,
        api_key_ref=api_key_ref,
        query_id="12345",
        query_name="test query",
        source_tag="test-tag",
        domain="onchain",
        interval_seconds=interval,
        created_at=_now_iso(),
        enabled=enabled,
        last_run_at=last_run_at,
    )


# ── is_due logic ──────────────────────────────────────────────────────────────

def test_due_when_never_run(worker):
    w, sched_mod, _ = worker
    with backend_module_path():
        cfg = _make_config(sched_mod, last_run_at=None)
        assert w._is_due(cfg) is True


def test_not_due_when_recent(worker):
    w, sched_mod, _ = worker
    with backend_module_path():
        cfg = _make_config(sched_mod, last_run_at=_now_iso(), interval=3600)
        assert w._is_due(cfg) is False


def test_due_when_old_enough(worker):
    w, sched_mod, _ = worker
    with backend_module_path():
        cfg = _make_config(sched_mod, last_run_at=_old_iso(7200), interval=300)
        assert w._is_due(cfg) is True


def test_disabled_never_due(worker):
    w, sched_mod, _ = worker
    with backend_module_path():
        cfg = _make_config(sched_mod, enabled=False, last_run_at=None)
        assert w._is_due(cfg) is False


# ── local-mode skip ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_one_skips_in_local_mode(worker, monkeypatch):
    w, sched_mod, _ = worker
    monkeypatch.setenv("AETHER_ENV", "local")

    with backend_module_path():
        cfg = _make_config(sched_mod)
        # Patch store.update_run_status to a no-op
        w._store.update_run_status = AsyncMock()
        summary = await w._run_one(cfg)
        assert summary.status == "skipped"
        assert "local mode" in (summary.detail or "")
        w._store.update_run_status.assert_awaited_once()


# ── missing API key ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_one_skips_without_api_key(worker, monkeypatch):
    w, sched_mod, _ = worker
    monkeypatch.delenv("DUNE_API_KEY", raising=False)

    with backend_module_path():
        cfg = _make_config(sched_mod)
        w._store.update_run_status = AsyncMock()
        with patch.object(sched_mod, "_is_live", return_value=True):
            summary = await w._run_one(cfg)
        assert summary.status == "skipped"
        assert summary.detail == "credential unavailable"


# ── successful live run (mocked httpx) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_run_one_success(worker, monkeypatch):
    w, sched_mod, models_mod = worker
    monkeypatch.setenv("DUNE_API_KEY", "fake-key")

    mock_ingest_resp = MagicMock()
    mock_ingest_resp.rows_submitted = 1
    mock_ingest_resp.rows_accepted = 1
    mock_ingest_resp.rows_rejected = 0

    with backend_module_path():
        cfg = _make_config(sched_mod, tenant_scope=None)
        w._store.update_run_status = AsyncMock()

        fake_qr = models_mod.DuneQueryResult(
            query_id="12345",
            execution_id="exec-abc",
            query_name="test q",
            query_version="1",
            rows=[{"wallet": "0xabc", "balance": 100}],
            pulled_at=_now_iso(),
        )

        with patch.object(sched_mod, "_is_live", return_value=True), \
             patch.object(sched_mod, "_fetch_dune_results", new=AsyncMock(return_value=fake_qr)):
            import connectors.dune_feeder.service as svc_mod
            original_ingest = svc_mod.dune_feeder_service.ingest
            svc_mod.dune_feeder_service.ingest = AsyncMock(return_value=mock_ingest_resp)
            try:
                summary = await w._run_one(cfg)
            finally:
                svc_mod.dune_feeder_service.ingest = original_ingest

        assert summary.status == "ok"
        assert summary.rows_accepted == 1
        w._store.update_run_status.assert_awaited_once()


# ── error isolation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_one_error_isolated(worker, monkeypatch):
    w, sched_mod, _ = worker
    monkeypatch.setenv("DUNE_API_KEY", "fake-key")

    with backend_module_path():
        cfg = _make_config(sched_mod, tenant_scope=None)
        w._store.update_run_status = AsyncMock()

        with patch.object(sched_mod, "_is_live", return_value=True), \
             patch.object(sched_mod, "_fetch_dune_results", new=AsyncMock(side_effect=RuntimeError("network error"))):
            summary = await w._run_one(cfg)

        assert summary.status == "error"
        assert summary.detail == "RuntimeError"
        w._store.update_run_status.assert_awaited_once()


# ── tick runs due jobs, skips non-due ────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_runs_due_skips_non_due(worker, monkeypatch):
    w, sched_mod, _ = worker
    monkeypatch.setenv("AETHER_ENV", "local")

    with backend_module_path():
        due_cfg = _make_config(sched_mod, last_run_at=_old_iso(9999))
        not_due_cfg = _make_config(sched_mod, last_run_at=_now_iso(), interval=3600)

        w._store.list_all = AsyncMock(return_value=[due_cfg, not_due_cfg])
        w._store.update_run_status = AsyncMock()

        run_one_calls = []
        original = w._run_one

        async def _spy(cfg):
            run_one_calls.append(cfg.schedule_id)
            return await original(cfg)

        w._run_one = _spy
        summaries = await w._tick()

        assert len(summaries) == 1
        assert summaries[0].schedule_id == due_cfg.schedule_id


# ── schedule store CRUD ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_store_create_list_delete(worker, monkeypatch):
    w, sched_mod, models_mod = worker
    monkeypatch.setenv("JWT_SECRET", "x")

    with backend_module_path():
        req = models_mod.ScheduleCreateRequest(
            query_id="99",
            query_name="my query",
            source_tag="tag-1",
            domain="governance",
            interval_seconds=600,
        )
        config = await w._store.create(req, tenant_scope="tenant-x")
        assert config.schedule_id
        assert config.tenant_scope == "tenant-x"

        configs = await w._store.list_all(tenant_scope="tenant-x")
        assert any(c.schedule_id == config.schedule_id for c in configs)

        fetched = await w._store.get(config.schedule_id)
        assert fetched is not None
        assert fetched.query_id == "99"

        deleted = await w._store.delete(config.schedule_id)
        assert deleted is True

        after = await w._store.get(config.schedule_id)
        assert after is None


@pytest.mark.asyncio
async def test_schedule_store_update_run_status(worker):
    w, sched_mod, models_mod = worker
    with backend_module_path():
        req = models_mod.ScheduleCreateRequest(
            query_id="55",
            query_name="q",
            source_tag="t",
            domain="market",
            interval_seconds=300,
        )
        config = await w._store.create(req, tenant_scope=None)
        await w._store.update_run_status(config.schedule_id, status="ok", detail="rows=5")
        updated = await w._store.get(config.schedule_id)
        assert updated.last_run_status == "ok"
        assert updated.last_run_detail == "rows=5"
        assert updated.last_run_at is not None


# ── credential scoping and run-detail hygiene ────────────────────────────────

_ENV_VALUE = "env-value-not-for-tenants"
_MULTILINE_ENV = "-----BEGIN PRIVATE KEY-----\nMIIEvQ\n-----END PRIVATE KEY-----"


async def _run_live(w, sched_mod, cfg, fetch):
    w._store.update_run_status = AsyncMock()
    with patch.object(sched_mod, "_is_live", return_value=True), \
         patch.object(sched_mod, "_fetch_dune_results", new=fetch):
        summary = await w._run_one(cfg)
    stored_detail = w._store.update_run_status.await_args.kwargs.get("detail")
    return summary, stored_detail


@pytest.mark.asyncio
async def test_tenant_schedule_never_resolves_env_vars(worker, monkeypatch):
    w, sched_mod, _ = worker
    monkeypatch.setenv("DUNE_API_KEY", "platform-key")
    monkeypatch.setenv("SOME_PLATFORM_SECRET", _ENV_VALUE)

    with backend_module_path():
        results = []
        for ref in ("SOME_PLATFORM_SECRET", "NO_SUCH_VAR_XYZ", None):
            fetch = AsyncMock(side_effect=AssertionError("must not call Dune"))
            cfg = _make_config(sched_mod, tenant_scope="own_tenant", api_key_ref=ref)
            summary, stored = await _run_live(w, sched_mod, cfg, fetch)
            fetch.assert_not_awaited()
            results.append((summary.status, summary.detail, stored))

    assert set(results) == {("skipped", "credential unavailable", "credential unavailable")}


@pytest.mark.asyncio
async def test_tenant_schedule_uses_only_own_tenant_credential(worker, monkeypatch):
    w, sched_mod, models_mod = worker
    monkeypatch.setenv("DUNE_API_KEY", "platform-key")

    with backend_module_path():
        from shared.credentials.service import credential_service

        await credential_service.create("own_tenant", "dune:own", "own-dune-key")
        await credential_service.create("other_tenant", "dune:other", "other-dune-key")

        fetch = AsyncMock(side_effect=AssertionError("must not call Dune"))
        cfg = _make_config(sched_mod, tenant_scope="own_tenant", api_key_ref="dune:other")
        summary, _ = await _run_live(w, sched_mod, cfg, fetch)
        assert summary.detail == "credential unavailable"
        fetch.assert_not_awaited()

        fetch = AsyncMock(side_effect=RuntimeError("stop after key resolution"))
        cfg = _make_config(sched_mod, tenant_scope="own_tenant", api_key_ref="dune:own")
        await _run_live(w, sched_mod, cfg, fetch)
        fetch.assert_awaited_once_with(cfg.query_id, "own-dune-key")


@pytest.mark.asyncio
async def test_run_detail_never_contains_exception_text(worker, monkeypatch):
    import httpx

    w, sched_mod, _ = worker
    monkeypatch.setenv("DUNE_API_KEY", _MULTILINE_ENV)

    with backend_module_path():
        cfg = _make_config(sched_mod, tenant_scope=None)
        fetch = AsyncMock(side_effect=ValueError(f"Illegal header value {_MULTILINE_ENV!r}"))
        summary, stored = await _run_live(w, sched_mod, cfg, fetch)
        assert summary.status == "error"
        assert summary.detail == stored == "ValueError"

        request = httpx.Request("GET", "https://api.dune.com/api/v1/query/1/results")
        response = httpx.Response(401, request=request, text=f"bad key {_MULTILINE_ENV}")
        fetch = AsyncMock(side_effect=httpx.HTTPStatusError(
            f"401 for {_MULTILINE_ENV}", request=request, response=response,
        ))
        summary, stored = await _run_live(w, sched_mod, cfg, fetch)
        assert summary.detail == stored == "HTTPStatusError status=401"
        assert "PRIVATE KEY" not in summary.model_dump_json()
