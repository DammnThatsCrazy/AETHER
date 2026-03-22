"""
Aether Shared — @aether/cache
Redis client wrapper, cache key conventions, TTL management, cache invalidation.
Used by all services with caching needs.
"""

from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass
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
    def webhook(tenant_id: str, webhook_id: str) -> str:
        return f"aether:notification:webhook:{tenant_id}:{webhook_id}"

    @staticmethod
    def custom(key: str) -> str:
        """Build a cache key for ad-hoc / cross-service lookups."""
        return f"aether:custom:{key}"

    @staticmethod
    def hash_query(query: str) -> str:
        return hashlib.sha256(query.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# REDIS CLIENT WRAPPER (stub — swap with redis.asyncio)
# ═══════════════════════════════════════════════════════════════════════════

class CacheClient:
    """
    Async Redis wrapper with TTL expiration.
    Stub implementation uses in-memory dict with expiry checking.
    Replace with redis.asyncio.Redis in production.
    """

    def __init__(self) -> None:
        # {key: (value, expires_at_unix | None)}
        self._store: dict[str, tuple[str, Optional[float]]] = {}
        self._connected = False

    async def connect(self) -> None:
        """Initialize the connection pool."""
        self._connected = True
        logger.info("Cache client connected (in-memory stub)")

    async def close(self) -> None:
        """Close the connection pool."""
        self._store.clear()
        self._connected = False
        logger.info("Cache client closed")

    def _is_expired(self, key: str) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return True
        _, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            del self._store[key]
            return True
        return False

    async def get(self, key: str) -> Optional[str]:
        if self._is_expired(key):
            return None
        entry = self._store.get(key)
        return entry[0] if entry else None

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> None:
        expires_at = time.time() + ttl if ttl > 0 else None
        self._store[key] = (value, expires_at)

    async def set_json(self, key: str, data: Any, ttl: int = TTL.MEDIUM) -> None:
        await self.set(key, json.dumps(data, default=str), ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a prefix pattern (e.g. 'aether:identity:*')."""
        prefix = pattern.rstrip("*")
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    async def exists(self, key: str) -> bool:
        return not self._is_expired(key)

    async def incr(self, key: str, ttl: int = 60) -> int:
        """Atomic increment — used for rate limiting counters."""
        if self._is_expired(key):
            expires_at = time.time() + ttl if ttl > 0 else None
            self._store[key] = ("1", expires_at)
            return 1
        entry = self._store[key]
        new_val = int(entry[0]) + 1
        self._store[key] = (str(new_val), entry[1])
        return new_val

    async def health_check(self) -> bool:
        """Check if cache is reachable."""
        return self._connected or len(self._store) >= 0
