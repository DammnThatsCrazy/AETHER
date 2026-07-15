"""Journey step repository — first-class ordered steps within a journey version."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from repositories.repos import get_pool
from shared.logger.logger import get_logger

logger = get_logger("aether.measurement.journey_step_repo")

_local_store: dict[str, list[dict[str, Any]]] = {}  # keyed by (tenant_id, journey_version_id)


def _version_key(tenant_id: str, journey_version_id: str) -> str:
    return f"{tenant_id}:{journey_version_id}"


class JourneyStepRepository:
    """Stores and queries individual journey steps.

    Steps are append-only per journey_version; a new version rebuilds all steps.
    The position column is the canonical ordering key within a version.
    """

    async def _pool(self):
        return await get_pool()

    async def bulk_create(
        self,
        steps: list[dict[str, Any]],
        *,
        connection: Any = None,
    ) -> int:
        """Insert a full set of steps for a journey version atomically.

        Caller must ensure steps have unique (tenant_id, journey_version_id, step_position).
        """
        if not steps:
            return 0

        if connection is not None:
            await _insert_steps(connection, steps)
            return len(steps)

        pool = await self._pool()

        if pool is None:
            tenant_id = steps[0].get("tenant_id")
            jvid = str(steps[0].get("journey_version_id"))
            key = _version_key(tenant_id, jvid)
            _local_store[key] = list(steps)
            return len(steps)

        # Build a multi-row VALUES insert; asyncpg handles this efficiently
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _insert_steps(conn, steps)
        return len(steps)

    async def delete_by_version(self, tenant_id: str, journey_version_id: str) -> int:
        """Remove all steps for a journey version (used before rebuilding)."""
        pool = await self._pool()

        if pool is None:
            key = _version_key(tenant_id, journey_version_id)
            count = len(_local_store.pop(key, []))
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM journey_steps WHERE tenant_id=$1 AND journey_version_id=$2::uuid",
                tenant_id, journey_version_id,
            )
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0

    async def list_by_version(
        self,
        tenant_id: str,
        journey_version_id: str,
        *,
        limit: int = 200,
        cursor: Optional[str] = None,
        families: Optional[list[str]] = None,
        statuses: Optional[list[str]] = None,
        session_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        chain_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()

        if pool is None:
            key = _version_key(tenant_id, journey_version_id)
            rows = list(_local_store.get(key, []))
            if families:
                rows = [r for r in rows if r.get("activity_family") in families]
            if statuses:
                rows = [r for r in rows if r.get("activity_status") in statuses]
            if session_id:
                rows = [r for r in rows if r.get("session_id") == session_id]
            if wallet_id:
                rows = [r for r in rows if r.get("wallet_id") == wallet_id]
            if chain_id:
                rows = [r for r in rows if r.get("chain_id") == chain_id]
            if campaign_id:
                rows = [r for r in rows if r.get("campaign_id") == campaign_id]
            if after:
                rows = [r for r in rows if (r.get("occurred_at") or "") > _ts_str(after)]
            if before:
                rows = [r for r in rows if (r.get("occurred_at") or "") < _ts_str(before)]
            rows.sort(key=lambda r: r.get("step_position", 0))
            if cursor is not None:
                pos = _decode_pos_cursor(cursor)
                rows = [r for r in rows if r.get("step_position", 0) > pos]
            return rows[:limit]

        conditions = ["tenant_id = $1", "journey_version_id = $2::uuid"]
        params: list[Any] = [tenant_id, journey_version_id]
        p = 3

        if families:
            conditions.append(f"activity_family = ANY(${p}::text[])")
            params.append(families)
            p += 1
        if statuses:
            conditions.append(f"activity_status = ANY(${p}::text[])")
            params.append(statuses)
            p += 1
        if session_id:
            conditions.append(f"session_id = ${p}")
            params.append(session_id)
            p += 1
        if wallet_id:
            conditions.append(f"wallet_id = ${p}")
            params.append(wallet_id)
            p += 1
        if chain_id:
            conditions.append(f"chain_id = ${p}")
            params.append(chain_id)
            p += 1
        if campaign_id:
            conditions.append(f"campaign_id = ${p}")
            params.append(campaign_id)
            p += 1
        if after:
            conditions.append(f"occurred_at > ${p}")
            params.append(after)
            p += 1
        if before:
            conditions.append(f"occurred_at < ${p}")
            params.append(before)
            p += 1
        if cursor is not None:
            pos = _decode_pos_cursor(cursor)
            conditions.append(f"step_position > ${p}")
            params.append(pos)
            p += 1

        params.append(limit)
        sql = f"""
            SELECT * FROM journey_steps
            WHERE {' AND '.join(conditions)}
            ORDER BY step_position ASC
            LIMIT ${p}
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def get_step(
        self,
        tenant_id: str,
        step_id: str,
    ) -> Optional[dict[str, Any]]:
        pool = await self._pool()

        if pool is None:
            for version_steps in _local_store.values():
                for step in version_steps:
                    if (step.get("tenant_id") == tenant_id
                            and str(step.get("step_id")) == step_id):
                        return step
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM journey_steps WHERE tenant_id=$1 AND step_id=$2::uuid",
                tenant_id, step_id,
            )
        return dict(row) if row else None

    async def get_adjacent(
        self,
        tenant_id: str,
        step_id: str,
    ) -> dict[str, Any]:
        """Return the previous and next steps relative to a given step."""
        step = await self.get_step(tenant_id, step_id)
        if step is None:
            return {"previous": None, "next": None}

        jvid = str(step.get("journey_version_id"))
        pos = step.get("step_position", 0)
        pool = await self._pool()

        if pool is None:
            key = _version_key(tenant_id, jvid)
            all_steps = _local_store.get(key, [])
            prev = next((s for s in reversed(all_steps) if s.get("step_position", 0) < pos), None)
            nxt = next((s for s in all_steps if s.get("step_position", 0) > pos), None)
            return {"previous": prev, "next": nxt}

        async with pool.acquire() as conn:
            prev_row = await conn.fetchrow(
                """
                SELECT * FROM journey_steps
                WHERE tenant_id=$1 AND journey_version_id=$2::uuid AND step_position < $3
                ORDER BY step_position DESC LIMIT 1
                """,
                tenant_id, jvid, pos,
            )
            next_row = await conn.fetchrow(
                """
                SELECT * FROM journey_steps
                WHERE tenant_id=$1 AND journey_version_id=$2::uuid AND step_position > $3
                ORDER BY step_position ASC LIMIT 1
                """,
                tenant_id, jvid, pos,
            )
        return {
            "previous": dict(prev_row) if prev_row else None,
            "next": dict(next_row) if next_row else None,
        }

    async def count_by_version(self, tenant_id: str, journey_version_id: str) -> int:
        pool = await self._pool()

        if pool is None:
            key = _version_key(tenant_id, journey_version_id)
            return len(_local_store.get(key, []))

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM journey_steps WHERE tenant_id=$1 AND journey_version_id=$2::uuid",
                tenant_id, journey_version_id,
            )
        return row["n"] if row else 0

    async def update_status_by_activity(
        self,
        tenant_id: str,
        activity_id: str,
        status: str,
    ) -> int:
        """Propagate activity status change to all steps referencing this activity."""
        pool = await self._pool()

        if pool is None:
            count = 0
            for version_steps in _local_store.values():
                for step in version_steps:
                    if (step.get("tenant_id") == tenant_id
                            and str(step.get("activity_id")) == activity_id):
                        step["activity_status"] = status
                        count += 1
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE journey_steps
                SET activity_status = $3
                WHERE tenant_id = $1 AND activity_id = $2::uuid
                """,
                tenant_id, activity_id, status,
            )
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0

    async def update_risk_annotation_for_journey(
        self,
        tenant_id: str,
        journey_id: str,
        annotation: dict[str, Any],
    ) -> int:
        """Write fraud/risk annotation to all steps in a journey (current version)."""
        import json as _json
        from decimal import Decimal

        pool = await self._pool()
        risk_score = annotation.get("risk_score")
        if isinstance(risk_score, float):
            risk_score = round(risk_score, 2)

        if pool is None:
            count = 0
            for version_steps in _local_store.values():
                for step in version_steps:
                    if (step.get("tenant_id") == tenant_id
                            and str(step.get("journey_id")) == str(journey_id)):
                        step.update({
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
                        count += 1
            return count

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE journey_steps SET
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
                WHERE tenant_id = $1 AND journey_id = $2::uuid
                """,
                tenant_id,
                journey_id,
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
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _insert_steps(conn: Any, steps: list[dict[str, Any]]) -> None:
    await conn.executemany(
        """
        INSERT INTO journey_steps (
            step_id, tenant_id, journey_id, journey_version_id,
            profile_id, cluster_id,
            step_position, occurred_at,
            activity_id, activity_family, activity_type,
            transition_type, transition_evidence,
            actor_type, channel, source,
            source_class, referral_mediation_type,
            ai_provider, ai_product, journey_role,
            evidence_confidence, verification_level,
            source_classifier_version, normalized_referrer_domain,
            source_classification_id, attribution_eligible,
            verified_referral_link_id,
            domain, app_id,
            dapp_id, chain_id, campaign_id, conversion_id,
            wallet_id, agent_id, session_id, device_id,
            activity_status,
            identity_confidence, identity_method, identity_version,
            evidence_summary, schema_version
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
            $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
            $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
            $31,$32,$33,$34,$35,$36,$37,$38,$39,$40,
            $41,$42,$43,$44
        )
        ON CONFLICT (tenant_id, journey_version_id, step_position) DO NOTHING
        """,
        [_step_params(step) for step in steps],
    )


def _step_params(s: dict[str, Any]) -> tuple:
    import json
    return (
        _ensure_uuid(s.get("step_id")),
        s.get("tenant_id"),
        _ensure_uuid(s.get("journey_id")),
        _ensure_uuid(s.get("journey_version_id")),
        s.get("profile_id"),
        s.get("cluster_id"),
        s.get("step_position"),
        _parse_ts(s.get("occurred_at")),
        _ensure_uuid(s.get("activity_id")),
        s.get("activity_family"),
        s.get("activity_type"),
        s.get("transition_type"),
        json.dumps(s.get("transition_evidence") or {}),
        s.get("actor_type"),
        s.get("channel"),
        s.get("source"),
        s.get("source_class"),
        s.get("referral_mediation_type"),
        s.get("ai_provider"),
        s.get("ai_product"),
        s.get("journey_role"),
        s.get("evidence_confidence"),
        s.get("verification_level"),
        s.get("source_classifier_version"),
        s.get("normalized_referrer_domain"),
        _ensure_optional_uuid(s.get("source_classification_id")),
        s.get("attribution_eligible", True),
        _ensure_optional_uuid(s.get("verified_referral_link_id")),
        s.get("domain"),
        s.get("app_id"),
        s.get("dapp_id"),
        s.get("chain_id"),
        s.get("campaign_id"),
        s.get("conversion_id"),
        s.get("wallet_id"),
        s.get("agent_id"),
        s.get("session_id"),
        s.get("device_id"),
        s.get("activity_status", "observed"),
        s.get("identity_confidence"),
        s.get("identity_method"),
        s.get("identity_version"),
        json.dumps(s.get("evidence_summary") or {}),
        s.get("schema_version", 1),
    )


def _ensure_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return uuid4()
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return uuid4()


def _ensure_optional_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


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


def _decode_pos_cursor(cursor: str) -> int:
    try:
        return int(cursor)
    except (ValueError, TypeError):
        return 0
