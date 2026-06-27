"""Journey repository — durable access to versioned journey_versions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.journey_repo")

_local_store: dict[str, dict[str, Any]] = {}  # keyed by journey_version_id


class JourneyRepository:
    """Versioned journey storage over journey_versions.

    Each journey has a lineage of versions. At any time, exactly one version
    has is_current=TRUE per (journey_id, tenant_id). New versions are inserted
    with is_current=TRUE; old current versions are flipped to FALSE in the same
    transaction.
    """

    async def _pool(self):
        return await get_pool()

    async def create_version(self, journey: dict[str, Any]) -> dict[str, Any]:
        """Insert a new journey version and mark the prior current version as stale.

        The caller must set journey_id if this is a new version of an existing journey,
        or leave it unset for a brand-new journey (a UUID will be generated).
        """
        journey_id = journey.get("journey_id") or str(uuid4())
        version_id = journey.get("journey_version_id") or str(uuid4())
        journey.setdefault("journey_id", journey_id)
        journey.setdefault("journey_version_id", version_id)
        journey.setdefault("computed_at", datetime.now(timezone.utc).isoformat())
        journey.setdefault("is_current", True)
        journey.setdefault("journey_type", "profile")
        journey.setdefault("journey_state", "open")
        journey.setdefault("compiler_version", "1.0")

        pool = await self._pool()
        if pool is None:
            tenant_id = journey.get("tenant_id")
            # Flip prior current
            for v in _local_store.values():
                if (v.get("tenant_id") == tenant_id
                        and v.get("journey_id") == journey_id
                        and v.get("is_current")):
                    v["is_current"] = False
            _local_store[version_id] = journey
            return journey

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE journey_versions
                    SET is_current = FALSE
                    WHERE tenant_id = $1 AND journey_id = $2 AND is_current = TRUE
                    """,
                    journey.get("tenant_id"), journey_id,
                )
                await conn.execute(
                    """
                    INSERT INTO journey_versions (
                        journey_version_id, journey_id, tenant_id,
                        profile_id, cluster_id, account_id,
                        organization_id, wallet_id, agent_id,
                        journey_type, journey_state,
                        started_at, ended_at, converted_at,
                        entry_touchpoint_id, exit_touchpoint_id,
                        conversion_ids, event_ids, touchpoint_ids,
                        session_ids, device_ids, campaign_ids, channel_sequence,
                        previous_version_id, rebuild_reason,
                        identity_version, data_watermark,
                        compiler_version, computed_at, is_current,
                        step_count, web3_activity_ids, agent_activity_ids, x402_activity_ids
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                        $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                        $31,$32,$33,$34
                    )
                    """,
                    version_id, journey_id, journey.get("tenant_id"),
                    journey.get("profile_id"), journey.get("cluster_id"),
                    journey.get("account_id"), journey.get("organization_id"),
                    journey.get("wallet_id"), journey.get("agent_id"),
                    journey.get("journey_type", "profile"),
                    journey.get("journey_state", "open"),
                    _parse_ts(journey.get("started_at")),
                    _parse_ts(journey.get("ended_at")),
                    _parse_ts(journey.get("converted_at")),
                    journey.get("entry_touchpoint_id"),
                    journey.get("exit_touchpoint_id"),
                    json.dumps(journey.get("conversion_ids", [])),
                    json.dumps(journey.get("event_ids", [])),
                    json.dumps(journey.get("touchpoint_ids", [])),
                    json.dumps(journey.get("session_ids", [])),
                    json.dumps(journey.get("device_ids", [])),
                    json.dumps(journey.get("campaign_ids", [])),
                    json.dumps(journey.get("channel_sequence", [])),
                    journey.get("previous_version_id"),
                    journey.get("rebuild_reason"),
                    journey.get("identity_version"),
                    _parse_ts(journey.get("data_watermark")),
                    journey.get("compiler_version", "1.0"),
                    _parse_ts(journey.get("computed_at")),
                    True,
                    journey.get("step_count", 0),
                    json.dumps(journey.get("web3_activity_ids", [])),
                    json.dumps(journey.get("agent_activity_ids", [])),
                    json.dumps(journey.get("x402_activity_ids", [])),
                )
        return journey

    async def get_current(self, tenant_id: str, journey_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return next(
                (v for v in _local_store.values()
                 if v.get("tenant_id") == tenant_id
                 and v.get("journey_id") == journey_id
                 and v.get("is_current")),
                None,
            )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM journey_versions
                WHERE tenant_id=$1 AND journey_id=$2 AND is_current=TRUE
                """,
                tenant_id, journey_id,
            )
            return dict(row) if row else None

    async def get_version(self, tenant_id: str, journey_version_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            v = _local_store.get(journey_version_id)
            if v and v.get("tenant_id") != tenant_id:
                return None
            return v

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM journey_versions WHERE tenant_id=$1 AND journey_version_id=$2",
                tenant_id, journey_version_id,
            )
            return dict(row) if row else None

    async def list_versions(self, tenant_id: str, journey_id: str) -> list[dict[str, Any]]:
        """Return all versions for a journey, newest first."""
        pool = await self._pool()
        if pool is None:
            rows = [
                v for v in _local_store.values()
                if v.get("tenant_id") == tenant_id and v.get("journey_id") == journey_id
            ]
            rows.sort(key=lambda v: v.get("computed_at", ""), reverse=True)
            return rows

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM journey_versions WHERE tenant_id=$1 AND journey_id=$2 ORDER BY computed_at DESC",
                tenant_id, journey_id,
            )
            return [dict(r) for r in rows]

    async def find_current_for_profile(
        self,
        tenant_id: str,
        profile_id: str,
    ) -> list[dict[str, Any]]:
        """Return all current journey versions for a profile (can have multiple open journeys)."""
        pool = await self._pool()
        if pool is None:
            return [
                v for v in _local_store.values()
                if v.get("tenant_id") == tenant_id
                and v.get("is_current")
                and (v.get("profile_id") == profile_id or v.get("cluster_id") == profile_id)
            ]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM journey_versions
                WHERE tenant_id=$1 AND is_current=TRUE
                AND (profile_id=$2 OR cluster_id=$2)
                ORDER BY computed_at DESC
                """,
                tenant_id, profile_id,
            )
            return [dict(r) for r in rows]

    async def list_current(
        self,
        tenant_id: str,
        *,
        journey_state: Optional[str] = None,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                v for v in _local_store.values()
                if v.get("tenant_id") == tenant_id
                and v.get("is_current")
                and (journey_state is None or v.get("journey_state") == journey_state)
            ]
            rows.sort(key=lambda v: v.get("computed_at", ""), reverse=True)
            return rows[:limit]

        conditions = ["tenant_id = $1", "is_current = TRUE"]
        params: list[Any] = [tenant_id]
        p = 2
        if journey_state:
            conditions.append(f"journey_state = ${p}")
            params.append(journey_state)
            p += 1
        if cursor:
            conditions.append(f"computed_at < ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM journey_versions
            WHERE {' AND '.join(conditions)}
            ORDER BY computed_at DESC
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
        after_started: Optional[datetime] = None,
        before_started: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return current journey versions that include this campaign_id in their campaign_ids array."""
        pool = await self._pool()
        if pool is None:
            rows = [
                v for v in _local_store.values()
                if v.get("tenant_id") == tenant_id
                and v.get("is_current")
                and campaign_id in (v.get("campaign_ids") or [])
                and (after_started is None or (v.get("started_at") or "") > after_started.isoformat())
                and (before_started is None or (v.get("started_at") or "") < before_started.isoformat())
            ]
            rows.sort(key=lambda v: v.get("started_at", ""), reverse=True)
            return rows[:limit]

        conditions = [
            "tenant_id = $1",
            "is_current = TRUE",
            "campaign_ids @> ARRAY[$2]::text[]",
        ]
        params: list[Any] = [tenant_id, campaign_id]
        p = 3
        if after_started:
            conditions.append(f"started_at > ${p}")
            params.append(after_started)
            p += 1
        if before_started:
            conditions.append(f"started_at < ${p}")
            params.append(before_started)
            p += 1
        if cursor:
            conditions.append(f"started_at < ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM journey_versions
            WHERE {' AND '.join(conditions)}
            ORDER BY started_at DESC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

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
