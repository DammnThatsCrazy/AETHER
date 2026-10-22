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
  - Uses DynamoDB when CACHE_BACKEND=dynamodb and DYNAMODB_CACHE_TABLE is set
    (the lean/staging multi-instance-safe backend)
  - Uses Redis when REDIS_HOST or REDIS_URL is configured (multi-instance safe)
  - Falls back to in-memory with threading locks (single-instance)
  - Provides TTL-based expiration
  - Supports filtered queries by field value
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import heapq
import json
import os
import random
import secrets
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional
from urllib.parse import quote

from shared.logger.logger import get_logger

logger = get_logger("aether.store")

try:
    import boto3 as _boto3_store

    BOTO3_STORE_AVAILABLE = True
except ImportError:  # pragma: no cover - the production dependency is declared
    _boto3_store = None  # type: ignore[assignment]
    BOTO3_STORE_AVAILABLE = False


def _inmemory_allowed() -> bool:
    env = os.getenv("AETHER_ENV", "local").lower()
    return env == "local" or os.getenv("AETHER_ALLOW_INMEMORY_STORE", "0") == "1"


def _require_inmemory_allowed(store_name: str) -> None:
    if not _inmemory_allowed():
        raise RuntimeError(
            f"In-memory store '{store_name}' is disabled outside local mode. "
            "Configure Redis or set AETHER_ALLOW_INMEMORY_STORE=1 for an explicit override."
        )


def redis_url_from_env() -> str:
    """Build the Redis URL used by Terraform-managed scale profiles."""
    explicit = os.getenv("REDIS_URL", "").strip()
    if explicit:
        return explicit
    host = os.getenv("REDIS_HOST", "localhost").strip() or "localhost"
    port = os.getenv("REDIS_PORT", "6379").strip() or "6379"
    database = os.getenv("REDIS_DB", "0").strip() or "0"
    password = os.getenv("REDIS_PASSWORD", "")
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/{database}"


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

    async def find_page(
        self, *, limit: int, cursor: Optional[str] = None,
        key_prefix: str = "", **filters,
    ) -> tuple[list[dict], Optional[str], bool]:
        """Read one bounded backend page of matching records.

        This is a storage scan, not an indexed query: filters are evaluated
        within the backend page. A continuation cursor can therefore produce
        an empty page while still reporting more storage rows to scan. Backend
        scans are not snapshot-consistent. In-memory mode visits the key set to
        select a bounded page; Redis may return more keys than SCAN's COUNT
        hint, but only ``limit`` records are fetched and decoded here.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support paged scans")

    async def get_versioned(self, key: str) -> tuple[Optional[dict], Any]:
        """Read one record together with an opaque token naming its current state.

        Pass the token to :meth:`set_if_unchanged`; the write succeeds only if
        the record has not changed since this read. The token is meaningful to
        the backend that issued it and must not be inspected or persisted.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support conditional writes")

    async def set_if_unchanged(
        self, key: str, value: dict, token: Any, ttl_seconds: int = 0,
    ) -> bool:
        """Write ``value`` only if the record still matches ``token``.

        Returns ``False`` (and writes nothing) when another writer changed the
        record after :meth:`get_versioned`, including across instances.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support conditional writes")

    async def atomic_update(
        self, key: str, mutate: Callable[[Optional[dict]], dict], *,
        ttl_seconds: int = 0, max_attempts: int = 16,
    ) -> dict:
        """Read-modify-write one record without losing concurrent updates."""
        return await update_atomically(
            self, key, mutate, ttl_seconds=ttl_seconds, max_attempts=max_attempts,
        )

    @abstractmethod
    async def append_list(self, key: str, value: dict) -> None:
        ...

    @abstractmethod
    async def get_list(self, key: str, limit: int = 100) -> list[dict]:
        ...

    @abstractmethod
    async def count(self, **filters) -> int:
        ...


class StoreConflictError(RuntimeError):
    """A conditional write kept losing to concurrent writers."""


def _supports_conditional_writes(store: Any) -> bool:
    """True when the store implements conditional writes (not the base stubs).

    Duck-typed stores that only provide ``get``/``set`` are accepted too; they
    take the in-process lock fallback.
    """
    implementation = getattr(type(store), "get_versioned", None)
    return (
        implementation is not None
        and implementation is not DurableStore.get_versioned
        and hasattr(type(store), "set_if_unchanged")
    )


async def update_atomically(
    store: Any, key: str, mutate: Callable[[Optional[dict]], dict], *,
    ttl_seconds: int = 0, max_attempts: int = 16,
) -> dict:
    """Apply ``mutate`` to one record so concurrent updates are never lost.

    ``mutate`` receives a private copy of the current record (``None`` if
    absent) and returns the record to store. It must be a pure, synchronous
    function of its argument because it is retried when another writer wins.

    Stores that implement :meth:`DurableStore.get_versioned` and
    :meth:`DurableStore.set_if_unchanged` (the in-memory, Redis and DynamoDB
    stores) get an optimistic, cross-instance-safe update. A store without them
    falls back to a per-key lock, which only serializes writers inside one
    process.
    """
    if not _supports_conditional_writes(store):
        locks = store.__dict__.setdefault("_atomic_update_locks", {})
        lock = locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = await store.get(key)
            updated = mutate(copy.deepcopy(current) if current is not None else None)
            if ttl_seconds > 0:
                await store.set(key, updated, ttl_seconds)
            else:
                await store.set(key, updated)
            return updated
    for attempt in range(max_attempts):
        current, token = await store.get_versioned(key)
        updated = mutate(copy.deepcopy(current) if current is not None else None)
        if await store.set_if_unchanged(key, updated, token, ttl_seconds):
            return updated
        await asyncio.sleep(random.uniform(0, min(0.2, 0.005 * (2 ** attempt))))
    raise StoreConflictError(
        f"could not update '{key}' after {max_attempts} conflicting attempts"
    )


_MAX_FIND_PAGE_SIZE = 1_000


def _page_query_fingerprint(store_name: str, key_prefix: str, filters: dict) -> str:
    query = json.dumps(
        [store_name, key_prefix, filters], ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:20]


def _encode_page_cursor(backend: str, fingerprint: str, state: object) -> str:
    payload = json.dumps(
        {"v": 1, "b": backend, "q": fingerprint, "s": state},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_page_cursor(cursor: Optional[str], backend: str, fingerprint: str) -> object:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid durable store page cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("b") != backend
        or payload.get("q") != fingerprint
        or "s" not in payload
    ):
        raise ValueError("durable store page cursor does not match this query")
    return payload["s"]


def _page_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("durable store page limit must be a positive integer")
    return min(limit, _MAX_FIND_PAGE_SIZE)


def _redis_escape_glob(value: str) -> str:
    """Escape Redis SCAN glob metacharacters in a literal key prefix."""
    return "".join("\\" + char if char in "*?[]\\" else char for char in value)


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
        self._versions: dict[str, int] = {}
        self._lock = threading.Lock()

    async def get(self, key: str) -> Optional[dict]:
        with self._lock:
            self._expire_check(key)
            return self._data.get(key)

    async def set(self, key: str, value: dict, ttl_seconds: int = 0) -> None:
        with self._lock:
            self._data[key] = value
            self._versions[key] = self._versions.get(key, 0) + 1
            if ttl_seconds > 0:
                self._expiry[key] = time.time() + ttl_seconds

    async def get_versioned(self, key: str) -> tuple[Optional[dict], Any]:
        with self._lock:
            self._expire_check(key)
            return self._data.get(key), self._versions.get(key, 0)

    async def set_if_unchanged(
        self, key: str, value: dict, token: Any, ttl_seconds: int = 0,
    ) -> bool:
        with self._lock:
            self._expire_check(key)
            if self._versions.get(key, 0) != token:
                return False
            self._data[key] = value
            self._versions[key] = token + 1
            if ttl_seconds > 0:
                self._expiry[key] = time.time() + ttl_seconds
            return True

    async def delete(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            self._versions[key] = self._versions.get(key, 0) + 1
            return existed

    async def find(self, **filters) -> list[dict]:
        with self._lock:
            self._expire_all()
            results = []
            for record in self._data.values():
                if all(record.get(k) == v for k, v in filters.items()):
                    results.append(record)
            return results

    async def find_page(
        self, *, limit: int, cursor: Optional[str] = None,
        key_prefix: str = "", **filters,
    ) -> tuple[list[dict], Optional[str], bool]:
        page_limit = _page_limit(limit)
        fingerprint = _page_query_fingerprint(self.name, key_prefix, filters)
        state = _decode_page_cursor(cursor, "memory", fingerprint)
        after_key = str(state) if state is not None else None
        with self._lock:
            self._expire_all()
            page_keys = heapq.nsmallest(
                page_limit + 1,
                (
                    key for key in self._data
                    if key.startswith(key_prefix) and (after_key is None or key > after_key)
                ),
            )
            scanned = page_keys[:page_limit]
            rows = [
                self._data[key] for key in scanned
                if all(self._data[key].get(field) == value for field, value in filters.items())
            ]
            truncated = len(page_keys) > len(scanned)
            next_cursor = (
                _encode_page_cursor("memory", fingerprint, scanned[-1])
                if truncated and scanned else None
            )
            return rows, next_cursor, truncated

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
        self._page_state_prefix = f"{self._prefix}__page_state__:"
        self._redis = None
        # Do not construct the local fallback eagerly: InMemoryStore correctly
        # raises in hosted environments, and a Redis-backed hosted store must
        # be constructible before its first network operation.
        self._fallback: InMemoryStore | None = None
        self._init_attempted = False

        self._redis_url = redis_url or redis_url_from_env()

    def _fallback_store(self) -> InMemoryStore:
        if self._fallback is None:
            self._fallback = InMemoryStore(self.name)
        return self._fallback

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
            return await self._fallback_store().get(key)
        raw = await r.get(self._prefix + key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: dict, ttl_seconds: int = 0) -> None:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().set(key, value, ttl_seconds)
        if ttl_seconds > 0:
            await r.setex(self._prefix + key, ttl_seconds, json.dumps(value))
        else:
            await r.set(self._prefix + key, json.dumps(value))

    async def get_versioned(self, key: str) -> tuple[Optional[dict], Any]:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().get_versioned(key)
        raw = await r.get(self._prefix + key)
        return (json.loads(raw) if raw else None), raw

    async def set_if_unchanged(
        self, key: str, value: dict, token: Any, ttl_seconds: int = 0,
    ) -> bool:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().set_if_unchanged(key, value, token, ttl_seconds)
        from redis.exceptions import WatchError

        redis_key = self._prefix + key
        async with r.pipeline(transaction=True) as pipe:
            try:
                # WATCH aborts EXEC if any client writes the key after this read,
                # so the compare-and-set is atomic across API instances.
                await pipe.watch(redis_key)
                if await pipe.get(redis_key) != token:
                    await pipe.unwatch()
                    return False
                pipe.multi()
                if ttl_seconds > 0:
                    pipe.setex(redis_key, ttl_seconds, json.dumps(value))
                else:
                    pipe.set(redis_key, json.dumps(value))
                await pipe.execute()
                return True
            except WatchError:
                return False

    async def delete(self, key: str) -> bool:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().delete(key)
        return bool(await r.delete(self._prefix + key))

    async def find(self, **filters) -> list[dict]:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().find(**filters)
        # Scan all keys with prefix (production: use secondary index)
        results = []
        async for key in r.scan_iter(match=self._prefix + "*"):
            if key.startswith(self._page_state_prefix):
                continue
            raw = await r.get(key)
            if raw:
                record = json.loads(raw)
                if all(record.get(k) == v for k, v in filters.items()):
                    results.append(record)
        return results

    async def find_page(
        self, *, limit: int, cursor: Optional[str] = None,
        key_prefix: str = "", **filters,
    ) -> tuple[list[dict], Optional[str], bool]:
        page_limit = _page_limit(limit)
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().find_page(
                limit=page_limit, cursor=cursor, key_prefix=key_prefix, **filters,
            )
        fingerprint = _page_query_fingerprint(self.name, key_prefix, filters)
        state = _decode_page_cursor(cursor, "redis", fingerprint)
        pending_keys: list[str] = []
        try:
            if state is None:
                scan_cursor = 0
                pending_state_id = None
            elif isinstance(state, dict):
                scan_cursor = int(state.get("scan_cursor", 0))
                pending_state_id = state.get("pending_state_id")
                if pending_state_id is not None and (
                    not isinstance(pending_state_id, str)
                    or not pending_state_id
                    or not all(char.isalnum() or char in "-_" for char in pending_state_id)
                ):
                    raise ValueError("invalid Redis pending page state")
                if pending_state_id:
                    pending_raw = await r.get(self._page_state_prefix + pending_state_id)
                    if pending_raw is None:
                        raise ValueError("Redis page cursor state expired; restart the scan")
                    pending_keys = json.loads(pending_raw)
                    if not isinstance(pending_keys, list) or not all(
                        isinstance(key, str) for key in pending_keys
                    ):
                        raise ValueError("invalid Redis pending page state")
            else:
                # Accept cursors written by the initial v1 implementation.
                scan_cursor = int(state)
                pending_state_id = None
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Redis page cursor") from exc

        scan_pattern = self._prefix + _redis_escape_glob(key_prefix) + "*"
        next_scan_cursor = scan_cursor
        if not pending_keys:
            next_scan_cursor, keys = await r.scan(
                scan_cursor, match=scan_pattern, count=page_limit,
            )
            pending_keys = [
                key for key in keys
                if not key.startswith(self._list_prefix)
                and not key.startswith(self._page_state_prefix)
            ]
        selected_keys = pending_keys[:page_limit]
        remaining_keys = pending_keys[page_limit:]
        raw_values = await r.mget(selected_keys) if selected_keys else []
        rows = []
        for key, raw in zip(selected_keys, raw_values):
            if not raw:
                continue
            record = json.loads(raw)
            if all(record.get(field) == value for field, value in filters.items()):
                rows.append(record)
        truncated = bool(remaining_keys) or int(next_scan_cursor) != 0
        next_state: dict[str, Any] = {"scan_cursor": int(next_scan_cursor)}
        if remaining_keys:
            pending_state_id = secrets.token_urlsafe(18)
            await r.setex(
                self._page_state_prefix + pending_state_id,
                86_400,
                json.dumps(remaining_keys, separators=(",", ":")),
            )
            next_state["pending_state_id"] = pending_state_id
        next_cursor = (
            _encode_page_cursor("redis", fingerprint, next_state)
            if truncated else None
        )
        return rows, next_cursor, truncated

    async def append_list(self, key: str, value: dict) -> None:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().append_list(key, value)
        await r.rpush(self._list_prefix + key, json.dumps(value))

    async def get_list(self, key: str, limit: int = 100) -> list[dict]:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().get_list(key, limit)
        raw_items = await r.lrange(self._list_prefix + key, -limit, -1)
        return [json.loads(item) for item in raw_items]

    async def count(self, **filters) -> int:
        r = await self._get_redis()
        if r is None:
            return await self._fallback_store().count(**filters)
        if not filters:
            count = 0
            async for key in r.scan_iter(match=self._prefix + "*"):
                if not key.startswith(self._page_state_prefix):
                    count += 1
            return count
        return len(await self.find(**filters))


# =========================================================================
# DynamoDB Store (lean/staging production backend)
# =========================================================================

def _from_dynamodb_number(value):
    """Undo boto3's ``Decimal`` number representation (legacy map elements)."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamodb_number(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamodb_number(v) for v in value]
    return value


def _decode_dynamodb_list_item(item):
    """A list element is JSON text; elements written before that encoding (native
    DynamoDB maps, float-free by necessity) are still returned as plain dicts."""
    if isinstance(item, str):
        return json.loads(item)
    return _from_dynamodb_number(item)


class DynamoDBStore(DurableStore):
    """DynamoDB-backed durable store for profiles that replace Redis.

    The Terraform-managed lean/staging profiles deliberately select DynamoDB
    instead of ElastiCache Redis. ``shared.store`` must honor that same
    selector: constructing an ``InMemoryStore`` in a non-local process fails
    closed by design, which previously made the API crash during import when
    the observability trace store was initialized.

    Items share the profile's cache table but use a store-specific key prefix,
    so they cannot collide with the cache client's entries. Values are JSON
    strings in the table's existing ``val`` attribute; list values use a
    separate DynamoDB list attribute and the same namespaced key, and each list
    element is likewise a JSON string.

    Encoding list elements as JSON (exactly as ``RedisStore`` does with
    ``rpush(json.dumps(value))``) rather than as native DynamoDB maps matters:
    boto3's ``TypeSerializer`` rejects Python ``float`` ("Float types are not
    supported. Use Decimal types instead.") and would hand numbers back as
    ``Decimal``. Observability traces carry ``duration_ms`` floats, so every
    trace append failed on the staging DynamoDB backend. JSON text keeps the
    record byte-identical across the in-memory, Redis and DynamoDB stores.
    """

    def __init__(self, name: str, table_name: str):
        if not BOTO3_STORE_AVAILABLE:
            raise RuntimeError(
                "boto3 is required for the DynamoDB durable store. "
                "Install boto3>=1.34.0."
            )
        if not table_name:
            raise RuntimeError(
                f"DynamoDB table is required for durable store '{name}'. "
                "Set DYNAMODB_CACHE_TABLE."
            )
        self.name = name
        self._table_name = table_name
        self._prefix = f"aether:store:{name}:"
        self._list_prefix = f"{self._prefix}list:"
        self._table = None

    def _get_table(self):
        if self._table is None:
            self._table = _boto3_store.resource("dynamodb").Table(self._table_name)  # type: ignore[union-attr]
        return self._table

    async def _run(self, fn):
        return await asyncio.to_thread(fn)

    def _key(self, key: str) -> str:
        return self._prefix + key

    def _list_key(self, key: str) -> str:
        return self._list_prefix + key

    @staticmethod
    def _expired(item: dict) -> bool:
        ttl_value = item.get("ttl")
        return ttl_value is not None and int(ttl_value) < int(time.time())

    async def get(self, key: str) -> Optional[dict]:
        response = await self._run(
            lambda: self._get_table().get_item(Key={"cache_key": self._key(key)})
        )
        item = response.get("Item")
        if not item or self._expired(item):
            return None
        raw = item.get("val")
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: dict, ttl_seconds: int = 0) -> None:
        item = {"cache_key": self._key(key), "val": json.dumps(value)}
        if ttl_seconds > 0:
            item["ttl"] = int(time.time()) + ttl_seconds
        await self._run(lambda: self._get_table().put_item(Item=item))

    async def get_versioned(self, key: str) -> tuple[Optional[dict], Any]:
        response = await self._run(
            lambda: self._get_table().get_item(
                Key={"cache_key": self._key(key)}, ConsistentRead=True,
            )
        )
        item = response.get("Item")
        if not item:
            return None, None
        raw = item.get("val")
        # An expired or empty row still exists until DynamoDB's TTL sweep, so the
        # token must name its exact content for the conditional write to replace it.
        token = ("raw", raw)
        if self._expired(item) or not raw:
            return None, token
        return json.loads(raw), token

    async def set_if_unchanged(
        self, key: str, value: dict, token: Any, ttl_seconds: int = 0,
    ) -> bool:
        from botocore.exceptions import ClientError

        item = {"cache_key": self._key(key), "val": json.dumps(value)}
        if ttl_seconds > 0:
            item["ttl"] = int(time.time()) + ttl_seconds
        kwargs: dict[str, Any] = {}
        if token is None:
            kwargs["ConditionExpression"] = "attribute_not_exists(cache_key)"
        elif token[1] is None:
            kwargs["ConditionExpression"] = "attribute_exists(cache_key) AND attribute_not_exists(#val)"
            kwargs["ExpressionAttributeNames"] = {"#val": "val"}
        else:
            kwargs["ConditionExpression"] = "#val = :old"
            kwargs["ExpressionAttributeNames"] = {"#val": "val"}
            kwargs["ExpressionAttributeValues"] = {":old": token[1]}
        try:
            await self._run(lambda: self._get_table().put_item(Item=item, **kwargs))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    async def delete(self, key: str) -> bool:
        response = await self._run(
            lambda: self._get_table().delete_item(
                Key={"cache_key": self._key(key)},
                ReturnValues="ALL_OLD",
            )
        )
        return bool(response.get("Attributes"))

    async def find(self, **filters) -> list[dict]:
        def _scan() -> list[dict]:
            table = self._get_table()
            results: list[dict] = []
            last_key = None
            while True:
                kwargs = {
                    "ProjectionExpression": "cache_key, #value, #ttl",
                    "ExpressionAttributeNames": {"#value": "val", "#ttl": "ttl"},
                }
                if last_key:
                    kwargs["ExclusiveStartKey"] = last_key
                response = table.scan(**kwargs)
                for item in response.get("Items", []):
                    item_key = item.get("cache_key", "")
                    if not item_key.startswith(self._prefix) or item_key.startswith(self._list_prefix):
                        continue
                    if self._expired(item):
                        continue
                    raw = item.get("val")
                    if not raw:
                        continue
                    record = json.loads(raw)
                    if all(record.get(k) == v for k, v in filters.items()):
                        results.append(record)
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    return results

        return await self._run(_scan)

    async def find_page(
        self, *, limit: int, cursor: Optional[str] = None,
        key_prefix: str = "", **filters,
    ) -> tuple[list[dict], Optional[str], bool]:
        page_limit = _page_limit(limit)
        fingerprint = _page_query_fingerprint(self.name, key_prefix, filters)
        state = _decode_page_cursor(cursor, "dynamodb", fingerprint)
        if state is not None and not isinstance(state, dict):
            raise ValueError("invalid DynamoDB page cursor")

        def _scan_page() -> tuple[list[dict], Optional[dict]]:
            kwargs: dict[str, Any] = {
                "Limit": page_limit,
                "ProjectionExpression": "cache_key, #value, #ttl",
                "FilterExpression": "begins_with(#key, :prefix)",
                "ExpressionAttributeNames": {
                    "#key": "cache_key", "#value": "val", "#ttl": "ttl",
                },
                "ExpressionAttributeValues": {
                    ":prefix": self._prefix + key_prefix,
                },
            }
            if state:
                kwargs["ExclusiveStartKey"] = state
            response = self._get_table().scan(**kwargs)
            rows: list[dict] = []
            for item in response.get("Items", []):
                item_key = item.get("cache_key", "")
                if item_key.startswith(self._list_prefix) or self._expired(item):
                    continue
                raw = item.get("val")
                if not raw:
                    continue
                record = json.loads(raw)
                if all(record.get(field) == value for field, value in filters.items()):
                    rows.append(record)
            return rows, response.get("LastEvaluatedKey")

        rows, last_key = await self._run(_scan_page)
        truncated = bool(last_key)
        next_cursor = (
            _encode_page_cursor("dynamodb", fingerprint, last_key)
            if last_key else None
        )
        return rows, next_cursor, truncated

    async def append_list(self, key: str, value: dict) -> None:
        encoded = json.dumps(value)
        await self._run(
            lambda: self._get_table().update_item(
                Key={"cache_key": self._list_key(key)},
                UpdateExpression="SET #items = list_append(if_not_exists(#items, :empty), :item)",
                ExpressionAttributeNames={"#items": "items"},
                ExpressionAttributeValues={":empty": [], ":item": [encoded]},
            )
        )

    async def get_list(self, key: str, limit: int = 100) -> list[dict]:
        response = await self._run(
            lambda: self._get_table().get_item(
                Key={"cache_key": self._list_key(key)},
                ProjectionExpression="#items",
                ExpressionAttributeNames={"#items": "items"},
            )
        )
        items = (response.get("Item") or {}).get("items", [])
        items = items[-limit:] if limit > 0 else []
        return [_decode_dynamodb_list_item(item) for item in items]

    async def count(self, **filters) -> int:
        return len(await self.find(**filters))


# =========================================================================
# Store Factory
# =========================================================================

_stores: dict[str, DurableStore] = {}


def reset_in_memory_stores() -> None:
    """Test helper: empty every in-memory DurableStore in place.

    Mirrors ``repositories.repos.reset_in_memory_stores``: store singletons are
    kept (cleared in place) so cached repository references that captured a
    ``get_store`` handle at import time keep pointing at the same store and stay
    resettable. Only in-memory stores are touched — a configured Redis store is
    left alone.
    """
    for store in _stores.values():
        if isinstance(store, InMemoryStore):
            store._data.clear()
            store._lists.clear()
            store._expiry.clear()


def get_store(name: str, prefer_redis: bool = True) -> DurableStore:
    """Get or create a named durable store.

    Args:
        name: Store name (e.g., "agent_tasks", "export_jobs")
        prefer_redis: If True, use the configured hosted durable backend before
            considering the local-only in-memory implementation.

    Returns:
        A DurableStore instance (Redis-backed or in-memory).
    """
    if name not in _stores:
        dynamodb_table = os.getenv("DYNAMODB_CACHE_TABLE", "")
        cache_backend = os.getenv("CACHE_BACKEND", "").lower()
        # RedisStore connects via REDIS_URL (falling back to REDIS_HOST/PORT), so
        # honour either here — otherwise a hosted deployment that sets only the
        # common REDIS_URL silently gets an in-memory store and fails closed.
        redis_configured = os.getenv("REDIS_HOST", "") or os.getenv("REDIS_URL", "")
        if prefer_redis and cache_backend == "dynamodb" and dynamodb_table:
            _stores[name] = DynamoDBStore(name, dynamodb_table)
        elif prefer_redis and redis_configured:
            _stores[name] = RedisStore(name)
        else:
            _stores[name] = InMemoryStore(name)
            logger.info("Using in-memory store for %s", name)
    return _stores[name]
