"""Aether Shared — Quota Flusher

Periodic background task that snapshots Redis quota and overage counters
into PostgreSQL for durability and reporting.

Schema (created on first flush, idempotent):
  CREATE TABLE tenant_usage (
      id BIGSERIAL PRIMARY KEY,
      tenant_id VARCHAR(64) NOT NULL,
      billing_period VARCHAR(7) NOT NULL,
      plan_tier VARCHAR(4),
      total_requests BIGINT NOT NULL DEFAULT 0,
      overage_requests BIGINT NOT NULL DEFAULT 0,
      overage_by_service JSONB NOT NULL DEFAULT '{}',
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE(tenant_id, billing_period)
  );
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.quota.flush")

_QUOTA_KEY_RE = re.compile(r"^rl:quota:(?P<tenant>[^:]+):(?P<period>\d{4}-\d{2})$")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tenant_usage (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    billing_period VARCHAR(7) NOT NULL,
    plan_tier VARCHAR(4),
    total_requests BIGINT NOT NULL DEFAULT 0,
    overage_requests BIGINT NOT NULL DEFAULT 0,
    overage_by_service JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, billing_period)
);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_period ON tenant_usage(billing_period);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_tenant ON tenant_usage(tenant_id);
"""

_UPSERT_SQL = """
INSERT INTO tenant_usage (
    tenant_id, billing_period, total_requests,
    overage_requests, overage_by_service, updated_at
)
VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
ON CONFLICT (tenant_id, billing_period)
DO UPDATE SET
    total_requests = EXCLUDED.total_requests,
    overage_requests = EXCLUDED.overage_requests,
    overage_by_service = EXCLUDED.overage_by_service,
    updated_at = NOW()
"""


class QuotaFlusher:
    """Periodically flushes quota counters from Redis to PostgreSQL."""

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._redis = redis_client
        self._table_ensured = False
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    def set_redis(self, client: Any) -> None:
        self._redis = client

    async def _ensure_table(self, pool: Any) -> None:
        if self._table_ensured:
            return
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        self._table_ensured = True

    async def flush_once(self) -> int:
        """Flush all quota keys to PostgreSQL. Returns rows written."""
        if self._redis is None:
            return 0
        try:
            from repositories.repos import get_pool
            pool = await get_pool()
        except Exception as e:
            logger.debug(f"DB pool unavailable, skipping quota flush: {e}")
            return 0
        if pool is None:
            return 0

        await self._ensure_table(pool)

        rows_written = 0
        cursor = 0
        try:
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=cursor, match="rl:quota:*", count=200,
                )
                for key in keys or []:
                    match = _QUOTA_KEY_RE.match(key)
                    if not match:
                        continue
                    tenant_id = match.group("tenant")
                    period = match.group("period")
                    total = await self._redis.get(key)
                    if total is None:
                        continue
                    total_int = int(total)

                    overage_key = f"rl:overage:{tenant_id}:{period}"
                    overage_raw = await self._redis.hgetall(overage_key) or {}
                    overage_by_service = {k: int(v) for k, v in overage_raw.items()}
                    overage_total = sum(overage_by_service.values())

                    async with pool.acquire() as conn:
                        await conn.execute(
                            _UPSERT_SQL,
                            tenant_id,
                            period,
                            total_int,
                            overage_total,
                            json.dumps(overage_by_service),
                        )
                    rows_written += 1
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"Quota flush error: {e}")
        return rows_written

    async def run_forever(self, interval_s: int = 60) -> None:
        """Run the flush loop until stopped."""
        self._stopped = False
        while not self._stopped:
            try:
                await asyncio.sleep(interval_s)
                if self._stopped:
                    break
                await self.flush_once()
            except asyncio.CancelledError:
                break
            except Exception as e:  # pragma: no cover — defensive
                logger.error(f"Quota flusher loop error: {e}")

    def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()

    def start(self, interval_s: int = 60) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.run_forever(interval_s))
