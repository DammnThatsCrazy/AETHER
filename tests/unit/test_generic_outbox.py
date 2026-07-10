"""Tests for shared/outbox.py GenericOutboxWorker and the refactored
AgenticGraphOutboxWorker (behavior-preserving equivalence)."""

from __future__ import annotations

import asyncio
import importlib
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
def env(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        outbox_mod = importlib.import_module("shared.outbox")
        yield SimpleNamespace(repos=repos, outbox=outbox_mod)


def _iso_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _make_repo(env, table: str = "test_generic_outbox"):
    class _OutboxRepo(env.repos.BaseRepository):
        def __init__(self) -> None:
            super().__init__(table)

    return _OutboxRepo()


def _enqueue(repo, tenant_id="t1", status="queued", attempts=0, **extra) -> str:
    row_id = str(uuid.uuid4())
    row = {
        "id": row_id,
        "tenant_id": tenant_id,
        "status": status,
        "attempts": attempts,
        "payload": {"n": row_id},
        **extra,
    }
    asyncio.run(repo.insert(row_id, row))
    return row_id


def _row(repo, row_id) -> dict:
    return asyncio.run(repo.find_by_id(row_id))


# ── GenericOutboxWorker ───────────────────────────────────────────────────────

def test_drain_once_success_marks_persisted(env):
    repo = _make_repo(env)
    seen: list[str] = []

    async def sink(row: dict) -> None:
        seen.append(row["id"])

    row_id = _enqueue(repo)
    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    summary = asyncio.run(worker.drain_once())

    assert summary["processed"] == 1
    assert summary["succeeded"] == 1
    assert summary["failed"] == 0
    assert summary["dead_lettered"] == 0
    assert seen == [row_id]
    stored = _row(repo, row_id)
    assert stored["status"] == "persisted"
    assert stored["attempts"] == 1


def test_success_status_delivered(env):
    repo = _make_repo(env)

    async def sink(row: dict) -> None:
        return None

    row_id = _enqueue(repo)
    worker = env.outbox.GenericOutboxWorker(
        repo, sink, name="test", success_status="delivered"
    )
    asyncio.run(worker.drain_once())
    assert _row(repo, row_id)["status"] == "delivered"


def test_invalid_success_status_rejected(env):
    repo = _make_repo(env)

    async def sink(row: dict) -> None:
        return None

    with pytest.raises(ValueError):
        env.outbox.GenericOutboxWorker(repo, sink, success_status="done")


def test_sink_exception_marks_failed_with_backoff(env):
    repo = _make_repo(env)

    async def sink(row: dict) -> None:
        raise RuntimeError("boom")

    row_id = _enqueue(repo)
    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test", backoff_base_s=10.0)
    summary = asyncio.run(worker.drain_once())

    assert summary["failed"] == 1
    assert summary["errors"] == [f"{row_id}:RuntimeError"]
    stored = _row(repo, row_id)
    assert stored["status"] == "failed"
    assert stored["attempts"] == 1
    assert "boom" in stored["last_error"]
    next_attempt = datetime.fromisoformat(
        stored["next_attempt_at"].replace("Z", "+00:00")
    )
    assert next_attempt > datetime.now(timezone.utc)


def test_failed_row_not_retried_before_backoff_window(env):
    repo = _make_repo(env)
    calls: list[str] = []

    async def sink(row: dict) -> None:
        calls.append(row["id"])

    future = _iso_z(datetime.now(timezone.utc) + timedelta(seconds=60))
    _enqueue(repo, status="failed", attempts=1, next_attempt_at=future)
    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    summary = asyncio.run(worker.drain_once())

    assert summary["processed"] == 0
    assert calls == []


def test_failed_row_retried_after_backoff_window_elapses(env):
    repo = _make_repo(env)

    async def sink(row: dict) -> None:
        return None

    past = _iso_z(datetime.now(timezone.utc) - timedelta(seconds=5))
    row_id = _enqueue(repo, status="failed", attempts=1, next_attempt_at=past)
    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    summary = asyncio.run(worker.drain_once())

    assert summary["processed"] == 1
    assert summary["succeeded"] == 1
    stored = _row(repo, row_id)
    assert stored["status"] == "persisted"
    assert stored["attempts"] == 2


def test_dead_letter_when_attempts_exhausted(env):
    repo = _make_repo(env)
    calls: list[str] = []

    async def sink(row: dict) -> None:
        calls.append(row["id"])

    past = _iso_z(datetime.now(timezone.utc) - timedelta(seconds=5))
    row_id = _enqueue(repo, status="failed", attempts=5, next_attempt_at=past)
    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test", max_attempts=5)
    summary = asyncio.run(worker.drain_once())

    assert summary["dead_lettered"] == 1
    assert calls == []  # sink never invoked for exhausted rows
    assert _row(repo, row_id)["status"] == "dead_lettered"


def test_sink_exception_isolated_to_its_row(env):
    repo = _make_repo(env)
    bad_id = _enqueue(repo, marker="bad")
    good_id = _enqueue(repo, marker="good")

    async def sink(row: dict) -> None:
        if row.get("marker") == "bad":
            raise ValueError("bad row")

    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    summary = asyncio.run(worker.drain_once())

    assert summary["processed"] == 2
    assert summary["succeeded"] == 1
    assert summary["failed"] == 1
    assert _row(repo, bad_id)["status"] == "failed"
    assert _row(repo, good_id)["status"] == "persisted"


def test_drain_processes_oldest_first(env):
    repo = _make_repo(env)
    ids = [_enqueue(repo) for _ in range(3)]
    # Force distinct, reversed created_at stamps: newest inserted first.
    base = datetime.now(timezone.utc)
    for i, row_id in enumerate(ids):
        stored = _row(repo, row_id)
        stored["created_at"] = (base - timedelta(minutes=i)).isoformat()

    order: list[str] = []

    async def sink(row: dict) -> None:
        order.append(row["id"])

    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    asyncio.run(worker.drain_once())
    assert order == list(reversed(ids))  # oldest (last enqueued here) first


def test_tenant_scoped_drain(env):
    repo = _make_repo(env)
    t1_id = _enqueue(repo, tenant_id="t1")
    t2_id = _enqueue(repo, tenant_id="t2")

    async def sink(row: dict) -> None:
        return None

    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    summary = asyncio.run(worker.drain_once(tenant_id="t1"))

    assert summary["processed"] == 1
    assert _row(repo, t1_id)["status"] == "persisted"
    assert _row(repo, t2_id)["status"] == "queued"


def test_batch_limit_bounds_fetch(env):
    repo = _make_repo(env)
    for _ in range(5):
        _enqueue(repo)

    async def sink(row: dict) -> None:
        return None

    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    summary = asyncio.run(worker.drain_once(limit=2))
    assert summary["processed"] == 2


def test_sink_row_mutations_persisted_with_mark(env):
    repo = _make_repo(env)

    async def sink(row: dict) -> None:
        row["delivery"] = {"success": True, "message_ref": "m-1"}

    row_id = _enqueue(repo)
    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    asyncio.run(worker.drain_once())
    stored = _row(repo, row_id)
    assert stored["delivery"] == {"success": True, "message_ref": "m-1"}


def test_build_coro_returns_fresh_coroutine(env):
    repo = _make_repo(env)

    async def sink(row: dict) -> None:
        return None

    worker = env.outbox.GenericOutboxWorker(repo, sink, name="test")
    coro = worker.build_coro()
    assert asyncio.iscoroutine(coro)
    coro.close()  # not awaited in tests — it loops forever


# ── AgenticGraphOutboxWorker refactor equivalence ────────────────────────────

class _FakeGraph:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.vertices: list = []
        self.edges: list = []

    async def add_vertex(self, v) -> None:
        if self.fail:
            raise RuntimeError("graph down")
        self.vertices.append(v)

    async def add_edge(self, e) -> None:
        if self.fail:
            raise RuntimeError("graph down")
        self.edges.append(e)


def _agentic(env):
    ob_repos = importlib.import_module("repositories.agentic_observability_repos")
    ow = importlib.import_module("services.agentic_observability.outbox_worker")
    return ob_repos.AgenticProjectionOutboxRepository(), ow


def _enqueue_mutation(outbox, tenant_id="t1", mutation_type="vertex", payload=None, **extra) -> str:
    # Same row shape services/agentic_observability/pipeline.py enqueues.
    outbox_id = str(uuid.uuid4())
    asyncio.run(outbox.insert(outbox_id, {
        "outbox_id": outbox_id,
        "tenant_id": tenant_id,
        "observation_id": str(uuid.uuid4()),
        "mutation_type": mutation_type,
        "payload": payload or {},
        "status": "queued",
        "attempts": 0,
        **extra,
    }))
    return outbox_id


def test_agentic_worker_projects_vertex_and_edge(env):
    outbox, ow = _agentic(env)
    graph = _FakeGraph()
    v_id = _enqueue_mutation(outbox, payload={
        "vertex_type": "AgentObservation", "vertex_id": "v-1", "properties": {"a": 1},
    })
    e_id = _enqueue_mutation(outbox, mutation_type="edge", payload={
        "edge_type": "observed", "from_vertex_id": "v-1", "to_vertex_id": "v-2",
    })

    worker = ow.AgenticGraphOutboxWorker(outbox, graph)
    result = asyncio.run(worker.process_batch("t1"))

    assert isinstance(result, ow.AgenticOutboxWorkerResult)
    assert result.tenant_id == "t1"
    assert result.processed == 2
    assert result.persisted == 2
    assert result.failed == 0 and result.dead_lettered == 0
    assert [v.vertex_id for v in graph.vertices] == ["v-1"]
    assert [e.from_vertex_id for e in graph.edges] == ["v-1"]
    for row_id in (v_id, e_id):
        stored = asyncio.run(outbox.find_by_id(row_id))
        assert stored["status"] == "persisted"
        assert stored["attempts"] == 1


def test_agentic_worker_failure_marks_failed_with_backoff(env):
    outbox, ow = _agentic(env)
    row_id = _enqueue_mutation(outbox, payload={"vertex_id": "v-1"})

    worker = ow.AgenticGraphOutboxWorker(outbox, _FakeGraph(fail=True))
    result = asyncio.run(worker.process_batch("t1"))

    assert result.failed == 1
    assert result.errors == [f"{row_id}:RuntimeError"]
    stored = asyncio.run(outbox.find_by_id(row_id))
    assert stored["status"] == "failed"
    assert stored["attempts"] == 1
    assert stored["next_attempt_at"]  # backoff window recorded


def test_agentic_worker_dead_letters_after_max_attempts(env):
    outbox, ow = _agentic(env)
    past = _iso_z(datetime.now(timezone.utc) - timedelta(seconds=5))
    row_id = _enqueue_mutation(
        outbox, status="failed", attempts=5, next_attempt_at=past,
        payload={"vertex_id": "v-1"},
    )

    worker = ow.AgenticGraphOutboxWorker(outbox, _FakeGraph(), max_attempts=5)
    result = asyncio.run(worker.process_batch("t1"))

    assert result.dead_lettered == 1
    stored = asyncio.run(outbox.find_by_id(row_id))
    assert stored["status"] == "dead_lettered"


def test_agentic_worker_tenant_isolation(env):
    outbox, ow = _agentic(env)
    t1_row = _enqueue_mutation(outbox, tenant_id="t1", payload={"vertex_id": "v-1"})
    t2_row = _enqueue_mutation(outbox, tenant_id="t2", payload={"vertex_id": "v-2"})

    worker = ow.AgenticGraphOutboxWorker(outbox, _FakeGraph())
    result = asyncio.run(worker.process_batch("t1"))

    assert result.processed == 1
    assert asyncio.run(outbox.find_by_id(t1_row))["status"] == "persisted"
    assert asyncio.run(outbox.find_by_id(t2_row))["status"] == "queued"
