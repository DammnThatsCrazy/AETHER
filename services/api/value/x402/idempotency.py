"""
Aether Service — Payment-Identifier Idempotency Store
Dedupe keyed by (tenant_id, payment_identifier).

Backend selection mirrors shared/cache:
  AETHER_ENV=local  → in-memory dict with TTL (single-process safe)
  AETHER_ENV=staging/production → Redis via shared/cache (multi-instance safe)

All public methods are async so callers are backend-agnostic.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_TTL_SECONDS = 86400  # 24h


# ── In-memory backend (local / test) ─────────────────────────────────────────

@dataclass
class _Entry:
    result: dict[str, Any]
    expires_at: float


class _InMemoryIdempotencyStore:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, _Entry] = {}

    def _key(self, tenant_id: str, payment_identifier: str) -> str:
        return f"{tenant_id}:{payment_identifier}"

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, e in self._entries.items() if e.expires_at <= now]
        for k in expired:
            del self._entries[k]

    async def record(self, tenant_id: str, payment_identifier: str, result: dict[str, Any]) -> None:
        self._purge_expired()
        self._entries[self._key(tenant_id, payment_identifier)] = _Entry(
            result=result,
            expires_at=time.time() + self._ttl,
        )

    async def lookup(self, tenant_id: str, payment_identifier: str) -> Optional[dict[str, Any]]:
        self._purge_expired()
        entry = self._entries.get(self._key(tenant_id, payment_identifier))
        return entry.result if entry else None

    def size(self) -> int:
        self._purge_expired()
        return len(self._entries)


# ── Redis backend (staging / production) ─────────────────────────────────────

class _RedisIdempotencyStore:
    """Async Redis-backed store — survives process restarts and horizontal scaling."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        from shared.cache.cache import CacheClient
        self._cache = CacheClient()
        self._ttl = ttl_seconds

    def _key(self, tenant_id: str, payment_identifier: str) -> str:
        return f"aether:x402:idempotency:{tenant_id}:{payment_identifier}"

    async def record(self, tenant_id: str, payment_identifier: str, result: dict[str, Any]) -> None:
        await self._cache.set_json(
            self._key(tenant_id, payment_identifier),
            result,
            ttl=self._ttl,
        )

    async def lookup(self, tenant_id: str, payment_identifier: str) -> Optional[dict[str, Any]]:
        return await self._cache.get_json(self._key(tenant_id, payment_identifier))


# ── Public type alias kept for backward compatibility ─────────────────────────

IdempotencyStore = _InMemoryIdempotencyStore


# ── Factory ───────────────────────────────────────────────────────────────────

_store: Optional[_InMemoryIdempotencyStore | _RedisIdempotencyStore] = None


def get_idempotency_store() -> _InMemoryIdempotencyStore | _RedisIdempotencyStore:
    global _store
    if _store is None:
        env = os.getenv("AETHER_ENV", "local").lower()
        if env in ("local", "test"):
            _store = _InMemoryIdempotencyStore()
        else:
            _store = _RedisIdempotencyStore()
    return _store


def reset_idempotency_store() -> None:
    global _store
    _store = None
