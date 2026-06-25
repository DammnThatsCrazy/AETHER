"""Touchpoint repository — durable access to silver_campaign_touchpoint_facts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.measurement.touchpoint_repo")

_IS_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"

# In-memory fallback (local/test only)
_local_store: dict[str, dict[str, Any]] = {}


class TouchpointRepository:
    """Canonical touchpoint storage over silver_campaign_touchpoint_facts.

    Production: asyncpg queries against PostgreSQL.
    Local/test: in-memory dict (shared via module-level _local_store).
    """

    async def _pool(self):
        return await get_pool()

    # ── Write ────────────────────────────────────────────────────────────────

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or ignore on idempotency_key conflict (safe replay)."""
        key = row.get("idempotency_key") or _derive_key(row)
        row.setdefault("idempotency_key", key)
        row.setdefault("touchpoint_id", str(uuid4()))
        row.setdefault("received_at", datetime.now(timezone.utc).isoformat())

        pool = await self._pool()
        if pool is None:
            _local_store[key] = row
            return row

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO silver_campaign_touchpoint_facts (
                    touchpoint_id, tenant_id, profile_id, cluster_id, anonymous_id,
                    session_id, device_id, account_id, organization_id, wallet_id,
                    agent_id, campaign_id, ad_group_id, ad_set_id, creative_id,
                    ad_id, placement_id, keyword_id, channel, source, medium,
                    platform, touchpoint_type, interaction_type,
                    is_view_through, is_click_through, viewable, engaged,
                    dwell_ms, position, frequency, occurred_at, received_at,
                    source_event_id, connector_record_id, source_connector_id,
                    utm_source, utm_medium, utm_campaign, utm_content, utm_term,
                    click_id, referrer, landing_url,
                    identity_resolution_method, identity_confidence, identity_version,
                    consent_snapshot_id, privacy_class, provenance, evidence_ids,
                    idempotency_key, schema_version
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                    $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
                    $31, $32, $33, $34, $35, $36, $37, $38, $39, $40,
                    $41, $42, $43, $44, $45, $46, $47, $48, $49, $50,
                    $51, $52, $53
                )
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                row.get("touchpoint_id"), row.get("tenant_id"),
                row.get("profile_id"), row.get("cluster_id"), row.get("anonymous_id"),
                row.get("session_id"), row.get("device_id"), row.get("account_id"),
                row.get("organization_id"), row.get("wallet_id"),
                row.get("agent_id"), row.get("campaign_id"), row.get("ad_group_id"),
                row.get("ad_set_id"), row.get("creative_id"), row.get("ad_id"),
                row.get("placement_id"), row.get("keyword_id"),
                row.get("channel"), row.get("source"), row.get("medium"),
                row.get("platform"),
                row.get("touchpoint_type", "page_view"),
                row.get("interaction_type"),
                row.get("is_view_through", False), row.get("is_click_through", False),
                row.get("viewable"), row.get("engaged"),
                row.get("dwell_ms"), row.get("position"), row.get("frequency"),
                _parse_ts(row.get("occurred_at")), _parse_ts(row.get("received_at")),
                row.get("source_event_id"), row.get("connector_record_id"),
                row.get("source_connector_id"),
                row.get("utm_source"), row.get("utm_medium"), row.get("utm_campaign"),
                row.get("utm_content"), row.get("utm_term"),
                row.get("click_id"), row.get("referrer"), row.get("landing_url"),
                row.get("identity_resolution_method"),
                row.get("identity_confidence"), row.get("identity_version"),
                row.get("consent_snapshot_id"),
                row.get("privacy_class", "behavioral"),
                json.dumps(row.get("provenance", {})),
                json.dumps(row.get("evidence_ids", [])),
                key,
                row.get("schema_version", 1),
            )
        return row

    async def upsert_from_campaign_touchpoint(
        self,
        tenant_id: str,
        campaign_id: str,
        touchpoint_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Convenience upsert for touchpoints arriving from the campaign API."""
        idem_key = hashlib.sha256(
            f"{tenant_id}:{touchpoint_id}:campaign_api".encode()
        ).hexdigest()

        row: dict[str, Any] = {
            "touchpoint_id": touchpoint_id,
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "anonymous_id": data.get("user_id"),  # user_id maps to anonymous_id at this stage
            "session_id": data.get("session_id"),
            "channel": data.get("channel"),
            "source": data.get("source"),
            "touchpoint_type": _classify_touchpoint(data.get("event_type", "pageview")),
            "occurred_at": data.get("occurred_at") or datetime.now(timezone.utc).isoformat(),
            "privacy_class": "behavioral",
            "idempotency_key": idem_key,
        }
        return await self.upsert(row)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_by_profile(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
        campaign_ids: Optional[list[str]] = None,
        limit: int = 500,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return touchpoints for a profile, ordered by occurred_at ascending."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and (r.get("profile_id") == profile_id or r.get("anonymous_id") == profile_id)
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        conditions = ["tenant_id = $1", "(profile_id = $2 OR anonymous_id = $2)"]
        params: list[Any] = [tenant_id, profile_id]
        p = 3
        if after_occurred:
            conditions.append(f"occurred_at > ${p}")
            params.append(after_occurred)
            p += 1
        if before_occurred:
            conditions.append(f"occurred_at < ${p}")
            params.append(before_occurred)
            p += 1
        if campaign_ids:
            conditions.append(f"campaign_id = ANY(${p}::text[])")
            params.append(campaign_ids)
            p += 1
        if cursor:
            conditions.append(f"occurred_at > ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM silver_campaign_touchpoint_facts
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
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
        channel: Optional[str] = None,
        touchpoint_type: Optional[str] = None,
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return touchpoints for a campaign — uses explicit pagination, no silent cap."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("campaign_id") == campaign_id
                and (channel is None or r.get("channel") == channel)
                and (touchpoint_type is None or r.get("touchpoint_type") == touchpoint_type)
                and (after_occurred is None or r.get("occurred_at", "") > after_occurred.isoformat())
                and (before_occurred is None or r.get("occurred_at", "") < before_occurred.isoformat())
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        conditions = ["tenant_id = $1", "campaign_id = $2"]
        params: list[Any] = [tenant_id, campaign_id]
        p = 3
        if after_occurred:
            conditions.append(f"occurred_at > ${p}")
            params.append(after_occurred)
            p += 1
        if before_occurred:
            conditions.append(f"occurred_at < ${p}")
            params.append(before_occurred)
            p += 1
        if channel:
            conditions.append(f"channel = ${p}")
            params.append(channel)
            p += 1
        if touchpoint_type:
            conditions.append(f"touchpoint_type = ${p}")
            params.append(touchpoint_type)
            p += 1
        if cursor:
            conditions.append(f"occurred_at > ${p}")
            params.append(_decode_cursor(cursor))
            p += 1
        params.append(limit)

        sql = f"""
            SELECT * FROM silver_campaign_touchpoint_facts
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    async def population_summary(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
    ) -> dict[str, int]:
        """Aggregate population funnel counts for a campaign.

        Returns observed/resolved/engaged counts from touchpoint data.
        Engagement is defined as any non-passive interaction
        (excludes impression, viewable_impression, ad_exposure, email_delivery, push_presentation).
        """
        _passive = {"impression", "viewable_impression", "ad_exposure", "email_delivery", "push_presentation"}

        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("campaign_id") == campaign_id
                and r.get("privacy_class") != "deleted"
                and (after_occurred is None or r.get("occurred_at", "") > after_occurred.isoformat())
                and (before_occurred is None or r.get("occurred_at", "") < before_occurred.isoformat())
            ]
            observed_ids: set[str] = set()
            resolved_ids: set[str] = set()
            engaged_ids: set[str] = set()
            for r in rows:
                anon = r.get("anonymous_id")
                pid = r.get("profile_id")
                cid = r.get("cluster_id")
                canonical = pid or cid or anon
                if canonical:
                    observed_ids.add(canonical)
                if pid or cid:
                    resolved_ids.add(pid or cid)
                if (pid or cid) and r.get("touchpoint_type") not in _passive:
                    engaged_ids.add(pid or cid)
            return {
                "observed": len(observed_ids),
                "resolved": len(resolved_ids),
                "engaged": len(engaged_ids),
            }

        conditions = ["tenant_id = $1", "campaign_id = $2", "privacy_class != 'deleted'"]
        params: list[Any] = [tenant_id, campaign_id]
        p = 3
        if after_occurred:
            conditions.append(f"occurred_at > ${p}")
            params.append(after_occurred)
            p += 1
        if before_occurred:
            conditions.append(f"occurred_at < ${p}")
            params.append(before_occurred)
            p += 1

        sql = f"""
            SELECT
              COUNT(DISTINCT COALESCE(profile_id, cluster_id, anonymous_id)) AS observed,
              COUNT(DISTINCT CASE WHEN profile_id IS NOT NULL OR cluster_id IS NOT NULL
                THEN COALESCE(profile_id, cluster_id) END) AS resolved,
              COUNT(DISTINCT CASE
                WHEN (profile_id IS NOT NULL OR cluster_id IS NOT NULL)
                  AND touchpoint_type NOT IN (
                    'impression','viewable_impression','ad_exposure',
                    'email_delivery','push_presentation'
                  )
                THEN COALESCE(profile_id, cluster_id) END) AS engaged
            FROM silver_campaign_touchpoint_facts
            WHERE {' AND '.join(conditions)}
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return {
                "observed": row["observed"] or 0,
                "resolved": row["resolved"] or 0,
                "engaged": row["engaged"] or 0,
            }

    async def get(self, tenant_id: str, touchpoint_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return next(
                (r for r in _local_store.values()
                 if r.get("tenant_id") == tenant_id and r.get("touchpoint_id") == touchpoint_id),
                None,
            )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM silver_campaign_touchpoint_facts WHERE tenant_id=$1 AND touchpoint_id=$2",
                tenant_id, touchpoint_id,
            )
            return dict(row) if row else None

    async def tombstone_for_profile(self, tenant_id: str, profile_id: str) -> int:
        """Privacy erasure: mark all touchpoints for a profile as deleted.

        Sets privacy_class='deleted' and nulls identity fields. The row is
        retained for aggregate counts but excluded from attribution and journey
        compilation. Returns the count of affected rows.
        """
        pool = await self._pool()
        if pool is None:
            count = 0
            for row in _local_store.values():
                if row.get("tenant_id") == tenant_id and (
                    row.get("profile_id") == profile_id or row.get("anonymous_id") == profile_id
                ):
                    row["privacy_class"] = "deleted"
                    row["profile_id"] = None
                    row["anonymous_id"] = None
                    row["cluster_id"] = None
                    row["account_id"] = None
                    row["wallet_id"] = None
                    row["agent_id"] = None
                    count += 1
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE silver_campaign_touchpoint_facts
                SET privacy_class = 'deleted',
                    profile_id    = NULL,
                    anonymous_id  = NULL,
                    cluster_id    = NULL,
                    account_id    = NULL,
                    wallet_id     = NULL,
                    agent_id      = NULL
                WHERE tenant_id = $1
                  AND (profile_id = $2 OR anonymous_id = $2)
                  AND privacy_class != 'deleted'
                """,
                tenant_id, profile_id,
            )
        try:
            return int(result.split()[-1])
        except Exception:
            return 0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _derive_key(row: dict[str, Any]) -> str:
    src = f"{row.get('tenant_id')}:{row.get('source_event_id')}:{row.get('touchpoint_type')}"
    return hashlib.sha256(src.encode()).hexdigest()


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


def _classify_touchpoint(event_type: str) -> str:
    mapping = {
        "click": "click",
        "ad_click": "click",
        "ad_exposed": "ad_exposure",
        "impression": "impression",
        "pageview": "page_view",
        "page_view": "page_view",
        "page": "page_view",
        "screen": "page_view",
        "session_start": "session_entry",
        "session_started": "session_entry",
        "product_viewed": "product_view",
        "landing": "landing",
        "email_delivered": "email_delivery",
        "email_opened": "email_open",
        "email_clicked": "email_click",
        "notification_presented": "push_presentation",
        "notification_clicked": "push_click",
    }
    return mapping.get(event_type, "page_view")
