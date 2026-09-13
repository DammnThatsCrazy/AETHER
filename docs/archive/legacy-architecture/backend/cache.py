"""
Aether Shared — @aether/cache
Redis client wrapper, cache key conventions, TTL management, cache invalidation.
Used by all services with caching needs.
"""

from __future__ import annotations

import hashlib
import json
from enum import IntEnum
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.cache")


# ═══════════════════════════════════════════════════════════════════════════
# TTL PRESETS (seconds)
# ═══════════════════════════════════════════════════════════════════════════

class TTL(IntEnum):
    SHORT = 60           # 1 minute — real-time data
    MEDIUM = 300         # 5 minutes — dashboard queries
    LONG = 3600          # 1 hour — analytics aggregations
    SESSION = 1800       # 30 minutes — user sessions
    PREDICTION = 900     # 15 minutes — ML predictions
    PROFILE = 600        # 10 minutes — identity profiles
    DAY = 86400          # 24 hours — static lookups


# ═══════════════════════════════════════════════════════════════════════════
# KEY CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════

class CacheKey:
    """
    Consistent key namespace:  aether:{service}:{resource}:{id}
    """

    @staticmethod
    def profile(tenant_id: str, user_id: str) -> str:
        return f"aether:identity:profile:{tenant_id}:{user_id}"

    @staticmethod
    def session(session_id: str) -> str:
        return f"aether:session:{session_id}"

    @staticmethod
    def prediction(model_name: str, entity_id: str) -> str:
        return f"aether:ml:prediction:{model_name}:{entity_id}"

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
    def hash_query(query: str) -> str:
        return hashlib.sha256(query.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# REDIS CLIENT WRAPPER (stub — swap with aioredis / redis-py)
# ═══════════════════════════════════════════════════════════════════════════

class CacheClient:
    """
    Async Redis wrapper. Stub implementation uses an in-memory dict.
    Replace with redis.asyncio.Redis in production.
    """

    def __init__(self):
        self._store: dict[str, tuple[Any, Optional[float]]] = {}
        # --- PRODUCTION ---
        # self._redis = redis.asyncio.Redis.from_url(settings.redis.url)

    async def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, _ = entry
        return value

    async def get_json(self, key: str) -> Optional[dict]:
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self,
        key: str,
        value: str,
        ttl: int = TTL.MEDIUM,
    ):
        self._store[key] = (value, ttl)
        logger.debug(f"Cache SET {key} (ttl={ttl}s)")

    async def set_json(self, key: str, data: dict, ttl: int = TTL.MEDIUM):
        await self.set(key, json.dumps(data), ttl)

    async def delete(self, key: str):
        self._store.pop(key, None)
        logger.debug(f"Cache DELETE {key}")

    async def delete_pattern(self, pattern: str):
        """Delete all keys matching a prefix pattern (e.g. 'aether:identity:*')."""
        prefix = pattern.rstrip("*")
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
        logger.debug(f"Cache DELETE_PATTERN {pattern} ({len(keys_to_delete)} keys)")

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def incr(self, key: str) -> int:
        """Atomic increment — used for rate limiting counters."""
        entry = self._store.get(key)
        if entry is None:
            self._store[key] = ("1", None)
            return 1
        new_val = int(entry[0]) + 1
        self._store[key] = (str(new_val), entry[1])
        return new_val
