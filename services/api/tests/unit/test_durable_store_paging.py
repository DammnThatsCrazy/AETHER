"""Cursor paging contracts for durable key/value stores."""

from __future__ import annotations

import asyncio
import json

import shared.store as store_mod


class _OversizedScanRedis:
    """Fake Redis that deliberately ignores SCAN's COUNT hint."""

    def __init__(self) -> None:
        self.values = {
            f"aether:page-test:tenant:{index}": json.dumps(
                {"tenant_id": "tenant", "id": str(index)}
            )
            for index in range(6)
        }
        self.scan_calls = 0

    async def scan(self, cursor, *, match, count):
        self.scan_calls += 1
        if int(cursor) == 0:
            # The response is intentionally larger than COUNT=2.
            return 7, list(self.values)[:5]
        if int(cursor) == 7:
            return 0, [list(self.values)[5]]
        raise AssertionError(f"unexpected scan cursor {cursor}")

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]

    async def setex(self, key, _ttl, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def scan_iter(self, *, match):
        for key in self.values:
            if key.startswith(match[:-1]):
                yield key


def test_redis_find_page_caps_decoded_rows_and_retains_excess_scan_keys(monkeypatch):
    redis = _OversizedScanRedis()
    store = store_mod.RedisStore("page-test")

    async def get_redis():
        return redis

    monkeypatch.setattr(store, "_get_redis", get_redis)

    async def exercise():
        pages = []
        cursor = None
        while True:
            rows, cursor, truncated = await store.find_page(
                limit=2, cursor=cursor, key_prefix="tenant:", tenant_id="tenant",
            )
            assert len(rows) <= 2
            pages.extend(row["id"] for row in rows)
            if not truncated:
                assert cursor is None
                break
            assert cursor
        return pages, await store.find(tenant_id="tenant"), await store.count()

    pages, found, count = asyncio.run(exercise())
    assert pages == ["0", "1", "2", "3", "4", "5"]
    assert len(found) == count == 6
    # Pending keys from the oversized first response were served without
    # asking Redis to repeat that scan segment.
    assert redis.scan_calls == 2


def test_in_memory_find_page_uses_keyset_cursor_without_duplicate_rows():
    store = store_mod.InMemoryStore("memory-page-test")

    async def exercise():
        for index in range(5):
            await store.set(
                f"tenant:{index}", {"tenant_id": "tenant", "id": str(index)}
            )
        first, cursor, truncated = await store.find_page(
            limit=2, key_prefix="tenant:", tenant_id="tenant",
        )
        second, cursor, truncated = await store.find_page(
            limit=2, cursor=cursor, key_prefix="tenant:", tenant_id="tenant",
        )
        third, cursor, truncated = await store.find_page(
            limit=2, cursor=cursor, key_prefix="tenant:", tenant_id="tenant",
        )
        return first, second, third, cursor, truncated

    first, second, third, cursor, truncated = asyncio.run(exercise())
    assert [row["id"] for row in first + second + third] == ["0", "1", "2", "3", "4"]
    assert cursor is None
    assert truncated is False
