"""Repository for self-serve tenant activation records.

One JSONB-backed table, ``tenant_activations``, following the same
BaseRepository pattern as :mod:`services.onboarding.repositories` and
:mod:`services.kyber.ops.command_repository`. Every read filters on
``tenant_id`` — tenant isolation is inherent to this store, not layered on by
callers.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository


class ActivationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("tenant_activations")

    async def get_for_tenant(self, tenant_id: str) -> Optional[dict[str, Any]]:
        """The current activation record for a tenant, or ``None``.

        There is one live record per tenant; the newest wins if a legacy
        duplicate ever existed.
        """
        records = await self.find_many(
            filters={"tenant_id": tenant_id},
            limit=1,
            sort_by="created_at",
            sort_order="desc",
        )
        return records[0] if records else None

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)

    async def save_or_update(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist an activation record whether or not it was written before.

        The service rewrites the whole row on every transition and does not
        track prior existence; choosing insert-vs-update here keeps a transition
        from silently becoming a no-op on an unsaved record.
        """
        payload = dict(record)
        activation_id = payload["activation_id"]
        if await self.find_by_id(activation_id) is None:
            return await self.insert(activation_id, payload)
        return await self.update(activation_id, payload)
