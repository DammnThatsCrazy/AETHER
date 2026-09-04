"""Exploration-session persistence — BaseRepository JSONB (mirrors saved views).

Sessions are stored as JSON — the full :class:`ExplorationSession` model dump
including the operation history. Record ids are tenant-qualified
(``{tenant_id}:{session_id}``) so identical session ids never collide across
tenants, and every read re-checks the tenant before returning a row. NO alembic
migration — BaseRepository owns the schema (the convention saved views
established).

NOTE on ``_strip_envelope``: for sessions, ``created_at`` / ``updated_at`` are
SESSION-MODEL fields (the ``ExplorationSession`` contract requires them), not
repo-envelope noise — so the strip helper removes only the repo-internal ``id``
key. ``to_session`` then rebuilds the model from the stripped record.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

from shared.exploration.models import ExplorationSession

_ENVELOPE_KEYS = ("id",)


def _strip_envelope(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _ENVELOPE_KEYS}


class ExplorationSessionRepository(BaseRepository):
    """Tenant-qualified exploration sessions over the JSONB base."""

    natural_id_key = "session_id"

    def __init__(self) -> None:
        super().__init__("exploration_sessions")

    @staticmethod
    def _record_id(tenant_id: str, session_id: str) -> str:
        return f"{tenant_id}:{session_id}"

    async def get_scoped(
        self, tenant_id: str, session_id: str
    ) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(self._record_id(tenant_id, session_id))
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return _strip_envelope(record)

    async def list_scoped(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id}, limit=limit, offset=offset
        )
        return [_strip_envelope(r) for r in rows]

    async def upsert_scoped(
        self, tenant_id: str, session_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        data = {**data, "tenant_id": tenant_id, self.natural_id_key: session_id}
        record_id = self._record_id(tenant_id, session_id)
        if await self.find_by_id(record_id) is not None:
            stored = await self.update(record_id, data)
        else:
            stored = await self.insert(record_id, data)
        return _strip_envelope(stored)

    async def delete_scoped(self, tenant_id: str, session_id: str) -> bool:
        if await self.get_scoped(tenant_id, session_id) is None:
            return False
        return await self.delete(self._record_id(tenant_id, session_id))

    @staticmethod
    def to_session(record: dict[str, Any]) -> ExplorationSession:
        """Rebuild an :class:`ExplorationSession` from a stored record."""
        return ExplorationSession.model_validate(record)


__all__ = ["ExplorationSessionRepository"]
