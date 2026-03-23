"""Aether Shared cache backed by Redis in non-local environments."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from config.settings import Environment, settings
from shared.logger.logger import get_logger

logger = get_logger("aether.cache")


class TTL:
    SHORT = 60
    MEDIUM = 300
    LONG = 3600
    SESSION = 1800
    PREDICTION = 900
    PROFILE = 600
    XL = 86400
    DAY = 86400


class CacheKey:
    @staticmethod
    def profile(tenant_id: str, user_id: str) -> str:
        return f"aether:identity:profile:{tenant_id}:{user_id}"

    @staticmethod
    def identity_profile(identity_id: str) -> str:
        return f"aether:identity:profile:{identity_id}"

    @staticmethod
    def session(session_id: str) -> str:
        return f"aether:session:{session_id}"

    @staticmethod
    def session_score(session_id: str) -> str:
        return f"aether:analytics:session_score:{session_id}"

    @staticmethod
    def prediction(model: str, entity_id: str) -> str:
        return f"aether:ml:prediction:{model}:{entity_id}"

    @staticmethod
    def analytics_query(tenant_id: str, query_hash: str) -> str:
        return f"aether:analytics:query:{tenant_id}:{query_hash}"

    @staticmethod
    def rate_limit(api_key: str) -> str:
        return f"aether:ratelimit:{api_key}"

    @staticmethod
    def consent(tenant_id: str, user_id: str) -> str:
        return f"aether:consent:{tenant_id}:{user_id}"

    @staticmethod
    def webhook(tenant_id: str, webhook_id: str) -> str:
        return f"aether:notification:webhook:{tenant_id}:{webhook_id}"

    @staticmethod
    def custom(*parts: str) -> str:
        return "aether:custom:" + ":".join(parts)

    @staticmethod
    def hash_query(query: str) -> str:
        import hashlib
        return hashlib.sha256(query.encode()).hexdigest()[:16]


def _state_dir(component: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = base / "aether" / component
    path.mkdir(parents=True, exist_ok=True)
    return path


class _SQLiteCacheBackend:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _purge_if_expired(self, conn: sqlite3.Connection, key: str) -> bool:
        row = conn.execute("SELECT expires_at FROM cache_entries WHERE key = ?", (key,)).fetchone()
        if row is None:
            return True
        expires_at = row["expires_at"]
        if expires_at is not None and expires_at < time.time():
            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
            return True
        return False

    async def get(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            if self._purge_if_expired(conn, key):
                return None
            row = conn.execute("SELECT value FROM cache_entries WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    async def set(self, key: str, value: str, ttl: int) -> None:
        expires_at = time.time() + ttl if ttl > 0 else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cache_entries(key, value, expires_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
                (key, value, expires_at),
            )

    async def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))

    async def delete_pattern(self, pattern: str) -> int:
        prefix = pattern.rstrip("*")
        with self._connect() as conn:
            rows = conn.execute("SELECT key FROM cache_entries WHERE key LIKE ?", (f"{prefix}%",)).fetchall()
            conn.execute("DELETE FROM cache_entries WHERE key LIKE ?", (f"{prefix}%",))
            return len(rows)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def health_check(self) -> bool:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return True


class CacheClient:
    def __init__(self) -> None:
        self._connected = False
        self._redis = None
        self._backend = None
        self._env = settings.env

    async def connect(self) -> None:
        redis_url = os.environ.get("REDIS_URL") or settings.redis.url
        explicit_redis = bool(os.environ.get("REDIS_URL") or os.environ.get("REDIS_HOST"))
        if self._env != Environment.LOCAL and not explicit_redis:
            raise RuntimeError("REDIS_URL or REDIS_HOST must be configured in non-local environments")
        if explicit_redis:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            self._backend = "redis"
            logger.info("Cache client connected to Redis")
        else:
            self._backend = _SQLiteCacheBackend(_state_dir("cache") / "cache.sqlite3")
            logger.info("Cache client connected to local durable SQLite backend")
        self._connected = True

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
        self._redis = None
        self._connected = False

    async def get(self, key: str) -> Optional[str]:
        if self._redis is not None:
            return await self._redis.get(key)
        return await self._backend.get(key)

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> None:
        if self._redis is not None:
            if ttl > 0:
                await self._redis.setex(key, ttl, value)
            else:
                await self._redis.set(key, value)
            return
        await self._backend.set(key, value, ttl)

    async def set_json(self, key: str, data: Any, ttl: int = TTL.MEDIUM) -> None:
        await self.set(key, json.dumps(data, default=str), ttl)

    async def delete(self, key: str) -> None:
        if self._redis is not None:
            await self._redis.delete(key)
            return
        await self._backend.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        if self._redis is not None:
            count = 0
            async for key in self._redis.scan_iter(match=pattern):
                await self._redis.delete(key)
                count += 1
            return count
        return await self._backend.delete_pattern(pattern)

    async def exists(self, key: str) -> bool:
        if self._redis is not None:
            return bool(await self._redis.exists(key))
        return await self._backend.exists(key)

    async def incr(self, key: str, ttl: int = 60) -> int:
        current = await self.get(key)
        new_value = int(current or "0") + 1
        await self.set(key, str(new_value), ttl)
        return new_value

    async def health_check(self) -> bool:
        if not self._connected:
            return False
        if self._redis is not None:
            return bool(await self._redis.ping())
        return await self._backend.health_check()
