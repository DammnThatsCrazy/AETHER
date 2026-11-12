"""The local Silver repository must preserve PostgreSQL primary-key isolation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intelligence.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)


async def test_distinct_tenant_silver_ids_cannot_overwrite_each_other() -> None:
    repository = SemanticFactRepository("silver_fact_primary_key_test")
    repository._store.clear()
    original = {
        "id": "shared-memory-id",
        "tenant_id": "tenant-a",
        "subject_ref": "entity-a",
        "occurred_at": datetime(2026, 10, 21, tzinfo=timezone.utc),
        "data": {"idempotency_key": "memory:tenant-a:shared-memory-id"},
    }
    assert await repository.upsert(original) == original
    assert await repository.upsert(original) == original

    conflicting = {
        **original,
        "tenant_id": "tenant-b",
        "subject_ref": "entity-b",
        "data": {"idempotency_key": "memory:tenant-b:shared-memory-id"},
    }
    with pytest.raises(ValueError, match="semantic_fact_primary_key_conflict"):
        await repository.upsert(conflicting)

    assert repository._store["shared-memory-id"] == original
