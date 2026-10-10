"""Durable tenant model preferences and metering entitlement helpers."""
from __future__ import annotations

import hashlib
import asyncio
from datetime import datetime, timezone

from repositories.repos import BaseRepository
from repositories.repos import get_pool

_LOCAL_BUDGET_LOCKS: dict[str, asyncio.Lock] = {}
_LOCAL_BUDGET_USAGE: dict[str, int] = {}
_LOCAL_RESERVATIONS: dict[str, tuple[str, int]] = {}


class TenantModelPreferenceRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("model_runtime_tenant_preferences")

    async def get_default(self, tenant_id: str) -> str | None:
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=1)
        return str(rows[0]["default_model_id"]) if rows and rows[0].get("default_model_id") else None

    async def set_default(self, tenant_id: str, model_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        record_id = "tenant_model_" + hashlib.sha256(tenant_id.encode()).hexdigest()
        await self.insert(record_id, {
            "tenant_id": tenant_id,
            "default_model_id": model_id,
        })


async def reserve_token_budget(tenant_id: str, request_id: str, estimated_tokens: int) -> bool:
    """Atomically reserve monthly model tokens against billing entitlement."""
    from services.billing.revops import TenantEntitlementRepository

    rows = await TenantEntitlementRepository().list_for_tenant(tenant_id)
    entitlement = next((row for row in rows
                        if row.get("feature_key") == "model_runtime.tokens"
                        and row.get("enabled") is True), None)
    if entitlement is None or entitlement.get("included_quantity") is None:
        return False
    limit = int(entitlement["included_quantity"])
    estimate = max(1, int(estimated_tokens))
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    pool = await get_pool()
    if pool is None:
        lock = _LOCAL_BUDGET_LOCKS.setdefault(tenant_id, asyncio.Lock())
        async with lock:
            reserved = sum(tokens for tenant, tokens in _LOCAL_RESERVATIONS.values() if tenant == tenant_id)
            consumed = _LOCAL_BUDGET_USAGE.get(tenant_id, 0)
            if consumed + reserved + estimate > limit:
                return False
            _LOCAL_RESERVATIONS[request_id] = (tenant_id, estimate)
            return True

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"model_runtime_budget:{tenant_id}:{start:%Y-%m}")
            await conn.execute("""CREATE TABLE IF NOT EXISTS model_runtime_token_reservations (
                tenant_id TEXT NOT NULL, request_id TEXT NOT NULL, period_start TIMESTAMPTZ NOT NULL,
                reserved_tokens BIGINT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, request_id))""")
            await conn.execute("""UPDATE model_runtime_token_reservations
                SET reserved_tokens = 0, status = 'expired'
                WHERE tenant_id = $1 AND period_start = $2 AND status = 'reserved'
                AND created_at < NOW() - INTERVAL '1 hour'""", tenant_id, start)
            consumed = await conn.fetchval("""SELECT COALESCE(SUM((data->'metadata'->>'total_tokens')::bigint), 0)
                FROM usage_metering_events WHERE tenant_id = $1
                AND data->>'event_type' = 'model_runtime_token_usage'
                AND (data->>'occurred_at')::timestamptz >= $2""", tenant_id, start)
            reserved = await conn.fetchval("""SELECT COALESCE(SUM(reserved_tokens), 0)
                FROM model_runtime_token_reservations WHERE tenant_id = $1
                AND period_start = $2 AND status = 'reserved'""", tenant_id, start)
            if int(consumed or 0) + int(reserved or 0) + estimate > limit:
                return False
            await conn.execute("""INSERT INTO model_runtime_token_reservations
                (tenant_id, request_id, period_start, reserved_tokens, status)
                VALUES ($1, $2, $3, $4, 'reserved') ON CONFLICT (tenant_id, request_id) DO NOTHING""",
                tenant_id, request_id, start, estimate)
    return True


async def settle_token_budget(tenant_id: str, request_id: str, actual_tokens: int, *, release: bool = False) -> None:
    """Settle or release a successful/failed invocation's token reservation."""
    pool = await get_pool()
    if pool is None:
        lock = _LOCAL_BUDGET_LOCKS.setdefault(tenant_id, asyncio.Lock())
        async with lock:
            reservation = _LOCAL_RESERVATIONS.pop(request_id, None)
            if reservation and not release:
                _LOCAL_BUDGET_USAGE[tenant_id] = _LOCAL_BUDGET_USAGE.get(tenant_id, 0) + max(0, int(actual_tokens))
        return
    async with pool.acquire() as conn:
        await conn.execute("""UPDATE model_runtime_token_reservations
            SET reserved_tokens = 0, status = $3
            WHERE tenant_id = $1 AND request_id = $2 AND status = 'reserved'""",
            tenant_id, request_id, "released" if release else "settled")
