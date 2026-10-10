"""Regression: ``BaseRepository._ensure_table`` must be race-safe.

At lean-worker startup the reward delivery outbox (and the reward DLQ sweeper,
and the API's identity resolver) logged::

    duplicate key value violates unique constraint "pg_class_relname_nsp_index"
    DETAIL: Key (relname, relnamespace)=(idx_reward_delivery_jobs_tenant, 2200)
    already exists.

Postgres ``CREATE TABLE/INDEX IF NOT EXISTS`` checks for the relation and then
creates it without holding a lock across the two steps, so concurrent
bootstrap from several repository instances (each worker loop and the API
build their own) raced on the catalog's unique index. Worse, on a migrated
database the table already exists (``20260828_reward_delivery_tables`` owns it,
with ``ix_reward_delivery_jobs_tenant``), so the runtime DDL only ever added a
redundant duplicate ``idx_*`` index.

``_CatalogPool`` models exactly that non-atomic check-then-create, plus
transaction-scoped advisory locks.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from repositories.repos import BaseRepository


class _DuplicateRelation(Exception):
    pass


class _Transaction:
    def __init__(self, conn: "_CatalogConn") -> None:
        self.conn = conn

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        for lock in self.conn.held:
            lock.release()
        self.conn.held.clear()


class _CatalogConn:
    def __init__(self, pool: "_CatalogPool") -> None:
        self.pool = pool
        self.held: list[asyncio.Lock] = []

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def execute(self, query: str, *args: Any) -> str:
        if "pg_advisory_xact_lock" in query:
            lock = self.pool.advisory.setdefault(args[0], asyncio.Lock())
            await lock.acquire()
            self.held.append(lock)
            return "SELECT 1"
        return await self.pool.execute(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        assert "to_regclass" in query
        return args[0] in self.pool.relations


class _Acquire:
    def __init__(self, pool: "_CatalogPool") -> None:
        self.conn = _CatalogConn(pool)

    async def __aenter__(self) -> _CatalogConn:
        return self.conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _CatalogPool:
    def __init__(self, relations: set[str] | None = None) -> None:
        self.relations: set[str] = set(relations or ())
        self.advisory: dict[str, asyncio.Lock] = {}
        self.ddl: list[str] = []

    def acquire(self) -> _Acquire:
        return _Acquire(self)

    async def execute(self, query: str, *args: Any) -> str:
        match = re.search(
            r"CREATE (?:TABLE|INDEX) IF NOT EXISTS (\w+)", query
        )
        if not match:
            return "OK"
        name = match.group(1)
        self.ddl.append(name)
        if name in self.relations:
            return "CREATE"  # NOTICE: relation already exists, skipping
        # Postgres releases control between the existence check and the
        # catalog insert — a concurrent creator can land in between.
        await asyncio.sleep(0)
        if name in self.relations:
            raise _DuplicateRelation(
                'duplicate key value violates unique constraint '
                f'"pg_class_relname_nsp_index" ({name})'
            )
        self.relations.add(name)
        return "CREATE"


class _JobsRepo(BaseRepository):
    def __init__(self, pool: _CatalogPool) -> None:
        super().__init__("reward_delivery_jobs")
        self._pool = pool


@pytest.mark.asyncio
async def test_concurrent_bootstrap_on_fresh_db_does_not_race():
    pool = _CatalogPool()
    repos = [_JobsRepo(pool) for _ in range(8)]

    results = await asyncio.gather(
        *(r._ensure_table() for r in repos), return_exceptions=True
    )

    assert [r for r in results if isinstance(r, Exception)] == []
    assert {"reward_delivery_jobs", "idx_reward_delivery_jobs_tenant"} <= pool.relations
    # Serialized: the first holder created both relations, later holders saw
    # the table and issued no DDL at all.
    assert pool.ddl == ["reward_delivery_jobs", "idx_reward_delivery_jobs_tenant"]


@pytest.mark.asyncio
async def test_migration_owned_table_gets_no_runtime_ddl():
    # ``20260828_reward_delivery_tables`` already created the table and its
    # ``ix_reward_delivery_jobs_tenant`` index.
    pool = _CatalogPool({"reward_delivery_jobs", "ix_reward_delivery_jobs_tenant"})

    await asyncio.gather(*(_JobsRepo(pool)._ensure_table() for _ in range(4)))

    assert pool.ddl == []
    assert "idx_reward_delivery_jobs_tenant" not in pool.relations


@pytest.mark.asyncio
async def test_ensure_table_runs_once_per_instance():
    pool = _CatalogPool()
    repo = _JobsRepo(pool)

    await repo._ensure_table()
    await repo._ensure_table()

    assert pool.ddl == ["reward_delivery_jobs", "idx_reward_delivery_jobs_tenant"]
