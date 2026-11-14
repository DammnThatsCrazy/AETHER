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
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = ROOT / "services" / "api"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.communication360.repository import (  # noqa: E402
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


def test_exact_subject_reference_read_is_tenant_typed_bounded_and_temporal() -> None:
    repo = Communication360FactsRepository()
    _run(
        repo.upsert(
            _row(
                TENANT_A,
                "episode-before",
                occurred_at="2026-09-03T09:59:59Z",
                received_at="2026-09-03T10:00:00Z",
                payload={"episode_id": "episode-1"},
            )
        )
    )
    _run(
        repo.upsert(
            _row(
                TENANT_A,
                "episode-singular",
                occurred_at="2026-09-03T10:15:00Z",
                received_at="2026-09-03T10:30:00Z",
                payload={"episode_id": "episode-1", "message_body": "private"},
            )
        )
    )
    _run(
        repo.upsert(
            _row(
                TENANT_A,
                "episode-plural",
                occurred_at="2026-09-03T10:30:00Z",
                received_at="2026-09-03T10:31:00Z",
                payload={"episode_ids": ["episode-1", "episode-2"]},
            )
        )
    )
    _run(
        repo.upsert(
            _row(
                TENANT_A,
                "journey-only",
                occurred_at="2026-09-03T10:15:00Z",
                received_at="2026-09-03T10:15:00Z",
                payload={"journey_id": "episode-1"},
            )
        )
    )
    _run(
        repo.upsert(
            _row(
                TENANT_B,
                "cross-tenant",
                occurred_at="2026-09-03T10:15:00Z",
                received_at="2026-09-03T10:15:00Z",
                payload={"episode_id": "episode-1"},
            )
        )
    )
    _run(
        repo.upsert(
            _row(
                TENANT_A,
                "free-text",
                occurred_at="2026-09-03T10:15:00Z",
                received_at="2026-09-03T10:15:00Z",
                payload={"description": "episode-1"},
            )
        )
    )

    rows, complete = _run(
        repo.facts_for_exact_reference(
            TENANT_A,
            "episode",
            "episode-1",
            after="2026-09-03T10:00:00Z",
            before="2026-09-03T11:00:00Z",
            received_before="2026-09-03T10:30:00Z",
        )
    )

    assert complete is True
    assert [row["idempotency_key"] for row in rows] == ["episode-singular"]
    assert "message_body" in rows[0]["payload"]  # repository preserves source evidence


def test_exact_subject_reference_read_rejects_invalid_temporal_bound() -> None:
    repo = Communication360FactsRepository()
    rows, complete = _run(
        repo.facts_for_exact_reference(
            TENANT_A,
            "journey",
            "journey-1",
            after="2026-09-03T10:00:00",  # no timezone is an invalid boundary
        )
    )
    assert rows == []
    assert complete is False


@pytest.mark.asyncio
async def test_postgres_fact_writes_bind_typed_timestamps_for_roster_batches(monkeypatch):
    class StrictTimestampConnection:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def transaction(self):
            return self

        async def execute(self, sql, *params):
            columns = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
            bound = dict(zip(columns, params))
            for field in ("occurred_at", "received_at"):
                assert isinstance(bound[field], datetime)
                assert bound[field].tzinfo is not None
                assert bound[field].utcoffset() is not None
            self.calls += 1
            return "INSERT 0 1"

    connection = StrictTimestampConnection()

    class Pool:
        def acquire(self):
            return connection

    async def database_pool():
        return Pool()

    repo = Communication360FactsRepository()
    monkeypatch.setattr(repo, "_pool", database_pool)
    first = _row(
        TENANT_A,
        "roster-1",
        kind="participant_binding",
        received_at="2026-09-03T12:01:00Z",
        payload={"role": "author"},
    )
    second = _row(
        TENANT_A,
        "roster-2",
        kind="participant_binding",
        received_at="2026-09-03T12:01:00Z",
        payload={"role": "recipient"},
    )

    await repo.upsert(first)
    await repo.upsert_many([first, second])

    assert connection.calls == 3
