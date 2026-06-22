"""Connector repository — durable access to measurement_connectors."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.connector_repo")

_local_store: dict[str, dict[str, Any]] = {}


class ConnectorRepository:
    """State and configuration store for measurement connectors."""

    async def _pool(self):
        return await get_pool()

    async def create(self, row: dict[str, Any]) -> dict[str, Any]:
        row.setdefault("connector_id", str(uuid4()))
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("status", "active")
        row.setdefault("health_status", "unknown")
        row.setdefault("config", {})
        row.setdefault("cursor_state", {})

        pool = await self._pool()
        if pool is None:
            _local_store[row["connector_id"]] = row
            return row

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO measurement_connectors (
                    connector_id, tenant_id, connector_type, name,
                    status, config, cursor_state,
                    last_sync_at, last_success_at, next_sync_at,
                    health_status, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                """,
                row.get("connector_id"), row.get("tenant_id"),
                row.get("connector_type"), row.get("name"),
                row.get("status", "active"),
                json.dumps(row.get("config", {})),
                json.dumps(row.get("cursor_state", {})),
                _parse_ts(row.get("last_sync_at")),
                _parse_ts(row.get("last_success_at")),
                _parse_ts(row.get("next_sync_at")),
                row.get("health_status", "unknown"),
                _parse_ts(row.get("created_at")),
            )
        return row

    async def get(self, tenant_id: str, connector_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            c = _local_store.get(connector_id)
            if c and c.get("tenant_id") != tenant_id:
                return None
            return c

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM measurement_connectors WHERE tenant_id=$1 AND connector_id=$2",
                tenant_id, connector_id,
            )
            return dict(row) if row else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        connector_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                c for c in _local_store.values()
                if c.get("tenant_id") == tenant_id
                and (status is None or c.get("status") == status)
                and (connector_type is None or c.get("connector_type") == connector_type)
            ]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        p = 2
        if status:
            conditions.append(f"status = ${p}")
            params.append(status)
            p += 1
        if connector_type:
            conditions.append(f"connector_type = ${p}")
            params.append(connector_type)
            p += 1

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM measurement_connectors WHERE {' AND '.join(conditions)} ORDER BY created_at DESC",
                *params,
            )
            return [dict(r) for r in rows]

    async def update_cursor(self, tenant_id: str, connector_id: str, cursor_state: dict[str, Any]) -> bool:
        pool = await self._pool()
        if pool is None:
            c = _local_store.get(connector_id)
            if c and c.get("tenant_id") == tenant_id:
                c["cursor_state"] = cursor_state
                return True
            return False

        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE measurement_connectors SET cursor_state=$1 WHERE tenant_id=$2 AND connector_id=$3",
                json.dumps(cursor_state), tenant_id, connector_id,
            )
            return result.split()[-1] != "0"

    async def record_sync(
        self,
        tenant_id: str,
        connector_id: str,
        *,
        success: bool,
        next_sync_at: Optional[datetime] = None,
        health_status: str = "healthy",
    ) -> bool:
        now = datetime.now(timezone.utc)
        pool = await self._pool()
        if pool is None:
            c = _local_store.get(connector_id)
            if c and c.get("tenant_id") == tenant_id:
                c["last_sync_at"] = now.isoformat()
                c["health_status"] = health_status
                if success:
                    c["last_success_at"] = now.isoformat()
                if next_sync_at:
                    c["next_sync_at"] = next_sync_at.isoformat()
            return True

        updates = ["last_sync_at = $3", f"health_status = $4"]
        params: list[Any] = [tenant_id, connector_id, now, health_status]
        if success:
            updates.append(f"last_success_at = $5")
            params.append(now)
        if next_sync_at:
            updates.append(f"next_sync_at = ${len(params) + 1}")
            params.append(next_sync_at)

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE measurement_connectors SET {', '.join(updates)} WHERE tenant_id=$1 AND connector_id=$2",
                *params,
            )
            return result.split()[-1] != "0"

    async def set_status(self, tenant_id: str, connector_id: str, status: str) -> bool:
        pool = await self._pool()
        if pool is None:
            c = _local_store.get(connector_id)
            if c and c.get("tenant_id") == tenant_id:
                c["status"] = status
                return True
            return False

        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE measurement_connectors SET status=$1 WHERE tenant_id=$2 AND connector_id=$3",
                status, tenant_id, connector_id,
            )
            return result.split()[-1] != "0"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)
