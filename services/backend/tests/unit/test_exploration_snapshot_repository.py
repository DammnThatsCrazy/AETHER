"""Atomic immutability and tenant isolation for exploration snapshots."""
from __future__ import annotations

import asyncio

import pytest

from repositories.repos import reset_in_memory_stores
from services.exploration.snapshots import ExplorationSnapshotRepository


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def test_concurrent_same_tenant_snapshot_id_has_one_creator():
    async def scenario():
        repo = ExplorationSnapshotRepository()
        results = await asyncio.gather(
            repo.create("tenant-a", "snap-1", {"result": {"nodes": []}}),
            repo.create("tenant-a", "snap-1", {"result": {"nodes": [{"id": "new"}]}}),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, ValueError) for result in results) == 1
        stored = await repo.get_scoped("tenant-a", "snap-1")
        assert stored["result"] in ({"nodes": []}, {"nodes": [{"id": "new"}]})

    _run(scenario())


def test_same_snapshot_id_is_isolated_between_tenants():
    async def scenario():
        repo = ExplorationSnapshotRepository()
        first = await repo.create("tenant-a", "snap-1", {"result": {"tenant": "a"}})
        second = await repo.create("tenant-b", "snap-1", {"result": {"tenant": "b"}})
        assert first["tenant_id"] == "tenant-a"
        assert second["tenant_id"] == "tenant-b"
        assert (await repo.get_scoped("tenant-a", "snap-1"))["result"] == {"tenant": "a"}
        assert (await repo.get_scoped("tenant-b", "snap-1"))["result"] == {"tenant": "b"}

    _run(scenario())
