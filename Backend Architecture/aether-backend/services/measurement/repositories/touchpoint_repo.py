"""Touchpoint repository — durable access to silver_campaign_touchpoint_facts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool
from services.traffic.generated_registry import canonical_source_class

logger = get_logger("aether.measurement.touchpoint_repo")

_IS_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"

# In-memory fallback (local/test only)
_local_store: dict[str, dict[str, Any]] = {}
_local_revisions: list[dict[str, Any]] = []


_TOUCHPOINT_COLUMNS: tuple[str, ...] = (
    "touchpoint_id", "tenant_id", "profile_id", "cluster_id", "anonymous_id",
    "session_id", "device_id", "account_id", "organization_id", "wallet_id",
    "agent_id", "campaign_id", "ad_group_id", "ad_set_id", "creative_id",
    "ad_id", "placement_id", "keyword_id", "audience_id", "offer_id",
    "landing_page_id", "channel", "source", "medium", "platform",
    "source_class", "traffic_origin", "economic_class", "channel_family",
    "entry_method", "proof_level", "evidence_conflicts",
    "referral_mediation_type", "ai_provider", "ai_product",
    "actor_type", "journey_role", "evidence_confidence", "verification_level",
    "source_classifier_version", "source_classified_at",
    "normalized_referrer_domain", "referrer_path_hash",
    "source_classification_evidence", "source_classification_id",
    "attribution_eligible", "verified_referral_link_id", "touchpoint_type",
    "interaction_type", "is_view_through", "is_click_through", "viewable",
    "engaged", "dwell_ms", "position", "frequency", "occurred_at",
    "received_at", "processed_at", "source_event_id", "connector_record_id",
    "source_connector_id", "utm_source", "utm_medium", "utm_campaign",
    "utm_content", "utm_term", "click_id", "referrer", "landing_url",
    "external_campaign_id", "external_account_id", "campaign_resolution_status",
    "campaign_resolution_method", "campaign_resolution_confidence",
    "campaign_resolution_version", "communication_fact_id", "external_message_id",
    "sequence_step", "variant_id", "link_id", "engagement_confidence",
    "machine_activity_probability", "identity_resolution_method",
    "identity_confidence", "identity_version", "consent_snapshot_id",
    "privacy_class", "provenance", "evidence_ids", "idempotency_key",
    "schema_version", "properties", "revenue_usd", "is_conversion",
)

_JSON_COLUMNS = frozenset({
    "source_classification_evidence", "provenance", "evidence_ids",
    "evidence_conflicts", "properties",
})
_JSON_LIST_COLUMNS = frozenset({"evidence_ids", "evidence_conflicts"})
_UUID_COLUMNS = frozenset({
    "touchpoint_id", "source_classification_id", "verified_referral_link_id",
})
_TIMESTAMP_COLUMNS = frozenset({
    "occurred_at", "received_at", "processed_at", "source_classified_at",
})
# NUMERIC(18,6) money columns — never bound as a Python/SQL float. Mirrors
# the representation used for every other money column in this migration
# family (canonical_conversions.gross_value, revenue_adjustments.amount;
# see services/measurement/repositories/conversion_repo.py::_to_decimal).
_MONEY_COLUMNS = frozenset({"revenue_usd"})

_CLASSIFICATION_FIELDS: tuple[str, ...] = (
    "channel", "source", "medium", "source_class", "traffic_origin",
    "economic_class", "channel_family", "entry_method", "proof_level",
    "evidence_conflicts", "referral_mediation_type",
    "ai_provider", "ai_product", "actor_type", "journey_role",
    "evidence_confidence", "verification_level", "source_classifier_version",
    "source_classified_at", "normalized_referrer_domain", "referrer_path_hash",
    "source_classification_evidence", "source_classification_id",
    "attribution_eligible", "verified_referral_link_id", "referrer",
)


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
        row.setdefault("privacy_class", "behavioral")
        row.setdefault("touchpoint_type", "page_view")
        row.setdefault("is_view_through", False)
        row.setdefault("is_click_through", False)
        row.setdefault("schema_version", 1)
        row.setdefault("properties", {})
        row.setdefault("is_conversion", False)
        # Normalize here — before the local/asyncpg branch split — so both
        # backends persist and return the same Decimal type. Local mode never
        # runs values through _db_value(), so coercing only there would leave
        # revenue_usd as a raw float/str in the in-memory store.
        row["revenue_usd"] = _to_decimal(row.get("revenue_usd"))
        if row.get("source_classifier_version"):
            row.setdefault("source_classification_id", str(uuid4()))
            row.setdefault("source_classified_at", row.get("received_at"))
            row.setdefault("attribution_eligible", True)

        pool = await self._pool()
        if pool is None:
            # Match PostgreSQL's (tenant_id, idempotency_key) uniqueness.
            # A bare idempotency key is not globally unique and must never
            # allow one tenant's replay to return another tenant's row.
            local_key = f"{row.get('tenant_id')}:{key}"
            existing = _local_store.get(local_key)
            if existing is not None:
                return existing
            _local_store[local_key] = dict(row)
            if row.get("source_classifier_version"):
                _local_revisions.append(_classification_revision(row, reason="ingestion"))
            return row

        placeholders = ", ".join(f"${idx}" for idx in range(1, len(_TOUCHPOINT_COLUMNS) + 1))
        sql = f"""
            INSERT INTO silver_campaign_touchpoint_facts ({', '.join(_TOUCHPOINT_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            RETURNING touchpoint_id
        """
        # The active classification and revision rows form a tenant-safe audit
        # relationship. Insert the touchpoint first with a null active pointer,
        # then append the revision and set the pointer in the same transaction;
        # both foreign keys are immediate rather than deferrable.
        values = [
            None if column == "source_classification_id"
            else _db_value(column, row.get(column))
            for column in _TOUCHPOINT_COLUMNS
        ]
        async with pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchval(sql, *values)
                if inserted and row.get("source_classifier_version"):
                    revision = _classification_revision(row, reason="ingestion")
                    await _insert_revision(conn, revision)
                    await conn.execute(
                        """
                        UPDATE silver_campaign_touchpoint_facts
                        SET source_classification_id=$3
                        WHERE tenant_id=$1 AND touchpoint_id=$2
                        """,
                        row.get("tenant_id"), _uuid_or_none(row.get("touchpoint_id")),
                        _uuid_or_none(row.get("source_classification_id")),
                    )
                persisted = await conn.fetchrow(
                    """
                    SELECT * FROM silver_campaign_touchpoint_facts
                    WHERE tenant_id=$1 AND idempotency_key=$2
                    """,
                    row.get("tenant_id"),
                    key,
                )
        return dict(persisted) if persisted else row

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
            "properties": data.get("properties") or {},
            "revenue_usd": data.get("revenue_usd"),
            "is_conversion": bool(data.get("is_conversion", False)),
        }
        return await self.upsert(row)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_by_profile(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        identity_type: Optional[str] = None,
        after_occurred: Optional[datetime] = None,
        before_occurred: Optional[datetime] = None,
        campaign_ids: Optional[list[str]] = None,
        limit: int = 500,
        cursor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return touchpoints for a profile or explicitly typed identity."""
        identity_columns = {
            "profile": "profile_id",
            "cluster": "cluster_id",
            "anonymous": "anonymous_id",
        }
        identity_column = identity_columns.get(identity_type or "")
        if identity_type is not None and identity_column is None:
            raise ValueError(f"unsupported identity_type: {identity_type}")
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
                        or r.get("anonymous_id") == profile_id
                    )
                )
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows[:limit]

        identity_condition = (
            f"{identity_column} = $2"
            if identity_column
            else "(profile_id = $2 OR anonymous_id = $2)"
        )
        conditions = ["tenant_id = $1", identity_condition]
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
                tenant_id, _uuid_or_none(touchpoint_id),
            )
            return dict(row) if row else None

    async def list_for_source_reclassification(
        self,
        tenant_id: str,
        *,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        limit: int = 500,
        cursor_occurred_at: Optional[datetime] = None,
        cursor_touchpoint_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Page historical touchpoints in a stable, restart-safe order."""
        safe_limit = max(1, min(int(limit), 5000))
        pool = await self._pool()
        if pool is None:
            rows = [
                dict(row) for row in _local_store.values()
                if row.get("tenant_id") == tenant_id
                and row.get("privacy_class") != "deleted"
            ]
            if start_at:
                rows = [r for r in rows if (_parse_ts(r.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= start_at]
            if end_at:
                rows = [r for r in rows if (_parse_ts(r.get("occurred_at")) or datetime.max.replace(tzinfo=timezone.utc)) < end_at]
            rows.sort(key=lambda r: (_parse_ts(r.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc), str(r.get("touchpoint_id", ""))))
            if cursor_occurred_at:
                cursor_key = (cursor_occurred_at, cursor_touchpoint_id or "")
                rows = [
                    r for r in rows
                    if ((_parse_ts(r.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc)), str(r.get("touchpoint_id", ""))) > cursor_key
                ]
            return rows[:safe_limit]

        conditions = ["tenant_id = $1", "privacy_class != 'deleted'"]
        params: list[Any] = [tenant_id]
        index = 2
        if start_at:
            conditions.append(f"occurred_at >= ${index}")
            params.append(start_at)
            index += 1
        if end_at:
            conditions.append(f"occurred_at < ${index}")
            params.append(end_at)
            index += 1
        if cursor_occurred_at:
            conditions.append(
                f"(occurred_at, touchpoint_id) > (${index}, ${index + 1}::uuid)"
            )
            params.extend(
                [
                    cursor_occurred_at,
                    _uuid_or_none(cursor_touchpoint_id)
                    or UUID("00000000-0000-0000-0000-000000000000"),
                ]
            )
            index += 2
        params.append(safe_limit)
        sql = f"""
            SELECT *
            FROM silver_campaign_touchpoint_facts
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC, touchpoint_id ASC
            LIMIT ${index}
        """
        async with pool.acquire() as conn:
            return [dict(row) for row in await conn.fetch(sql, *params)]

    async def apply_source_classification(
        self,
        tenant_id: str,
        touchpoint_id: str,
        classification: dict[str, Any],
        *,
        input_hash: str,
        reason: str,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append an immutable classification revision and update current projections.

        The touchpoint and canonical activity updates share the same transaction as
        the revision insert. Replaying the same classifier version + input hash is
        therefore idempotent and never destroys the prior audit trail.
        """
        now = datetime.now(timezone.utc)
        classification_id = str(uuid4())
        values = dict(classification)
        values["source_classification_id"] = classification_id
        values.setdefault("source_classified_at", now)
        values.setdefault("attribution_eligible", True)
        values.setdefault("source_classification_evidence", {})

        pool = await self._pool()
        if pool is None:
            row = next(
                (
                    item for item in _local_store.values()
                    if item.get("tenant_id") == tenant_id
                    and str(item.get("touchpoint_id")) == str(touchpoint_id)
                ),
                None,
            )
            if row is None:
                raise KeyError(f"touchpoint not found: {touchpoint_id}")
            duplicate = next(
                (
                    rev for rev in _local_revisions
                    if rev["tenant_id"] == tenant_id
                    and str(rev["touchpoint_id"]) == str(touchpoint_id)
                    and rev["classifier_version"] == values.get("source_classifier_version")
                    and rev["input_hash"] == input_hash
                ),
                None,
            )
            if duplicate:
                return dict(row)
            prior = _classification_snapshot(row)
            previous = next(
                (
                    rev for rev in reversed(_local_revisions)
                    if rev["tenant_id"] == tenant_id
                    and str(rev["touchpoint_id"]) == str(touchpoint_id)
                    and rev.get("is_current")
                ),
                None,
            )
            revision = _classification_revision(
                {**row, **values}, reason=reason, input_hash=input_hash,
                job_id=job_id, prior_classification=prior,
                previous_classification_id=(previous or {}).get("classification_id"),
            )
            if previous:
                previous["is_current"] = False
                previous["superseded_by"] = classification_id
            _local_revisions.append(revision)
            row.update({field: values.get(field) for field in _CLASSIFICATION_FIELDS})
            from services.measurement.repositories.activity_repo import ActivityRepository
            await ActivityRepository().apply_source_classification(
                tenant_id,
                touchpoint_id=str(touchpoint_id),
                source_event_id=row.get("source_event_id"),
                classification=values,
            )
            return dict(row)

        touchpoint_uuid = _uuid_or_none(touchpoint_id)
        if touchpoint_uuid is None:
            raise ValueError("touchpoint_id must be a UUID")
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT * FROM silver_campaign_touchpoint_facts
                    WHERE tenant_id=$1 AND touchpoint_id=$2
                    FOR UPDATE
                    """,
                    tenant_id, touchpoint_uuid,
                )
                if row is None:
                    raise KeyError(f"touchpoint not found: {touchpoint_id}")
                duplicate = await conn.fetchval(
                    """
                    SELECT classification_id
                    FROM touchpoint_source_classification_revisions
                    WHERE tenant_id=$1 AND touchpoint_id=$2
                      AND classifier_version=$3 AND input_hash=$4
                    """,
                    tenant_id, touchpoint_uuid,
                    values.get("source_classifier_version"), input_hash,
                )
                if duplicate:
                    return dict(row)

                current = await conn.fetchrow(
                    """
                    SELECT classification_id
                    FROM touchpoint_source_classification_revisions
                    WHERE tenant_id=$1 AND touchpoint_id=$2 AND is_current=TRUE
                    FOR UPDATE
                    """,
                    tenant_id, touchpoint_uuid,
                )
                prior = _classification_snapshot(dict(row))
                revision = _classification_revision(
                    {**dict(row), **values}, reason=reason, input_hash=input_hash,
                    job_id=job_id, prior_classification=prior,
                    previous_classification_id=(str(current["classification_id"]) if current else None),
                )
                if current:
                    # Avoid both the partial-current uniqueness conflict and
                    # the immediate superseded_by FK: insert the successor as
                    # non-current, link the predecessor, then flip it current.
                    revision["is_current"] = False
                    await _insert_revision(conn, revision)
                    await conn.execute(
                        """
                        UPDATE touchpoint_source_classification_revisions
                        SET is_current=FALSE, superseded_by=$3
                        WHERE tenant_id=$1 AND classification_id=$2
                        """,
                        tenant_id, current["classification_id"], _uuid_or_none(classification_id),
                    )
                    await conn.execute(
                        """
                        UPDATE touchpoint_source_classification_revisions
                        SET is_current=TRUE
                        WHERE tenant_id=$1 AND classification_id=$2
                        """,
                        tenant_id, _uuid_or_none(classification_id),
                    )
                else:
                    await _insert_revision(conn, revision)

                assignments = ", ".join(
                    f"{field}=${idx}" for idx, field in enumerate(_CLASSIFICATION_FIELDS, start=3)
                )
                update_params = [
                    _db_value(field, values.get(field)) for field in _CLASSIFICATION_FIELDS
                ]
                await conn.execute(
                    f"""
                    UPDATE silver_campaign_touchpoint_facts
                    SET {assignments}
                    WHERE tenant_id=$1 AND touchpoint_id=$2
                    """,
                    tenant_id, touchpoint_uuid, *update_params,
                )

                # Keep the existing canonical activity projection in sync; this
                # is a repair, not a second parallel activity pipeline.
                activity_fields = tuple(
                    field for field in _CLASSIFICATION_FIELDS
                    if field not in {
                        "referrer", "referrer_path_hash",
                        "source_classification_evidence", "source_classified_at",
                    }
                )
                activity_assignments = ", ".join(
                    f"{field}=${idx}" for idx, field in enumerate(activity_fields, start=3)
                )
                activity_params = [
                    _db_value(field, values.get(field)) for field in activity_fields
                ]
                domain_param = len(activity_fields) + 3
                source_event_param = len(activity_fields) + 4
                await conn.execute(
                    f"""
                    UPDATE canonical_activity
                    SET {activity_assignments},
                        domain=${domain_param},
                        silver_fact_id=$2,
                        silver_table='silver_campaign_touchpoint_facts'
                    WHERE tenant_id=$1
                      AND (
                        silver_fact_id=$2
                        OR (
                          silver_table='silver_campaign_touchpoint_facts'
                          AND source_event_id=${source_event_param}
                        )
                      )
                    """,
                    tenant_id, touchpoint_uuid, *activity_params,
                    values.get("normalized_referrer_domain"),
                    row.get("source_event_id"),
                )
                refreshed = await conn.fetchrow(
                    "SELECT * FROM silver_campaign_touchpoint_facts WHERE tenant_id=$1 AND touchpoint_id=$2",
                    tenant_id, touchpoint_uuid,
                )
                return dict(refreshed)

    async def classification_history(
        self, tenant_id: str, touchpoint_id: str
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                dict(rev) for rev in _local_revisions
                if rev.get("tenant_id") == tenant_id
                and str(rev.get("touchpoint_id")) == str(touchpoint_id)
            ]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM touchpoint_source_classification_revisions
                WHERE tenant_id=$1 AND touchpoint_id=$2
                ORDER BY classified_at ASC, classification_id ASC
                """,
                tenant_id, _uuid_or_none(touchpoint_id),
            )
            return [dict(row) for row in rows]

    async def source_classification_health(self, tenant_id: str) -> dict[str, Any]:
        """Return bounded operational counts for the existing Kyber surface."""
        pool = await self._pool()
        if pool is None:
            rows = [
                row for row in _local_store.values()
                if row.get("tenant_id") == tenant_id and row.get("privacy_class") != "deleted"
            ]
            return _health_summary(rows)
        async with pool.acquire() as conn:
            summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::bigint AS total,
                    COUNT(*) FILTER (WHERE source_classifier_version IS NOT NULL)::bigint AS classified,
                    COUNT(*) FILTER (WHERE source_classifier_version IS NULL)::bigint AS unclassified,
                    COUNT(*) FILTER (WHERE attribution_eligible=FALSE)::bigint AS excluded,
                    COUNT(*) FILTER (
                        WHERE verification_level = 'verified'
                           OR verification_level LIKE 'verified%'
                    )::bigint AS verified
                FROM silver_campaign_touchpoint_facts
                WHERE tenant_id=$1 AND privacy_class != 'deleted'
                """,
                tenant_id,
            )
            versions = await conn.fetch(
                """
                SELECT COALESCE(source_classifier_version, 'unclassified') AS name, COUNT(*)::bigint AS count
                FROM silver_campaign_touchpoint_facts
                WHERE tenant_id=$1 AND privacy_class != 'deleted'
                GROUP BY 1 ORDER BY count DESC, name ASC
                """,
                tenant_id,
            )
            providers = await conn.fetch(
                """
                SELECT ai_provider AS name, COUNT(*)::bigint AS count
                FROM silver_campaign_touchpoint_facts
                WHERE tenant_id=$1 AND privacy_class != 'deleted' AND ai_provider IS NOT NULL
                GROUP BY 1 ORDER BY count DESC, name ASC LIMIT 50
                """,
                tenant_id,
            )
            mediation = await conn.fetch(
                """
                SELECT referral_mediation_type AS name, COUNT(*)::bigint AS count
                FROM silver_campaign_touchpoint_facts
                WHERE tenant_id=$1 AND privacy_class != 'deleted' AND referral_mediation_type IS NOT NULL
                GROUP BY 1 ORDER BY count DESC, name ASC LIMIT 50
                """,
                tenant_id,
            )
            dimension_rows: dict[str, list[dict[str, Any]]] = {}
            for key, column in (
                ("source_classes", "source_class"),
                ("economic_classes", "economic_class"),
                ("channel_families", "channel_family"),
                ("proof_levels", "proof_level"),
            ):
                fetched = await conn.fetch(
                    f"""
                    SELECT {column} AS name, COUNT(*)::bigint AS count
                    FROM silver_campaign_touchpoint_facts
                    WHERE tenant_id=$1 AND privacy_class != 'deleted' AND {column} IS NOT NULL
                    GROUP BY 1 ORDER BY count DESC, name ASC LIMIT 50
                    """,
                    tenant_id,
                )
                dimension_rows[key] = _merge_canonical_counts(
                    [dict(row) for row in fetched],
                    normalize=(column == "source_class"),
                )
            return {
                "summary": dict(summary),
                "versions": [dict(row) for row in versions],
                "providers": [dict(row) for row in providers],
                "mediation": [dict(row) for row in mediation],
                **dimension_rows,
            }

    async def source_classification_operations(
        self,
        tenant_id: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        platform: Optional[str] = None,
        sdk: Optional[str] = None,
    ) -> dict[str, Any]:
        """Operator source-classification operations aggregation (spec §15.3).

        Reads the durable, tenant-scoped silver + adjacent tables
        (silver_campaign_touchpoint_facts, deferred_attribution_handoffs,
        apple_attribution_postbacks, jobs) plus the shadow divergence table and
        returns the numeric body of the Kyber ``/operations`` contract. An
        unknown / empty tenant yields a well-formed zeroed structure — never an
        error. ``sdk`` filters entry_method by native family prefix
        ('ios' -> ios_*, 'android' -> android_*).
        """
        pool = await self._pool()
        if pool is None:
            return await self._operations_from_local(
                tenant_id, start=start, end=end, platform=platform, sdk=sdk
            )
        return await self._operations_from_pool(
            pool, tenant_id, start=start, end=end, platform=platform, sdk=sdk
        )

    async def _operations_from_pool(
        self, pool, tenant_id, *, start, end, platform, sdk
    ) -> dict[str, Any]:
        conds = ["tenant_id = $1", "privacy_class != 'deleted'"]
        args: list[Any] = [tenant_id]
        if start is not None:
            args.append(start)
            conds.append(f"occurred_at >= ${len(args)}")
        if end is not None:
            args.append(end)
            conds.append(f"occurred_at <= ${len(args)}")
        if platform:
            args.append(platform)
            conds.append(f"platform = ${len(args)}")
        sdk_prefix = _sdk_entry_prefix(sdk)
        if sdk_prefix:
            args.append(f"{sdk_prefix}%")
            conds.append(f"entry_method LIKE ${len(args)}")
        where = " AND ".join(conds)
        async with pool.acquire() as conn:
            summary = await conn.fetchrow(
                f"""
                SELECT
                  COUNT(*)::bigint AS touchpoints,
                  COUNT(*) FILTER (WHERE attribution_eligible)::bigint AS attribution_eligible,
                  COUNT(*) FILTER (WHERE attribution_eligible = FALSE
                        AND actor_type = 'machine')::bigint AS machine_excluded,
                  COUNT(*) FILTER (WHERE source_class = 'direct_unknown')::bigint AS direct_unknown,
                  COUNT(*) FILTER (WHERE evidence_conflicts IS NOT NULL
                        AND jsonb_typeof(evidence_conflicts) = 'array'
                        AND jsonb_array_length(evidence_conflicts) > 0)::bigint AS evidence_conflicts,
                  COUNT(*) FILTER (WHERE entry_method = 'ios_universal_link')::bigint AS universal_link,
                  COUNT(*) FILTER (WHERE entry_method = 'android_install_referrer')::bigint AS install_referrer,
                  COUNT(*) FILTER (WHERE verified_referral_link_id IS NOT NULL)::bigint AS handoff_success
                FROM silver_campaign_touchpoint_facts WHERE {where}
                """,
                *args,
            )
            by_class = await conn.fetch(
                f"""SELECT source_class AS name, COUNT(*)::bigint AS count
                    FROM silver_campaign_touchpoint_facts WHERE {where}
                    AND source_class IS NOT NULL GROUP BY 1""",
                *args,
            )
            by_proof = await conn.fetch(
                f"""SELECT proof_level AS name, COUNT(*)::bigint AS count
                    FROM silver_campaign_touchpoint_facts WHERE {where}
                    AND proof_level IS NOT NULL GROUP BY 1""",
                *args,
            )
            deferred = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) FILTER (WHERE consumed_at IS NOT NULL)::bigint AS resolved,
                  COUNT(*) FILTER (WHERE consumed_at IS NULL AND expires_at < now())::bigint AS expired,
                  COUNT(*) FILTER (WHERE consumed_at IS NULL AND expires_at >= now())::bigint AS unmatched
                FROM deferred_attribution_handoffs WHERE tenant_id = $1
                """,
                tenant_id,
            )
            apple = await conn.fetchrow(
                "SELECT COUNT(*)::bigint AS c FROM apple_attribution_postbacks WHERE tenant_id = $1",
                tenant_id,
            )
            jobs = await conn.fetch(
                "SELECT status, COUNT(*)::bigint AS count FROM jobs "
                "WHERE tenant_id = $1 AND job_type = $2 GROUP BY status",
                tenant_id, _RECLASSIFICATION_JOB_TYPE,
            )
        class_counts = {str(r["name"]): int(r["count"]) for r in by_class}
        proof_counts = {str(r["name"]): int(r["count"]) for r in by_proof}
        job_status = {str(r["status"]): int(r["count"]) for r in jobs}
        drift = await _shadow_divergence_rate(tenant_id)
        return _assemble_operations(
            touchpoints=int(summary["touchpoints"] or 0),
            attribution_eligible=int(summary["attribution_eligible"] or 0),
            machine_excluded=int(summary["machine_excluded"] or 0),
            direct_unknown=int(summary["direct_unknown"] or 0),
            evidence_conflict=int(summary["evidence_conflicts"] or 0),
            universal_link=int(summary["universal_link"] or 0),
            install_referrer=int(summary["install_referrer"] or 0),
            handoff_success=int(summary["handoff_success"] or 0),
            class_counts=class_counts,
            proof_counts=proof_counts,
            deferred={
                "resolved": int(deferred["resolved"] or 0),
                "unmatched": int(deferred["unmatched"] or 0),
                "expired": int(deferred["expired"] or 0),
            },
            adattributionkit=int(apple["c"] or 0),
            job_status=job_status,
            drift_rate=drift,
        )

    async def _operations_from_local(
        self, tenant_id, *, start, end, platform, sdk
    ) -> dict[str, Any]:
        sdk_prefix = _sdk_entry_prefix(sdk)
        rows = []
        for r in _local_store.values():
            if r.get("tenant_id") != tenant_id or r.get("privacy_class") == "deleted":
                continue
            occurred = _iso(r.get("occurred_at"))
            if start is not None and (occurred is None or occurred < start.isoformat()):
                continue
            if end is not None and (occurred is None or occurred > end.isoformat()):
                continue
            if platform and r.get("platform") != platform:
                continue
            if sdk_prefix and not str(r.get("entry_method") or "").startswith(sdk_prefix):
                continue
            rows.append(r)
        touchpoints = len(rows)
        class_counts: dict[str, int] = {}
        proof_counts: dict[str, int] = {}
        attribution_eligible = machine_excluded = direct_unknown = 0
        evidence_conflict = universal_link = install_referrer = handoff_success = 0
        for r in rows:
            sc = r.get("source_class")
            if sc:
                class_counts[str(sc)] = class_counts.get(str(sc), 0) + 1
            pl = r.get("proof_level")
            if pl:
                proof_counts[str(pl)] = proof_counts.get(str(pl), 0) + 1
            if r.get("attribution_eligible") is not False:
                attribution_eligible += 1
            elif r.get("actor_type") == "machine":
                machine_excluded += 1
            if sc == "direct_unknown":
                direct_unknown += 1
            conflicts = r.get("evidence_conflicts") or []
            if isinstance(conflicts, (list, tuple)) and len(conflicts) > 0:
                evidence_conflict += 1
            if r.get("entry_method") == "ios_universal_link":
                universal_link += 1
            if r.get("entry_method") == "android_install_referrer":
                install_referrer += 1
            if r.get("verified_referral_link_id"):
                handoff_success += 1
        drift = await _shadow_divergence_rate(tenant_id)
        return _assemble_operations(
            touchpoints=touchpoints,
            attribution_eligible=attribution_eligible,
            machine_excluded=machine_excluded,
            direct_unknown=direct_unknown,
            evidence_conflict=evidence_conflict,
            universal_link=universal_link,
            install_referrer=install_referrer,
            handoff_success=handoff_success,
            class_counts=class_counts,
            proof_counts=proof_counts,
            deferred={"resolved": 0, "unmatched": 0, "expired": 0},
            adattributionkit=0,
            job_status={},
            drift_rate=drift,
        )

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

def _merge_canonical_counts(
    rows: list[dict[str, Any]], *, normalize: bool
) -> list[dict[str, Any]]:
    """Optionally normalize legacy names, merging counts (read path only)."""
    merged: dict[str, int] = {}
    for row in rows:
        name = str(row.get("name") or "")
        if normalize:
            name = canonical_source_class(name)
        merged[name] = merged.get(name, 0) + int(row.get("count") or 0)
    return [
        {"name": name, "count": count}
        for name, count in sorted(merged.items(), key=lambda item: (-item[1], item[0]))
    ]


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


def _uuid_or_none(value: Any) -> Optional[UUID]:
    if value in (None, ""):
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _db_value(column: str, value: Any) -> Any:
    if column in _JSON_COLUMNS:
        default: Any = [] if column in _JSON_LIST_COLUMNS else {}
        return json.dumps(default if value is None else value, default=str)
    if column in _UUID_COLUMNS:
        return _uuid_or_none(value)
    if column in _TIMESTAMP_COLUMNS:
        return _parse_ts(value)
    if column in _MONEY_COLUMNS:
        return _to_decimal(value)
    return value


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Coerce to Decimal via str() — never via float() — to avoid binary
    floating-point artifacts (e.g. Decimal(0.1) != Decimal('0.1')). Mirrors
    services/measurement/repositories/conversion_repo.py::_to_decimal, the
    canonical pattern for every other money column in this table family.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _classification_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = {field: row.get(field) for field in _CLASSIFICATION_FIELDS}
    raw_referrer = snapshot.get("referrer")
    if raw_referrer:
        # Revision history is immutable, so legacy raw referrers must be
        # normalized before they enter it. Never preserve path/query values in
        # ``prior_classification`` merely because the source row predates the
        # privacy-safe classifier.
        from services.traffic.classifier import SourceClassifier

        domain, safe_referrer, path_hash = SourceClassifier.normalize_referrer(
            referrer=str(raw_referrer),
            referrer_domain=str(snapshot.get("normalized_referrer_domain") or ""),
        )
        snapshot["referrer"] = safe_referrer or None
        snapshot["normalized_referrer_domain"] = domain or None
        snapshot["referrer_path_hash"] = (
            snapshot.get("referrer_path_hash") or path_hash
        )
    return snapshot


def _classification_revision(
    row: dict[str, Any],
    *,
    reason: str,
    input_hash: Optional[str] = None,
    job_id: Optional[str] = None,
    prior_classification: Optional[dict[str, Any]] = None,
    previous_classification_id: Optional[str] = None,
) -> dict[str, Any]:
    classification = _classification_snapshot(row)
    evidence = row.get("source_classification_evidence") or {}
    stable_input_hash = input_hash or hashlib.sha256(
        json.dumps(evidence, sort_keys=True, default=str).encode()
    ).hexdigest()
    return {
        "classification_id": str(row.get("source_classification_id") or uuid4()),
        "tenant_id": row.get("tenant_id"),
        "touchpoint_id": str(row.get("touchpoint_id")),
        "classifier_version": row.get("source_classifier_version") or "unknown",
        "input_hash": stable_input_hash,
        "prior_classification": prior_classification or {},
        "classification": classification,
        "evidence": evidence,
        "confidence": row.get("evidence_confidence"),
        "verification_level": row.get("verification_level"),
        "reason": reason,
        "job_id": job_id,
        "previous_classification_id": previous_classification_id,
        "superseded_by": None,
        "is_current": True,
        "classified_at": _parse_ts(row.get("source_classified_at")) or datetime.now(timezone.utc),
    }


async def _insert_revision(conn: Any, revision: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO touchpoint_source_classification_revisions (
            classification_id, tenant_id, touchpoint_id, classifier_version,
            input_hash, prior_classification, classification, evidence,
            confidence, verification_level, reason, job_id,
            previous_classification_id, superseded_by, is_current, classified_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb,
            $9, $10, $11, $12, $13, $14, $15, $16
        )
        ON CONFLICT (tenant_id, touchpoint_id, classifier_version, input_hash)
        DO NOTHING
        """,
        _uuid_or_none(revision.get("classification_id")),
        revision.get("tenant_id"),
        _uuid_or_none(revision.get("touchpoint_id")),
        revision.get("classifier_version"),
        revision.get("input_hash"),
        json.dumps(revision.get("prior_classification"), default=str),
        json.dumps(revision.get("classification") or {}, default=str),
        json.dumps(revision.get("evidence") or {}, default=str),
        revision.get("confidence"), revision.get("verification_level"),
        revision.get("reason"), revision.get("job_id"),
        _uuid_or_none(revision.get("previous_classification_id")),
        _uuid_or_none(revision.get("superseded_by")),
        bool(revision.get("is_current", True)),
        _parse_ts(revision.get("classified_at")),
    )


_RECLASSIFICATION_JOB_TYPE = "measurement.source_classification_repair"


def _sdk_entry_prefix(sdk: Optional[str]) -> str:
    """Map an sdk filter to the entry_method family prefix it constrains."""
    if not sdk:
        return ""
    token = sdk.strip().lower()
    if token in ("ios", "apple"):
        return "ios"
    if token == "android":
        return "android"
    return ""


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def _shadow_divergence_rate(tenant_id: str) -> float:
    """Legacy-vs-canonical divergence rate for the classification_drift field."""
    try:
        from services.traffic.shadow import ShadowDivergenceRepository

        result = await ShadowDivergenceRepository().divergence_rate(tenant_id)
        return float(result.get("rate") or 0.0)
    except Exception:  # pragma: no cover — drift is advisory, never blocks the route
        return 0.0


def _assemble_operations(
    *,
    touchpoints: int,
    attribution_eligible: int,
    machine_excluded: int,
    direct_unknown: int,
    evidence_conflict: int,
    universal_link: int,
    install_referrer: int,
    handoff_success: int,
    class_counts: dict[str, int],
    proof_counts: dict[str, int],
    deferred: dict[str, int],
    adattributionkit: int,
    job_status: dict[str, int],
    drift_rate: float,
) -> dict[str, Any]:
    """Assemble the numeric body of the Kyber /operations contract.

    Fields without a durable, tenant-scoped source (invalid_source_link,
    source_link_replay, install-referrer error states, sdk parse failures,
    handoff expired/failed) are returned as honest zeros rather than leaking
    process-global metric counters that cannot be tenant-scoped.
    """
    direct_unknown_rate = (direct_unknown / touchpoints) if touchpoints else 0.0
    utm_inconsistency_rate = (evidence_conflict / touchpoints) if touchpoints else 0.0
    completed = job_status.get("succeeded", 0) + job_status.get("partially_succeeded", 0)
    return {
        "totals": {
            "touchpoints": touchpoints,
            "attribution_eligible": attribution_eligible,
            "machine_excluded": machine_excluded,
        },
        "classification_by_source_class": class_counts,
        "classification_by_proof_level": proof_counts,
        "direct_unknown_rate": round(direct_unknown_rate, 6),
        "evidence_conflict_count": evidence_conflict,
        "invalid_source_link_count": 0,
        "source_link_replay_count": 0,
        "handoff_correlation": {
            "success": handoff_success,
            "expired": 0,
            "failed": 0,
        },
        "install_referrer_retrieval": {"retrieved": install_referrer},
        "universal_link_processing_count": universal_link,
        "deferred_attribution": {
            "resolved": deferred.get("resolved", 0),
            "unmatched": deferred.get("unmatched", 0),
            "expired": deferred.get("expired", 0),
        },
        "adattributionkit_ingestion_count": adattributionkit,
        "sdk_deep_link_parse_failures": 0,
        "reclassification_jobs": {
            "running": job_status.get("running", 0) + job_status.get("queued", 0),
            "failed": job_status.get("failed", 0),
            "completed": completed,
        },
        "utm_inconsistency_rate": round(utm_inconsistency_rate, 6),
        "classification_drift": {
            "legacy_vs_canonical_divergence_rate": round(drift_rate, 6),
        },
    }


def _health_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {
        "total": len(rows),
        "classified": 0,
        "unclassified": 0,
        "excluded": 0,
        "verified": 0,
    }
    versions: dict[str, int] = {}
    providers: dict[str, int] = {}
    mediation: dict[str, int] = {}
    source_classes: dict[str, int] = {}
    economic_classes: dict[str, int] = {}
    channel_families: dict[str, int] = {}
    proof_levels: dict[str, int] = {}
    for row in rows:
        version = row.get("source_classifier_version") or "unclassified"
        versions[version] = versions.get(version, 0) + 1
        if row.get("source_classifier_version"):
            counts["classified"] += 1
        else:
            counts["unclassified"] += 1
        if row.get("attribution_eligible") is False:
            counts["excluded"] += 1
        if str(row.get("verification_level") or "").startswith("verified"):
            counts["verified"] += 1
        if row.get("ai_provider"):
            provider = str(row["ai_provider"])
            providers[provider] = providers.get(provider, 0) + 1
        if row.get("referral_mediation_type"):
            kind = str(row["referral_mediation_type"])
            mediation[kind] = mediation.get(kind, 0) + 1
        for values, field, normalize in (
            (source_classes, "source_class", True),
            (economic_classes, "economic_class", False),
            (channel_families, "channel_family", False),
            (proof_levels, "proof_level", False),
        ):
            raw = row.get(field)
            if raw:
                name = canonical_source_class(str(raw)) if normalize else str(raw)
                values[name] = values.get(name, 0) + 1
    as_rows = lambda values: [
        {"name": name, "count": count}
        for name, count in sorted(values.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "summary": counts,
        "versions": as_rows(versions),
        "providers": as_rows(providers),
        "mediation": as_rows(mediation),
        "source_classes": as_rows(source_classes),
        "economic_classes": as_rows(economic_classes),
        "channel_families": as_rows(channel_families),
        "proof_levels": as_rows(proof_levels),
    }


def _reset_local_touchpoints() -> None:
    """Test helper: clear the process-local repository fallback."""
    _local_store.clear()
    _local_revisions.clear()
