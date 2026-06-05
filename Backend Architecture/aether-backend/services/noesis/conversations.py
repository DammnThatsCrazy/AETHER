"""Stateless-compatible conversation persistence for Noesis."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import NotFoundError, utc_now

from .models import NoesisQueryRequest, NoesisResponse


class NoesisConversationStore:
    """Small repository wrapper around the existing JSONB/in-memory store pattern."""

    def __init__(self) -> None:
        self._repo = BaseRepository("noesis_conversations")

    async def record_turn(
        self,
        request: NoesisQueryRequest,
        response: NoesisResponse,
        effective_tenant_id: str,
    ) -> str:
        conversation_id = request.conversation_id or response.conversation_id or str(uuid.uuid4())
        now = utc_now().isoformat()
        existing = await self._repo.find_by_id(conversation_id)
        if existing and (existing.get("tenant_id") != effective_tenant_id or existing.get("surface") != request.surface):
            raise NotFoundError("Noesis conversation")
        title = request.message.strip()[:80] or "Noesis conversation"
        safe_response = response.model_dump(exclude_none=True)
        safe_response.pop("query_debug", None)
        user_message = {"role": "user", "content": request.message, "created_at": now}
        assistant_message = {
            "role": "assistant",
            "content": response.answer,
            "created_at": now,
            "response": safe_response,
        }
        if existing:
            messages = list(existing.get("messages", []))
            record = {
                **existing,
                "updated_at": now,
                "messages": [*messages, user_message, assistant_message],
            }
            await self._repo.update(conversation_id, record)
        else:
            record = {
                "conversation_id": conversation_id,
                "tenant_id": effective_tenant_id,
                "surface": request.surface,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "messages": [user_message, assistant_message],
            }
            await self._repo.insert(conversation_id, record)
        return conversation_id

    async def list_for_scope(
        self,
        *,
        surface: str,
        tenant_id: Optional[str],
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        filters: Optional[dict[str, Any]] = {"surface": surface}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        rows = await self._repo.find_many(filters=filters, limit=min(max(limit, 1), 100))
        return [self._summary(row) for row in rows]


    async def export_for_scope(
        self,
        *,
        surface: str,
        tenant_id: Optional[str],
        limit: int = 500,
    ) -> dict[str, Any]:
        filters: Optional[dict[str, Any]] = {"surface": surface}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        rows = await self._repo.find_many(filters=filters, limit=min(max(limit, 1), 1000))
        redacted = [self._redact_record(row) for row in rows]
        return {"conversations": redacted, "count": len(redacted)}

    async def delete(self, conversation_id: str, *, tenant_id: Optional[str], surface: str) -> dict[str, Any]:
        record = await self.get(conversation_id, tenant_id=tenant_id, surface=surface)
        await self._repo.delete(conversation_id)
        return {
            "deleted": True,
            "conversation_id": conversation_id,
            "tenant_id": record.get("tenant_id", ""),
            "surface": record.get("surface", surface),
        }

    def _redact_record(self, record: dict[str, Any]) -> dict[str, Any]:
        redacted = {**record}
        messages = []
        for message in record.get("messages", []):
            msg = dict(message)
            response = msg.get("response")
            if isinstance(response, dict):
                response = dict(response)
                response.pop("query_debug", None)
                msg["response"] = response
            messages.append(msg)
        redacted["messages"] = messages
        return redacted

    async def purge_expired(self, *, retention_days: int, surface: Optional[str] = None) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(retention_days, 1))
        filters = {"surface": surface} if surface else None
        rows = await self._repo.find_many(filters=filters, limit=1000)
        deleted: list[str] = []
        for row in rows:
            updated_at = str(row.get("updated_at") or row.get("created_at") or "")
            try:
                updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if updated < cutoff:
                conversation_id = str(row.get("conversation_id") or row.get("id") or "")
                if conversation_id:
                    await self._repo.delete(conversation_id)
                    deleted.append(conversation_id)
        return {"deleted": len(deleted), "conversation_ids": deleted, "retention_days": retention_days}

    async def get(self, conversation_id: str, *, tenant_id: Optional[str], surface: str) -> dict[str, Any]:
        record = await self._repo.find_by_id(conversation_id)
        if not record or record.get("surface") != surface:
            raise NotFoundError("Noesis conversation")
        if tenant_id and record.get("tenant_id") != tenant_id:
            raise NotFoundError("Noesis conversation")
        return record

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        messages = row.get("messages", [])
        return {
            "conversation_id": row.get("conversation_id", row.get("id", "")),
            "surface": row.get("surface", "aether"),
            "tenant_id": row.get("tenant_id", ""),
            "title": row.get("title", "Noesis conversation"),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
            "message_count": len(messages),
            "last_message": messages[-1].get("content", "") if messages else "",
        }
