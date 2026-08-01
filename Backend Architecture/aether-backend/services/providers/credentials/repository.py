"""Durable repository for provider credential versions.

Thin ``BaseRepository`` wrapper over ``provider_credential_versions`` (JSONB
store; Postgres in production, shared in-memory locally). It exposes slot-scoped
query helpers; all invariant enforcement and encryption live in the authority.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository
from services.providers.credentials.schema import CredentialState


class CredentialVersionRepo(BaseRepository):
    TABLE = "provider_credential_versions"

    def __init__(self) -> None:
        super().__init__(self.TABLE)

    async def versions_for_slot(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> list[dict]:
        """All versions of one slot, newest first."""
        return await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "provider": provider,
                "environment": environment,
                "slot_name": slot_name,
            },
            limit=500,
        )

    async def active_version(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> Optional[dict]:
        return await self._one_in_state(
            tenant_id, provider, environment, slot_name, CredentialState.ACTIVE
        )

    async def previous_version(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> Optional[dict]:
        return await self._one_in_state(
            tenant_id, provider, environment, slot_name, CredentialState.PREVIOUS
        )

    async def _one_in_state(
        self, tenant_id: str, provider: str, environment: str, slot_name: str, state: str
    ) -> Optional[dict]:
        rows = await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "provider": provider,
                "environment": environment,
                "slot_name": slot_name,
                "state": state,
            },
            limit=2,
        )
        return rows[0] if rows else None

    async def for_tenant(self, tenant_id: str) -> list[dict]:
        """All non-tombstoned versions for a tenant (connection views)."""
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        return [r for r in rows if r.get("state") != CredentialState.TOMBSTONED]

    async def next_version_number(
        self, tenant_id: str, provider: str, environment: str, slot_name: str
    ) -> int:
        rows = await self.versions_for_slot(tenant_id, provider, environment, slot_name)
        return 1 + max((int(r.get("credential_version", 0)) for r in rows), default=0)

    async def save(self, record: dict[str, Any]) -> dict:
        """Insert-or-update a full row keyed by its ``id``."""
        record_id = record["id"]
        if await self.find_by_id(record_id) is None:
            return await self.insert(record_id, record)
        return await self.update(record_id, record)


__all__ = ["CredentialVersionRepo"]
