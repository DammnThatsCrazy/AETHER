"""Comms repositories — durable access to silver_comms_facts,
communication_state, communication_suppressions, and campaign message/link
dimensions.

Production: asyncpg against PostgreSQL. Local/test: in-memory module stores
(same interface), mirroring TouchpointRepository's established pattern.
All queries are tenant-scoped; cursor pagination uses (occurred_at, fact key).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from shared.logger.logger import get_logger
from repositories.repos import get_pool

logger = get_logger("aether.comms.repository")

# In-memory fallbacks (local/test only — production requires a pool)
_local_facts: dict[str, dict[str, Any]] = {}
_local_state: dict[str, dict[str, Any]] = {}
_local_suppressions: dict[str, dict[str, Any]] = {}
_local_messages: dict[str, dict[str, Any]] = {}
_local_links: dict[str, dict[str, Any]] = {}


def reset_local_stores() -> None:
    """Test helper — clears all in-memory fallbacks."""
    for store in (_local_facts, _local_state, _local_suppressions,
                  _local_messages, _local_links):
        store.clear()


def _encode_cursor(occurred_at: str, key: str) -> str:
    return base64.urlsafe_b64encode(f"{occurred_at}|{key}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    occurred_at, _, key = raw.partition("|")
    return occurred_at, key


_FACT_COLUMNS: tuple[str, ...] = (
    "fact_id", "tenant_id", "source_event_id", "source_event_type",
    "actor_id", "user_id", "anonymous_id", "org_id", "occurred_at",
    "received_at", "consent_snapshot_id", "privacy_class", "idempotency_key",
    "payload", "comms_type", "channel", "campaign_id", "message_id",
    "support_case_id", "deliverability",
    "provider", "provider_account_id", "provider_event_id",
    "source_connector_id", "direction", "message_category",
    "communication_state", "journey_role", "actor_kind",
    "sender_entity_id", "recipient_entity_id", "recipient_alias_id",
    "recipient_display", "recipient_is_shared_mailbox", "profile_id",
    "cluster_id", "organization_id", "agent_id", "external_campaign_id",
    "external_flow_id", "external_message_id", "external_thread_id",
    "external_template_id", "sequence_step", "variant_id", "link_id",
    "link_url_hash", "audience_id", "segment_id", "delivery_status",
    "bounce_type", "suppression_scope", "unsubscribe_scope",
    "engagement_type", "engagement_confidence", "engagement_strength",
    "machine_activity_probability", "suspected_machine_activity",
    "automated_response_kind", "classifier_version",
    "identity_resolution_method", "identity_confidence",
    "campaign_resolution_method", "campaign_resolution_confidence",
    "campaign_resolution_status", "campaign_resolution_version",
    "raw_evidence_ref", "evidence_ids", "provenance",
    "canonical_activity_key", "schema_version",
)

_JSON_COLUMNS = {"payload", "provenance"}


class CommsFactsRepository:
    """Durable storage over silver_comms_facts."""

    async def _pool(self):
        return await get_pool()

    # ── Write ────────────────────────────────────────────────────────────────

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or ignore on (tenant_id, idempotency_key) conflict — replay safe."""
        row.setdefault("fact_id", str(uuid4()))
        row.setdefault("received_at", datetime.now(timezone.utc).isoformat())
        key = f"{row.get('tenant_id')}:{row.get('idempotency_key')}"

        pool = await self._pool()
        if pool is None:
            # Idempotent local write — first write wins, mirroring DO NOTHING.
            _local_facts.setdefault(key, row)
            return _local_facts[key]

        cols = [c for c in _FACT_COLUMNS if c in row]
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        values = [
            json.dumps(row[c]) if c in _JSON_COLUMNS and row[c] is not None else row[c]
            for c in cols
        ]
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO silver_comms_facts ({', '.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                *values,
            )
        return row

    # ── Read: Profile360 ─────────────────────────────────────────────────────

    async def list_for_entity(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        channel: Optional[str] = None,
        category: Optional[str] = None,
        direction: Optional[str] = None,
        campaign_id: Optional[str] = None,
        external_message_id: Optional[str] = None,
        state: Optional[str] = None,
        human_qualified: Optional[bool] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Cursor-paginated communication facts for a profile/entity."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id
                and entity_id in (r.get("profile_id"), r.get("recipient_entity_id"),
                                  r.get("user_id"))
            ]
            rows = _apply_local_filters(
                rows, channel=channel, category=category, direction=direction,
                campaign_id=campaign_id, external_message_id=external_message_id,
                state=state, human_qualified=human_qualified,
                after=after, before=before,
            )
            rows.sort(key=lambda r: str(r.get("occurred_at") or ""), reverse=True)
            if cursor:
                c_at, c_key = _decode_cursor(cursor)
                rows = [r for r in rows if str(r.get("occurred_at")) < c_at
                        or (str(r.get("occurred_at")) == c_at and str(r.get("fact_id")) < c_key)]
            page = rows[:limit]
            next_cursor = (
                _encode_cursor(str(page[-1].get("occurred_at")), str(page[-1].get("fact_id")))
                if len(rows) > limit and page else None
            )
            return page, next_cursor

        conditions = ["tenant_id = $1",
                      "(profile_id = $2 OR recipient_entity_id = $2 OR user_id = $2)"]
        params: list[Any] = [tenant_id, entity_id]

        def _add(cond_sql: str, value: Any) -> None:
            params.append(value)
            conditions.append(cond_sql.format(n=len(params)))

        if channel:
            _add("channel = ${n}", channel)
        if category:
            _add("message_category = ${n}", category)
        if direction:
            _add("direction = ${n}", direction)
        if campaign_id:
            _add("campaign_id = ${n}", campaign_id)
        if external_message_id:
            _add("external_message_id = ${n}", external_message_id)
        if state:
            _add("communication_state = ${n}", state)
        if human_qualified is True:
            conditions.append("COALESCE(suspected_machine_activity, false) = false")
            conditions.append("engagement_type IS NOT NULL")
        if after:
            _add("occurred_at >= ${n}", _parse_ts(after))
        if before:
            _add("occurred_at <= ${n}", _parse_ts(before))
        if cursor:
            c_at, c_key = _decode_cursor(cursor)
            params.append(_parse_ts(c_at))
            params.append(c_key)
            conditions.append(
                f"(occurred_at, fact_id::text) < (${len(params)-1}, ${len(params)})"
            )

        sql = f"""
            SELECT * FROM silver_comms_facts
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at DESC, fact_id DESC
            LIMIT {int(limit) + 1}
        """
        async with pool.acquire() as conn:
            records = await conn.fetch(sql, *params)
        rows = [dict(r) for r in records]
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(str(last["occurred_at"]), str(last["fact_id"]))
        return rows, next_cursor

    async def entity_summary(self, tenant_id: str, entity_id: str) -> dict[str, Any]:
        """Aggregate communication counts for the Profile360 summary card."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id
                and entity_id in (r.get("profile_id"), r.get("recipient_entity_id"),
                                  r.get("user_id"))
            ]
            human = [r for r in rows if not r.get("suspected_machine_activity")]
            return {
                "communications": len(rows),
                "email_campaigns": len({r.get("campaign_id") for r in rows if r.get("campaign_id")}),
                "human_clicks": sum(1 for r in human if r.get("source_event_type") in ("email_clicked", "notification_clicked")),
                "replies": sum(1 for r in human if r.get("source_event_type") in ("email_replied", "message_replied_observed") and not r.get("automated_response_kind")),
                "communication_outcomes": sum(1 for r in rows if r.get("journey_role") == "outcome"),
            }

        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS communications,
                    COUNT(DISTINCT campaign_id) FILTER (WHERE campaign_id IS NOT NULL) AS email_campaigns,
                    COUNT(*) FILTER (
                        WHERE source_event_type IN ('email_clicked', 'notification_clicked')
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS human_clicks,
                    COUNT(*) FILTER (
                        WHERE source_event_type IN ('email_replied', 'message_replied_observed')
                        AND automated_response_kind IS NULL
                    ) AS replies,
                    COUNT(*) FILTER (WHERE journey_role = 'outcome') AS communication_outcomes
                FROM silver_comms_facts
                WHERE tenant_id = $1
                  AND (profile_id = $2 OR recipient_entity_id = $2 OR user_id = $2)
                """,
                tenant_id, entity_id,
            )
        return dict(rec) if rec else {}

    # ── Read: Campaign 360 ───────────────────────────────────────────────────

    async def list_for_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        state: Optional[str] = None,
        human_qualified: Optional[bool] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id and str(r.get("campaign_id")) == str(campaign_id)
            ]
            rows = _apply_local_filters(rows, state=state, human_qualified=human_qualified)
            rows.sort(key=lambda r: str(r.get("occurred_at") or ""), reverse=True)
            return rows[:limit], None

        conditions = ["tenant_id = $1", "campaign_id = $2"]
        params: list[Any] = [tenant_id, campaign_id]
        if state:
            params.append(state)
            conditions.append(f"communication_state = ${len(params)}")
        if human_qualified is True:
            conditions.append("COALESCE(suspected_machine_activity, false) = false")
        if cursor:
            c_at, c_key = _decode_cursor(cursor)
            params.append(_parse_ts(c_at))
            params.append(c_key)
            conditions.append(
                f"(occurred_at, fact_id::text) < (${len(params)-1}, ${len(params)})"
            )
        sql = f"""
            SELECT * FROM silver_comms_facts
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at DESC, fact_id DESC
            LIMIT {int(limit) + 1}
        """
        async with pool.acquire() as conn:
            records = await conn.fetch(sql, *params)
        rows = [dict(r) for r in records]
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(str(last["occurred_at"]), str(last["fact_id"]))
        return rows, next_cursor

    async def campaign_funnel(self, tenant_id: str, campaign_id: str) -> dict[str, Any]:
        """Email funnel for Campaign 360 overview — provider-reported and
        human-qualified modes in one pass."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id and str(r.get("campaign_id")) == str(campaign_id)
            ]
            return _local_funnel(rows)

        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                SELECT
                    COUNT(DISTINCT recipient_alias_id) FILTER (WHERE source_event_type = 'email_sent') AS sent,
                    COUNT(DISTINCT recipient_alias_id) FILTER (WHERE source_event_type = 'email_delivered') AS delivered,
                    COUNT(DISTINCT recipient_alias_id) FILTER (WHERE source_event_type = 'email_opened') AS reported_opens,
                    COUNT(DISTINCT recipient_alias_id) FILTER (
                        WHERE source_event_type = 'email_opened'
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS human_opens,
                    COUNT(DISTINCT recipient_alias_id) FILTER (WHERE source_event_type = 'email_clicked') AS reported_clicks,
                    COUNT(DISTINCT recipient_alias_id) FILTER (
                        WHERE source_event_type = 'email_clicked'
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS human_clicks,
                    COUNT(DISTINCT recipient_alias_id) FILTER (
                        WHERE source_event_type IN ('email_replied', 'message_replied_observed')
                        AND automated_response_kind IS NULL
                    ) AS replies,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_bounced' AND bounce_type = 'hard') AS hard_bounces,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_bounced' AND COALESCE(bounce_type, 'soft') <> 'hard') AS soft_bounces,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_spam_complaint') AS complaints,
                    COUNT(*) FILTER (WHERE source_event_type = 'unsubscribe_observed') AS unsubscribes,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_suppressed') AS suppressions,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_deferred') AS deferred,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_dropped') AS dropped,
                    COUNT(*) FILTER (WHERE COALESCE(suspected_machine_activity, false)) AS machine_events,
                    COUNT(*) AS total_events
                FROM silver_comms_facts
                WHERE tenant_id = $1 AND campaign_id = $2
                """,
                tenant_id, campaign_id,
            )
        return dict(rec) if rec else {}

    async def message_stats(self, tenant_id: str, campaign_id: str) -> list[dict[str, Any]]:
        """Per-message rollup for the Campaign 360 Messages tab."""
        pool = await self._pool()
        if pool is None:
            by_msg: dict[str, list[dict[str, Any]]] = {}
            for r in _local_facts.values():
                if r.get("tenant_id") == tenant_id and str(r.get("campaign_id")) == str(campaign_id):
                    by_msg.setdefault(str(r.get("external_message_id") or "unattributed"), []).append(r)
            return [
                {"external_message_id": mid, "sequence_step": rows[0].get("sequence_step"),
                 **_local_funnel(rows)}
                for mid, rows in sorted(by_msg.items())
            ]

        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT
                    COALESCE(external_message_id, 'unattributed') AS external_message_id,
                    MIN(sequence_step) AS sequence_step,
                    COUNT(DISTINCT recipient_alias_id) FILTER (WHERE source_event_type = 'email_delivered') AS delivered,
                    COUNT(DISTINCT recipient_alias_id) FILTER (
                        WHERE source_event_type = 'email_clicked'
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS human_clicks,
                    COUNT(DISTINCT recipient_alias_id) FILTER (
                        WHERE source_event_type IN ('email_replied', 'message_replied_observed')
                        AND automated_response_kind IS NULL
                    ) AS replies,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_bounced') AS bounces,
                    COUNT(*) FILTER (WHERE COALESCE(suspected_machine_activity, false)) AS machine_events,
                    COUNT(*) AS total_events
                FROM silver_comms_facts
                WHERE tenant_id = $1 AND campaign_id = $2
                GROUP BY COALESCE(external_message_id, 'unattributed')
                ORDER BY MIN(sequence_step) NULLS LAST, external_message_id
                """,
                tenant_id, campaign_id,
            )
        return [dict(r) for r in records]

    async def link_stats(self, tenant_id: str, campaign_id: str) -> list[dict[str, Any]]:
        """Per-link human-click rollup for link performance."""
        pool = await self._pool()
        if pool is None:
            by_link: dict[str, int] = {}
            msg_of: dict[str, Any] = {}
            for r in _local_facts.values():
                if (r.get("tenant_id") == tenant_id
                        and str(r.get("campaign_id")) == str(campaign_id)
                        and r.get("source_event_type") == "email_clicked"
                        and not r.get("suspected_machine_activity")
                        and r.get("link_id")):
                    by_link[r["link_id"]] = by_link.get(r["link_id"], 0) + 1
                    msg_of[r["link_id"]] = r.get("external_message_id")
            return [
                {"link_id": link, "external_message_id": msg_of.get(link), "human_clicks": n}
                for link, n in sorted(by_link.items())
            ]

        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT link_id,
                       MAX(external_message_id) AS external_message_id,
                       COUNT(*) AS human_clicks,
                       COUNT(DISTINCT recipient_alias_id) AS unique_clickers
                FROM silver_comms_facts
                WHERE tenant_id = $1 AND campaign_id = $2
                  AND source_event_type = 'email_clicked'
                  AND COALESCE(suspected_machine_activity, false) = false
                  AND link_id IS NOT NULL
                GROUP BY link_id
                ORDER BY COUNT(*) DESC
                """,
                tenant_id, campaign_id,
            )
        return [dict(r) for r in records]

    async def campaign_population(
        self, tenant_id: str, campaign_id: str,
        *, stage: Optional[str] = None,
        bounced: Optional[bool] = None,
        suppressed: Optional[bool] = None,
        unsubscribed: Optional[bool] = None,
        complained: Optional[bool] = None,
        human_qualified: Optional[bool] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Per-recipient population rows for one campaign (Phase 19).

        Each row carries the recipient's highest reached stage
        (``attempted → delivered → engaged → replied``), delivery flags, and
        human-qualified engagement counts. Stage/flag filters compose.
        Recipients are keyed by alias hash (falling back to entity id) —
        no raw addresses appear anywhere.
        """
        rows = await self._population_rows(tenant_id, campaign_id, limit=limit * 5)

        out = []
        for row in rows:
            if stage and row["stage"] != stage:
                continue
            if bounced is not None and bool(row["bounced"]) != bounced:
                continue
            if suppressed is not None and bool(row["suppressed"]) != suppressed:
                continue
            if unsubscribed is not None and bool(row["unsubscribed"]) != unsubscribed:
                continue
            if complained is not None and bool(row["complained"]) != complained:
                continue
            if human_qualified is True and row["human_clicks"] == 0 and row["replies"] == 0:
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    async def _population_rows(
        self, tenant_id: str, campaign_id: str, *, limit: int,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            by_recipient: dict[str, list[dict[str, Any]]] = {}
            for r in _local_facts.values():
                if (r.get("tenant_id") == tenant_id
                        and str(r.get("campaign_id")) == str(campaign_id)):
                    key = str(r.get("recipient_alias_id") or r.get("recipient_entity_id")
                              or r.get("profile_id") or r.get("fact_id"))
                    by_recipient.setdefault(key, []).append(r)
            return [
                _classify_recipient(key, facts)
                for key, facts in sorted(by_recipient.items())
            ][:limit]

        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT
                    COALESCE(recipient_alias_id, recipient_entity_id, profile_id,
                             fact_id::text) AS recipient_key,
                    MAX(COALESCE(recipient_entity_id, profile_id)) AS entity_id,
                    MAX(recipient_display) AS recipient_display,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_sent') AS sent,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_delivered') AS delivered,
                    COUNT(*) FILTER (
                        WHERE source_event_type = 'email_opened'
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS human_opens,
                    COUNT(*) FILTER (
                        WHERE source_event_type = 'email_clicked'
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS human_clicks,
                    COUNT(*) FILTER (
                        WHERE source_event_type IN ('email_replied', 'message_replied_observed')
                        AND automated_response_kind IS NULL
                    ) AS replies,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_bounced') AS bounces,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_spam_complaint') AS complaints,
                    COUNT(*) FILTER (WHERE source_event_type = 'unsubscribe_observed') AS unsubscribes,
                    COUNT(*) FILTER (WHERE source_event_type = 'email_suppressed') AS suppressions,
                    MAX(occurred_at) FILTER (
                        WHERE engagement_type IS NOT NULL
                        AND COALESCE(suspected_machine_activity, false) = false
                    ) AS last_engagement_at,
                    MAX(identity_confidence) AS identity_confidence
                FROM silver_comms_facts
                WHERE tenant_id = $1 AND campaign_id = $2
                GROUP BY COALESCE(recipient_alias_id, recipient_entity_id, profile_id,
                                  fact_id::text)
                ORDER BY MAX(occurred_at) DESC
                LIMIT $3
                """,
                tenant_id, campaign_id, limit,
            )
        return [_population_row_from_record(dict(r)) for r in records]

    async def tombstone_by_profile(self, tenant_id: str, entity_id: str) -> int:
        """DSR erasure: delete communication facts and derived state for an
        entity (ADR-C10).

        Active suppression records are intentionally retained — honoring an
        opt-out after erasure requires keeping the suppression itself.
        Returns the number of facts removed.
        """
        pool = await self._pool()
        if pool is None:
            keys = [
                k for k, r in _local_facts.items()
                if r.get("tenant_id") == tenant_id
                and entity_id in (r.get("profile_id"), r.get("recipient_entity_id"),
                                  r.get("user_id"), r.get("recipient_alias_id"))
            ]
            for k in keys:
                _local_facts.pop(k, None)
            state_keys = [k for k in _local_state if k.startswith(f"{tenant_id}:{entity_id}:")]
            for k in state_keys:
                _local_state.pop(k, None)
            removed = len(keys)
        else:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM silver_comms_facts
                    WHERE tenant_id = $1
                      AND (profile_id = $2 OR recipient_entity_id = $2
                           OR user_id = $2 OR recipient_alias_id = $2)
                    """,
                    tenant_id, entity_id,
                )
                await conn.execute(
                    "DELETE FROM communication_state WHERE tenant_id = $1 AND entity_id = $2",
                    tenant_id, entity_id,
                )
            removed = int(result.split()[-1]) if result else 0
        from shared.logger.logger import metrics as _metrics
        _metrics.increment(
            "comms_dsr_erasures_total", labels={"tenant_id": tenant_id}
        )
        logger.info(
            "comms_dsr_erasure tenant=%s entity=%s facts_removed=%d",
            tenant_id, entity_id, removed,
        )
        return removed

    async def facts_for_state_rebuild(
        self, tenant_id: str, entity_id: str, channel: str = "email",
    ) -> list[dict[str, Any]]:
        """All facts needed to rebuild communication state for one entity."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id
                and r.get("channel") == channel
                and entity_id in (r.get("profile_id"), r.get("recipient_entity_id"),
                                  r.get("recipient_alias_id"), r.get("user_id"))
            ]
            rows.sort(key=lambda r: str(r.get("occurred_at") or ""))
            return rows
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT * FROM silver_comms_facts
                WHERE tenant_id = $1 AND channel = $2
                  AND (profile_id = $3 OR recipient_entity_id = $3
                       OR recipient_alias_id = $3 OR user_id = $3)
                ORDER BY occurred_at ASC
                """,
                tenant_id, channel, entity_id,
            )
        return [dict(r) for r in records]


class CommunicationStateRepository:
    """Rebuildable communication-state projection (Phase 8)."""

    async def _pool(self):
        return await get_pool()

    async def upsert(self, state: dict[str, Any]) -> dict[str, Any]:
        key = (f"{state['tenant_id']}:{state['entity_id']}:"
               f"{state.get('channel', 'email')}:{state.get('scope', 'marketing')}")
        state.setdefault("computed_at", datetime.now(timezone.utc).isoformat())
        pool = await self._pool()
        if pool is None:
            _local_state[key] = state
            return state
        cols = [
            "tenant_id", "entity_id", "channel", "scope",
            "subscription_status", "deliverability_status",
            "last_sent_at", "last_delivered_at", "last_reported_open_at",
            "last_human_engagement_at", "last_click_at", "last_reply_at",
            "total_sent", "total_delivered", "total_reported_opens",
            "total_human_clicks", "total_replies",
            "hard_bounce_count", "soft_bounce_count", "complaint_count",
            "suppression_scope", "unsubscribe_scope", "provider_profiles",
            "source_freshness_at", "computed_at", "schema_version",
        ]
        values = [
            json.dumps(state.get(c) or {}) if c == "provider_profiles"
            else state.get(c) for c in cols
        ]
        update_cols = [c for c in cols if c not in ("tenant_id", "entity_id", "channel", "scope")]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO communication_state ({', '.join(cols)})
                VALUES ({', '.join(f'${i+1}' for i in range(len(cols)))})
                ON CONFLICT (tenant_id, entity_id, channel, scope)
                DO UPDATE SET {set_clause}
                """,
                *values,
            )
        return state

    async def get(
        self, tenant_id: str, entity_id: str,
        channel: str = "email", scope: str = "marketing",
    ) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return _local_state.get(f"{tenant_id}:{entity_id}:{channel}:{scope}")
        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                SELECT * FROM communication_state
                WHERE tenant_id = $1 AND entity_id = $2 AND channel = $3 AND scope = $4
                """,
                tenant_id, entity_id, channel, scope,
            )
        return dict(rec) if rec else None

    async def list_for_entity(self, tenant_id: str, entity_id: str) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                s for k, s in _local_state.items()
                if k.startswith(f"{tenant_id}:{entity_id}:")
            ]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                "SELECT * FROM communication_state WHERE tenant_id = $1 AND entity_id = $2",
                tenant_id, entity_id,
            )
        return [dict(r) for r in records]


class CommunicationSuppressionRepository:
    """Scoped suppression state (ADR-C7). Fail-closed helpers included."""

    async def _pool(self):
        return await get_pool()

    async def add(self, suppression: dict[str, Any]) -> dict[str, Any]:
        suppression.setdefault("suppression_id", str(uuid4()))
        suppression.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        suppression.setdefault("active", True)
        key = f"{suppression['tenant_id']}:{suppression['suppression_id']}"
        pool = await self._pool()
        if pool is None:
            _local_suppressions[key] = suppression
            return suppression
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO communication_suppressions (
                    suppression_id, tenant_id, entity_id, recipient_alias_id,
                    channel, scope, scope_ref, reason, source_event_id,
                    provider, active, created_at,
                    provider_account_id, canonical_entity_id, canonical_profile_id,
                    consent_purpose, processing_basis,
                    provider_enforcement_state, aether_enforcement_state,
                    last_reconciled_at, evidence_reference
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                          $13,$14,$15,$16,$17,$18,$19,$20,$21)
                ON CONFLICT DO NOTHING
                """,
                suppression["suppression_id"], suppression["tenant_id"],
                suppression.get("entity_id"), suppression.get("recipient_alias_id"),
                suppression.get("channel", "email"), suppression["scope"],
                suppression.get("scope_ref"), suppression["reason"],
                suppression.get("source_event_id"), suppression.get("provider"),
                suppression["active"], _parse_ts(suppression["created_at"]),
                suppression.get("provider_account_id"),
                suppression.get("canonical_entity_id"),
                suppression.get("canonical_profile_id"),
                suppression.get("consent_purpose"),
                suppression.get("processing_basis"),
                suppression.get("provider_enforcement_state"),
                suppression.get("aether_enforcement_state"),
                _parse_ts(suppression["last_reconciled_at"])
                if suppression.get("last_reconciled_at") else None,
                suppression.get("evidence_reference"),
            )
        return suppression

    async def active_for(
        self, tenant_id: str, *, entity_id: Optional[str] = None,
        recipient_alias_id: Optional[str] = None, channel: str = "email",
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                s for s in _local_suppressions.values()
                if s.get("tenant_id") == tenant_id and s.get("active")
                and s.get("channel") == channel
                and ((entity_id and s.get("entity_id") == entity_id)
                     or (recipient_alias_id and s.get("recipient_alias_id") == recipient_alias_id))
            ]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT * FROM communication_suppressions
                WHERE tenant_id = $1 AND active AND channel = $2
                  AND (($3::text IS NOT NULL AND entity_id = $3)
                       OR ($4::text IS NOT NULL AND recipient_alias_id = $4))
                """,
                tenant_id, channel, entity_id, recipient_alias_id,
            )
        return [dict(r) for r in records]

    async def list_active_for_tenant(
        self, tenant_id: str, *, provider: Optional[str] = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        """All active suppressions for a tenant (read API + reconciliation)."""
        pool = await self._pool()
        if pool is None:
            rows = [
                s for s in _local_suppressions.values()
                if s.get("tenant_id") == tenant_id and s.get("active")
                and (provider is None or s.get("provider") == provider)
            ]
            return rows[:limit]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT * FROM communication_suppressions
                WHERE tenant_id = $1 AND active
                  AND ($2::text IS NULL OR provider = $2)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                tenant_id, provider, limit,
            )
        return [dict(r) for r in records]


class CampaignMessageRepository:
    """Message and link dimensions under the canonical campaign (ADR-C9)."""

    async def _pool(self):
        return await get_pool()

    async def upsert_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        msg.setdefault("message_id", str(uuid4()))
        key = f"{msg['tenant_id']}:{msg['provider']}:{msg['external_message_id']}"
        pool = await self._pool()
        if pool is None:
            existing = _local_messages.get(key)
            if existing:
                existing.update({k: v for k, v in msg.items() if v is not None and k != "message_id"})
                return existing
            _local_messages[key] = msg
            return msg
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO campaign_messages (
                    message_id, tenant_id, campaign_id, provider,
                    provider_account_id, external_message_id, external_template_id,
                    name, subject_redacted, sequence_step, variant_id, channel,
                    message_category, status, source_connector_id, properties
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                ON CONFLICT (tenant_id, provider, external_message_id)
                DO UPDATE SET
                    campaign_id = EXCLUDED.campaign_id,
                    name = COALESCE(EXCLUDED.name, campaign_messages.name),
                    status = EXCLUDED.status,
                    last_seen_at = now()
                """,
                msg["message_id"], msg["tenant_id"], msg.get("campaign_id"),
                msg["provider"], msg.get("provider_account_id"),
                msg["external_message_id"], msg.get("external_template_id"),
                msg.get("name"), msg.get("subject_redacted"),
                msg.get("sequence_step"), msg.get("variant_id"),
                msg.get("channel", "email"), msg.get("message_category", "marketing"),
                msg.get("status", "active"), msg.get("source_connector_id"),
                json.dumps(msg.get("properties") or {}),
            )
        return msg

    async def list_for_campaign(self, tenant_id: str, campaign_id: str) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                m for m in _local_messages.values()
                if m.get("tenant_id") == tenant_id and str(m.get("campaign_id")) == str(campaign_id)
            ]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT * FROM campaign_messages
                WHERE tenant_id = $1 AND campaign_id = $2
                ORDER BY sequence_step NULLS LAST, external_message_id
                """,
                tenant_id, campaign_id,
            )
        return [dict(r) for r in records]

    async def get_by_external_id(
        self, tenant_id: str, provider: str, external_message_id: str,
    ) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return _local_messages.get(f"{tenant_id}:{provider}:{external_message_id}")
        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                SELECT * FROM campaign_messages
                WHERE tenant_id = $1 AND provider = $2 AND external_message_id = $3
                """,
                tenant_id, provider, external_message_id,
            )
        return dict(rec) if rec else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_local_filters(rows: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
    out = rows
    if filters.get("channel"):
        out = [r for r in out if r.get("channel") == filters["channel"]]
    if filters.get("category"):
        out = [r for r in out if r.get("message_category") == filters["category"]]
    if filters.get("direction"):
        out = [r for r in out if r.get("direction") == filters["direction"]]
    if filters.get("campaign_id"):
        out = [r for r in out if str(r.get("campaign_id")) == str(filters["campaign_id"])]
    if filters.get("external_message_id"):
        out = [r for r in out if r.get("external_message_id") == filters["external_message_id"]]
    if filters.get("state"):
        out = [r for r in out if r.get("communication_state") == filters["state"]]
    if filters.get("human_qualified") is True:
        out = [r for r in out
               if not r.get("suspected_machine_activity") and r.get("engagement_type")]
    if filters.get("after"):
        out = [r for r in out if str(r.get("occurred_at") or "") >= str(filters["after"])]
    if filters.get("before"):
        out = [r for r in out if str(r.get("occurred_at") or "") <= str(filters["before"])]
    return out


def _local_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def uniq(pred) -> int:
        return len({r.get("recipient_alias_id") or r.get("fact_id")
                    for r in rows if pred(r)})

    human = lambda r: not r.get("suspected_machine_activity")  # noqa: E731
    return {
        "sent": uniq(lambda r: r.get("source_event_type") == "email_sent"),
        "delivered": uniq(lambda r: r.get("source_event_type") == "email_delivered"),
        "reported_opens": uniq(lambda r: r.get("source_event_type") == "email_opened"),
        "human_opens": uniq(lambda r: r.get("source_event_type") == "email_opened" and human(r)),
        "reported_clicks": uniq(lambda r: r.get("source_event_type") == "email_clicked"),
        "human_clicks": uniq(lambda r: r.get("source_event_type") == "email_clicked" and human(r)),
        "replies": uniq(lambda r: r.get("source_event_type") in ("email_replied", "message_replied_observed")
                        and not r.get("automated_response_kind")),
        "hard_bounces": sum(1 for r in rows if r.get("source_event_type") == "email_bounced" and r.get("bounce_type") == "hard"),
        "soft_bounces": sum(1 for r in rows if r.get("source_event_type") == "email_bounced" and r.get("bounce_type") != "hard"),
        "complaints": sum(1 for r in rows if r.get("source_event_type") == "email_spam_complaint"),
        "unsubscribes": sum(1 for r in rows if r.get("source_event_type") == "unsubscribe_observed"),
        "suppressions": sum(1 for r in rows if r.get("source_event_type") == "email_suppressed"),
        "deferred": sum(1 for r in rows if r.get("source_event_type") == "email_deferred"),
        "dropped": sum(1 for r in rows if r.get("source_event_type") == "email_dropped"),
        "machine_events": sum(1 for r in rows if r.get("suspected_machine_activity")),
        "total_events": len(rows),
    }


def _classify_recipient(key: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Local-mode recipient classification mirroring the SQL rollup."""
    def count(pred) -> int:
        return sum(1 for f in facts if pred(f))

    human = lambda f: not f.get("suspected_machine_activity")  # noqa: E731
    record = {
        "recipient_key": key,
        "entity_id": next(
            (f.get("recipient_entity_id") or f.get("profile_id")
             for f in facts if f.get("recipient_entity_id") or f.get("profile_id")),
            None,
        ),
        "recipient_display": next(
            (f.get("recipient_display") for f in facts if f.get("recipient_display")), None,
        ),
        "sent": count(lambda f: f.get("source_event_type") == "email_sent"),
        "delivered": count(lambda f: f.get("source_event_type") == "email_delivered"),
        "human_opens": count(lambda f: f.get("source_event_type") == "email_opened" and human(f)),
        "human_clicks": count(lambda f: f.get("source_event_type") == "email_clicked" and human(f)),
        "replies": count(lambda f: f.get("source_event_type") in ("email_replied", "message_replied_observed")
                         and not f.get("automated_response_kind")),
        "bounces": count(lambda f: f.get("source_event_type") == "email_bounced"),
        "complaints": count(lambda f: f.get("source_event_type") == "email_spam_complaint"),
        "unsubscribes": count(lambda f: f.get("source_event_type") == "unsubscribe_observed"),
        "suppressions": count(lambda f: f.get("source_event_type") == "email_suppressed"),
        "last_engagement_at": max(
            (str(f.get("occurred_at")) for f in facts
             if f.get("engagement_type") and human(f)), default=None,
        ),
        "identity_confidence": max(
            (float(f["identity_confidence"]) for f in facts
             if f.get("identity_confidence") is not None), default=None,
        ),
    }
    return _population_row_from_record(record)


def _population_row_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Derive the highest reached stage and delivery flags for one recipient."""
    replies = int(record.get("replies") or 0)
    human_clicks = int(record.get("human_clicks") or 0)
    human_opens = int(record.get("human_opens") or 0)
    delivered = int(record.get("delivered") or 0)
    sent = int(record.get("sent") or 0)

    if replies > 0:
        stage = "replied"
    elif human_clicks > 0 or human_opens > 0:
        stage = "engaged"
    elif delivered > 0:
        stage = "delivered"
    elif sent > 0:
        stage = "attempted"
    else:
        stage = "observed"

    return {
        "recipient_key": str(record.get("recipient_key")),
        "entity_id": record.get("entity_id"),
        "recipient_display": record.get("recipient_display"),
        "stage": stage,
        "sent": sent,
        "delivered": delivered,
        "human_opens": human_opens,
        "human_clicks": human_clicks,
        "replies": replies,
        "bounced": int(record.get("bounces") or 0) > 0,
        "complained": int(record.get("complaints") or 0) > 0,
        "unsubscribed": int(record.get("unsubscribes") or 0) > 0,
        "suppressed": int(record.get("suppressions") or 0) > 0,
        "last_engagement_at": (
            str(record["last_engagement_at"]) if record.get("last_engagement_at") else None
        ),
        "identity_confidence": (
            float(record["identity_confidence"])
            if record.get("identity_confidence") is not None else None
        ),
        "profile360": f"/v1/profile/{record['entity_id']}" if record.get("entity_id") else None,
    }


def _parse_ts(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value
