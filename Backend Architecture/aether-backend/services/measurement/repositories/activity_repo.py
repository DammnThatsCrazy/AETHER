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
        from uuid import uuid4
        # Ensure activity_id is always set before hitting the DB so the PK is never NULL.
        if not activity.get("activity_id"):
            activity = {**activity, "activity_id": str(uuid4())}

        pool = await self._pool()
        idem_key = f"{activity.get('tenant_id')}:{activity.get('idempotency_key')}"

        if pool is None:
            if idem_key not in _local_store:
                _local_store[idem_key] = activity
            return _local_store[idem_key]

        columns = (
            "activity_id", "tenant_id", "idempotency_key",
            "profile_id", "cluster_id", "anonymous_id",
            "account_id", "organization_id", "session_id", "device_id",
            "browser_id", "install_id", "wallet_id", "wallet_address", "agent_id",
            "activity_family", "activity_type", "actor_type",
            "channel", "source", "medium", "platform", "surface",
            "source_class", "traffic_origin", "economic_class", "channel_family",
            "entry_method", "proof_level", "evidence_conflicts",
            "referral_mediation_type", "ai_provider", "ai_product",
            "journey_role", "evidence_confidence", "verification_level",
            "source_classifier_version", "normalized_referrer_domain",
            "source_classification_id", "attribution_eligible", "verified_referral_link_id",
            "domain", "app_id", "screen", "landing_url", "referrer",
            "dapp_id", "protocol_id", "chain_id", "contract_address",
            "tx_hash", "block_number", "campaign_id", "conversion_id",
            "occurred_at", "client_occurred_at", "server_received_at",
            "chain_observed_at", "chain_confirmed_at", "activity_status",
            "source_event_id", "source_system", "source_connector_id",
            "identity_method", "identity_confidence", "identity_version",
            "consent_snapshot_id", "privacy_class", "sequence_key", "schema_version",
            "silver_fact_id", "silver_table", "gross_amount", "net_amount", "fee_amount",
            "currency", "token_address", "value_wei",
        )
        values = (
            _uuid(activity.get("activity_id")), activity.get("tenant_id"),
            activity.get("idempotency_key"), activity.get("profile_id"),
            activity.get("cluster_id"), activity.get("anonymous_id"),
            activity.get("account_id"), activity.get("organization_id"),
            activity.get("session_id"), activity.get("device_id"),
            activity.get("browser_id"), activity.get("install_id"),
            activity.get("wallet_id"), activity.get("wallet_address"),
            activity.get("agent_id"), activity.get("activity_family"),
            activity.get("activity_type"), activity.get("actor_type"),
            activity.get("channel"), activity.get("source"), activity.get("medium"),
            activity.get("platform"), activity.get("surface"), activity.get("source_class"),
            activity.get("traffic_origin"), activity.get("economic_class"),
            activity.get("channel_family"), activity.get("entry_method"),
            activity.get("proof_level"),
            _json_list(activity.get("evidence_conflicts")),
            activity.get("referral_mediation_type"), activity.get("ai_provider"),
            activity.get("ai_product"), activity.get("journey_role"),
            activity.get("evidence_confidence"), activity.get("verification_level"),
            activity.get("source_classifier_version"),
            activity.get("normalized_referrer_domain"),
            _uuid(activity.get("source_classification_id")),
            activity.get("attribution_eligible", True),
            _uuid(activity.get("verified_referral_link_id")),
            activity.get("domain"), activity.get("app_id"), activity.get("screen"),
            activity.get("landing_url"), activity.get("referrer"),
            activity.get("dapp_id"), activity.get("protocol_id"), activity.get("chain_id"),
            activity.get("contract_address"), activity.get("tx_hash"),
            activity.get("block_number"), activity.get("campaign_id"),
            activity.get("conversion_id"), _parse_ts(activity.get("occurred_at")),
            _parse_ts(activity.get("client_occurred_at")),
            _parse_ts(activity.get("server_received_at")) or datetime.now(timezone.utc),
            _parse_ts(activity.get("chain_observed_at")),
            _parse_ts(activity.get("chain_confirmed_at")),
            activity.get("activity_status", "observed"), activity.get("source_event_id"),
            activity.get("source_system"), activity.get("source_connector_id"),
            activity.get("identity_method"), activity.get("identity_confidence"),
            activity.get("identity_version"), activity.get("consent_snapshot_id"),
            activity.get("privacy_class", "behavioral"), activity.get("sequence_key"),
            activity.get("schema_version", 1), _uuid(activity.get("silver_fact_id")),
            activity.get("silver_table"), _decimal(activity.get("gross_amount")),
            _decimal(activity.get("net_amount")), _decimal(activity.get("fee_amount")),
            activity.get("currency"), activity.get("token_address"), activity.get("value_wei"),
        )
        placeholders = ",".join(f"${i}" for i in range(1, len(columns) + 1))
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO canonical_activity ({','.join(columns)}) "
                f"VALUES ({placeholders}) "
                "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING",
                *values,
            )
            persisted = await conn.fetchrow(
                """
                SELECT * FROM canonical_activity
                WHERE tenant_id=$1 AND idempotency_key=$2
                """,
                activity.get("tenant_id"),
                activity.get("idempotency_key"),
            )
        return dict(persisted) if persisted else activity

    async def apply_source_classification(
        self,
        tenant_id: str,
        *,
        touchpoint_id: str,
        source_event_id: Optional[str],
        classification: dict[str, Any],
    ) -> int:
        """Synchronize the current classification projection for a Silver touchpoint.

        Canonical activity remains the journey compiler's authoritative input;
        historical reclassification therefore updates its denormalized source
        projection explicitly.  The immutable revision history lives on the
        touchpoint side and every journey rebuild creates a new version.
        """
        fields = (
            "channel", "source", "medium", "actor_type", "source_class",
            "traffic_origin", "economic_class", "channel_family",
            "entry_method", "proof_level", "evidence_conflicts",
            "referral_mediation_type", "ai_provider", "ai_product", "journey_role",
            "evidence_confidence", "verification_level", "source_classifier_version",
            "normalized_referrer_domain", "source_classification_id",
            "attribution_eligible", "verified_referral_link_id", "referrer",
        )
        pool = await self._pool()
        if pool is None:
            count = 0
            for row in _local_store.values():
                same_touchpoint = str(row.get("silver_fact_id") or "") == str(touchpoint_id)
                same_event = bool(source_event_id) and row.get("source_event_id") == source_event_id
                if row.get("tenant_id") == tenant_id and (same_touchpoint or same_event):
                    for field in fields:
                        if field in classification:
                            row[field] = classification[field]
                    row["domain"] = classification.get("normalized_referrer_domain")
                    row["silver_fact_id"] = str(touchpoint_id)
                    row["silver_table"] = "silver_campaign_touchpoint_facts"
                    count += 1
            return count

        assignments = [f"{field} = ${index + 3}" for index, field in enumerate(fields)]
        params = [tenant_id, _uuid(touchpoint_id)] + [
            _uuid(classification.get(field))
            if field in {"source_classification_id", "verified_referral_link_id"}
            else _json_list(classification.get(field))
            if field == "evidence_conflicts"
            else classification.get(field)
            for field in fields
        ]
        params.extend([classification.get("normalized_referrer_domain"), source_event_id])
        domain_param = len(params) - 1
        event_param = len(params)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE canonical_activity
                SET {', '.join(assignments)}, domain = ${domain_param},
                    silver_fact_id = $2,
                    silver_table = 'silver_campaign_touchpoint_facts'
                WHERE tenant_id = $1
                  AND (
                    silver_fact_id = $2::uuid
                    OR (silver_table = 'silver_campaign_touchpoint_facts'
                        AND source_event_id = ${event_param})
                  )
                """,
                *params,
            )
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0

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
        identity_type: str = "profile",
        limit: int = 2000,
        cursor: Optional[str] = None,
        families: Optional[list[str]] = None,
        statuses: Optional[list[str]] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Load canonical activity for a typed identity, ordered deterministically."""
        identity_columns = {
            "profile": "profile_id",
            "cluster": "cluster_id",
            "anonymous": "anonymous_id",
        }
        identity_column = identity_columns.get(identity_type)
        if identity_column is None:
            raise ValueError(f"unsupported identity_type: {identity_type}")
        pool = await self._pool()

        _excluded_statuses = {"tombstoned", "deleted", "consent_restricted"}
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get(identity_column) == profile_id
                and r.get("activity_status") not in _excluded_statuses
                and (families is None or str(r.get("activity_family", "")) in families)
                and (statuses is None or str(r.get("activity_status", "")) in statuses)
                and (after is None or r.get("occurred_at", "") > _ts_str(after))
                and (before is None or r.get("occurred_at", "") < _ts_str(before))
            ]
            rows.sort(key=lambda r: (r.get("occurred_at", ""), r.get("sequence_key") or "", str(r.get("activity_id", ""))))
            return rows[:limit]

        conditions = ["tenant_id = $1", f"{identity_column} = $2",
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

    async def update_risk_annotation(
        self,
        tenant_id: str,
        activity_id: str,
        annotation: dict[str, Any],
    ) -> None:
        """Write fraud/risk annotation fields back to a canonical activity row."""
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        from decimal import Decimal

        pool = await self._pool()
        idem_key = f"{tenant_id}:{activity_id}"

        risk_score = annotation.get("risk_score")
        if isinstance(risk_score, float):
            risk_score = round(risk_score, 2)

        if pool is None:
            for key, row in _local_store.items():
                if row.get("tenant_id") == tenant_id and str(row.get("activity_id", "")) == str(activity_id):
                    row.update({
                        "risk_score": risk_score,
                        "risk_tier": annotation.get("risk_tier"),
                        "fraud_status": annotation.get("fraud_status"),
                        "fraud_disposition": annotation.get("fraud_disposition"),
                        "fraud_decision_id": annotation.get("fraud_decision_id"),
                        "fraud_network_ids": annotation.get("fraud_network_ids", []),
                        "fraud_signal_types": annotation.get("fraud_signal_types", []),
                        "fraud_evidence_refs": annotation.get("fraud_evidence_refs", []),
                        "risk_evaluated_at": annotation.get("risk_evaluated_at"),
                        "risk_model_version": annotation.get("risk_model_version"),
                        "risk_policy_version": annotation.get("risk_policy_version"),
                        "risk_explanation": annotation.get("risk_explanation"),
                        "risk_evaluation_state": annotation.get("risk_evaluation_state", "not_evaluated"),
                    })
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE canonical_activity SET
                    risk_score = $3,
                    risk_tier = $4,
                    fraud_status = $5,
                    fraud_disposition = $6,
                    fraud_decision_id = $7,
                    fraud_network_ids = $8,
                    fraud_signal_types = $9,
                    fraud_evidence_refs = $10::jsonb,
                    risk_evaluated_at = $11,
                    risk_model_version = $12,
                    risk_policy_version = $13,
                    risk_explanation = $14,
                    risk_evaluation_state = $15
                WHERE tenant_id = $1 AND activity_id = $2
                """,
                tenant_id,
                activity_id,
                Decimal(str(risk_score)) if risk_score is not None else None,
                annotation.get("risk_tier"),
                annotation.get("fraud_status"),
                annotation.get("fraud_disposition"),
                annotation.get("fraud_decision_id"),
                annotation.get("fraud_network_ids", []),
                annotation.get("fraud_signal_types", []),
                _json.dumps(annotation.get("fraud_evidence_refs", [])),
                annotation.get("risk_evaluated_at"),
                annotation.get("risk_model_version"),
                annotation.get("risk_policy_version"),
                annotation.get("risk_explanation"),
                annotation.get("risk_evaluation_state", "not_evaluated"),
            )


    async def find_by_source_event(
        self, tenant_id: str, source_event_id: str
    ) -> list[dict[str, Any]]:
        """Find canonical activities by their originating source event id."""
        pool = await self._pool()
        if pool is None:
            return [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("source_event_id") == source_event_id
            ]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM canonical_activity WHERE tenant_id=$1 AND source_event_id=$2",
                tenant_id, source_event_id,
            )
        return [dict(r) for r in rows]

    async def count_by_source(self, tenant_id: str, source_system: str) -> int:
        """Count canonical activities by source_system."""
        pool = await self._pool()
        if pool is None:
            return sum(
                1 for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("source_system") == source_system
            )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM canonical_activity WHERE tenant_id=$1 AND source_system=$2",
                tenant_id, source_system,
            )
        return row["cnt"] if row else 0

    async def list_agentic_steps(
        self, tenant_id: str, agent_id: Optional[str] = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """List agentic observation steps from canonical_activity."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("source_system") == "agentic_observability"
                and (agent_id is None or r.get("agent_id") == agent_id)
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
            return rows[:limit]
        conditions = ["tenant_id = $1", "source_system = 'agentic_observability'"]
        params: list[Any] = [tenant_id]
        p = 2
        if agent_id:
            conditions.append(f"agent_id = ${p}")
            params.append(agent_id)
            p += 1
        params.append(limit)
        sql = f"""
            SELECT * FROM canonical_activity
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at DESC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def list_agentic_by_agent(
        self, tenant_id: str, agent_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """List agentic steps for a specific agent."""
        return await self.list_agentic_steps(tenant_id, agent_id=agent_id, limit=limit)

    async def list_agentic_by_campaign(
        self, tenant_id: str, campaign_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """List agentic canonical activities attributed to a campaign."""
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("source_system") == "agentic_observability"
                and r.get("campaign_id") == campaign_id
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
            return rows[:limit]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM canonical_activity
                WHERE tenant_id=$1 AND source_system='agentic_observability' AND campaign_id=$2
                ORDER BY occurred_at DESC LIMIT $3
                """,
                tenant_id, campaign_id, limit,
            )
        return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_list(value: Any) -> str:
    """Serialize a JSON list column value (asyncpg binds str to jsonb)."""
    if value is None:
        return json.dumps([])
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), default=str)
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


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
