"""ClickHouse client: a transport/store failure must RAISE, never look like an
empty result (Zero Silent Failure, program sec7).

The invariant under test: ``query()`` returning ``[]`` means a genuinely empty
read, never a failed read; ``insert()`` never swallows a write failure.
"""

from __future__ import annotations

import pytest

from shared.cis.clickhouse import (
    ClickHouseClient,
    ClickHouseUnavailableError,
    _InMemoryClickHouseBackend,
)


class _FailingBackend:
    async def query(self, sql, params=None):
        raise RuntimeError("clickhouse transport down")

    async def insert(self, table, rows):
        raise RuntimeError("clickhouse transport down")

    async def health_check(self):
        raise RuntimeError("down")

    async def close(self):
        return None


class _EmptyBackend:
    """A backend that is healthy but has no rows — genuine empty."""

    async def query(self, sql, params=None):
        return []

    async def insert(self, table, rows):
        return None

    async def health_check(self):
        return True

    async def close(self):
        return None


def _client_with(backend) -> ClickHouseClient:
    client = ClickHouseClient()
    client._backend = backend  # noqa: SLF001 — direct injection for unit test
    client._connected = True
    client._mode = "test"
    return client


class TestQueryFailureIsLoud:
    async def test_query_raises_on_transport_failure(self):
        client = _client_with(_FailingBackend())
        with pytest.raises(ClickHouseUnavailableError):
            await client.query("SELECT 1")

    async def test_query_never_returns_bare_list_on_failure(self):
        client = _client_with(_FailingBackend())
        with pytest.raises(ClickHouseUnavailableError):
            await client.query("SELECT 1")

    async def test_query_error_wraps_original_exception(self):
        client = _client_with(_FailingBackend())
        with pytest.raises(ClickHouseUnavailableError) as exc_info:
            await client.query("SELECT 1")
        assert isinstance(exc_info.value.__cause__, RuntimeError)


class TestInsertFailureIsLoud:
    async def test_insert_raises_on_transport_failure(self):
        client = _client_with(_FailingBackend())
        with pytest.raises(ClickHouseUnavailableError):
            await client.insert("telemetry", [{"x": 1}])

    async def test_insert_empty_rows_is_noop(self):
        client = _client_with(_FailingBackend())
        # No rows → nothing to write → no failure, no raise.
        await client.insert("telemetry", [])


class TestTrueEmptyIsDistinct:
    async def test_query_returns_list_for_genuine_empty(self):
        client = _client_with(_EmptyBackend())
        assert await client.query("SELECT * FROM x") == []

    async def test_in_memory_query_empty_for_unknown_table(self):
        backend = _InMemoryClickHouseBackend()
        assert await backend.query("SELECT * FROM missing_table") == []

    async def test_in_memory_insert_then_query_returns_rows(self):
        backend = _InMemoryClickHouseBackend()
        await backend.insert("t", [{"a": 1}])
        rows = await backend.query("SELECT * FROM t")
        assert rows == [{"a": 1}]

    async def test_in_memory_backend_never_raises_for_healthy_ops(self):
        # In-memory local backend has no failure mode — it is the true-empty path.
        client = _client_with(_InMemoryClickHouseBackend())
        await client.insert("t", [{"a": 2}])
        assert await client.query("SELECT * FROM t") == [{"a": 2}]
