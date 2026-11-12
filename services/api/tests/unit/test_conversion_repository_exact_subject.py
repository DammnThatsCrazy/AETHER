"""Exact tenant/account and tenant/agent reads of canonical conversions."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")

from journeys.measurement.repositories import conversion_repo  # noqa: E402


@pytest.mark.asyncio
async def test_exact_account_and_agent_conversion_reads_keep_tenant_and_time_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_pool(_self: conversion_repo.ConversionRepository) -> None:
        return None

    monkeypatch.setattr(conversion_repo.ConversionRepository, "_pool", no_pool)
    monkeypatch.setattr(
        conversion_repo,
        "_local_store",
        {
            "first": {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-1",
                "account_id": "account-1",
                "agent_id": "agent-1",
                "occurred_at": "2026-10-01T10:00:00Z",
            },
            "second": {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-2",
                "account_id": "account-1",
                "agent_id": "agent-2",
                "occurred_at": "2026-10-02T10:00:00Z",
            },
            "other-account": {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-3",
                "account_id": "account-2",
                "agent_id": "agent-1",
                "occurred_at": "2026-10-03T10:00:00Z",
            },
            "other-tenant": {
                "tenant_id": "tenant-b",
                "conversion_id": "conversion-4",
                "account_id": "account-1",
                "agent_id": "agent-1",
                "occurred_at": "2026-10-04T10:00:00Z",
            },
        },
    )
    repository = conversion_repo.ConversionRepository()

    account_rows = await repository.list_by_account("tenant-a", "account-1", limit=3)
    agent_rows = await repository.list_by_agent("tenant-a", "agent-1", limit=3)
    bounded_rows = await repository.list_by_account(
        "tenant-a",
        "account-1",
        after_occurred=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        limit=3,
    )

    assert [row["conversion_id"] for row in account_rows] == ["conversion-1", "conversion-2"]
    assert [row["conversion_id"] for row in agent_rows] == ["conversion-1", "conversion-3"]
    assert [row["conversion_id"] for row in bounded_rows] == ["conversion-2"]
    assert [row["conversion_id"] for row in await repository.list_by_account("tenant-a", "account-1", limit=1)] == [
        "conversion-1"
    ]


@pytest.mark.asyncio
async def test_exact_subject_conversion_read_rejects_unscoped_inputs() -> None:
    repository = conversion_repo.ConversionRepository()
    with pytest.raises(ValueError, match="tenant, subject and positive limit"):
        await repository.list_by_account("", "account-1")
    with pytest.raises(ValueError, match="tenant, subject and positive limit"):
        await repository.list_by_agent("tenant-a", "", limit=1)


@pytest.mark.asyncio
async def test_exact_subject_conversion_postgres_query_filters_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, tuple[object, ...]]] = []

    class Connection:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            captured.append((sql, params))
            return []

    class Acquire:
        async def __aenter__(self) -> Connection:
            return Connection()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Pool:
        def acquire(self) -> Acquire:
            return Acquire()

    async def pool(_self: conversion_repo.ConversionRepository) -> Pool:
        return Pool()

    monkeypatch.setattr(conversion_repo.ConversionRepository, "_pool", pool)
    repository = conversion_repo.ConversionRepository()
    after = datetime(2026, 10, 1, tzinfo=timezone.utc)
    before = datetime(2026, 10, 3, tzinfo=timezone.utc)

    await repository.list_by_account(
        "tenant-a", "account-1", after_occurred=after, before_occurred=before, limit=8
    )
    await repository.list_by_agent("tenant-a", "agent-1", limit=4)

    account_sql, account_params = captured[0]
    assert "tenant_id = $1 AND account_id = $2" in account_sql
    assert "occurred_at > $3 AND occurred_at < $4" in account_sql
    assert "LIMIT $5" in account_sql
    assert account_params == ("tenant-a", "account-1", after, before, 8)
    agent_sql, agent_params = captured[1]
    assert "tenant_id = $1 AND agent_id = $2" in agent_sql
    assert "LIMIT $3" in agent_sql
    assert agent_params == ("tenant-a", "agent-1", 4)
