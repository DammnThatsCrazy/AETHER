"""Durable persistence for value semantics — price/valuation/rollup snapshots
and valuation audit trails.

JSONB-backed (auto-created by BaseRepository in production; in-memory for dev).
The additive alembic migration 20260721_value_semantics provides the explicit
typed schema. Amounts are decimal strings; unknown values are never 0.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now


class _ValueRepo(BaseRepository):
    async def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class PriceSnapshotRepository(_ValueRepo):
    def __init__(self) -> None:
        super().__init__("value_price_snapshots")


class ValuationSnapshotRepository(_ValueRepo):
    def __init__(self) -> None:
        super().__init__("value_valuation_snapshots")


class ValueRollupSnapshotRepository(_ValueRepo):
    def __init__(self) -> None:
        super().__init__("value_rollup_snapshots")


class SourceValuationAuditRepository(_ValueRepo):
    def __init__(self) -> None:
        super().__init__("value_source_valuation_audit")


class UnpricedStaleAssetAuditRepository(_ValueRepo):
    def __init__(self) -> None:
        super().__init__("value_unpriced_stale_audit")


class ValueSnapshotService:
    """Record + read value snapshots. Writers (valuation/backfill paths) call
    record_*; read surfaces + Kyber diagnostics call list_*.
    """

    def __init__(
        self,
        valuations: Optional[ValuationSnapshotRepository] = None,
        rollups: Optional[ValueRollupSnapshotRepository] = None,
        audits: Optional[SourceValuationAuditRepository] = None,
    ) -> None:
        self.valuations = valuations or ValuationSnapshotRepository()
        self.rollups = rollups or ValueRollupSnapshotRepository()
        self.audits = audits or SourceValuationAuditRepository()

    async def record_valuation(self, tenant_id: str, aether_value: dict) -> dict:
        record = {
            "id": aether_value.get("id") or f"val_{utc_now().timestamp()}",
            "tenant_id": tenant_id,
            "usd_value": (aether_value.get("valuation") or {}).get("usd_value"),
            "valuation_method": (aether_value.get("valuation") or {}).get("valuation_method"),
            "native": aether_value.get("native"),
            "recorded_at": utc_now().isoformat(),
        }
        await self.valuations.insert(record["id"], record)
        return record

    async def record_rollup(self, tenant_id: str, metric: str, rollup: dict) -> dict:
        record = {
            "id": f"rollup_{metric}_{utc_now().timestamp()}",
            "tenant_id": tenant_id,
            "metric": metric,
            "total_usd": rollup.get("total_usd"),
            "rollup_status": rollup.get("rollup_status"),
            "unpriced_count": rollup.get("unpriced_count"),
            "excluded_count": rollup.get("excluded_count"),
            "recorded_at": utc_now().isoformat(),
        }
        await self.rollups.insert(record["id"], record)
        return record

    async def list_valuations(self, tenant_id: str, limit: int = 100) -> list[dict]:
        return await self.valuations.list_for_tenant(tenant_id, limit=limit)
