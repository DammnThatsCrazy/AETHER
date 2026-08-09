"""Spend repository — durable access to spend_records (actual ad spend, not budget)."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.spend_repo")

_local_store: dict[str, dict[str, Any]] = {}


class SpendRepository:
    """Actual advertising spend ledger over spend_records.

    ROAS must always use this table, never campaign.budget_usd.
    All writes are idempotent — connectors can replay without double-counting.
    """

    async def _pool(self):
        return await get_pool()

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or update spend record. ON CONFLICT updates mutable spend columns.

        Currency is REQUIRED — there is no silent USD default (program sec19).
        ``billing_currency`` is resolved to ``normalized_currency=USD`` via the
        FX seam (``services/value/fx_provider`` snapshot); a non-USD currency
        without an available rate raises instead of being recorded 1:1.
        """
        row.setdefault("spend_record_id", str(uuid4()))
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("schema_version", 1)

        billing_currency = row.get("billing_currency")
        norm_currency, exchange_rate = normalize_currency_for_usd(billing_currency)
        row["billing_currency"] = billing_currency
        row["normalized_currency"] = norm_currency
        row["exchange_rate"] = str(exchange_rate)

        key = row.get("idempotency_key")
        if not key:
            raise ValueError("idempotency_key is required for spend records")

        pool = await self._pool()
        if pool is None:
            existing_key = f"{row.get('tenant_id')}:{key}"
            _local_store[existing_key] = row
            return row

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO spend_records (
                    spend_record_id, tenant_id, platform, ad_account_id,
                    campaign_id, ad_group_id, ad_set_id, creative_id, ad_id,
                    placement_id, keyword_id,
                    period_start, period_end, source_timezone,
                    billing_currency, normalized_currency, exchange_rate,
                    impressions, reach, frequency, clicks, engagements,
                    video_views, viewable_impressions,
                    media_spend, platform_fees, agency_fees,
                    creative_cost, affiliate_cost, other_cost, total_cost,
                    source_record_id, source_connector_id, sync_run_id,
                    provenance, idempotency_key, schema_version, created_at,
                    external_campaign_id, external_account_id,
                    campaign_resolution_status, campaign_resolution_method,
                    campaign_resolution_version
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                    $31,$32,$33,$34,$35,$36,$37,$38,
                    $39,$40,$41,$42,$43
                )
                ON CONFLICT (tenant_id, idempotency_key) DO UPDATE SET
                    impressions = EXCLUDED.impressions,
                    reach = EXCLUDED.reach,
                    clicks = EXCLUDED.clicks,
                    engagements = EXCLUDED.engagements,
                    video_views = EXCLUDED.video_views,
                    viewable_impressions = EXCLUDED.viewable_impressions,
                    media_spend = EXCLUDED.media_spend,
                    platform_fees = EXCLUDED.platform_fees,
                    agency_fees = EXCLUDED.agency_fees,
                    creative_cost = EXCLUDED.creative_cost,
                    affiliate_cost = EXCLUDED.affiliate_cost,
                    other_cost = EXCLUDED.other_cost,
                    total_cost = EXCLUDED.total_cost,
                    exchange_rate = EXCLUDED.exchange_rate,
                    external_campaign_id = COALESCE(EXCLUDED.external_campaign_id, spend_records.external_campaign_id),
                    external_account_id = COALESCE(EXCLUDED.external_account_id, spend_records.external_account_id),
                    campaign_resolution_status = COALESCE(EXCLUDED.campaign_resolution_status, spend_records.campaign_resolution_status),
                    campaign_resolution_method = COALESCE(EXCLUDED.campaign_resolution_method, spend_records.campaign_resolution_method),
                    campaign_resolution_version = COALESCE(EXCLUDED.campaign_resolution_version, spend_records.campaign_resolution_version)
                """,
                row.get("spend_record_id"), row.get("tenant_id"),
                row.get("platform"), row.get("ad_account_id"),
                row.get("campaign_id"), row.get("ad_group_id"), row.get("ad_set_id"),
                row.get("creative_id"), row.get("ad_id"),
                row.get("placement_id"), row.get("keyword_id"),
                _parse_ts(row.get("period_start")), _parse_ts(row.get("period_end")),
                row.get("source_timezone", "UTC"),
                row.get("billing_currency", "USD"),
                row.get("normalized_currency", "USD"),
                _to_decimal(row.get("exchange_rate", "1.0")),
                int(row.get("impressions", 0)), int(row.get("reach", 0)),
                _to_decimal(row.get("frequency")),
                int(row.get("clicks", 0)), int(row.get("engagements", 0)),
                int(row.get("video_views", 0)), int(row.get("viewable_impressions", 0)),
                _to_decimal(row.get("media_spend", "0")),
                _to_decimal(row.get("platform_fees", "0")),
                _to_decimal(row.get("agency_fees", "0")),
                _to_decimal(row.get("creative_cost", "0")),
                _to_decimal(row.get("affiliate_cost", "0")),
                _to_decimal(row.get("other_cost", "0")),
                _to_decimal(row.get("total_cost", "0")),
                row.get("source_record_id"), row.get("source_connector_id"),
                row.get("sync_run_id"),
                json.dumps(row.get("provenance", {})),
                key, row.get("schema_version", 1),
                _parse_ts(row.get("created_at")),
                row.get("external_campaign_id"),
                row.get("external_account_id"),
                row.get("campaign_resolution_status"),
                row.get("campaign_resolution_method"),
                row.get("campaign_resolution_version"),
            )
        return row

    async def list_by_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id and r.get("campaign_id") == campaign_id
            ]
            rows.sort(key=lambda r: r.get("period_start", ""))
            return rows[:limit]

        conditions = ["tenant_id = $1", "campaign_id = $2"]
        params: list[Any] = [tenant_id, campaign_id]
        p = 3
        if period_start:
            conditions.append(f"period_end >= ${p}")
            params.append(period_start)
            p += 1
        if period_end:
            conditions.append(f"period_start <= ${p}")
            params.append(period_end)
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM spend_records
            WHERE {' AND '.join(conditions)}
            ORDER BY period_start ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def total_spend(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        currency: str = "USD",
    ) -> Decimal:
        """Sum USD-normalized total_cost for a campaign within a period.

        Each row's native ``total_cost`` is converted to USD via its recorded
        ``exchange_rate`` (rows written since sec19 always carry a correct
        rate). A row normalized to anything other than USD raises — mixed or
        un-normalized money is never silently summed.
        """
        rows = await self.list_by_campaign(
            tenant_id, campaign_id,
            period_start=period_start,
            period_end=period_end,
            limit=10000,
        )
        return sum((_usd_total_cost(r) for r in rows), Decimal("0"))

    async def reconciliation_report(
        self,
        tenant_id: str,
        campaign_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        """Return daily spend breakdown for reconciliation against platform reports."""
        rows = await self.list_by_campaign(
            tenant_id, campaign_id,
            period_start=period_start,
            period_end=period_end,
            limit=10000,
        )
        by_day: dict[str, Decimal] = {}
        for r in rows:
            ps = r.get("period_start")
            if ps:
                day_key = str(ps)[:10]
                by_day[day_key] = by_day.get(day_key, Decimal("0")) + _usd_total_cost(r)

        return {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_spend": sum(by_day.values(), Decimal("0")),
            "record_count": len(rows),
            "daily_breakdown": [
                {"date": day, "spend": float(amt)} for day, amt in sorted(by_day.items())
            ],
        }

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        platform: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        limit: int = 500,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and (platform is None or r.get("platform") == platform)
            ]
            rows.sort(key=lambda r: r.get("period_start", ""), reverse=True)
            return rows[:limit]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        p = 2
        if platform:
            conditions.append(f"platform = ${p}")
            params.append(platform)
            p += 1
        if period_start:
            conditions.append(f"period_end >= ${p}")
            params.append(period_start)
            p += 1
        if period_end:
            conditions.append(f"period_start <= ${p}")
            params.append(period_end)
            p += 1
        if cursor:
            conditions.append(f"period_start < ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM spend_records
            WHERE {' AND '.join(conditions)}
            ORDER BY period_start DESC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

def normalize_currency_for_usd(billing_currency: Any) -> tuple[str, Decimal]:
    """Resolve ``billing_currency`` to ``(normalized_currency, exchange_rate)``.

    Invariants (program sec19):
    - Currency is REQUIRED — a missing/empty value raises instead of silently
      defaulting to USD.
    - USD is the identity base (rate 1.0) — no FX needed.
    - A non-USD currency is resolved through the FX snapshot seam
      (``services/value/fx_provider``). No available rate raises — a non-USD
      amount is NEVER recorded as a silent 1:1 USD amount.
    """
    norm = str(billing_currency or "").strip().upper()
    if not norm:
        raise ValueError(
            "billing_currency is required for money records — refusing to "
            "default to USD"
        )
    if norm == "USD":
        return "USD", Decimal("1")
    return "USD", _usd_rate_for(norm)


def _usd_rate_for(currency: str) -> Decimal:
    """USD value of one unit of ``currency`` via the FX snapshot seam."""
    # Importing fx_provider registers the snapshot PriceProvider with
    # services.value.price_sources (self-registering module). Lazy so the
    # dependency only activates when a non-USD amount is actually converted.
    from services.value import fx_provider as _fx  # noqa: F401  (registers snapshot)
    from services.value.price_sources import price

    valuation = price(Decimal("1"), currency)
    if valuation is None or valuation.get("usd_value") is None:
        raise ValueError(
            f"No FX rate available for currency {currency!r} — refusing to "
            "record a silent 1:1 USD normalization"
        )
    return Decimal(str(valuation["usd_value"]))


def _usd_total_cost(row: dict[str, Any]) -> Decimal:
    """Convert a row's native ``total_cost`` to USD via its recorded rate.

    Raises when the row is not normalized to USD (mixed/un-normalized money is
    never silently summed). A USD-normalized row with no rate is treated as
    identity (legacy rows always carried rate 1.0).
    """
    amount = _to_decimal(row.get("total_cost")) or Decimal("0")
    norm = str(row.get("normalized_currency") or "USD").strip().upper()
    if norm != "USD":
        raise ValueError(
            f"spend row {row.get('spend_record_id')!r} is normalized to {norm!r}, "
            "not USD — refusing to total mixed currencies"
        )
    rate = _to_decimal(row.get("exchange_rate"))
    return amount * rate if rate is not None else amount


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
