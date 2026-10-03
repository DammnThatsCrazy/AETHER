"""Durable SDK integration liveness, without subject/device identifiers."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import utc_now

SDK_HEARTBEAT_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS sdk_heartbeat_status (
    tenant_id TEXT NOT NULL,
    sdk_name TEXT NOT NULL,
    tenant_app_key TEXT NOT NULL,
    sdk_version TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    heartbeat_count BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, sdk_name, tenant_app_key)
)
"""

_MEMORY_ROWS: dict[tuple[str, str, str], dict[str, Any]] = {}
_MEMORY_LOCK: Optional[asyncio.Lock] = None
_MEMORY_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _lock() -> asyncio.Lock:
    global _MEMORY_LOCK, _MEMORY_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEMORY_LOCK is None or _MEMORY_LOCK_LOOP is not loop:
        _MEMORY_LOCK = asyncio.Lock()
        _MEMORY_LOCK_LOOP = loop
    return _MEMORY_LOCK


def reset_sdk_heartbeat_status_memory() -> None:
    _MEMORY_ROWS.clear()


class SDKHeartbeatStatusRepository:
    async def record(
        self, *, tenant_id: str, sdk_name: str, tenant_app_key: str,
        sdk_version: str, received_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        seen = received_at or utc_now()
        pool = await get_pool()
        key = (tenant_id, sdk_name, tenant_app_key)
        if pool is None:
            async with _lock():
                row = _MEMORY_ROWS.get(key)
                if row is None:
                    row = {
                        "tenant_id": tenant_id,
                        "sdk_name": sdk_name,
                        "tenant_app_key": tenant_app_key,
                        "sdk_version": sdk_version,
                        "first_seen_at": seen,
                        "last_seen_at": seen,
                        "heartbeat_count": 1,
                    }
                    _MEMORY_ROWS[key] = row
                else:
                    row["sdk_version"] = sdk_version
                    row["last_seen_at"] = max(row["last_seen_at"], seen)
                    row["heartbeat_count"] += 1
                return dict(row)

        async with pool.acquire() as conn:
            await conn.execute(SDK_HEARTBEAT_STATUS_DDL)
            row = await conn.fetchrow(
                """INSERT INTO sdk_heartbeat_status
                   (tenant_id, sdk_name, tenant_app_key, sdk_version,
                    first_seen_at, last_seen_at, heartbeat_count)
                   VALUES ($1, $2, $3, $4, $5, $5, 1)
                   ON CONFLICT (tenant_id, sdk_name, tenant_app_key)
                   DO UPDATE SET sdk_version = EXCLUDED.sdk_version,
                     last_seen_at = GREATEST(sdk_heartbeat_status.last_seen_at, EXCLUDED.last_seen_at),
                     heartbeat_count = sdk_heartbeat_status.heartbeat_count + 1
                   RETURNING tenant_id, sdk_name, tenant_app_key, sdk_version,
                     first_seen_at, last_seen_at, heartbeat_count""",
                tenant_id, sdk_name, tenant_app_key, sdk_version, seen,
            )
        return dict(row)

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        pool = await get_pool()
        if pool is None:
            async with _lock():
                return [
                    dict(row) for row in _MEMORY_ROWS.values()
                    if row["tenant_id"] == tenant_id
                ]
        async with pool.acquire() as conn:
            await conn.execute(SDK_HEARTBEAT_STATUS_DDL)
            rows = await conn.fetch(
                """SELECT tenant_id, sdk_name, tenant_app_key, sdk_version,
                          first_seen_at, last_seen_at, heartbeat_count
                   FROM sdk_heartbeat_status WHERE tenant_id = $1
                   ORDER BY sdk_name, tenant_app_key""",
                tenant_id,
            )
        return [dict(row) for row in rows]


_repository: Optional[SDKHeartbeatStatusRepository] = None


def get_sdk_heartbeat_status_repository() -> SDKHeartbeatStatusRepository:
    global _repository
    if _repository is None:
        _repository = SDKHeartbeatStatusRepository()
    return _repository
