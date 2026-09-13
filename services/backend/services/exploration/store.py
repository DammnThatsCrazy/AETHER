"""Saved-view persistence for the exploration fabric — BaseRepository JSONB.

Saved views are stored as an auto-created JSONB table (see
``repositories/repos.py``); in the local environment the store is in-memory.
Record ids are tenant-qualified (``{tenant_id}:{view_id}``) so identical view
ids never collide across tenants, and every read re-checks the tenant before
returning a row. NO alembic migration — BaseRepository owns the schema (the
convention PR 1 established for new stores).
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

_ENVELOPE_KEYS = ("created_at", "updated_at")


def _strip_envelope(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _ENVELOPE_KEYS and k != "id"}


class ExplorationViewRepository(BaseRepository):
    """Tenant-qualified saved exploration views over the JSONB base."""

    natural_id_key = "view_id"

    def __init__(self) -> None:
        super().__init__("exploration_saved_views")

    @staticmethod
    def _record_id(tenant_id: str, view_id: str) -> str:
        return f"{tenant_id}:{view_id}"

    async def get_scoped(self, tenant_id: str, view_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(self._record_id(tenant_id, view_id))
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
        self, tenant_id: str, view_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        data = {**data, "tenant_id": tenant_id, self.natural_id_key: view_id}
        record_id = self._record_id(tenant_id, view_id)
        if await self.find_by_id(record_id) is not None:
            stored = await self.update(record_id, data)
        else:
            stored = await self.insert(record_id, data)
        return _strip_envelope(stored)

    async def delete_scoped(self, tenant_id: str, view_id: str) -> bool:
        if await self.get_scoped(tenant_id, view_id) is None:
            return False
        return await self.delete(self._record_id(tenant_id, view_id))


__all__ = ["ExplorationViewRepository"]
