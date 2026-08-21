"""Conversion repository — durable access to canonical_conversions."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.conversion_repo")

_IS_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"

_local_store: dict[str, dict[str, Any]] = {}


class ConversionRepository:
    """Canonical conversion ledger over canonical_conversions.

    Authority ranking determines which source record wins on conflict:
    commerce webhooks (90) > server-confirmed (80) > CRM (70) >
    client-observed (50) > ad-platform imported (30).

    Lower-authority records are kept as evidence but do not overwrite
    the canonical row.
    """

    async def _pool(self):
        return await get_pool()

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert conversion or update if incoming authority_rank is higher."""
        key = row.get("deduplication_key") or _derive_dedup_key(row)
        row.setdefault("deduplication_key", key)
        row.setdefault("conversion_id", str(uuid4()))
        row.setdefault("observed_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("conversion_status", "confirmed")
        row.setdefault("authority_rank", 50)
        row.setdefault("attribution_eligible", True)
        row.setdefault("currency", "USD")
        row.setdefault("normalized_currency", "USD")
        row.setdefault("exchange_rate", "1.0")
        row.setdefault("quantity", 1)
        row.setdefault("schema_version", 1)

        # ── M2 (Program 5, multi-currency): real FX conversion ───────────────
        # When the source currency differs from the normalized target, resolve
        # a REAL, source-backed rate through services.value.price_sources — the
        # shared USD price registry the M1 FX snapshot provider registers into —
        # instead of the hardcoded "1.0" default set above, and record its
        # provenance. Same-currency rows keep the real 1.0 parity (correct, not
        # fabricated) and are left untouched. A genuinely unavailable rate is
        # recorded as unpriced / None-sourced — never a fabricated foreign 1.0
        # (M1 "unpriced, never silent parity" invariant). Excluding unpriced
        # rows from rollups is M3, deliberately not done here.
        src_currency = str(row.get("currency", "USD")).upper()
        norm_currency = str(row.get("normalized_currency", "USD")).upper()
        if src_currency != norm_currency:
            fx = _resolve_conversion_rate(src_currency, norm_currency)
            if not fx["unpriced"]:
                row["exchange_rate"] = fx["exchange_rate"]
            provenance = dict(row.get("provenance") or {})
            provenance["fx_conversion"] = {
                "exchange_rate": row.get("exchange_rate"),
                "conversion_source": fx["conversion_source"],
                "method": fx["method"],
                "base_currency": norm_currency,
                "quote_currency": src_currency,
                "priced": not fx["unpriced"],
                "as_of": fx["priced_at"],
            }
            row["provenance"] = provenance
        else:
            # Same-currency rows are real 1.0 parity by definition. A caller may
            # supply an explicit exchange_rate, which ``setdefault`` above
            # preserves and this branch (skipping FX normalization) would
            # otherwise leave in place — a USD->USD row could then persist a
            # rate like 2.0 with no fx_conversion provenance, silently distorting
            # normalized revenue. Force exact 1.0 parity: never a fabricated
            # same-currency rate.
            row["exchange_rate"] = "1.0"

        pool = await self._pool()
        if pool is None:
            existing = next(
                (r for r in _local_store.values()
                 if r.get("tenant_id") == row.get("tenant_id")
                 and r.get("deduplication_key") == key),
                None,
            )
            if existing is None or row.get("authority_rank", 50) >= existing.get("authority_rank", 50):
                _local_store[key] = row
            return row

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO canonical_conversions (
                    conversion_id, tenant_id, conversion_type, conversion_name,
                    goal_id, profile_id, cluster_id, account_id,
                    organization_id, wallet_id, agent_id,
                    order_id, payment_id, subscription_id, invoice_id,
                    opportunity_id, transaction_hash, external_conversion_id,
                    gross_value, discount_value, tax_value, shipping_value,
                    fee_value, refund_value, chargeback_value,
                    contribution_value, net_value,
                    currency, normalized_currency, exchange_rate, quantity,
                    product_ids, line_items,
                    occurred_at, observed_at, confirmed_at, adjusted_at, reversed_at,
                    conversion_status, conversion_source, authority_rank,
                    deduplication_key, attribution_eligible,
                    consent_snapshot_id, identity_version,
                    provenance, evidence_ids,
                    source_connector_id, source_event_id, schema_version
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                    $31,$32,$33,$34,$35,$36,$37,$38,$39,$40,
                    $41,$42,$43,$44,$45,$46,$47,$48,$49,$50
                )
                ON CONFLICT (tenant_id, deduplication_key)
                DO UPDATE SET
                    gross_value = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.gross_value ELSE canonical_conversions.gross_value END,
                    net_value = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.net_value ELSE canonical_conversions.net_value END,
                    -- A higher-authority replay updates the monetary value; its
                    -- FX fields must move with it, or the row keeps the old
                    -- currency/rate/source (and returns the new values it never
                    -- persisted), producing incorrect normalized revenue. Gate
                    -- them on the same authority condition as the amounts.
                    currency = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.currency ELSE canonical_conversions.currency END,
                    normalized_currency = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.normalized_currency ELSE canonical_conversions.normalized_currency END,
                    exchange_rate = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.exchange_rate ELSE canonical_conversions.exchange_rate END,
                    provenance = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.provenance ELSE canonical_conversions.provenance END,
                    conversion_status = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN EXCLUDED.conversion_status ELSE canonical_conversions.conversion_status END,
                    authority_rank = GREATEST(EXCLUDED.authority_rank, canonical_conversions.authority_rank),
                    adjusted_at = CASE WHEN EXCLUDED.authority_rank >= canonical_conversions.authority_rank
                        THEN now() ELSE canonical_conversions.adjusted_at END
                """,
                row.get("conversion_id"), row.get("tenant_id"),
                row.get("conversion_type"), row.get("conversion_name"),
                row.get("goal_id"), row.get("profile_id"), row.get("cluster_id"),
                row.get("account_id"), row.get("organization_id"), row.get("wallet_id"),
                row.get("agent_id"), row.get("order_id"), row.get("payment_id"),
                row.get("subscription_id"), row.get("invoice_id"),
                row.get("opportunity_id"), row.get("transaction_hash"),
                row.get("external_conversion_id"),
                _to_decimal(row.get("gross_value")),
                _to_decimal(row.get("discount_value", "0")),
                _to_decimal(row.get("tax_value", "0")),
                _to_decimal(row.get("shipping_value", "0")),
                _to_decimal(row.get("fee_value", "0")),
                _to_decimal(row.get("refund_value", "0")),
                _to_decimal(row.get("chargeback_value", "0")),
                _to_decimal(row.get("contribution_value")),
                _to_decimal(row.get("net_value")),
                row.get("currency", "USD"),
                row.get("normalized_currency", "USD"),
                _to_decimal(row.get("exchange_rate", "1.0")),
                row.get("quantity", 1),
                json.dumps(row.get("product_ids", [])),
                json.dumps(row.get("line_items", [])),
                _parse_ts(row.get("occurred_at")),
                _parse_ts(row.get("observed_at")),
                _parse_ts(row.get("confirmed_at")),
                _parse_ts(row.get("adjusted_at")),
                _parse_ts(row.get("reversed_at")),
                row.get("conversion_status", "confirmed"),
                row.get("conversion_source"),
                row.get("authority_rank", 50),
                key,
                row.get("attribution_eligible", True),
                row.get("consent_snapshot_id"),
                row.get("identity_version"),
                json.dumps(row.get("provenance", {})),
                json.dumps(row.get("evidence_ids", [])),
                row.get("source_connector_id"),
                row.get("source_event_id"),
                row.get("schema_version", 1),
            )
        return row

    async def get(self, tenant_id: str, conversion_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return next(
                (r for r in _local_store.values()
                 if r.get("tenant_id") == tenant_id and r.get("conversion_id") == conversion_id),
                None,
            )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM canonical_conversions WHERE tenant_id=$1 AND conversion_id=$2",
                tenant_id, conversion_id,
            )
            return dict(row) if row else None

    async def list_by_profile(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        identity_type: Optional[str] = None,
        conversion_type: Optional[str] = None,
        status: Optional[str] = None,
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
        attribution_eligible_only: bool = False,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        identity_columns = {"profile": "profile_id", "cluster": "cluster_id"}
        identity_column = identity_columns.get(identity_type or "")
        if identity_type not in (None, "profile", "cluster"):
            # Canonical conversions do not carry anonymous_id.
            return []
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and (
                    r.get(identity_column) == profile_id
                    if identity_column
                    else (
                        r.get("profile_id") == profile_id
                        or r.get("cluster_id") == profile_id
                    )
                )
                and (conversion_type is None or r.get("conversion_type") == conversion_type)
                and (status is None or r.get("conversion_status") == status)
                and (not attribution_eligible_only or r.get("attribution_eligible"))
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        identity_condition = (
            f"{identity_column} = $2"
            if identity_column
            else "(profile_id = $2 OR cluster_id = $2)"
        )
        conditions = ["tenant_id = $1", identity_condition]
        params: list[Any] = [tenant_id, profile_id]
        p = 3
        for col, val in (("conversion_type", conversion_type), ("conversion_status", status)):
            if val:
                conditions.append(f"{col} = ${p}")
                params.append(val)
                p += 1
        if after_occurred:
            conditions.append(f"occurred_at > ${p}")
            params.append(after_occurred)
            p += 1
        if before_occurred:
            conditions.append(f"occurred_at < ${p}")
            params.append(before_occurred)
            p += 1
        if attribution_eligible_only:
            conditions.append("attribution_eligible = TRUE")
        if cursor:
            conditions.append(f"occurred_at > ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM canonical_conversions
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def list_by_erasure_identity(
        self,
        tenant_id: str,
        identity_id: str,
        *,
        attribution_eligible_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return conversions matching profile_id OR cluster_id OR account_id.

        This mirrors ``tombstone_for_profile``'s WHERE clause exactly — unlike
        ``list_by_profile``'s default identity match (profile_id OR
        cluster_id only), ``tombstone_for_profile`` ALSO tombstones
        conversions identified solely by ``account_id``. Any caller that needs
        to know, ahead of a tombstone, which conversions a given identity's
        erasure is about to affect (e.g. DSR re-attribution scope discovery)
        must use this method rather than ``list_by_profile`` — otherwise a
        conversion reachable only via ``account_id`` gets tombstoned without
        ever appearing in that caller's snapshot.
        """
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and (
                    r.get("profile_id") == identity_id
                    or r.get("cluster_id") == identity_id
                    or r.get("account_id") == identity_id
                )
                and (not attribution_eligible_only or r.get("attribution_eligible"))
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        conditions = [
            "tenant_id = $1",
            "(profile_id = $2 OR cluster_id = $2 OR account_id = $2)",
        ]
        params: list[Any] = [tenant_id, identity_id]
        p = 3
        if attribution_eligible_only:
            conditions.append("attribution_eligible = TRUE")
        params.append(limit)

        sql = f"""
            SELECT * FROM canonical_conversions
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def list_by_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        cluster_id: Optional[str] = None,
        conversion_type: Optional[str] = None,
        status: Optional[str] = None,
        attribution_run_id: Optional[str] = None,
        channel: Optional[str] = None,
        creative_id: Optional[str] = None,
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
        include_unattributed: bool = False,
        limit: int = 500,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return conversions linked to a campaign.

        By default returns only attributed conversions (via attribution_credits join).
        Set include_unattributed=True to include all conversions that touched this campaign
        via touchpoint facts (profile_id match), though local mode returns empty for this path.
        """
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("campaign_id") == campaign_id
                and (cluster_id is None or r.get("cluster_id") == cluster_id)
                and (conversion_type is None or r.get("conversion_type") == conversion_type)
                and (status is None or r.get("conversion_status") == status)
                and (after_occurred is None or r.get("occurred_at", "") > after_occurred.isoformat())
                and (before_occurred is None or r.get("occurred_at", "") < before_occurred.isoformat())
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        if include_unattributed:
            # Join through touchpoint facts — wider net than attribution credits
            conditions = [
                "cc.tenant_id = $1",
                "tp.campaign_id = $2",
                "tp.tenant_id = $1",
            ]
            params: list[Any] = [tenant_id, campaign_id]
            p = 3
            join_clause = (
                "JOIN silver_campaign_touchpoint_facts tp "
                "ON (tp.profile_id = cc.profile_id OR tp.cluster_id = cc.cluster_id) "
                "AND tp.tenant_id = cc.tenant_id"
            )
        else:
            conditions = ["cc.tenant_id = $1", "ac.campaign_id = $2", "ar.is_active = TRUE"]
            params = [tenant_id, campaign_id]
            p = 3
            join_clause = (
                "JOIN attribution_credits ac ON ac.conversion_id = cc.conversion_id "
                "JOIN attribution_runs ar ON ar.attribution_run_id = ac.attribution_run_id"
            )
            if attribution_run_id:
                conditions.append(f"ac.attribution_run_id = ${p}")
                params.append(attribution_run_id)
                p += 1
            if channel:
                conditions.append(f"ac.channel = ${p}")
                params.append(channel)
                p += 1
            if creative_id:
                conditions.append(f"ac.creative_id = ${p}")
                params.append(creative_id)
                p += 1

        if cluster_id:
            conditions.append(f"cc.cluster_id = ${p}")
            params.append(cluster_id)
            p += 1
        if conversion_type:
            conditions.append(f"cc.conversion_type = ${p}")
            params.append(conversion_type)
            p += 1
        if status:
            conditions.append(f"cc.conversion_status = ${p}")
            params.append(status)
            p += 1
        if after_occurred:
            conditions.append(f"cc.occurred_at > ${p}")
            params.append(after_occurred)
            p += 1
        if before_occurred:
            conditions.append(f"cc.occurred_at < ${p}")
            params.append(before_occurred)
            p += 1
        if cursor:
            conditions.append(f"cc.occurred_at > ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT DISTINCT cc.*
            FROM canonical_conversions cc
            {join_clause}
            WHERE {' AND '.join(conditions)}
            ORDER BY cc.occurred_at ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def campaign_population_summary(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        attribution_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return converted/attributed counts and revenue for a campaign.

        Queries canonical_conversions + attribution_credits to give the lower
        funnel numbers that complement touchpoint-level population_summary().
        """
        pool = await self._pool()
        if pool is None:
            rows = [r for r in _local_store.values() if r.get("tenant_id") == tenant_id]
            converted = len([r for r in rows if r.get("attribution_eligible")])
            return {
                "converted_count": converted,
                "attributed_count": 0,
                "attributed_gross_revenue": 0.0,
                "attributed_net_revenue": 0.0,
            }

        run_filter = ""
        params: list[Any] = [tenant_id, campaign_id]
        if attribution_run_id:
            run_filter = "AND ac.attribution_run_id = $3"
            params.append(attribution_run_id)

        sql = f"""
            SELECT
              COUNT(DISTINCT cc.conversion_id) AS converted_count,
              COUNT(DISTINCT CASE WHEN ac.conversion_id IS NOT NULL THEN cc.conversion_id END) AS attributed_count,
              COALESCE(SUM(ac.credit_weight * cc.gross_value), 0) AS attributed_gross_revenue,
              COALESCE(SUM(ac.credit_weight * cc.net_value), 0) AS attributed_net_revenue
            FROM canonical_conversions cc
            JOIN attribution_credits ac ON ac.conversion_id = cc.conversion_id
            JOIN attribution_runs ar ON ar.attribution_run_id = ac.attribution_run_id
            WHERE cc.tenant_id = $1
              AND ac.campaign_id = $2
              AND ar.is_active = TRUE
              {run_filter}
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return {
                "converted_count": row["converted_count"] or 0,
                "attributed_count": row["attributed_count"] or 0,
                "attributed_gross_revenue": float(row["attributed_gross_revenue"] or 0),
                "attributed_net_revenue": float(row["attributed_net_revenue"] or 0),
            }

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
        attribution_eligible_only: bool = False,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return conversions for a tenant with optional time bounds — used by backfill."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and (not attribution_eligible_only or r.get("attribution_eligible"))
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        p = 2
        if after_occurred:
            conditions.append(f"occurred_at > ${p}")
            params.append(after_occurred)
            p += 1
        if before_occurred:
            conditions.append(f"occurred_at < ${p}")
            params.append(before_occurred)
            p += 1
        if attribution_eligible_only:
            conditions.append("attribution_eligible = TRUE")
        if cursor:
            conditions.append(f"occurred_at > ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM canonical_conversions
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def tombstone_for_profile(self, tenant_id: str, profile_id: str) -> int:
        """Privacy erasure: mark all conversions for a profile as attribution-ineligible.

        Sets attribution_eligible=FALSE and nulls identity fields. The conversion
        record is retained for financial reconciliation but excluded from all
        attribution runs. Returns the count of affected rows.
        """
        pool = await self._pool()
        if pool is None:
            count = 0
            for row in _local_store.values():
                if row.get("tenant_id") == tenant_id and (
                    row.get("profile_id") == profile_id
                    or row.get("cluster_id") == profile_id
                    or row.get("account_id") == profile_id
                ):
                    row["attribution_eligible"] = False
                    row["profile_id"] = None
                    row["cluster_id"] = None
                    row["account_id"] = None
                    row["wallet_id"] = None
                    row["agent_id"] = None
                    row["conversion_status"] = "privacy_tombstoned"
                    count += 1
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE canonical_conversions
                SET attribution_eligible = FALSE,
                    profile_id           = NULL,
                    cluster_id           = NULL,
                    account_id           = NULL,
                    wallet_id            = NULL,
                    agent_id             = NULL,
                    conversion_status    = 'privacy_tombstoned',
                    adjusted_at          = now()
                WHERE tenant_id = $1
                  AND (profile_id = $2 OR cluster_id = $2 OR account_id = $2)
                  AND attribution_eligible = TRUE
                """,
                tenant_id, profile_id,
            )
        try:
            return int(result.split()[-1])
        except Exception:
            return 0

    async def mark_reversed(self, tenant_id: str, conversion_id: str) -> Optional[dict[str, Any]]:
        """Mark a conversion as reversed (e.g., full refund/chargeback)."""
        pool = await self._pool()
        if pool is None:
            row = next(
                (r for r in _local_store.values()
                 if r.get("tenant_id") == tenant_id and r.get("conversion_id") == conversion_id),
                None,
            )
            if row:
                row["conversion_status"] = "reversed"
                row["reversed_at"] = datetime.now(timezone.utc).isoformat()
                row["attribution_eligible"] = False
            return row

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE canonical_conversions
                SET conversion_status = 'reversed',
                    reversed_at = now(),
                    attribution_eligible = FALSE
                WHERE tenant_id = $1 AND conversion_id = $2
                RETURNING *
                """,
                tenant_id, conversion_id,
            )
            return dict(row) if row else None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_conversion_rate(
    source_currency: str, normalized_currency: str
) -> dict[str, Any]:
    """Resolve a REAL source→normalized FX rate via services.value.price_sources.

    Program 5 (multi-currency) M2. ``exchange_rate`` follows the platform
    convention ``normalized_value = native_value * exchange_rate`` — i.e. the
    value of ONE source-currency unit expressed in ``normalized_currency``.
    Because price_sources is a USD price registry, the rate is derived from the
    two USD legs (``source_usd / normalized_usd``); for the common
    USD-normalized case ``normalized_usd == 1`` so the source USD rate is used
    directly.

    Returns ``{exchange_rate, conversion_source, method, priced_at, unpriced}``
    (``exchange_rate`` is a text-decimal for the NUMERIC column, or None when
    unpriced). ``unpriced`` is True when a real rate is genuinely unavailable —
    the caller must then NOT fabricate a foreign 1.0 (M1 invariant) and records
    the row as unpriced / None-sourced. Same-currency callers never reach here.
    Values are Decimal end-to-end; no float ever touches a money/rate value.
    """
    # Lazy import keeps module import cheap and avoids any import-time cycle;
    # fx_provider.register() idempotently wires the M1 snapshot FX provider into
    # the shared registry so a real rate is resolvable on this write path even
    # when no separate startup hook has imported it yet.
    from services.value import fx_provider, price_sources

    fx_provider.register()

    _unpriced = {
        "exchange_rate": None,
        "conversion_source": None,
        "method": "unpriced",
        "priced_at": None,
        "unpriced": True,
    }

    source_leg = price_sources.price(Decimal(1), source_currency)
    normalized_leg = price_sources.price(Decimal(1), normalized_currency)
    if (
        source_leg is None
        or normalized_leg is None
        or source_leg.get("conversion_rate") is None
        or normalized_leg.get("conversion_rate") is None
    ):
        return _unpriced

    source_usd = Decimal(source_leg["conversion_rate"])
    normalized_usd = Decimal(normalized_leg["conversion_rate"])
    if normalized_usd == 0:
        return _unpriced

    rate = source_usd / normalized_usd
    source = source_leg.get("conversion_source")
    if normalized_currency != "USD":
        # Cross rate: provenance names both legs it was derived from.
        source = f"{source}/{normalized_leg.get('conversion_source')}"
    return {
        "exchange_rate": format(rate, "f"),
        "conversion_source": source,
        "method": source_leg.get("valuation_method") or "fx_rate",
        "priced_at": source_leg.get("priced_at"),
        "unpriced": False,
    }


def _derive_dedup_key(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("tenant_id", "")),
        str(row.get("conversion_type", "")),
        str(row.get("source_event_id") or row.get("order_id") or row.get("payment_id") or uuid4()),
    ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


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
        return datetime.min.replace(tzinfo=timezone.utc)
