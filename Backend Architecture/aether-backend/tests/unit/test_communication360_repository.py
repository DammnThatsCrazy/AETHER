"""Unit tests for the Phase-3 Communication360 facts repository.

Under ``AETHER_ENV=local`` without ``DATABASE_URL``, ``get_pool()`` returns
None, so these exercise the in-memory fallback — the same semantics the SQL
path implements over ``communication360_facts``: idempotent upsert on
``(tenant_id, idempotency_key)`` (first write wins / ``DO NOTHING``),
tenant/kind/since query filtering, and fetch-by-``fact_id``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.communication360.repository import (  # noqa: E402
    Communication360FactsRepository,
    reset_local_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_store():
    reset_local_stores()
    yield
    reset_local_stores()


def _row(tenant: str, key: str, kind: str = "conversation",
         occurred_at: str = "2026-09-03T12:00:00Z", **extra) -> dict:
    row = {
        "tenant_id": tenant,
        "idempotency_key": key,
        "kind": kind,
        "occurred_at": occurred_at,
    }
    row.update(extra)
    return row


def test_upsert_is_idempotent_on_tenant_idempotency_key() -> None:
    repo = Communication360FactsRepository()
    first = _run(repo.upsert(_row(
        TENANT_A, "key-1", kind="conversation",
        payload={"conversation_id": "conv-1"},
    )))
    second = _run(repo.upsert(_row(
        TENANT_A, "key-1", kind="conversation",
        payload={"conversation_id": "conv-1-DIFFERENT"},
    )))
    # First write wins (DO NOTHING semantics) — same stored row returned.
    assert second is first
    assert second["payload"] == {"conversation_id": "conv-1"}

    rows = _run(repo.query(TENANT_A))
    assert len(rows) == 1
    assert rows[0]["payload"] == {"conversation_id": "conv-1"}


def test_upsert_defaults_fact_id_and_received_at() -> None:
    repo = Communication360FactsRepository()
    stored = _run(repo.upsert(_row(TENANT_A, "key-1", kind="information")))
    assert stored.get("fact_id")
    assert stored.get("received_at")
    fetched = _run(repo.get(TENANT_A, stored["fact_id"]))
    assert fetched is not None
    assert fetched["fact_id"] == stored["fact_id"]


def test_query_filters_by_tenant() -> None:
    repo = Communication360FactsRepository()
    _run(repo.upsert(_row(TENANT_A, "a-1", kind="conversation",
                          occurred_at="2026-09-03T10:00:00Z")))
    _run(repo.upsert(_row(TENANT_B, "b-1", kind="conversation",
                          occurred_at="2026-09-03T11:00:00Z")))
    _run(repo.upsert(_row(TENANT_A, "a-2", kind="matter",
                          occurred_at="2026-09-03T12:00:00Z")))

    rows_a = _run(repo.query(TENANT_A))
    assert {r["idempotency_key"] for r in rows_a} == {"a-1", "a-2"}
    assert all(r["tenant_id"] == TENANT_A for r in rows_a)


def test_query_filters_by_kind() -> None:
    repo = Communication360FactsRepository()
    _run(repo.upsert(_row(TENANT_A, "a-1", kind="conversation")))
    _run(repo.upsert(_row(TENANT_A, "a-2", kind="matter")))
    _run(repo.upsert(_row(TENANT_A, "a-3", kind="conversation")))

    convs = _run(repo.query(TENANT_A, kind="conversation"))
    assert {r["idempotency_key"] for r in convs} == {"a-1", "a-3"}
    matters = _run(repo.query(TENANT_A, kind="matter"))
    assert {r["idempotency_key"] for r in matters} == {"a-2"}
    none = _run(repo.query(TENANT_A, kind="commitment"))
    assert none == []


def test_query_filters_by_since_and_applies_limit() -> None:
    repo = Communication360FactsRepository()
    _run(repo.upsert(_row(TENANT_A, "a-1", kind="conversation",
                          occurred_at="2026-09-03T10:00:00Z")))
    _run(repo.upsert(_row(TENANT_A, "a-2", kind="conversation",
                          occurred_at="2026-09-03T11:00:00Z")))
    _run(repo.upsert(_row(TENANT_A, "a-3", kind="conversation",
                          occurred_at="2026-09-03T12:00:00Z")))

    since_rows = _run(repo.query(TENANT_A, kind="conversation",
                                since="2026-09-03T10:30:00Z"))
    assert {r["idempotency_key"] for r in since_rows} == {"a-2", "a-3"}

    limited = _run(repo.query(TENANT_A, kind="conversation", limit=2))
    assert [r["idempotency_key"] for r in limited] == ["a-1", "a-2"]


def test_get_returns_row_and_none_for_missing() -> None:
    repo = Communication360FactsRepository()
    stored = _run(repo.upsert(_row(TENANT_A, "a-1", kind="communication_act",
                                   actor_id="entity-1")))
    fetched = _run(repo.get(TENANT_A, stored["fact_id"]))
    assert fetched is not None
    assert fetched["actor_id"] == "entity-1"
    assert _run(repo.get(TENANT_A, "does-not-exist")) is None
    assert _run(repo.get(TENANT_B, stored["fact_id"])) is None
