"""In-memory behaviour of the client-sync feed repository + read service."""
from __future__ import annotations

import asyncio

import pytest

from repositories.client_sync_repo import (
    get_client_sync_repository,
    reset_client_sync_memory,
)
from services.client_sync import service as sync_service

A = "t:tenant-a"
B = "t:tenant-b"


def _run(coro):
    return asyncio.run(coro)


def _emit(repo, scope, ctype="continuation_changed", rid="c1", src=None):
    return repo.enqueue(
        scope_key=scope, principal_id="user-1", change_type=ctype,
        resource_kind="continuation", resource_id=rid, revision="1", source_event_id=src,
    )


@pytest.fixture(autouse=True)
def _clean():
    reset_client_sync_memory()
    yield
    reset_client_sync_memory()


def test_enqueue_allocates_monotonic_seq():
    repo = get_client_sync_repository()
    a = _run(_emit(repo, A, rid="c1"))
    b = _run(_emit(repo, A, rid="c2"))
    assert a["seq"] == 1
    assert b["seq"] == 2
    assert b["resource_id"] == "c2"


def test_enqueue_idempotent_on_source_event_id():
    repo = get_client_sync_repository()
    first = _run(_emit(repo, A, src="evt-1"))
    dup = _run(_emit(repo, A, src="evt-1"))
    assert first is not None
    assert dup is None  # deduped, no new row
    assert _run(repo.max_seq(A)) == 1


def test_read_since_filters_by_seq():
    repo = get_client_sync_repository()
    _run(_emit(repo, A, rid="c1"))
    _run(_emit(repo, A, rid="c2"))
    _run(_emit(repo, A, rid="c3"))
    rows = _run(repo.read_since(A, cursor_seq=1, limit=200))
    assert [r["resource_id"] for r in rows] == ["c2", "c3"]


def test_scope_isolation():
    repo = get_client_sync_repository()
    _run(_emit(repo, A, rid="a1"))
    _run(_emit(repo, B, rid="b1"))
    a_rows = _run(repo.read_since(A, 0, 200))
    b_rows = _run(repo.read_since(B, 0, 200))
    assert [r["resource_id"] for r in a_rows] == ["a1"]
    assert [r["resource_id"] for r in b_rows] == ["b1"]
    # Each scope has its own seq counter starting at 1.
    assert a_rows[0]["seq"] == 1 and b_rows[0]["seq"] == 1


def test_service_read_returns_cursor_and_events():
    repo = get_client_sync_repository()
    _run(_emit(repo, A, rid="c1"))
    _run(_emit(repo, A, rid="c2"))
    resp = _run(sync_service.read(A, cursor=None, limit=200))
    assert len(resp["events"]) == 2
    assert resp["reset"] is False
    assert resp["cursor"].endswith(":2")
    # Resume from the returned cursor → no repeats.
    resp2 = _run(sync_service.read(A, cursor=resp["cursor"], limit=200))
    assert resp2["events"] == []


def test_service_read_only_10_change_types_accepted():
    """The feed never emits an out-of-contract change type."""
    from shared.client_sync.models import SYNC_CHANGE_TYPES
    repo = get_client_sync_repository()
    _run(repo.enqueue(scope_key=A, principal_id="u", change_type="continuation_changed"))
    resp = _run(sync_service.read(A, cursor=None))
    assert resp["events"][0]["change_type"] in SYNC_CHANGE_TYPES
