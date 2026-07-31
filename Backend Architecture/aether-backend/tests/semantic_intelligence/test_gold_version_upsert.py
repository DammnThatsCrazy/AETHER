"""Version-checked gold upsert: a stale writer must not clobber newer state.

Gold rows were last-write-wins regardless of the payload's ``version`` /
``reducer_version`` — an old replay or an outdated reducer could silently
overwrite newer state. The repository now refuses an incoming payload that is
strictly older on the schema version, or (at equal schema version) older
within the same reducer family; anything not comparable keeps last-write-wins
(legacy rows without versions).
"""
from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
    incoming_supersedes,
)

pytestmark = pytest.mark.asyncio

_TABLE = "test_gold_version_upsert"


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()


def _fact(marker: str, *, version=None, reducer_version=None) -> dict:
    data: dict = {"marker": marker, "idempotency_key": "idem-1"}
    if version is not None:
        data["version"] = version
    if reducer_version is not None:
        data["reducer_version"] = reducer_version
    return {"id": f"row-{marker}", "tenant_id": "t1", "data": data}


async def _persisted_marker(repo: SemanticFactRepository) -> str:
    rows = list(repo._store.values())
    assert len(rows) == 1
    return rows[0]["data"]["marker"]


class TestGoldVersionCheckedUpsert:
    async def test_older_schema_version_does_not_overwrite(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("new", version=3))
        await repo.upsert(_fact("stale", version=2))
        assert await _persisted_marker(repo) == "new"

    async def test_newer_schema_version_overwrites(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("old", version=2))
        await repo.upsert(_fact("new", version=3))
        assert await _persisted_marker(repo) == "new"

    async def test_same_version_older_reducer_suffix_skipped(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("new", version=2, reducer_version="weighted-reducer.v3"))
        await repo.upsert(_fact("stale", version=2, reducer_version="weighted-reducer.v1"))
        assert await _persisted_marker(repo) == "new"

    async def test_same_version_newer_reducer_suffix_overwrites(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("old", version=2, reducer_version="weighted-reducer.v1"))
        await repo.upsert(_fact("new", version=2, reducer_version="weighted-reducer.v3"))
        assert await _persisted_marker(repo) == "new"

    async def test_reducer_version_under_semantic_delta_is_honoured(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        newer = _fact("new", version=2)
        newer["data"]["semantic_delta"] = {"reducer_version": "weighted-reducer.v3"}
        stale = _fact("stale", version=2)
        stale["data"]["semantic_delta"] = {"reducer_version": "weighted-reducer.v2"}
        await repo.upsert(newer)
        await repo.upsert(stale)
        assert await _persisted_marker(repo) == "new"

    async def test_missing_versions_keep_last_write_wins(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("first"))
        await repo.upsert(_fact("second"))
        assert await _persisted_marker(repo) == "second"

    async def test_different_reducer_families_keep_last_write_wins(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("first", version=2, reducer_version="weighted-reducer.v3"))
        await repo.upsert(_fact("second", version=2, reducer_version="episodic-reducer.v1"))
        assert await _persisted_marker(repo) == "second"

    async def test_stale_write_returns_persisted_row_not_input(self):
        repo = SemanticFactRepository(_TABLE, mode="gold")
        await repo.upsert(_fact("new", version=3))
        returned = await repo.upsert(_fact("stale", version=2))
        assert returned["data"]["marker"] == "new"

    async def test_silver_mode_unaffected(self):
        repo = SemanticFactRepository(_TABLE, mode="silver")
        await repo.upsert(_fact("first", version=2))
        await repo.upsert(_fact("second", version=3))
        # Silver is immutable observation storage: first write stands.
        assert await _persisted_marker(repo) == "first"


class TestSupersedesComparator:
    def test_unparseable_values_keep_lww(self):
        assert incoming_supersedes({"version": "x"}, {"version": 2}) is True
        assert incoming_supersedes(
            {"reducer_version": "no-suffix"}, {"reducer_version": "also-none"}
        ) is True

    def test_equal_everything_keeps_lww(self):
        row = {"version": 2, "reducer_version": "weighted-reducer.v1"}
        assert incoming_supersedes(row, dict(row)) is True
