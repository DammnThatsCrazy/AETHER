"""Adjustment repository — append-only access to revenue_adjustments."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.adjustment_repo")

_local_store: dict[str, dict[str, Any]] = {}


class AdjustmentRepository:
    """Append-only revenue adjustment ledger over revenue_adjustments.

    No updates or deletes — every adjustment is immutable once recorded.
    Net effect on a conversion is computed by summing all adjustments.
    """

    async def _pool(self):
        return await get_pool()

    async def append(self, row: dict[str, Any]) -> dict[str, Any]:
        """Record a revenue adjustment. Idempotent on (tenant_id, idempotency_key)."""
        row.setdefault("adjustment_id", str(uuid4()))
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("currency", "USD")
        row.setdefault("schema_version", 1)

        key = row.get("idempotency_key")
        if not key:
            raise ValueError("idempotency_key is required for revenue adjustments")

        pool = await self._pool()
        if pool is None:
            existing_key = f"{row.get('tenant_id')}:{key}"
            if existing_key not in _local_store:
                _local_store[existing_key] = row
            return row

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO revenue_adjustments (
                    adjustment_id, tenant_id, conversion_id,
                    adjustment_type, amount, currency, normalized_amount,
                    occurred_at, reason, source_event_id, connector_record_id,
                    evidence_ids, idempotency_key, schema_version, created_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15
                )
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                row.get("adjustment_id"), row.get("tenant_id"),
                row.get("conversion_id"),
                row.get("adjustment_type"), _to_decimal(row.get("amount")),
                row.get("currency", "USD"),
                _to_decimal(row.get("normalized_amount")),
                _parse_ts(row.get("occurred_at")),
                row.get("reason"), row.get("source_event_id"),
                row.get("connector_record_id"),
                json.dumps(row.get("evidence_ids", []), default=str),
                key, row.get("schema_version", 1),
                _parse_ts(row.get("created_at")),
            )
        return row

    async def list_for_conversion(
        self,
        tenant_id: str,
        conversion_id: str,
        *,
        limit: Optional[int] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Return exact conversion adjustments in stable event order.

        A bounded caller may request one extra row to detect truncation.
        Existing ledger callers omit ``limit`` to read the complete history.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        if after is not None and (after.tzinfo is None or after.utcoffset() is None):
            raise ValueError("after must include a timezone")
        if before is not None and (before.tzinfo is None or before.utcoffset() is None):
            raise ValueError("before must include a timezone")
        if after is not None and before is not None and before <= after:
            raise ValueError("event-time window must be increasing")
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id and r.get("conversion_id") == conversion_id
            ]
            if after is not None or before is not None:
                from shared.temporal.instant import try_parse_instant

                bounded_rows: list[tuple[datetime, dict[str, Any]]] = []
                for row in rows:
                    raw_occurred_at = row.get("occurred_at")
                    if isinstance(raw_occurred_at, datetime):
                        occurred_at = raw_occurred_at
                    elif isinstance(raw_occurred_at, str):
                        occurred_at, _ = try_parse_instant(raw_occurred_at)
                    else:
                        occurred_at = None
                    if occurred_at is None or occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
                        raise ValueError("revenue adjustment event time is invalid")
                    if after is not None and occurred_at <= after:
                        continue
                    if before is not None and occurred_at >= before:
                        continue
                    bounded_rows.append((occurred_at, row))
                bounded_rows.sort(key=lambda item: (item[0], str(item[1].get("adjustment_id") or "")))
                rows = [row for _, row in bounded_rows]
            else:
                rows.sort(key=lambda r: (str(r.get("occurred_at") or ""), str(r.get("adjustment_id") or "")))
            return rows if limit is None else rows[:limit]

        async with pool.acquire() as conn:
            query = (
                "SELECT * FROM revenue_adjustments "
                "WHERE tenant_id = $1 AND conversion_id = $2 "
                "AND ($3::timestamptz IS NULL OR occurred_at > $3::timestamptz) "
                "AND ($4::timestamptz IS NULL OR occurred_at < $4::timestamptz) "
                "ORDER BY occurred_at ASC, adjustment_id ASC"
            )
            if limit is None:
                rows = await conn.fetch(query, tenant_id, conversion_id, after, before)
            else:
                rows = await conn.fetch(
                    query + " LIMIT $5", tenant_id, conversion_id, after, before, limit
                )
            return [dict(r) for r in rows]

    async def net_adjustment(self, tenant_id: str, conversion_id: str) -> Decimal:
        """Sum all adjustment amounts for a conversion (can be negative for refunds)."""
        rows = await self.list_for_conversion(tenant_id, conversion_id)
        return sum((_to_decimal(r.get("normalized_amount") or r.get("amount")) or Decimal("0") for r in rows), Decimal("0"))

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        adjustment_type: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        limit: int = 500,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and (adjustment_type is None or r.get("adjustment_type") == adjustment_type)
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
            return rows[:limit]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        p = 2
        if adjustment_type:
            conditions.append(f"adjustment_type = ${p}")
            params.append(adjustment_type)
            p += 1
        if after:
            conditions.append(f"occurred_at > ${p}")
            params.append(after)
            p += 1
        if before:
            conditions.append(f"occurred_at < ${p}")
            params.append(before)
            p += 1
        if cursor:
            conditions.append(f"occurred_at < ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM revenue_adjustments
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at DESC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _decode_cursor(cursor: str) -> datetime:
    try:
        return datetime.fromisoformat(cursor)
    except ValueError:
        return datetime.now(timezone.utc)
