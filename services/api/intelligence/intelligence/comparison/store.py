"""Comparison workbench persistence — BaseRepository JSONB pattern.

Definitions, runs, and findings are stored as auto-created JSONB tables (see
``repositories/repos.py``); in the local environment the store is in-memory.
Record IDs are tenant-qualified (``{tenant_id}:{natural_id}``) so identical
natural ids never collide across tenants, and every read path re-checks the
tenant before returning a row. NO alembic migrations — BaseRepository owns
the schema (the convention PR 1 established for new stores).
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

# Persistence-envelope keys added by BaseRepository that are not part of the
# engine records (contract models are extra="forbid").
_ENVELOPE_KEYS = ("created_at", "updated_at")


def _strip_envelope(record: dict[str, Any], id_key: str) -> dict[str, Any]:
    """Drop BaseRepository envelope keys and the tenant-qualified ``id``.

    The natural id lives under ``id_key`` inside the payload, so the
    repository-level ``id`` (``tenant:natural``) is never leaked to callers.
    """
    return {
        k: v for k, v in record.items() if k not in _ENVELOPE_KEYS and k != "id"
    }


class TenantScopedComparisonRepository(BaseRepository):
    """Tenant-qualified IDs + tenant-checked reads over the JSONB base."""

    #: Key inside the payload that holds the natural (caller-visible) id.
    natural_id_key: str = "id"

    @staticmethod
    def _record_id(tenant_id: str, natural_id: str) -> str:
        return f"{tenant_id}:{natural_id}"

    async def get_scoped(self, tenant_id: str, natural_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(self._record_id(tenant_id, natural_id))
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return _strip_envelope(record, self.natural_id_key)

    async def list_scoped(
        self,
        tenant_id: str,
        extra_filters: Optional[dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id, **(extra_filters or {})}
        rows = await self.find_many(filters=filters, limit=limit, offset=offset)
        return [_strip_envelope(r, self.natural_id_key) for r in rows]

    async def upsert_scoped(
        self, tenant_id: str, natural_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        data = {**data, "tenant_id": tenant_id, self.natural_id_key: natural_id}
        stored = await self.insert(self._record_id(tenant_id, natural_id), data)
        return _strip_envelope(stored, self.natural_id_key)

    async def update_scoped(
        self, tenant_id: str, natural_id: str, patch: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        existing = await self.get_scoped(tenant_id, natural_id)
        if existing is None:
            return None
        stored = await self.update(self._record_id(tenant_id, natural_id), patch)
        return _strip_envelope(stored, self.natural_id_key)

    async def delete_scoped(self, tenant_id: str, natural_id: str) -> bool:
        # Guard: never delete another tenant's row via a crafted natural_id.
        if await self.get_scoped(tenant_id, natural_id) is None:
            return False
        return await self.delete(self._record_id(tenant_id, natural_id))


class ComparisonDefinitionRepository(TenantScopedComparisonRepository):
    natural_id_key = "definition_id"

    def __init__(self) -> None:
        super().__init__("comparison_definitions")


class ComparisonRunRepository(TenantScopedComparisonRepository):
    natural_id_key = "run_id"

    def __init__(self) -> None:
        super().__init__("comparison_runs")

    async def list_for_definition(
        self, tenant_id: str, definition_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self.list_scoped(
            tenant_id, {"definition_id": definition_id}, limit=limit, offset=offset
        )


class ComparisonFindingRepository(TenantScopedComparisonRepository):
    natural_id_key = "finding_id"

    def __init__(self) -> None:
        super().__init__("comparison_findings")

    async def list_for_run(
        self, tenant_id: str, run_id: str, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self.list_scoped(
            tenant_id, {"comparison_run_id": run_id}, limit=limit, offset=offset
        )


__all__ = [
    "TenantScopedComparisonRepository",
    "ComparisonDefinitionRepository",
    "ComparisonRunRepository",
    "ComparisonFindingRepository",
]
