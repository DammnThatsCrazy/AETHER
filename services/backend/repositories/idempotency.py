"""Tenant-scoped ingestion idempotency store.

Keys are always prefixed with tenant_id to prevent cross-tenant leakage.
The canonical key format is:  {tenant_id}:{event_id}:{schema_version}
"""
from __future__ import annotations

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from repositories.repos import BaseRepository

logger = get_logger("aether.repository.idempotency")


class IdempotencyRepository(BaseRepository):
    """Append-only idempotency log for ingestion events."""

    def __init__(self) -> None:
        super().__init__("ingestion_idempotency")

    async def check_and_set(self, key: str, tenant_id: str) -> bool:
        """Return True (new) and persist, or False (duplicate, no write).

        The key MUST already be prefixed with tenant_id so look-ups are
        always tenant-scoped.  Raises ValueError if tenant_id is missing
        from the key prefix to prevent accidental cross-tenant collisions.
        """
        if not key.startswith(f"{tenant_id}:"):
            raise ValueError(
                f"Idempotency key must start with tenant_id prefix. "
                f"Got key={key!r}, tenant_id={tenant_id!r}"
            )
        existing = await self.find_by_id(key)
        if existing is not None:
            return False
        await self.insert(key, {"tenant_id": tenant_id, "created_at": utc_now().isoformat()})
        return True


ingestion_idempotency_repo = IdempotencyRepository()
