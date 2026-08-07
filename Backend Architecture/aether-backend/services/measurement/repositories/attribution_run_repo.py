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
# Model configs share the same dual-mode store idiom as runs/credits: in local
# mode (no pool) both the write (API) and the read (engine.get_model_config)
# hit this one module object, so an API-created config is actually visible to
# the engine. Production persists to the attribution_model_configs table.
_local_model_configs: dict[str, list[dict[str, Any]]] = {}


def _reset_local_attribution() -> None:
    """Test helper — clear the in-memory attribution stores between cases.

    reset_in_memory_stores() operates on BaseRepository tables and does not
    touch these module-level dicts, so tests that exercise the config→engine
    bridge must reset them explicitly to avoid cross-test bleed.
    """
    _local_runs.clear()
    _local_credits.clear()
    _local_model_configs.clear()

_RUN_MUTABLE_COLUMNS = (
    "status", "failure_reason", "is_active", "completed_at", "started_at",
    "credit_total", "unattributed_credit", "model_confidence", "identity_confidence",
    "journey_id", "journey_version_id", "input_touchpoint_ids",
    "excluded_touchpoint_ids", "exclusion_reasons", "data_watermark",
    "trigger_reason", "source_classifier_version", "prior_attribution_run_id",
)

_CREDIT_COLUMNS = (
    "credit_id", "tenant_id", "attribution_run_id", "conversion_id",
    "touchpoint_id", "campaign_id", "ad_group_id", "ad_set_id",
    "creative_id", "ad_id", "placement_id", "keyword_id",
    "channel", "source", "source_class", "referral_mediation_type",
    "ai_provider", "ai_product", "actor_type", "journey_role",
    "evidence_confidence", "verification_level", "source_classifier_version",
    "normalized_referrer_domain", "source_classification_id",
    "attribution_eligible", "verified_referral_link_id",
    "credit_weight", "attributed_conversion_count",
    "attributed_gross_revenue", "attributed_net_revenue",
    "attributed_contribution_value", "identity_confidence", "model_confidence",
    "explanation", "evidence_ids", "created_at",
)


class AttributionRunRepository:
    """Durable access to attribution_runs and attribution_credits tables.

    Production: asyncpg queries against PostgreSQL.
    Local/test: in-memory dicts (shared via module-level stores).
    """

    async def _pool(self):
        return await get_pool()

    async def get_model_config(
        self, tenant_id: str, model_config_id: str
    ) -> Optional[dict[str, Any]]:
        """Load the authoritative versioned model configuration."""

        config_uuid = _uuid_or_none(model_config_id)
        if config_uuid is None:
            return None
        pool = await self._pool()
        if pool is None:
            # Compare against the normalized UUID so local lookup matches
            # Postgres's case-insensitive UUID equality (a caller may pass an
            # upper/mixed-case UUID string).
            for cfg in _local_model_configs.get(tenant_id, []):
                if str(cfg.get("model_config_id")) == str(config_uuid):
                    return cfg
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM attribution_model_configs
                WHERE tenant_id=$1 AND model_config_id=$2
                """,
                tenant_id,
                config_uuid,
            )
        return dict(row) if row else None

    async def create_model_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Persist a versioned attribution model config so the engine can read it.

        Local mode writes the shared module store the engine reads via
        get_model_config; production upserts the typed attribution_model_configs
        table. This closes the split where the API wrote a per-worker in-memory
        dict that the engine (which queries the table) never saw.
        """
        config.setdefault("model_config_id", str(uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        config.setdefault("created_at", now)
        config.setdefault("effective_from", now)
        config.setdefault("status", "active")
        tenant_id = config.get("tenant_id")

        pool = await self._pool()
        if pool is None:
            _local_model_configs.setdefault(tenant_id, []).append(config)
            return config

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO attribution_model_configs (
                    model_config_id, tenant_id, name, model_type, model_version,
                    conversion_types, click_lookback_window, view_lookback_window,
                    session_timeout_seconds, direct_traffic_policy,
                    identity_confidence_min, fraud_policy, status,
                    effective_from, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (tenant_id, model_config_id) DO UPDATE SET
                    name=EXCLUDED.name,
                    model_type=EXCLUDED.model_type,
                    model_version=EXCLUDED.model_version,
                    conversion_types=EXCLUDED.conversion_types,
                    click_lookback_window=EXCLUDED.click_lookback_window,
                    view_lookback_window=EXCLUDED.view_lookback_window,
                    session_timeout_seconds=EXCLUDED.session_timeout_seconds,
                    direct_traffic_policy=EXCLUDED.direct_traffic_policy,
                    identity_confidence_min=EXCLUDED.identity_confidence_min,
                    fraud_policy=EXCLUDED.fraud_policy,
                    status=EXCLUDED.status
                """,
                _uuid_or_none(config["model_config_id"]), tenant_id,
                config.get("name"), config.get("model_type"),
                config.get("model_version", "1.0"),
                json.dumps(config.get("conversion_types") or ["all"]),
                int(config.get("click_lookback_window", 720)),
                int(config.get("view_lookback_window", 168)),
                int(config.get("session_timeout_seconds", 1800)),
                config.get("direct_traffic_policy", "include"),
                config.get("identity_confidence_min", 0.5),
                config.get("fraud_policy", "exclude"),
                config.get("status", "active"),
                _parse_ts(config.get("effective_from")) or datetime.now(timezone.utc),
                _parse_ts(config.get("created_at")) or datetime.now(timezone.utc),
            )
        return config

    async def list_model_configs(self, tenant_id: str) -> list[dict[str, Any]]:
        """List a tenant's attribution model configs (newest first)."""
        pool = await self._pool()
        if pool is None:
            return list(_local_model_configs.get(tenant_id, []))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM attribution_model_configs
                WHERE tenant_id=$1
                ORDER BY created_at DESC
                """,
                tenant_id,
            )
        return [dict(r) for r in rows]

    # ── Runs ─────────────────────────────────────────────────────────────────

    async def create_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Insert a new attribution run (status='pending')."""
        run.setdefault("attribution_run_id", str(uuid4()))
        run.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        run.setdefault("status", "pending")
        run.setdefault("is_active", False)
        run.setdefault("input_touchpoint_ids", [])
        run.setdefault("excluded_touchpoint_ids", [])
        run.setdefault("exclusion_reasons", {})

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
                    model_config_snapshot,
                    input_touchpoint_ids, excluded_touchpoint_ids, exclusion_reasons,
                    eligible_revenue, credit_total, unattributed_credit,
                    identity_confidence, model_confidence, data_watermark,
                    currency, status, failure_reason, is_active,
                    trigger_reason, source_classifier_version, prior_attribution_run_id,
                    started_at, completed_at, created_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,$27,$28,$29,$30
                )
                """,
                _uuid_or_none(run.get("attribution_run_id")), run.get("tenant_id"),
                _uuid_or_none(run.get("conversion_id")), run.get("conversion_version"),
                _uuid_or_none(run.get("journey_id")), _uuid_or_none(run.get("journey_version_id")),
                _uuid_or_none(run.get("model_config_id")), run.get("model_type", "last_touch"),
                run.get("model_version", "1.0"), run.get("code_version"),
                json.dumps(run.get("model_config_snapshot") or {}, default=str),
                json.dumps(run.get("input_touchpoint_ids", [])),
                json.dumps(run.get("excluded_touchpoint_ids", [])),
                json.dumps(run.get("exclusion_reasons", {})),
                _to_decimal(run.get("eligible_revenue")),
                _to_decimal(run.get("credit_total", "1.0")),
                _to_decimal(run.get("unattributed_credit", "0.0")),
                run.get("identity_confidence"), run.get("model_confidence"),
                _parse_ts(run.get("data_watermark")),
                run.get("currency", "USD"), run.get("status", "pending"),
                run.get("failure_reason"), run.get("is_active", False),
                run.get("trigger_reason"), run.get("source_classifier_version"),
                _uuid_or_none(run.get("prior_attribution_run_id")),
                _parse_ts(run.get("started_at")), _parse_ts(run.get("completed_at")),
                _parse_ts(run.get("created_at")),
            )
        return run

    async def update_run(
        self,
        attribution_run_id: str,
        updates: dict[str, Any],
        *,
        tenant_id: str,
    ) -> Optional[dict[str, Any]]:
        """Update mutable fields on a run (status, completed_at, failure_reason, is_active)."""
        pool = await self._pool()
        if pool is None:
            run = _local_runs.get(attribution_run_id)
            if run is None or run.get("tenant_id") != tenant_id:
                return None
            run.update(updates)
            return run

        sets, params = _run_update_parts(updates)
        if not sets:
            return await self.get_run(attribution_run_id, tenant_id=tenant_id)

        params.append(_uuid_or_none(attribution_run_id))
        run_param = len(params)
        params.append(tenant_id)
        tenant_param = len(params)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE attribution_runs SET {', '.join(sets)} "
                f"WHERE attribution_run_id=${run_param} "
                f"AND tenant_id=${tenant_param} RETURNING *",
                *params,
            )
            return dict(row) if row else None

    async def complete_run_atomically(
        self,
        attribution_run_id: str,
        tenant_id: str,
        conversion_id: str,
        credits: list[dict[str, Any]],
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Insert credits and switch the active run in one transaction.

        This is the only success path that should activate an attribution run.
        A failed insert or concurrent unique-index conflict rolls the whole
        switch back, leaving the previously active run and its credits intact.
        """
        completed_updates = {
            **updates,
            "status": "complete",
            "is_active": True,
            "completed_at": updates.get("completed_at")
            or datetime.now(timezone.utc).isoformat(),
        }
        prepared_credits = [
            _prepare_credit(c, tenant_id, attribution_run_id, conversion_id)
            for c in credits
        ]

        pool = await self._pool()
        if pool is None:
            run = _local_runs.get(attribution_run_id)
            if (
                run is None
                or run.get("tenant_id") != tenant_id
                or str(run.get("conversion_id")) != str(conversion_id)
            ):
                return None

            # All validation/preparation happens before mutating either store,
            # giving local mode the same observable all-or-nothing behavior.
            for prior in _local_runs.values():
                if (
                    prior.get("tenant_id") == tenant_id
                    and str(prior.get("conversion_id")) == str(conversion_id)
                    and prior.get("attribution_run_id") != attribution_run_id
                ):
                    prior["is_active"] = False
            _local_credits.extend(prepared_credits)
            run.update(completed_updates)
            return run

        async with pool.acquire() as conn:
            async with conn.transaction():
                target = await conn.fetchrow(
                    """
                    SELECT attribution_run_id FROM attribution_runs
                    WHERE tenant_id=$1 AND attribution_run_id=$2
                      AND conversion_id=$3
                    FOR UPDATE
                    """,
                    tenant_id, _uuid_or_none(attribution_run_id), _uuid_or_none(conversion_id),
                )
                if target is None:
                    return None

                # Serialize against the current active run before switching.
                await conn.fetch(
                    """
                    SELECT attribution_run_id FROM attribution_runs
                    WHERE tenant_id=$1 AND conversion_id=$2 AND is_active=TRUE
                    FOR UPDATE
                    """,
                    tenant_id, _uuid_or_none(conversion_id),
                )
                if prepared_credits:
                    await _insert_credits_conn(conn, prepared_credits)
                await conn.execute(
                    """
                    UPDATE attribution_runs SET is_active=FALSE
                    WHERE tenant_id=$1 AND conversion_id=$2
                      AND attribution_run_id<>$3 AND is_active=TRUE
                    """,
                    tenant_id, _uuid_or_none(conversion_id), _uuid_or_none(attribution_run_id),
                )

                sets, params = _run_update_parts(completed_updates)
                params.extend([tenant_id, _uuid_or_none(attribution_run_id)])
                tenant_param = len(params) - 1
                run_param = len(params)
                row = await conn.fetchrow(
                    f"UPDATE attribution_runs SET {', '.join(sets)} "
                    f"WHERE tenant_id=${tenant_param} AND attribution_run_id=${run_param} "
                    "RETURNING *",
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
                        and str(run.get("conversion_id")) == str(conversion_id)
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
                tenant_id, _uuid_or_none(conversion_id),
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
                    _uuid_or_none(attribution_run_id), tenant_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM attribution_runs WHERE attribution_run_id=$1",
                    _uuid_or_none(attribution_run_id),
                )
            return dict(row) if row else None

    async def get_active_run(self, tenant_id: str, conversion_id: str) -> Optional[dict[str, Any]]:
        """Return the currently active attribution run for a conversion."""
        pool = await self._pool()
        if pool is None:
            return next(
                (r for r in _local_runs.values()
                 if r.get("tenant_id") == tenant_id
                 and str(r.get("conversion_id")) == str(conversion_id)
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
                tenant_id, _uuid_or_none(conversion_id),
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
            # campaign_id lives on attribution_credits, not attribution_runs — look up via credits
            if campaign_id is not None:
                run_ids_for_campaign = {
                    c["attribution_run_id"] for c in _local_credits
                    if c.get("campaign_id") == campaign_id and c.get("tenant_id") == tenant_id
                }
            else:
                run_ids_for_campaign = None
            rows = [
                r for r in _local_runs.values()
                if r.get("tenant_id") == tenant_id
                and (run_ids_for_campaign is None or r.get("attribution_run_id") in run_ids_for_campaign)
                and (conversion_id is None or r.get("conversion_id") == conversion_id)
                and (status is None or r.get("status") == status)
            ]
            rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            return rows[:limit]

        conditions = ["ar.tenant_id = $1"]
        params: list[Any] = [tenant_id]
        p = 2
        join_credits = False
        if campaign_id:
            # campaign_id lives on attribution_credits, not attribution_runs
            join_credits = True
            conditions.append(f"ac.campaign_id = ${p}")
            params.append(campaign_id)
            p += 1
        if conversion_id:
            conditions.append(f"ar.conversion_id = ${p}")
            params.append(_uuid_or_none(conversion_id))
            p += 1
        if status:
            conditions.append(f"ar.status = ${p}")
            params.append(status)
            p += 1
        if cursor:
            conditions.append(f"ar.created_at < ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        join_clause = (
            "JOIN attribution_credits ac ON ac.attribution_run_id = ar.attribution_run_id AND ac.tenant_id = ar.tenant_id"
            if join_credits
            else ""
        )
        sql = f"""
            SELECT DISTINCT ar.* FROM attribution_runs ar
            {join_clause}
            WHERE {' AND '.join(conditions)}
            ORDER BY ar.created_at DESC
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
                prepared = _prepare_credit(
                    c,
                    str(c.get("tenant_id") or ""),
                    str(c.get("attribution_run_id") or ""),
                    str(c.get("conversion_id") or ""),
                )
                _local_credits.append(prepared)
            return len(credits)

        async with pool.acquire() as conn:
            async with conn.transaction():
                prepared = [
                    _prepare_credit(
                        c,
                        str(c.get("tenant_id") or ""),
                        str(c.get("attribution_run_id") or ""),
                        str(c.get("conversion_id") or ""),
                    )
                    for c in credits
                ]
                await _insert_credits_conn(conn, prepared)
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
                tenant_id, _uuid_or_none(attribution_run_id),
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
                    JOIN attribution_runs ar
                      ON ar.tenant_id = ac.tenant_id
                     AND ar.attribution_run_id = ac.attribution_run_id
                    WHERE ac.tenant_id = $1 AND ac.conversion_id = $2 AND ar.is_active = TRUE
                    ORDER BY ac.credit_weight DESC
                    """,
                    tenant_id, _uuid_or_none(conversion_id),
                )
                return [dict(r) for r in rows]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM attribution_credits WHERE tenant_id=$1 AND conversion_id=$2 ORDER BY credit_weight DESC",
                tenant_id, _uuid_or_none(conversion_id),
            )
            return [dict(r) for r in rows]

    async def list_active_credits_for_conversions(
        self, tenant_id: str, conversion_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Bulk-load active credits for journey economic drill-downs."""

        conversion_uuids = [
            value
            for value in (_uuid_or_none(item) for item in conversion_ids)
            if value is not None
        ]
        if not conversion_uuids:
            return []
        pool = await self._pool()
        if pool is None:
            requested = {str(value) for value in conversion_uuids}
            active_ids = {
                str(run_id)
                for run_id, run in _local_runs.items()
                if run.get("tenant_id") == tenant_id
                and run.get("is_active")
                and str(run.get("conversion_id")) in requested
            }
            return [
                credit
                for credit in _local_credits
                if credit.get("tenant_id") == tenant_id
                and str(credit.get("attribution_run_id")) in active_ids
            ]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ac.*
                FROM attribution_credits ac
                JOIN attribution_runs ar
                  ON ar.tenant_id = ac.tenant_id
                 AND ar.attribution_run_id = ac.attribution_run_id
                WHERE ac.tenant_id=$1
                  AND ac.conversion_id = ANY($2::uuid[])
                  AND ar.is_active=TRUE
                """,
                tenant_id,
                conversion_uuids,
            )
        return [dict(row) for row in rows]

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
            active_run_ids = {
                run_id for run_id, run in _local_runs.items()
                if run.get("tenant_id") == tenant_id and run.get("is_active")
            }
            credits = [
                c for c in _local_credits
                if c.get("tenant_id") == tenant_id
                and c.get("attribution_run_id") in active_run_ids
                and c.get("campaign_id") == campaign_id
                and (
                    start_date is None
                    or (_parse_ts(c.get("conversion_occurred_at")) or datetime.min.replace(tzinfo=timezone.utc))
                    >= start_date
                )
                and (
                    end_date is None
                    or (_parse_ts(c.get("conversion_occurred_at")) or datetime.max.replace(tzinfo=timezone.utc))
                    < end_date
                )
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
            conditions.append(f"cc.occurred_at >= ${p}")
            params.append(start_date)
            p += 1
        if end_date:
            conditions.append(f"cc.occurred_at < ${p}")
            params.append(end_date)
            p += 1
        if cluster_id:
            conditions.append(f"cc.cluster_id = ${p}")
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
            JOIN attribution_runs ar
              ON ar.tenant_id = ac.tenant_id
             AND ar.attribution_run_id = ac.attribution_run_id
            JOIN canonical_conversions cc
              ON cc.tenant_id = ac.tenant_id
             AND cc.conversion_id = ac.conversion_id
            WHERE {' AND '.join(conditions)}
            ORDER BY ac.credit_weight DESC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            credits = [dict(r) for r in rows]

        return _aggregate_campaign_credits(credits, model_type)

    async def referral_performance(
        self,
        tenant_id: str,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        campaign_id: Optional[str] = None,
        ai_provider: Optional[str] = None,
        ai_product: Optional[str] = None,
        referral_mediation_type: Optional[str] = None,
        source_class: Optional[str] = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        """Aggregate active credit economics by referral/source dimensions."""
        filters = {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "campaign_id": campaign_id,
            "ai_provider": ai_provider,
            "ai_product": ai_product,
            "referral_mediation_type": referral_mediation_type,
            "source_class": source_class,
        }
        pool = await self._pool()
        if pool is None:
            active_runs = {
                run_id: run for run_id, run in _local_runs.items()
                if run.get("tenant_id") == tenant_id and run.get("is_active")
            }
            credits: list[dict[str, Any]] = []
            for credit in _local_credits:
                run = active_runs.get(str(credit.get("attribution_run_id")))
                if run is None:
                    continue
                conversion_occurred_at = _parse_ts(
                    credit.get("conversion_occurred_at")
                )
                if start_date and (
                    conversion_occurred_at is None
                    or conversion_occurred_at < start_date
                ):
                    continue
                if end_date and (
                    conversion_occurred_at is None
                    or conversion_occurred_at >= end_date
                ):
                    continue
                if campaign_id and credit.get("campaign_id") != campaign_id:
                    continue
                if ai_provider and credit.get("ai_provider") != ai_provider:
                    continue
                if ai_product and credit.get("ai_product") != ai_product:
                    continue
                if referral_mediation_type and credit.get("referral_mediation_type") != referral_mediation_type:
                    continue
                if source_class and credit.get("source_class") != source_class:
                    continue
                if not credit.get("source_class") and not credit.get("referral_mediation_type"):
                    continue
                credits.append(credit)
            return _aggregate_referral_performance(tenant_id, filters, credits, limit)

        conditions = [
            "ac.tenant_id = $1",
            "ar.is_active = TRUE",
            "(ac.source_class IS NOT NULL OR ac.referral_mediation_type IS NOT NULL)",
        ]
        params: list[Any] = [tenant_id]

        def _add_condition(sql: str, value: Any) -> None:
            params.append(value)
            conditions.append(sql.format(p=len(params)))

        if start_date:
            _add_condition("cc.occurred_at >= ${p}", start_date)
        if end_date:
            _add_condition("cc.occurred_at < ${p}", end_date)
        if campaign_id:
            _add_condition("ac.campaign_id = ${p}", campaign_id)
        if ai_provider:
            _add_condition("ac.ai_provider = ${p}", ai_provider)
        if ai_product:
            _add_condition("ac.ai_product = ${p}", ai_product)
        if referral_mediation_type:
            _add_condition("ac.referral_mediation_type = ${p}", referral_mediation_type)
        if source_class:
            _add_condition("ac.source_class = ${p}", source_class)
        params.append(max(1, min(limit, 1000)))
        limit_param = len(params)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    ac.source_class,
                    ac.referral_mediation_type,
                    ac.ai_provider,
                    ac.ai_product,
                    ac.actor_type,
                    ac.journey_role,
                    ac.verification_level,
                    COUNT(*) AS credit_count,
                    COUNT(DISTINCT ac.conversion_id) AS conversion_count,
                    COALESCE(SUM(ac.attributed_conversion_count), 0) AS attributed_conversions,
                    COALESCE(SUM(ac.attributed_gross_revenue), 0) AS attributed_gross_revenue,
                    COALESCE(SUM(ac.attributed_net_revenue), 0) AS attributed_net_revenue,
                    COALESCE(SUM(ac.attributed_contribution_value), 0) AS attributed_contribution_value
                FROM attribution_credits ac
                JOIN attribution_runs ar
                  ON ar.tenant_id = ac.tenant_id
                 AND ar.attribution_run_id = ac.attribution_run_id
                JOIN canonical_conversions cc
                  ON cc.tenant_id = ac.tenant_id
                 AND cc.conversion_id = ac.conversion_id
                WHERE {' AND '.join(conditions)}
                GROUP BY
                    ac.source_class, ac.referral_mediation_type,
                    ac.ai_provider, ac.ai_product, ac.actor_type,
                    ac.journey_role, ac.verification_level
                ORDER BY attributed_net_revenue DESC, credit_count DESC
                LIMIT ${limit_param}
                """,
                *params,
            )
        grouped = [dict(row) for row in rows]
        return _referral_performance_response(tenant_id, filters, grouped)

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
            params.append(_uuid_or_none(attribution_run_id))

        sql = f"""
            SELECT
                cc.cluster_id,
                COUNT(DISTINCT ac.conversion_id) AS conversion_count,
                COALESCE(SUM(ac.credit_weight * cc.gross_value), 0) AS attributed_gross_revenue,
                COALESCE(SUM(ac.credit_weight * cc.net_value), 0) AS attributed_net_revenue
            FROM attribution_credits ac
            JOIN canonical_conversions cc
              ON cc.tenant_id = ac.tenant_id
             AND cc.conversion_id = ac.conversion_id
            JOIN attribution_runs ar
              ON ar.tenant_id = ac.tenant_id
             AND ar.attribution_run_id = ac.attribution_run_id
            WHERE ac.tenant_id = $1
              AND ac.campaign_id = $2
              AND ar.is_active = TRUE
              {run_filter}
            GROUP BY cc.cluster_id
            ORDER BY attributed_gross_revenue DESC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_update_parts(updates: dict[str, Any]) -> tuple[list[str], list[Any]]:
    sets: list[str] = []
    params: list[Any] = []
    for col in _RUN_MUTABLE_COLUMNS:
        if col not in updates:
            continue
        value = updates[col]
        if col in ("completed_at", "started_at", "data_watermark"):
            value = _parse_ts(value)
        elif col in ("journey_id", "journey_version_id", "prior_attribution_run_id"):
            value = _uuid_or_none(value)
        elif col in ("credit_total", "unattributed_credit"):
            value = _to_decimal(value)
        elif col in ("input_touchpoint_ids", "excluded_touchpoint_ids", "exclusion_reasons"):
            value = json.dumps(value or ([] if col != "exclusion_reasons" else {}))
        params.append(value)
        sets.append(f"{col} = ${len(params)}")
    return sets, params


def _prepare_credit(
    credit: dict[str, Any],
    tenant_id: str,
    attribution_run_id: str,
    conversion_id: str,
) -> dict[str, Any]:
    """Validate credit ownership and apply immutable identifiers/defaults."""
    prepared = dict(credit)
    for field, expected in (
        ("tenant_id", tenant_id),
        ("attribution_run_id", attribution_run_id),
        ("conversion_id", conversion_id),
    ):
        existing = prepared.get(field)
        if existing is not None and str(existing) != str(expected):
            raise ValueError(f"credit {field} does not match attribution run")
        prepared[field] = expected
    prepared.setdefault("credit_id", str(uuid4()))
    prepared.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    prepared.setdefault("attribution_eligible", True)
    prepared.setdefault("evidence_ids", [])
    return prepared


def _credit_params(c: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _uuid_or_none(c.get("credit_id")), c.get("tenant_id"), _uuid_or_none(c.get("attribution_run_id")),
        _uuid_or_none(c.get("conversion_id")), _uuid_or_none(c.get("touchpoint_id")), c.get("campaign_id"),
        c.get("ad_group_id"), c.get("ad_set_id"), c.get("creative_id"),
        c.get("ad_id"), c.get("placement_id"), c.get("keyword_id"),
        c.get("channel"), c.get("source"), c.get("source_class"),
        c.get("referral_mediation_type"), c.get("ai_provider"), c.get("ai_product"),
        c.get("actor_type"), c.get("journey_role"), c.get("evidence_confidence"),
        c.get("verification_level"), c.get("source_classifier_version"),
        c.get("normalized_referrer_domain"), _uuid_or_none(c.get("source_classification_id")),
        c.get("attribution_eligible", True), _uuid_or_none(c.get("verified_referral_link_id")),
        _to_decimal(c.get("credit_weight", "0")),
        _to_decimal(c.get("attributed_conversion_count", "0")),
        _to_decimal(c.get("attributed_gross_revenue")),
        _to_decimal(c.get("attributed_net_revenue")),
        _to_decimal(c.get("attributed_contribution_value")),
        c.get("identity_confidence"), c.get("model_confidence"), c.get("explanation"),
        json.dumps(c.get("evidence_ids", [])),
        _parse_ts(c.get("created_at")) or datetime.now(timezone.utc),
    )


async def _insert_credits_conn(conn: Any, credits: list[dict[str, Any]]) -> None:
    placeholders = ",".join(f"${index}" for index in range(1, len(_CREDIT_COLUMNS) + 1))
    await conn.executemany(
        f"INSERT INTO attribution_credits ({','.join(_CREDIT_COLUMNS)}) "
        f"VALUES ({placeholders})",
        [_credit_params(c) for c in credits],
    )

def _aggregate_campaign_credits(credits: list[dict[str, Any]], model_type: Optional[str]) -> dict[str, Any]:
    if not credits:
        return {
            "total_attributed_conversions": Decimal("0"),
            "total_attributed_gross_revenue": Decimal("0"),
            "total_attributed_net_revenue": Decimal("0"),
            "conversions": Decimal("0"),
            "attributed_gross_revenue": Decimal("0"),
            "attributed_net_revenue": Decimal("0"),
            "credit_count": 0,
            "touchpoint_count": 0,
            "model_type": model_type,
            "data_quality": "not_provisioned",
            "dimension_rollups": _dimension_rollups([]),
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
        "conversions": total_conversions,
        "attributed_gross_revenue": total_gross,
        "attributed_net_revenue": total_net,
        "credit_count": len(credits),
        "touchpoint_count": len({str(c.get("touchpoint_id")) for c in credits if c.get("touchpoint_id")}),
        "model_type": model_type or derived_model,
        "data_quality": "complete",
        "dimension_rollups": _dimension_rollups(credits),
        "credits": credits,
    }


_ROLLUP_DIMENSIONS = (
    "source_class",
    "referral_mediation_type",
    "ai_provider",
    "ai_product",
    "actor_type",
    "journey_role",
    "verification_level",
)


def _dimension_rollups(credits: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for dimension in _ROLLUP_DIMENSIONS:
        groups: dict[str, dict[str, Any]] = {}
        for credit in credits:
            value = str(credit.get(dimension) or "unclassified")
            group = groups.setdefault(value, {
                "value": value,
                "credit_count": 0,
                "attributed_conversions": Decimal("0"),
                "attributed_gross_revenue": Decimal("0"),
                "attributed_net_revenue": Decimal("0"),
                "attributed_contribution_value": Decimal("0"),
            })
            group["credit_count"] += 1
            group["attributed_conversions"] += (
                _to_decimal(credit.get("attributed_conversion_count") or "0") or Decimal("0")
            )
            group["attributed_gross_revenue"] += (
                _to_decimal(credit.get("attributed_gross_revenue") or "0") or Decimal("0")
            )
            group["attributed_net_revenue"] += (
                _to_decimal(credit.get("attributed_net_revenue") or "0") or Decimal("0")
            )
            group["attributed_contribution_value"] += (
                _to_decimal(credit.get("attributed_contribution_value") or "0") or Decimal("0")
            )
        result[dimension] = sorted(
            groups.values(),
            key=lambda group: (
                group["attributed_net_revenue"],
                group["attributed_conversions"],
            ),
            reverse=True,
        )
    # Campaign360 needs the dimensions together (provider + product +
    # mediation + actor + role), while existing consumers use the independent
    # per-dimension arrays above. Keep both views in one backward-compatible
    # payload instead of creating a second reporting endpoint.
    combined = _aggregate_referral_performance("", {}, credits, 1000)
    result["items"] = combined["rows"]
    return result


def _aggregate_referral_performance(
    tenant_id: str,
    filters: dict[str, Any],
    credits: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for credit in credits:
        key = tuple(credit.get(dimension) for dimension in _ROLLUP_DIMENSIONS)
        row = grouped.setdefault(key, {
            **{dimension: credit.get(dimension) for dimension in _ROLLUP_DIMENSIONS},
            "credit_count": 0,
            "conversion_ids": set(),
            "attributed_conversions": Decimal("0"),
            "attributed_gross_revenue": Decimal("0"),
            "attributed_net_revenue": Decimal("0"),
            "attributed_contribution_value": Decimal("0"),
        })
        row["credit_count"] += 1
        row["conversion_ids"].add(str(credit.get("conversion_id")))
        for field in (
            "attributed_conversions",
            "attributed_gross_revenue",
            "attributed_net_revenue",
            "attributed_contribution_value",
        ):
            credit_field = (
                "attributed_conversion_count"
                if field == "attributed_conversions"
                else field
            )
            row[field] += _to_decimal(credit.get(credit_field) or "0") or Decimal("0")

    rows: list[dict[str, Any]] = []
    for row in grouped.values():
        conversion_ids = row.pop("conversion_ids")
        row["conversion_count"] = len(conversion_ids)
        rows.append(row)
    rows.sort(
        key=lambda row: (row["attributed_net_revenue"], row["credit_count"]),
        reverse=True,
    )
    return _referral_performance_response(
        tenant_id,
        filters,
        rows[:max(1, min(limit, 1000))],
    )


def _normalize_source_class_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize source_class outward in the canonical vocabulary (read path).

    Storage keeps historical values until an explicit reclassification repair;
    rows that only differ by a legacy alias are merged so callers never see
    both 'direct' and 'direct_unknown' for the same evidence.
    """
    from services.traffic.generated_registry import canonical_source_class

    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    numeric_fields = (
        "attributed_conversions",
        "attributed_gross_revenue",
        "attributed_net_revenue",
        "attributed_contribution_value",
    )
    count_fields = ("credit_count", "conversion_count")
    for row in rows:
        normalized = dict(row)
        if normalized.get("source_class"):
            normalized["source_class"] = canonical_source_class(
                str(normalized["source_class"])
            )
        key = tuple(normalized.get(dimension) for dimension in _ROLLUP_DIMENSIONS)
        existing = merged.get(key)
        if existing is None:
            merged[key] = normalized
            continue
        for field in count_fields:
            if field in existing or field in normalized:
                existing[field] = int(existing.get(field) or 0) + int(
                    normalized.get(field) or 0
                )
        for field in numeric_fields:
            existing[field] = (
                (_to_decimal(existing.get(field) or "0") or Decimal("0"))
                + (_to_decimal(normalized.get(field) or "0") or Decimal("0"))
            )
    result = list(merged.values())
    result.sort(
        key=lambda row: (
            _to_decimal(row.get("attributed_net_revenue") or "0") or Decimal("0"),
            int(row.get("credit_count") or 0),
        ),
        reverse=True,
    )
    return result


def _referral_performance_response(
    tenant_id: str,
    filters: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = _normalize_source_class_rows(rows)
    return {
        "tenant_id": tenant_id,
        "filters": filters,
        "data_quality": "complete" if rows else "not_provisioned",
        "row_count": len(rows),
        "total_attributed_conversions": sum(
            (_to_decimal(row.get("attributed_conversions") or "0") or Decimal("0"))
            for row in rows
        ),
        "total_attributed_gross_revenue": sum(
            (_to_decimal(row.get("attributed_gross_revenue") or "0") or Decimal("0"))
            for row in rows
        ),
        "total_attributed_net_revenue": sum(
            (_to_decimal(row.get("attributed_net_revenue") or "0") or Decimal("0"))
            for row in rows
        ),
        "total_attributed_contribution_value": sum(
            (_to_decimal(row.get("attributed_contribution_value") or "0") or Decimal("0"))
            for row in rows
        ),
        "rows": rows,
    }


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _uuid_or_none(value: Any) -> Optional[UUID]:
    if value in (None, ""):
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _decode_cursor(cursor: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(cursor)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
