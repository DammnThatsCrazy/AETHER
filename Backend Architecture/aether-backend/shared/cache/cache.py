"""
Aether Shared — @aether/cache
Redis client wrapper, cache key conventions, TTL management, cache invalidation.
Used by all services with caching needs.

Production: connects to Redis via REDIS_HOST/REDIS_PORT env vars.
Local/dev: falls back to in-memory dict when AETHER_ENV=local.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from enum import IntEnum
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.cache")

# Optional Redis import — graceful degradation if not installed
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False

# Optional boto3 import (used for DynamoDB cache backend)
try:
    import boto3 as _boto3_cache
    BOTO3_CACHE_AVAILABLE = True
except ImportError:
    _boto3_cache = None  # type: ignore[assignment]
    BOTO3_CACHE_AVAILABLE = False


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
    def prediction(model_name: str, entity_id: str,
                   artifact_version: str = "", contract_hash: str = "") -> str:
        if artifact_version or contract_hash:
            return f"aether:ml:prediction:{model_name}:{entity_id}:{artifact_version}:{contract_hash}"
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
    def api_key(key_hash: str) -> str:
        """Cache key for API key validation lookups."""
        return f"aether:auth:apikey:{key_hash}"

    @staticmethod
    def hash_query(query: str) -> str:
        return hashlib.sha256(query.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _redis_url() -> str:
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    password = os.getenv("REDIS_PASSWORD", "")
    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND (local/dev only)
# ═══════════════════════════════════════════════════════════════════════════

class _InMemoryBackend:
    """Dict-based cache for local development. NOT for production."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, Optional[float]]] = {}

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

    async def set(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> None:
        expires_at = time.time() + ttl if ttl > 0 else None
        self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> int:
        prefix = pattern.rstrip("*")
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    async def exists(self, key: str) -> bool:
        return not self._is_expired(key)

    async def set_nx(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> bool:
        """Set key only if it does not exist. Returns True if claimed, False if already set."""
        if not self._is_expired(key):
            return False
        expires_at = time.time() + ttl if ttl > 0 else None
        self._store[key] = (value, expires_at)
        return True

    async def incr(self, key: str, ttl: int = 60) -> int:
        if self._is_expired(key):
            expires_at = time.time() + ttl if ttl > 0 else None
            self._store[key] = ("1", expires_at)
            return 1
        entry = self._store[key]
        new_val = int(entry[0]) + 1
        self._store[key] = (str(new_val), entry[1])
        return new_val

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._store.clear()


# ═══════════════════════════════════════════════════════════════════════════
# REDIS BACKEND (production)
# ═══════════════════════════════════════════════════════════════════════════

class _RedisBackend:
    """Real Redis backend using redis.asyncio."""

    def __init__(self, url: str) -> None:
        if not REDIS_AVAILABLE:
            raise RuntimeError(
                "redis package not installed. Install with: pip install redis>=5.0"
            )
        self._url = url
        self._client: Optional[aioredis.Redis] = None  # type: ignore[name-defined]

    async def _ensure_connected(self) -> aioredis.Redis:  # type: ignore[name-defined]
        if self._client is None:
            self._client = aioredis.from_url(  # type: ignore[union-attr]
                self._url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        return self._client

    async def get(self, key: str) -> Optional[str]:
        client = await self._ensure_connected()
        return await client.get(key)

    async def set(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> None:
        client = await self._ensure_connected()
        if ttl > 0:
            await client.setex(key, ttl, value)
        else:
            await client.set(key, value)

    async def delete(self, key: str) -> None:
        client = await self._ensure_connected()
        await client.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        client = await self._ensure_connected()
        count = 0
        async for key in client.scan_iter(match=pattern, count=100):
            await client.delete(key)
            count += 1
        return count

    async def exists(self, key: str) -> bool:
        client = await self._ensure_connected()
        return bool(await client.exists(key))

    async def set_nx(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> bool:
        """Set key only if it does not exist. Returns True if claimed, False if already set."""
        client = await self._ensure_connected()
        result = await client.set(key, value, nx=True, ex=ttl)
        return bool(result)

    async def incr(self, key: str, ttl: int = 60) -> int:
        client = await self._ensure_connected()
        pipe = client.pipeline()
        pipe.incr(key)
        if ttl > 0:
            pipe.expire(key, ttl)
        results = await pipe.execute()
        return results[0]

    async def ping(self) -> bool:
        try:
            client = await self._ensure_connected()
            return await client.ping()
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None


# ═══════════════════════════════════════════════════════════════════════════
# DYNAMODB BACKEND (alternative production backend)
# ═══════════════════════════════════════════════════════════════════════════

class _DynamoDBBackend:
    """DynamoDB-backed cache using sync boto3 wrapped in asyncio executor.

    Table schema:
      PK  cache_key  (String)
      val            (String)  — stored value
      cnt            (Number)  — used by incr
      ttl            (Number)  — DynamoDB TTL attribute (epoch seconds)
    """

    def __init__(self, table_name: str) -> None:
        if not BOTO3_CACHE_AVAILABLE:
            raise RuntimeError(
                "boto3 not installed. Install with: pip install boto3>=1.34.0"
            )
        self._table_name = table_name
        self._table: Optional[Any] = None

    def _get_table(self) -> Any:
        if self._table is None:
            resource = _boto3_cache.resource("dynamodb")  # type: ignore[union-attr]
            self._table = resource.Table(self._table_name)
        return self._table

    async def _run(self, fn: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    async def get(self, key: str) -> Optional[str]:
        now = int(time.time())
        response = await self._run(
            lambda: self._get_table().get_item(Key={"cache_key": key})
        )
        item = response.get("Item")
        if item is None:
            return None
        ttl_val = item.get("ttl")
        if ttl_val is not None and int(ttl_val) < now:
            return None
        return item.get("val")

    async def set(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> None:
        expires_at = int(time.time()) + ttl if ttl > 0 else None
        item: dict[str, Any] = {"cache_key": key, "val": value}
        if expires_at is not None:
            item["ttl"] = expires_at
        await self._run(lambda: self._get_table().put_item(Item=item))

    async def delete(self, key: str) -> None:
        await self._run(
            lambda: self._get_table().delete_item(Key={"cache_key": key})
        )

    async def delete_pattern(self, pattern: str) -> int:
        # DynamoDB has no native pattern scan; perform a full scan with filter
        prefix = pattern.rstrip("*")
        loop = asyncio.get_event_loop()

        def _scan_and_delete() -> int:
            table = self._get_table()
            count = 0
            last_key = None
            while True:
                kwargs: dict[str, Any] = {
                    "ProjectionExpression": "cache_key",
                    "FilterExpression": "begins_with(cache_key, :pfx)",
                    "ExpressionAttributeValues": {":pfx": prefix},
                }
                if last_key:
                    kwargs["ExclusiveStartKey"] = last_key
                resp = table.scan(**kwargs)
                for item in resp.get("Items", []):
                    table.delete_item(Key={"cache_key": item["cache_key"]})
                    count += 1
                last_key = resp.get("LastEvaluatedKey")
                if not last_key:
                    break
            return count

        return await loop.run_in_executor(None, _scan_and_delete)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def incr(self, key: str, ttl: int = 60) -> int:
        expires_at = int(time.time()) + ttl if ttl > 0 else None
        update_expr = "ADD cnt :one"
        expr_values: dict[str, Any] = {":one": 1}
        if expires_at is not None:
            update_expr += " SET #t = if_not_exists(#t, :ttl)"
            expr_values[":ttl"] = expires_at

        def _update() -> int:
            kwargs: dict[str, Any] = {
                "Key": {"cache_key": key},
                "UpdateExpression": update_expr,
                "ExpressionAttributeValues": expr_values,
                "ReturnValues": "ALL_NEW",
            }
            if expires_at is not None:
                kwargs["ExpressionAttributeNames"] = {"#t": "ttl"}
            resp = self._get_table().update_item(**kwargs)
            return int(resp["Attributes"].get("cnt", 1))

        return await asyncio.get_event_loop().run_in_executor(None, _update)

    async def ping(self) -> bool:
        try:
            await self._run(lambda: self._get_table().table_status)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        self._table = None


# ═══════════════════════════════════════════════════════════════════════════
# CACHE CLIENT (public API — auto-selects backend)
# ═══════════════════════════════════════════════════════════════════════════

class CacheClient:
    """
    Async cache client with TTL expiration.

    Backend selection:
    - AETHER_ENV=local → in-memory dict (no Redis required)
    - AETHER_ENV=staging/production → Redis (fails if unavailable)
    """

    def __init__(self) -> None:
        self._backend: Optional[_InMemoryBackend | _RedisBackend | _DynamoDBBackend] = None
        self._connected = False
        self._mode = "uninitialized"

    async def connect(self) -> None:
        """Initialize the cache backend based on environment."""
        dynamo_table = os.getenv("DYNAMODB_CACHE_TABLE", "")
        if dynamo_table and BOTO3_CACHE_AVAILABLE:
            self._backend = _DynamoDBBackend(dynamo_table)
            self._mode = "dynamodb"
            logger.info(f"Cache client connected (DynamoDB table: {dynamo_table})")
        elif _is_local_env() or not REDIS_AVAILABLE:
            if not _is_local_env() and not REDIS_AVAILABLE:
                logger.warning(
                    "Redis package not installed — using in-memory cache. "
                    "This is NOT safe for production."
                )
            self._backend = _InMemoryBackend()
            self._mode = "in-memory"
            logger.info("Cache client connected (in-memory, local mode)")
        else:
            url = _redis_url()
            self._backend = _RedisBackend(url)
            # Verify connectivity
            if not await self._backend.ping():
                if _is_local_env():
                    logger.warning("Redis not reachable — falling back to in-memory")
                    self._backend = _InMemoryBackend()
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(
                        f"Redis not reachable at {url}. "
                        "Set AETHER_ENV=local for in-memory fallback."
                    )
            else:
                self._mode = "redis"
                logger.info(f"Cache client connected (Redis at {url})")
        self._connected = True

    async def close(self) -> None:
        if self._backend:
            await self._backend.close()
        self._connected = False
        logger.info("Cache client closed")

    async def get(self, key: str) -> Optional[str]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get(key)  # type: ignore[union-attr]

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> None:
        if self._backend is None:
            await self.connect()
        await self._backend.set(key, value, ttl)  # type: ignore[union-attr]

    async def set_json(self, key: str, data: Any, ttl: int = TTL.MEDIUM) -> None:
        await self.set(key, json.dumps(data, default=str), ttl)

    async def set_nx(self, key: str, value: str, ttl: int = TTL.MEDIUM) -> bool:
        """Atomically set key only if it does not exist. Returns True if claimed."""
        if self._backend is None:
            await self.connect()
        return await self._backend.set_nx(key, value, ttl)  # type: ignore[union-attr]

    async def delete(self, key: str) -> None:
        if self._backend is None:
            await self.connect()
        await self._backend.delete(key)  # type: ignore[union-attr]

    async def delete_pattern(self, pattern: str) -> int:
        if self._backend is None:
            await self.connect()
        return await self._backend.delete_pattern(pattern)  # type: ignore[union-attr]

    async def exists(self, key: str) -> bool:
        if self._backend is None:
            await self.connect()
        return await self._backend.exists(key)  # type: ignore[union-attr]

    async def incr(self, key: str, ttl: int = 60) -> int:
        if self._backend is None:
            await self.connect()
        return await self._backend.incr(key, ttl)  # type: ignore[union-attr]

    async def health_check(self) -> bool:
        """Check if cache is reachable."""
        if self._backend is None:
            return False
        try:
            return await self._backend.ping()
        except Exception:
            return False

    @property
    def mode(self) -> str:
        return self._mode
