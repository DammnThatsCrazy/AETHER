"""Measurement connector repository — durable access to measurement_connectors.

Production: asyncpg queries against the typed ``measurement_connectors`` table.
Local/test (``AETHER_ENV=local``, no pool): a module-level in-memory store shared
across instances, so ``connect`` followed by ``list``/``get``/``sync`` is
consistent. The raw-pool route handlers previously skipped the write entirely in
local mode (``if pool:``) and returned a fabricated ``connector_id`` that no
subsequent read could ever see, and swallowed INSERT failures in production —
either way reporting a connected source that was never persisted.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.connector_repo")

_IS_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"

# In-memory fallback (local/test only), keyed by "tenant_id:connector_id" so one
# tenant can never read or mutate another tenant's connector.
_local_connectors: dict[str, dict[str, Any]] = {}

_TIMESTAMP_FIELDS = (
    "last_sync_at", "last_success_at", "next_sync_at", "created_at", "updated_at",
)


def _reset_local_connectors() -> None:
    """Test helper — clear the in-memory connector store between cases."""
    _local_connectors.clear()


def _uuid_or_none(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with timestamp columns coerced to ISO strings (or None), so
    local (str) and production (datetime) rows present the same shape to callers."""
    out = dict(record)
    for field in _TIMESTAMP_FIELDS:
        if field in out:
            out[field] = _iso(out[field])
    return out


class MeasurementConnectorRepository:
    """Durable access to ``measurement_connectors`` (dual-mode: asyncpg / in-memory)."""

    async def _pool(self):
        return await get_pool()

    async def create(
        self,
        *,
        tenant_id: str,
        connector_type: str,
        name: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist a new connector and return it.

        Raises on write failure so the caller cannot return a fabricated
        ``connector_id`` for a source that was never stored.
        """
        connector_id = str(uuid4())
        now = datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "connector_id": connector_id,
            "tenant_id": tenant_id,
            "connector_type": connector_type,
            "name": name or connector_type,
            "status": "active",
            "config": dict(config or {}),
            "cursor_state": {},
            "last_sync_at": None,
            "last_success_at": None,
            "next_sync_at": None,
            "health_status": "unknown",
            "health_message": None,
            "sync_run_count": 0,
            "error_count": 0,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        pool = await self._pool()
        if pool is None:
            _local_connectors[f"{tenant_id}:{connector_id}"] = dict(record)
            return _normalize(record)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO measurement_connectors
                  (connector_id, tenant_id, connector_type, name, config, status,
                   cursor_state, health_status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'active', '{}'::jsonb, 'unknown', NOW(), NOW())
                RETURNING connector_id, tenant_id, connector_type, name, status,
                          health_status, health_message, last_sync_at, last_success_at,
                          next_sync_at, error_count, created_at, updated_at
                """,
                UUID(connector_id), tenant_id, connector_type,
                name or connector_type, json.dumps(dict(config or {})),
            )
        merged = {**record, **(dict(row) if row else {})}
        merged["connector_id"] = str(merged.get("connector_id", connector_id))
        return _normalize(merged)

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [v for v in _local_connectors.values() if v.get("tenant_id") == tenant_id]
            rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            return [_normalize(r) for r in rows]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM measurement_connectors WHERE tenant_id = $1 "
                "ORDER BY created_at DESC",
                tenant_id,
            )
        return [_normalize(dict(r)) for r in rows]

    async def get(self, tenant_id: str, connector_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            record = _local_connectors.get(f"{tenant_id}:{connector_id}")
            return _normalize(record) if record else None
        cid = _uuid_or_none(connector_id)
        if cid is None:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM measurement_connectors "
                "WHERE tenant_id = $1 AND connector_id = $2",
                tenant_id, cid,
            )
        return _normalize(dict(row)) if row else None

    async def request_sync(self, tenant_id: str, connector_id: str) -> bool:
        """Queue a sync for the connector. Returns False when it does not exist."""
        pool = await self._pool()
        if pool is None:
            record = _local_connectors.get(f"{tenant_id}:{connector_id}")
            if record is None:
                return False
            now = datetime.now(timezone.utc).isoformat()
            record["next_sync_at"] = now
            record["updated_at"] = now
            return True
        cid = _uuid_or_none(connector_id)
        if cid is None:
            return False
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT connector_id FROM measurement_connectors "
                "WHERE tenant_id = $1 AND connector_id = $2",
                tenant_id, cid,
            )
            if row is None:
                return False
            await conn.execute(
                "UPDATE measurement_connectors SET next_sync_at = NOW(), updated_at = NOW() "
                "WHERE tenant_id = $1 AND connector_id = $2",
                tenant_id, cid,
            )
        return True
