"""
Aether Shared — Durable Key-Value Store

Provides a unified interface for in-memory, Redis, and database-backed
stores. All backend services that previously used raw dicts with threading
locks should use this abstraction instead.

Usage:
    from shared.store import get_store

    store = get_store("agent_tasks")         # auto-selects Redis if available
    await store.set("task-123", {...})
    task = await store.get("task-123")
    tasks = await store.find(tenant_id="t-001")

The store automatically:
  - Uses Redis when REDIS_HOST is configured (multi-instance safe)
  - Falls back to in-memory with threading locks (single-instance)
  - Provides TTL-based expiration
  - Supports filtered queries by field value
"""

from __future__ import annotations

import json
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.store")


def _inmemory_allowed() -> bool:
    env = os.getenv("AETHER_ENV", "local").lower()
    return env == "local" or os.getenv("AETHER_ALLOW_INMEMORY_STORE", "0") == "1"


def _require_inmemory_allowed(store_name: str) -> None:
    if not _inmemory_allowed():
        raise RuntimeError(
            f"In-memory store '{store_name}' is disabled outside local mode. "
            "Configure Redis or set AETHER_ALLOW_INMEMORY_STORE=1 for an explicit override."
        )


# =========================================================================
# Store Interface
# =========================================================================

class DurableStore(ABC):
    """Abstract interface for key-value stores."""

    @abstractmethod
    async def get(self, key: str) -> Optional[dict]:
        ...

    @abstractmethod
    async def set(self, key: str, value: dict, ttl_seconds: int = 0) -> None:
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        ...

    @abstractmethod
    async def find(self, **filters) -> list[dict]:
        ...

    @abstractmethod
    async def append_list(self, key: str, value: dict) -> None:
        ...

    @abstractmethod
    async def get_list(self, key: str, limit: int = 100) -> list[dict]:
        ...

    @abstractmethod
    async def count(self, **filters) -> int:
        ...


# =========================================================================
# In-Memory Store (single-instance, development/testing)
# =========================================================================

class InMemoryStore(DurableStore):
    """Thread-safe in-memory store with optional TTL."""

    def __init__(self, name: str):
        _require_inmemory_allowed(name)
        self.name = name
        self._data: dict[str, dict] = {}
        self._lists: dict[str, list[dict]] = {}
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()

    async def get(self, key: str) -> Optional[dict]:
        with self._lock:
            self._expire_check(key)
            return self._data.get(key)

    async def set(self, key: str, value: dict, ttl_seconds: int = 0) -> None:
        with self._lock:
            self._data[key] = value
            if ttl_seconds > 0:
                self._expiry[key] = time.time() + ttl_seconds

    async def delete(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return existed

    async def find(self, **filters) -> list[dict]:
        with self._lock:
            self._expire_all()
            results = []
            for record in self._data.values():
                if all(record.get(k) == v for k, v in filters.items()):
                    results.append(record)
            return results

    async def append_list(self, key: str, value: dict) -> None:
        with self._lock:
            self._lists.setdefault(key, []).append(value)

    async def get_list(self, key: str, limit: int = 100) -> list[dict]:
        with self._lock:
            items = self._lists.get(key, [])
            return items[-limit:]

    async def count(self, **filters) -> int:
        with self._lock:
            self._expire_all()
            if not filters:
                return len(self._data)
            return sum(
                1 for r in self._data.values()
                if all(r.get(k) == v for k, v in filters.items())
            )

    def _expire_check(self, key: str) -> None:
        if key in self._expiry and time.time() > self._expiry[key]:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    def _expire_all(self) -> None:
        now = time.time()
        expired = [k for k, exp in self._expiry.items() if now > exp]
        for k in expired:
            self._data.pop(k, None)
            self._expiry.pop(k, None)


# =========================================================================
# Redis Store (multi-instance, production)
# =========================================================================

class RedisStore(DurableStore):
    """Redis-backed store for multi-instance deployments.

    Falls back to InMemoryStore only in local mode or with explicit override.
    """

    def __init__(self, name: str, redis_url: str = ""):
        self.name = name
        self._prefix = f"aether:{name}:"
        self._list_prefix = f"aether:{name}:list:"
        self._redis = None
        self._fallback = InMemoryStore(name)
        self._init_attempted = False

        self._redis_url = redis_url or os.getenv(
            "REDIS_URL",
            f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}/0"
        )

    async def _get_redis(self):
        if self._init_attempted:
            return self._redis
        self._init_attempted = True
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("Redis store connected: %s (prefix=%s)", self._redis_url, self._prefix)
        except Exception as exc:
            if not _inmemory_allowed():
                raise RuntimeError(
                    f"Redis unavailable for store {self.name}: {exc}. "
                    "In-memory fallback is disabled outside local mode."
                ) from exc
            logger.warning("Redis unavailable for store %s, using in-memory fallback: %s", self.name, exc)
            self._redis = None
        return self._redis

    async def get(self, key: str) -> Optional[dict]:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.get(key)
        raw = await r.get(self._prefix + key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: dict, ttl_seconds: int = 0) -> None:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.set(key, value, ttl_seconds)
        if ttl_seconds > 0:
            await r.setex(self._prefix + key, ttl_seconds, json.dumps(value))
        else:
            await r.set(self._prefix + key, json.dumps(value))

    async def delete(self, key: str) -> bool:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.delete(key)
        return bool(await r.delete(self._prefix + key))

    async def find(self, **filters) -> list[dict]:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.find(**filters)
        # Scan all keys with prefix (production: use secondary index)
        results = []
        async for key in r.scan_iter(match=self._prefix + "*"):
            raw = await r.get(key)
            if raw:
                record = json.loads(raw)
                if all(record.get(k) == v for k, v in filters.items()):
                    results.append(record)
        return results

    async def append_list(self, key: str, value: dict) -> None:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.append_list(key, value)
        await r.rpush(self._list_prefix + key, json.dumps(value))

    async def get_list(self, key: str, limit: int = 100) -> list[dict]:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.get_list(key, limit)
        raw_items = await r.lrange(self._list_prefix + key, -limit, -1)
        return [json.loads(item) for item in raw_items]

    async def count(self, **filters) -> int:
        r = await self._get_redis()
        if r is None:
            return await self._fallback.count(**filters)
        if not filters:
            count = 0
            async for _ in r.scan_iter(match=self._prefix + "*"):
                count += 1
            return count
        return len(await self.find(**filters))


# =========================================================================
# Store Factory
# =========================================================================

_stores: dict[str, DurableStore] = {}


def get_store(name: str, prefer_redis: bool = True) -> DurableStore:
    """Get or create a named durable store.

    Args:
        name: Store name (e.g., "agent_tasks", "export_jobs")
        prefer_redis: If True, attempt Redis first with in-memory fallback

    Returns:
        A DurableStore instance (Redis-backed or in-memory).
    """
    if name not in _stores:
        redis_host = os.getenv("REDIS_HOST", "")
        if prefer_redis and redis_host:
            _stores[name] = RedisStore(name)
        else:
            _stores[name] = InMemoryStore(name)
            logger.info("Using in-memory store for %s", name)
    return _stores[name]
