"""Attribution run and credit repository — durable access to attribution_runs and attribution_credits."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.attribution_run_repo")

_IS_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"

_local_runs: dict[str, dict[str, Any]] = {}
_local_credits: list[dict[str, Any]] = []


class AttributionRunRepository:
    """Durable access to attribution_runs and attribution_credits tables.

    Production: asyncpg queries against PostgreSQL.
    Local/test: in-memory dicts (shared via module-level stores).
    """

    async def _pool(self):
        return await get_pool()

    # ── Runs ─────────────────────────────────────────────────────────────────

    async def create_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Insert a new attribution run (status='pending')."""
        run.setdefault("attribution_run_id", str(uuid4()))
        run.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        run.setdefault("status", "pending")
        run.setdefault("is_active", False)

        pool = await self._pool()
        if pool is None:
            _local_runs[run["attribution_run_id"]] = run
            return run

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO attribution_runs (
                    attribution_run_id, tenant_id, conversion_id,
                    conversion_version, journey_id, journey_version_id,
                    model_config_id, model_type, model_version, code_version,
                    input_touchpoint_count, excluded_touchpoint_count,
                    eligible_revenue, credit_total, unattributed_credit,
                    identity_confidence, model_confidence, data_watermark,
                    currency, status, failure_reason, is_active,
                    started_at, completed_at, created_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25
                )
                """,
                run.get("attribution_run_id"), run.get("tenant_id"),
                run.get("conversion_id"), run.get("conversion_version"),
                run.get("journey_id"), run.get("journey_version_id"),
                run.get("model_config_id"), run.get("model_type", "last_touch"),
                run.get("model_version", "1.0"), run.get("code_version"),
                run.get("input_touchpoint_count", 0),
                run.get("excluded_touchpoint_count", 0),
                _to_decimal(run.get("eligible_revenue")),
                _to_decimal(run.get("credit_total", "1.0")),
                _to_decimal(run.get("unattributed_credit", "0.0")),
                run.get("identity_confidence"), run.get("model_confidence"),
                _parse_ts(run.get("data_watermark")),
                run.get("currency", "USD"), run.get("status", "pending"),
                run.get("failure_reason"), run.get("is_active", False),
                _parse_ts(run.get("started_at")), _parse_ts(run.get("completed_at")),
                _parse_ts(run.get("created_at")),
            )
        return run

    async def update_run(self, attribution_run_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Update mutable fields on a run (status, completed_at, failure_reason, is_active)."""
        pool = await self._pool()
        if pool is None:
            run = _local_runs.get(attribution_run_id)
            if run is None:
                return None
            run.update(updates)
            return run

        sets = []
        params: list[Any] = []
        p = 1
        for col in ("status", "failure_reason", "is_active", "completed_at", "started_at",
                    "credit_total", "unattributed_credit", "model_confidence", "identity_confidence"):
            if col in updates:
                sets.append(f"{col} = ${p}")
                val = updates[col]
                if col in ("completed_at", "started_at"):
                    val = _parse_ts(val)
                elif col in ("credit_total", "unattributed_credit"):
                    val = _to_decimal(val)
                params.append(val)
                p += 1
        if not sets:
            return await self.get_run(attribution_run_id)

        params.append(attribution_run_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE attribution_runs SET {', '.join(sets)} WHERE attribution_run_id=${p} RETURNING *",
                *params,
            )
            return dict(row) if row else None

    async def deactivate_prior_runs(self, tenant_id: str, conversion_id: str) -> int:
        """Mark all current active runs for a conversion as inactive before activating a new one."""
        pool = await self._pool()
        if pool is None:
            count = 0
            for run in _local_runs.values():
                if (run.get("tenant_id") == tenant_id
                        and run.get("conversion_id") == conversion_id
                        and run.get("is_active")):
                    run["is_active"] = False
                    count += 1
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE attribution_runs SET is_active = FALSE
                WHERE tenant_id = $1 AND conversion_id = $2 AND is_active = TRUE
                """,
                tenant_id, conversion_id,
            )
            return int(result.split()[-1]) if result else 0

    async def get_run(self, attribution_run_id: str, tenant_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            run = _local_runs.get(attribution_run_id)
            if run and tenant_id and run.get("tenant_id") != tenant_id:
                return None
            return run

        async with pool.acquire() as conn:
            if tenant_id:
                row = await conn.fetchrow(
                    "SELECT * FROM attribution_runs WHERE attribution_run_id=$1 AND tenant_id=$2",
                    attribution_run_id, tenant_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM attribution_runs WHERE attribution_run_id=$1",
                    attribution_run_id,
                )
            return dict(row) if row else None

    async def get_active_run(self, tenant_id: str, conversion_id: str) -> Optional[dict[str, Any]]:
        """Return the currently active attribution run for a conversion."""
        pool = await self._pool()
        if pool is None:
            return next(
                (r for r in _local_runs.values()
                 if r.get("tenant_id") == tenant_id
                 and r.get("conversion_id") == conversion_id
                 and r.get("is_active")),
                None,
            )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM attribution_runs
                WHERE tenant_id=$1 AND conversion_id=$2 AND is_active=TRUE
                ORDER BY created_at DESC LIMIT 1
                """,
                tenant_id, conversion_id,
            )
            return dict(row) if row else None

    async def list_runs(
        self,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        conversion_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_runs.values()
                if r.get("tenant_id") == tenant_id
                and (campaign_id is None or r.get("campaign_id") == campaign_id)
                and (conversion_id is None or r.get("conversion_id") == conversion_id)
                and (status is None or r.get("status") == status)
            ]
            rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            return rows[:limit]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        p = 2
        if campaign_id:
            conditions.append(f"campaign_id = ${p}")
            params.append(campaign_id)
            p += 1
        if conversion_id:
            conditions.append(f"conversion_id = ${p}")
            params.append(conversion_id)
            p += 1
        if status:
            conditions.append(f"status = ${p}")
            params.append(status)
            p += 1
        if cursor:
            conditions.append(f"created_at < ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM attribution_runs
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    # ── Credits ──────────────────────────────────────────────────────────────

    async def insert_credits(self, credits: list[dict[str, Any]]) -> int:
        """Bulk insert attribution credits for a run. Returns count inserted."""
        if not credits:
            return 0

        pool = await self._pool()
        if pool is None:
            for c in credits:
                c.setdefault("credit_id", str(uuid4()))
                c.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                _local_credits.append(c)
            return len(credits)

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    """
                    INSERT INTO attribution_credits (
                        credit_id, tenant_id, attribution_run_id, conversion_id,
                        touchpoint_id, campaign_id, ad_group_id, ad_set_id,
                        creative_id, ad_id, placement_id, keyword_id,
                        channel, source, credit_weight,
                        attributed_conversion_count,
                        attributed_gross_revenue, attributed_net_revenue,
                        attributed_contribution_value,
                        identity_confidence, model_confidence,
                        explanation, evidence_ids, created_at
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                        $21,$22,$23,$24
                    )
                    """,
                    [
                        (
                            c.get("credit_id", str(uuid4())),
                            c.get("tenant_id"), c.get("attribution_run_id"),
                            c.get("conversion_id"), c.get("touchpoint_id"),
                            c.get("campaign_id"), c.get("ad_group_id"), c.get("ad_set_id"),
                            c.get("creative_id"), c.get("ad_id"),
                            c.get("placement_id"), c.get("keyword_id"),
                            c.get("channel"), c.get("source"),
                            _to_decimal(c.get("credit_weight", "0")),
                            _to_decimal(c.get("attributed_conversion_count", "0")),
                            _to_decimal(c.get("attributed_gross_revenue")),
                            _to_decimal(c.get("attributed_net_revenue")),
                            _to_decimal(c.get("attributed_contribution_value")),
                            c.get("identity_confidence"), c.get("model_confidence"),
                            c.get("explanation"),
                            json.dumps(c.get("evidence_ids", [])),
                            _parse_ts(c.get("created_at")) or datetime.now(timezone.utc),
                        )
                        for c in credits
                    ],
                )
        return len(credits)

    async def list_credits_for_run(self, tenant_id: str, attribution_run_id: str) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                c for c in _local_credits
                if c.get("tenant_id") == tenant_id
                and c.get("attribution_run_id") == attribution_run_id
            ]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM attribution_credits WHERE tenant_id=$1 AND attribution_run_id=$2 ORDER BY credit_weight DESC",
                tenant_id, attribution_run_id,
            )
            return [dict(r) for r in rows]

    async def list_credits_for_conversion(
        self,
        tenant_id: str,
        conversion_id: str,
        *,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Return credits for a conversion, optionally restricted to the active run."""
        pool = await self._pool()
        if pool is None:
            if active_only:
                active = await self.get_active_run(tenant_id, conversion_id)
                if active is None:
                    return []
                run_id = active["attribution_run_id"]
                return [
                    c for c in _local_credits
                    if c.get("attribution_run_id") == run_id
                ]
            return [
                c for c in _local_credits
                if c.get("tenant_id") == tenant_id and c.get("conversion_id") == conversion_id
            ]

        if active_only:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ac.*
                    FROM attribution_credits ac
                    JOIN attribution_runs ar ON ar.attribution_run_id = ac.attribution_run_id
                    WHERE ac.tenant_id = $1 AND ac.conversion_id = $2 AND ar.is_active = TRUE
                    ORDER BY ac.credit_weight DESC
                    """,
                    tenant_id, conversion_id,
                )
                return [dict(r) for r in rows]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM attribution_credits WHERE tenant_id=$1 AND conversion_id=$2 ORDER BY credit_weight DESC",
                tenant_id, conversion_id,
            )
            return [dict(r) for r in rows]

    async def campaign_credit_summary(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        model_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        cluster_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict[str, Any]:
        """Aggregate attribution credits for a campaign — used by campaign attribution endpoint.

        Returns a summary dict with:
          - total_attributed_conversions (count)
          - total_attributed_gross_revenue
          - total_attributed_net_revenue
          - credit_count
          - model_type (the model used, if consistent across runs)
          - data_quality (QualityStatus string)
          - credits (list of per-touchpoint credit rows)
        """
        pool = await self._pool()
        if pool is None:
            credits = [
                c for c in _local_credits
                if c.get("tenant_id") == tenant_id
                and c.get("campaign_id") == campaign_id
                and (cluster_id is None or c.get("cluster_id") == cluster_id)
                and (channel is None or c.get("channel") == channel)
            ]
            return _aggregate_campaign_credits(credits, model_type)

        conditions = ["ac.tenant_id = $1", "ac.campaign_id = $2", "ar.is_active = TRUE"]
        params: list[Any] = [tenant_id, campaign_id]
        p = 3

        if model_type:
            conditions.append(f"ar.model_type = ${p}")
            params.append(model_type)
            p += 1
        if start_date:
            conditions.append(f"ar.completed_at >= ${p}")
            params.append(start_date)
            p += 1
        if end_date:
            conditions.append(f"ar.completed_at < ${p}")
            params.append(end_date)
            p += 1
        if cluster_id:
            conditions.append(f"ac.cluster_id = ${p}")
            params.append(cluster_id)
            p += 1
        if channel:
            conditions.append(f"ac.channel = ${p}")
            params.append(channel)
            p += 1

        sql = f"""
            SELECT
                ac.*,
                ar.model_type,
                ar.model_version,
                ar.completed_at AS run_completed_at
            FROM attribution_credits ac
            JOIN attribution_runs ar ON ar.attribution_run_id = ac.attribution_run_id
            WHERE {' AND '.join(conditions)}
            ORDER BY ac.credit_weight DESC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            credits = [dict(r) for r in rows]

        return _aggregate_campaign_credits(credits, model_type)

    async def campaign_cluster_rollup(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        attribution_run_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return attribution economics grouped by cluster_id for a campaign.

        Useful for populating the Campaign 360 clusters tab with revenue rollups.
        Local mode always returns an empty list (no cross-table joins available).
        """
        pool = await self._pool()
        if pool is None:
            credits_by_cluster: dict[str, dict[str, Any]] = {}
            for c in _local_credits:
                if c.get("tenant_id") != tenant_id or c.get("campaign_id") != campaign_id:
                    continue
                if attribution_run_id and c.get("attribution_run_id") != attribution_run_id:
                    continue
                cid = c.get("cluster_id") or "__unresolved__"
                if cid not in credits_by_cluster:
                    credits_by_cluster[cid] = {
                        "cluster_id": cid if cid != "__unresolved__" else None,
                        "conversion_count": 0,
                        "attributed_gross_revenue": 0.0,
                        "attributed_net_revenue": 0.0,
                    }
                entry = credits_by_cluster[cid]
                entry["conversion_count"] += 1
                entry["attributed_gross_revenue"] += float(
                    _to_decimal(c.get("attributed_gross_revenue") or c.get("gross_value") or "0") or 0
                )
                entry["attributed_net_revenue"] += float(
                    _to_decimal(c.get("attributed_net_revenue") or c.get("net_value") or "0") or 0
                )
            return sorted(
                credits_by_cluster.values(),
                key=lambda x: x["attributed_gross_revenue"],
                reverse=True,
            )

        run_filter = ""
        params: list[Any] = [tenant_id, campaign_id]
        if attribution_run_id:
            run_filter = "AND ac.attribution_run_id = $3"
            params.append(attribution_run_id)

        sql = f"""
            SELECT
                ac.cluster_id,
                COUNT(DISTINCT ac.conversion_id) AS conversion_count,
                COALESCE(SUM(ac.credit_weight * cc.gross_value), 0) AS attributed_gross_revenue,
                COALESCE(SUM(ac.credit_weight * cc.net_value), 0) AS attributed_net_revenue
            FROM attribution_credits ac
            JOIN canonical_conversions cc ON cc.conversion_id = ac.conversion_id
            JOIN attribution_runs ar ON ar.attribution_run_id = ac.attribution_run_id
            WHERE ac.tenant_id = $1
              AND ac.campaign_id = $2
              AND ar.is_active = TRUE
              {run_filter}
            GROUP BY ac.cluster_id
            ORDER BY attributed_gross_revenue DESC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _aggregate_campaign_credits(credits: list[dict[str, Any]], model_type: Optional[str]) -> dict[str, Any]:
    if not credits:
        return {
            "total_attributed_conversions": Decimal("0"),
            "total_attributed_gross_revenue": Decimal("0"),
            "total_attributed_net_revenue": Decimal("0"),
            "credit_count": 0,
            "model_type": model_type,
            "data_quality": "not_provisioned",
            "credits": [],
        }

    total_conversions = sum(
        _to_decimal(c.get("attributed_conversion_count", "0")) for c in credits
    )
    total_gross = sum(
        _to_decimal(c.get("attributed_gross_revenue") or "0") for c in credits
    )
    total_net = sum(
        _to_decimal(c.get("attributed_net_revenue") or "0") for c in credits
    )
    model_types = {c.get("model_type") for c in credits if c.get("model_type")}
    derived_model = next(iter(model_types)) if len(model_types) == 1 else "mixed"

    return {
        "total_attributed_conversions": total_conversions,
        "total_attributed_gross_revenue": total_gross,
        "total_attributed_net_revenue": total_net,
        "credit_count": len(credits),
        "model_type": model_type or derived_model,
        "data_quality": "complete",
        "credits": credits,
    }


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
