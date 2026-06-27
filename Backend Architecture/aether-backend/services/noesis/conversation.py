"""Noesis conversation persistence.

Stores a sliding window of recent query turns per (conversation_id, tenant_id)
in CacheClient (Redis in production, in-memory in dev).

- Turns are append-only; only the last _MAX_TURNS_STORED are retained.
- Conversations expire after _CONVERSATION_TTL seconds of inactivity.
- Any cache failure silently degrades (turns are not stored/retrieved).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from shared.cache.cache import CacheClient, CacheKey
from shared.logger.logger import get_logger

logger = get_logger("aether.service.noesis.conversation")

_CONVERSATION_TTL = 3600   # 1 hour inactivity expiry
_MAX_TURNS_STORED = 20     # hard cap on stored turns per conversation
_MAX_TURNS_RETURNED = 5    # default context window returned to callers


class NoesisConversationStore:
    """Append-only sliding window of Noesis conversation turns."""

    def __init__(self, cache: CacheClient | None = None) -> None:
        self._cache = cache or CacheClient()

    def _key(self, conversation_id: str, tenant_id: str) -> str:
        return CacheKey.custom(f"noesis:conv:{tenant_id}:{conversation_id}")

    async def append(
        self,
        conversation_id: str,
        tenant_id: str,
        message: str,
        intent: str,
        mode: str,
        answer: str,
    ) -> None:
        """Add a turn to the conversation. Silently no-ops on failure."""
        try:
            key = self._key(conversation_id, tenant_id)
            raw = await self._cache.get(key)
            turns: list[dict] = json.loads(raw) if raw else []
            turns.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "message": message[:500],   # cap stored message length
                "intent": intent,
                "mode": mode,
                "answer": answer[:300],     # cap stored answer length
            })
            if len(turns) > _MAX_TURNS_STORED:
                turns = turns[-_MAX_TURNS_STORED:]
            await self._cache.set(key, json.dumps(turns), ttl=_CONVERSATION_TTL)
            await self.register_conversation(conversation_id, tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis conversation append failed: {exc}")

    async def get_recent(
        self,
        conversation_id: str,
        tenant_id: str,
        n: int = _MAX_TURNS_RETURNED,
        limit: int | None = None,
    ) -> list[dict]:
        """Return up to n recent turns. Returns [] on any failure."""
        n = limit if limit is not None else n
        try:
            key = self._key(conversation_id, tenant_id)
            raw = await self._cache.get(key)
            if not raw:
                return []
            turns: list[dict] = json.loads(raw)
            return turns[-n:]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis conversation get failed: {exc}")
            return []

    def _index_key(self, tenant_id: str) -> str:
        return CacheKey.custom(f"noesis:conv:index:{tenant_id}")

    async def register_conversation(self, conversation_id: str, tenant_id: str) -> None:
        """Register a conversation ID in the tenant's conversation index."""
        try:
            key = self._index_key(tenant_id)
            raw = await self._cache.get(key)
            index: list[str] = json.loads(raw) if raw else []
            if conversation_id not in index:
                index.append(conversation_id)
                index = index[-100:]  # keep last 100 conversation IDs
            await self._cache.set(key, json.dumps(index), ttl=_CONVERSATION_TTL * 24)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis conversation register failed: {exc}")

    async def list_for_tenant(self, tenant_id: str, limit: int = 20) -> list[dict]:
        """List recent conversation summaries for a tenant."""
        try:
            key = self._index_key(tenant_id)
            raw = await self._cache.get(key)
            if not raw:
                return []
            index: list[str] = json.loads(raw)
            results = []
            for conv_id in reversed(index[-limit:]):
                turns = await self.get_recent(conv_id, tenant_id, n=1)
                last = turns[-1] if turns else {}
                results.append({
                    "conversation_id": conv_id,
                    "last_message": last.get("message", ""),
                    "last_intent": last.get("intent", ""),
                    "last_ts": last.get("ts", ""),
                })
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis conversation list failed: {exc}")
            return []
