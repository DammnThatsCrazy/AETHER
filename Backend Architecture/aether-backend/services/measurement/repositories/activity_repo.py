"""Canonical activity repository — durable cross-rail activity ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from repositories.repos import get_pool
from shared.logger.logger import get_logger

logger = get_logger("aether.measurement.activity_repo")

_local_store: dict[str, dict[str, Any]] = {}  # keyed by (tenant_id, idempotency_key)


class ActivityRepository:
    """Idempotent storage for canonical cross-rail activity facts.

    All writes are ON CONFLICT DO NOTHING against (tenant_id, idempotency_key),
    making every caller safe to replay from any source.

    Status updates (reorg, confirmation) are the only mutating operations and
    always require an explicit activity_id + tenant_id pair.
    """

    async def _pool(self):
        return await get_pool()

    async def upsert(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Insert a canonical activity row; silently skip if already present."""
        pool = await self._pool()
        idem_key = f"{activity.get('tenant_id')}:{activity.get('idempotency_key')}"

        if pool is None:
            if idem_key not in _local_store:
                _local_store[idem_key] = activity
            return _local_store[idem_key]

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO canonical_activity (
                    activity_id, tenant_id, idempotency_key,
                    profile_id, cluster_id, anonymous_id,
                    account_id, organization_id,
                    session_id, device_id, browser_id, install_id,
                    wallet_id, wallet_address, agent_id,
                    activity_family, activity_type, actor_type,
                    channel, source, medium, platform,
                    domain, app_id, screen, landing_url, referrer,
                    dapp_id, protocol_id, chain_id, contract_address,
                    tx_hash, block_number,
                    campaign_id, conversion_id,
                    occurred_at, client_occurred_at, server_received_at,
                    chain_observed_at, chain_confirmed_at,
                    activity_status,
                    source_event_id, source_system, source_connector_id,
                    identity_method, identity_confidence, identity_version,
                    consent_snapshot_id, privacy_class,
                    sequence_key, schema_version,
                    silver_fact_id, silver_table,
                    gross_amount, net_amount, fee_amount,
                    currency, token_address, value_wei
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                    $31,$32,$33,$34,$35,$36,$37,$38,$39,$40,
                    $41,$42,$43,$44,$45,$46,$47,$48,$49,$50,
                    $51,$52,$53,$54,$55,$56,$57,$58,$59,$60
                )
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                _uuid(activity.get("activity_id")),
                activity.get("tenant_id"),
                activity.get("idempotency_key"),
                activity.get("profile_id"),
                activity.get("cluster_id"),
                activity.get("anonymous_id"),
                activity.get("account_id"),
                activity.get("organization_id"),
                activity.get("session_id"),
                activity.get("device_id"),
                activity.get("browser_id"),
                activity.get("install_id"),
                activity.get("wallet_id"),
                activity.get("wallet_address"),
                activity.get("agent_id"),
                activity.get("activity_family"),
                activity.get("activity_type"),
                activity.get("actor_type"),
                activity.get("channel"),
                activity.get("source"),
                activity.get("medium"),
                activity.get("platform"),
                activity.get("domain"),
                activity.get("app_id"),
                activity.get("screen"),
                activity.get("landing_url"),
                activity.get("referrer"),
                activity.get("dapp_id"),
                activity.get("protocol_id"),
                activity.get("chain_id"),
                activity.get("contract_address"),
                activity.get("tx_hash"),
                activity.get("block_number"),
                activity.get("campaign_id"),
                activity.get("conversion_id"),
                _parse_ts(activity.get("occurred_at")),
                _parse_ts(activity.get("client_occurred_at")),
                _parse_ts(activity.get("server_received_at")) or datetime.now(timezone.utc),
                _parse_ts(activity.get("chain_observed_at")),
                _parse_ts(activity.get("chain_confirmed_at")),
                activity.get("activity_status", "observed"),
                activity.get("source_event_id"),
                activity.get("source_system"),
                activity.get("source_connector_id"),
                activity.get("identity_method"),
                activity.get("identity_confidence"),
                activity.get("identity_version"),
                activity.get("consent_snapshot_id"),
                activity.get("privacy_class", "behavioral"),
                activity.get("sequence_key"),
                activity.get("schema_version", 1),
                _uuid(activity.get("silver_fact_id")),
                activity.get("silver_table"),
                _decimal(activity.get("gross_amount")),
                _decimal(activity.get("net_amount")),
                _decimal(activity.get("fee_amount")),
                activity.get("currency"),
                activity.get("token_address"),
                activity.get("value_wei"),
            )
        return activity

    async def update_status(
        self,
        tenant_id: str,
        activity_id: str,
        status: str,
        *,
        chain_confirmed_at: Optional[datetime] = None,
        chain_observed_at: Optional[datetime] = None,
    ) -> bool:
        """Update lifecycle status of a single activity (e.g. on reorg or confirmation)."""
        pool = await self._pool()

        if pool is None:
            for row in _local_store.values():
                if (row.get("tenant_id") == tenant_id
                        and str(row.get("activity_id")) == activity_id):
                    row["activity_status"] = status
                    if chain_confirmed_at:
                        row["chain_confirmed_at"] = chain_confirmed_at.isoformat()
                    if chain_observed_at:
                        row["chain_observed_at"] = chain_observed_at.isoformat()
                    return True
            return False

        extra_sets = ""
        extra_params: list[Any] = [tenant_id, activity_id, status]
        p = 4
        if chain_confirmed_at:
            extra_sets += f", chain_confirmed_at = ${p}"
            extra_params.append(chain_confirmed_at)
            p += 1
        if chain_observed_at:
            extra_sets += f", chain_observed_at = ${p}"
            extra_params.append(chain_observed_at)

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE canonical_activity
                SET activity_status = $3{extra_sets}
                WHERE tenant_id = $1 AND activity_id = $2::uuid
                """,
                *extra_params,
            )
        return result != "UPDATE 0"

    async def update_status_by_tx_hash(
        self,
        tenant_id: str,
        tx_hash: str,
        status: str,
        *,
        chain_confirmed_at: Optional[datetime] = None,
    ) -> list[str]:
        """Update all activities for a tx_hash; returns affected activity_ids."""
        pool = await self._pool()

        if pool is None:
            affected = []
            for row in _local_store.values():
                if row.get("tenant_id") == tenant_id and row.get("tx_hash") == tx_hash:
                    row["activity_status"] = status
                    if chain_confirmed_at:
                        row["chain_confirmed_at"] = chain_confirmed_at.isoformat()
                    affected.append(str(row.get("activity_id")))
            return affected

        params: list[Any] = [tenant_id, tx_hash, status]
        extra = ""
        if chain_confirmed_at:
            extra = ", chain_confirmed_at = $4"
            params.append(chain_confirmed_at)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                UPDATE canonical_activity
                SET activity_status = $3{extra}
                WHERE tenant_id = $1 AND tx_hash = $2
                RETURNING activity_id::text
                """,
                *params,
            )
        return [r["activity_id"] for r in rows]

    async def tombstone_by_profile(self, tenant_id: str, profile_id: str) -> int:
        """Mark all activities for a profile as consent_restricted (DSR/consent revocation)."""
        pool = await self._pool()

        if pool is None:
            count = 0
            for row in _local_store.values():
                if (row.get("tenant_id") == tenant_id
                        and row.get("profile_id") == profile_id):
                    row["activity_status"] = "tombstoned"
                    count += 1
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE canonical_activity
                SET activity_status = 'tombstoned'
                WHERE tenant_id = $1 AND profile_id = $2
                  AND activity_status NOT IN ('tombstoned', 'deleted')
                """,
                tenant_id, profile_id,
            )
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0

    async def list_by_profile(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        limit: int = 2000,
        cursor: Optional[str] = None,
        families: Optional[list[str]] = None,
        statuses: Optional[list[str]] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Load all canonical activity for a profile, ordered deterministically."""
        pool = await self._pool()

        _excluded_statuses = {"tombstoned", "deleted", "consent_restricted"}
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("profile_id") == profile_id
                and r.get("activity_status") not in _excluded_statuses
                and (families is None or str(r.get("activity_family", "")) in families)
                and (statuses is None or str(r.get("activity_status", "")) in statuses)
                and (after is None or r.get("occurred_at", "") > _ts_str(after))
                and (before is None or r.get("occurred_at", "") < _ts_str(before))
            ]
            rows.sort(key=lambda r: (r.get("occurred_at", ""), r.get("sequence_key") or "", str(r.get("activity_id", ""))))
            return rows[:limit]

        conditions = ["tenant_id = $1", "profile_id = $2",
                      "activity_status NOT IN ('tombstoned', 'deleted', 'consent_restricted')"]
        params: list[Any] = [tenant_id, profile_id]
        p = 3

        if families:
            conditions.append(f"activity_family = ANY(${p}::text[])")
            params.append(families)
            p += 1
        if statuses:
            conditions.append(f"activity_status = ANY(${p}::text[])")
            params.append(statuses)
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
            conditions.append(f"(occurred_at, activity_id::text) > (${p}, ${p+1})")
            cur_ts, cur_id = _decode_cursor(cursor)
            params.extend([cur_ts, cur_id])
            p += 2

        params.append(limit)
        sql = f"""
            SELECT * FROM canonical_activity
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC, sequence_key ASC NULLS LAST, activity_id ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def list_by_anonymous(
        self,
        tenant_id: str,
        anonymous_id: str,
        *,
        limit: int = 2000,
        families: Optional[list[str]] = None,
        statuses: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Load activity for an anonymous identity."""
        pool = await self._pool()

        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("anonymous_id") == anonymous_id
                and (families is None or r.get("activity_family") in families)
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        conditions = ["tenant_id = $1", "anonymous_id = $2",
                      "activity_status NOT IN ('tombstoned', 'deleted', 'consent_restricted')"]
        params: list[Any] = [tenant_id, anonymous_id]
        p = 3
        if families:
            conditions.append(f"activity_family = ANY(${p}::text[])")
            params.append(families)
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM canonical_activity
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC, sequence_key ASC NULLS LAST, activity_id ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def list_by_wallet(
        self,
        tenant_id: str,
        wallet_id: str,
        *,
        limit: int = 500,
        families: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()

        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("wallet_id") == wallet_id
                and (families is None or r.get("activity_family") in families)
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        conditions = ["tenant_id = $1", "wallet_id = $2",
                      "activity_status NOT IN ('tombstoned', 'deleted', 'consent_restricted')"]
        params: list[Any] = [tenant_id, wallet_id]
        p = 3
        if families:
            conditions.append(f"activity_family = ANY(${p}::text[])")
            params.append(families)
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM canonical_activity
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC, activity_id ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def list_by_tx_hash(
        self,
        tenant_id: str,
        tx_hash: str,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()

        if pool is None:
            return [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id and r.get("tx_hash") == tx_hash
            ]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM canonical_activity WHERE tenant_id=$1 AND tx_hash=$2 ORDER BY occurred_at ASC",
                tenant_id, tx_hash,
            )
        return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _ts_str(dt: datetime) -> str:
    return dt.isoformat()


def _uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _decimal(value: Any):
    if value is None:
        return None
    from decimal import Decimal
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        parts = cursor.split("|", 1)
        ts = datetime.fromisoformat(parts[0])
        uid = parts[1] if len(parts) > 1 else ""
        return ts, uid
    except Exception:
        return datetime.now(timezone.utc), ""
