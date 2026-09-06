"""Reconciled Control Plane — durable execution records (Phase 2).

Direct-SQL repositories over the tables created by the
``20260906_rcp_execution.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring
``services/data_exchange/saved_mappings.py`` and the Phase-1
``change_sets_repository``).

These stores record what a ChangeSet did while it moved through the §34
executor — evidence first, never fabricated:

* ``ChangeSetEventRepository`` — append-only status history (§34 transitions).
* ``ChangeEvidenceRepository`` — one row per executed/attempted change
  (§32 step 22 / §12.13), with the §12.15 epistemic claim type.
* ``LastKnownGoodRepository`` — durable LKG (§32 step 21 / §12.12); a later
  establishment atomically replaces the prior one for the same integration.
* ``ChangeSetRollbackRepository`` — §12.11 rollback records.
* ``ChangeSetApprovalRepository`` — §21 role-gated approvals (§12.13
  ``approval_refs`` point here).
* ``ActionRequiredRepository`` — unresolved changes surfaced for action
  (§32 step 23 / §12.14).

Every repository keeps the module-local in-memory fallback (``get_pool()``
None under ``AETHER_ENV=local``), so unit tests exercise the same columnar path
the executor uses without a live Postgres. Tenancy is always carried in the
WHERE clause — no cross-tenant read is possible through these APIs.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    ACTION_REQUIRED_STATUSES,
    ActionRequiredView,
    ChangeEvidenceView,
    ChangeSetApprovalView,
    LastKnownGoodView,
    ROLLBACK_STATUSES,
    RollbackRecordView,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_execution.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS before_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS target_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS rollback_ref TEXT;

CREATE TABLE IF NOT EXISTS change_set_events (
    event_id TEXT PRIMARY KEY,
    changeset_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_change_set_events_changeset
    ON change_set_events (changeset_id, occurred_at);

CREATE TABLE IF NOT EXISTS change_evidence (
    change_evidence_id TEXT PRIMARY KEY,
    changeset_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    initiator TEXT NOT NULL,
    policy_ref TEXT,
    before_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    after_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT,
    claim_type TEXT NOT NULL,
    confidence TEXT NOT NULL,
    risk_ref TEXT,
    simulation_ref TEXT,
    rollout_ref TEXT,
    validation_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    approval_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    rollback_ref TEXT,
    tenant_action_required BOOLEAN NOT NULL DEFAULT false,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    contradictory_evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_change_evidence_changeset
    ON change_evidence (changeset_ref);

CREATE TABLE IF NOT EXISTS last_known_good (
    lkg_id TEXT PRIMARY KEY,
    managed_integration_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    desired_state_ref TEXT,
    artifact_ref TEXT,
    runtime_config_ref TEXT,
    schema_ref TEXT,
    mapping_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    integration_contract_ref TEXT,
    policy_ref TEXT,
    provider_state_ref TEXT,
    verified_health_ref TEXT,
    established_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_last_known_good_integration
    ON last_known_good (tenant_id, environment_id, managed_integration_ref);

CREATE TABLE IF NOT EXISTS change_set_rollbacks (
    rollback_id TEXT PRIMARY KEY,
    changeset_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    last_known_good_ref TEXT,
    rollback_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    queue_recovery_policy TEXT,
    replay_policy TEXT,
    validation_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_change_set_rollbacks_changeset
    ON change_set_rollbacks (changeset_ref);

CREATE TABLE IF NOT EXISTS change_set_approvals (
    approval_id TEXT PRIMARY KEY,
    changeset_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    required_approval_ref TEXT NOT NULL,
    granted_role TEXT NOT NULL,
    granted_by_actor TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'approved',
    note TEXT,
    decided_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_change_set_approvals_changeset
    ON change_set_approvals (changeset_ref);

CREATE TABLE IF NOT EXISTS action_required (
    action_id TEXT PRIMARY KEY,
    tenant_ref TEXT NOT NULL,
    managed_integration_ref TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    impact TEXT,
    deadline TIMESTAMPTZ,
    required_actor TEXT NOT NULL,
    required_action TEXT NOT NULL,
    continuity_state TEXT,
    data_loss_expected BOOLEAN NOT NULL DEFAULT false,
    resolution_ref TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_action_required_status
    ON action_required (status);
"""

# Module-local in-memory backing stores, shared by every repository instance.
# Keys are the row's primary key (mirrors services/data_exchange/saved_mappings.py).
_EVENT_STORE: dict[str, dict] = {}
_EVIDENCE_STORE: dict[str, dict] = {}
_LKG_STORE: dict[str, dict] = {}
_ROLLBACK_STORE: dict[str, dict] = {}
_APPROVAL_STORE: dict[str, dict] = {}
_ACTION_STORE: dict[str, dict] = {}


def reset_execution_record_stores() -> None:
    """Test helper: empty every module-local execution-record store."""
    _EVENT_STORE.clear()
    _EVIDENCE_STORE.clear()
    _LKG_STORE.clear()
    _ROLLBACK_STORE.clear()
    _APPROVAL_STORE.clear()
    _ACTION_STORE.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        return coerce_utc_lenient(raw) or raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _iso(raw: Any) -> Optional[str]:
    dt = _parse_ts(raw)
    return dt.isoformat() if dt is not None else None


def _parse_json(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return _json.loads(value)
        except ValueError:
            return {}
    return value


def _rowcount(result: Any) -> int:
    """Asyncpg ``pool.execute`` returns a command-status *string* — parse the
    trailing count like every other repo."""
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


class _ExecutionRepo:
    """Shared pool/ensure plumbing for the execution-record repositories."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool


# ── §34 append-only status history ───────────────────────────────────────────


class ChangeSetEventRepository(_ExecutionRepo):
    """Append-only ChangeSet status-history (§34 transitions)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _EVENT_STORE

    async def append(
        self,
        *,
        event_id: str,
        changeset_id: str,
        tenant_id: str,
        environment_id: str,
        to_status: str,
        from_status: Optional[str] = None,
        actor: str = "executor",
        reason: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> dict:
        at = occurred_at or _now()
        row = {
            "event_id": event_id,
            "changeset_id": changeset_id,
            "tenant_id": tenant_id,
            "environment_id": environment_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor": actor,
            "reason": reason,
            "occurred_at": at.isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[event_id] = dict(row)
        else:
            await pool.execute(
                "INSERT INTO change_set_events (event_id, changeset_id, "
                "tenant_id, environment_id, from_status, to_status, actor, "
                "reason, occurred_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                event_id, changeset_id, tenant_id, environment_id,
                from_status, to_status, actor, reason, at,
            )
        return row

    async def list_for_changeset(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        changeset_id: str,
        limit: int = 200,
    ) -> list[dict]:
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("changeset_id") == changeset_id
                and r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
            ]
            rows.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
            return [_iso_row(r) for r in rows[:limit]]
        records = await pool.fetch(
            "SELECT event_id, changeset_id, tenant_id, environment_id, "
            "from_status, to_status, actor, reason, occurred_at "
            "FROM change_set_events "
            "WHERE tenant_id=$1 AND environment_id=$2 AND changeset_id=$3 "
            "ORDER BY occurred_at DESC LIMIT $4",
            tenant_id, environment_id, changeset_id, limit,
        )
        return [_iso_row(dict(r)) for r in records]


def _iso_row(row: dict) -> dict:
    row = dict(row)
    row["occurred_at"] = _iso(row.get("occurred_at"))
    return row


# ── §12.13 change evidence ───────────────────────────────────────────────────


class ChangeEvidenceRepository(_ExecutionRepo):
    """One row per executed/attempted change (§32 step 22 / §12.13)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _EVIDENCE_STORE

    async def create(self, view: ChangeEvidenceView) -> dict:
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.change_evidence_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO change_evidence (change_evidence_id, changeset_ref, "
            "tenant_id, environment_id, initiator, policy_ref, "
            "before_state_refs, after_state_refs, reason, claim_type, "
            "confidence, risk_ref, simulation_ref, rollout_ref, "
            "validation_refs, approval_refs, rollback_ref, "
            "tenant_action_required, evidence_refs, "
            "contradictory_evidence_refs, started_at, completed_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,"
            "$13,$14,$15::jsonb,$16::jsonb,$17,$18,$19::jsonb,$20::jsonb,"
            "$21,$22)",
            view.change_evidence_id, view.changeset_ref, view.tenant_id,
            view.environment_id, view.initiator, view.policy_ref,
            _json.dumps(view.before_state_refs), _json.dumps(view.after_state_refs),
            view.reason, view.claim_type, view.confidence, view.risk_ref,
            view.simulation_ref, view.rollout_ref,
            _json.dumps(view.validation_refs), _json.dumps(view.approval_refs),
            view.rollback_ref, view.tenant_action_required,
            _json.dumps(view.evidence_refs),
            _json.dumps(view.contradictory_evidence_refs),
            view.started_at, view.completed_at,
        )
        return row

    async def get(
        self, tenant_id: str, environment_id: str, change_evidence_id: str
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(change_evidence_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM change_evidence "
            "WHERE tenant_id=$1 AND environment_id=$2 AND "
            "change_evidence_id=$3",
            tenant_id, environment_id, change_evidence_id,
        )
        return _evidence_row(dict(record)) if record is not None else None

    async def list_for_changeset(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        changeset_ref: str,
        limit: int = 200,
    ) -> list[dict]:
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("changeset_ref") == changeset_ref
                and r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
            ]
            rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        records = await pool.fetch(
            "SELECT * FROM change_evidence "
            "WHERE tenant_id=$1 AND environment_id=$2 AND changeset_ref=$3 "
            "ORDER BY started_at DESC LIMIT $4",
            tenant_id, environment_id, changeset_ref, limit,
        )
        return [_evidence_row(dict(r)) for r in records]


def _evidence_row(row: dict) -> dict:
    row = dict(row)
    for col in (
        "before_state_refs", "after_state_refs", "validation_refs",
        "approval_refs", "evidence_refs", "contradictory_evidence_refs",
    ):
        row[col] = _parse_json(row.get(col))
    row["started_at"] = _iso(row.get("started_at"))
    row["completed_at"] = _iso(row.get("completed_at"))
    return row


# ── §12.12 last-known-good ───────────────────────────────────────────────────


class LastKnownGoodRepository(_ExecutionRepo):
    """Durable LKG per (tenant, env, integration) — replace-on-establish."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _LKG_STORE

    async def establish(self, view: LastKnownGoodView) -> dict:
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            # One LKG per integration: establishing a newer LKG replaces the
            # prior row (mirrors the SQL unique index semantics).
            for existing_id, existing in list(self._store.items()):
                if (
                    existing.get("tenant_id") == view.tenant_id
                    and existing.get("environment_id") == view.environment_id
                    and existing.get("managed_integration_ref")
                    == view.managed_integration_ref
                ):
                    del self._store[existing_id]
            self._store[view.lkg_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO last_known_good (lkg_id, managed_integration_ref, "
            "tenant_id, environment_id, desired_state_ref, artifact_ref, "
            "runtime_config_ref, schema_ref, mapping_refs, "
            "integration_contract_ref, policy_ref, provider_state_ref, "
            "verified_health_ref, established_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14) "
            "ON CONFLICT (tenant_id, environment_id, managed_integration_ref) "
            "DO UPDATE SET lkg_id=EXCLUDED.lkg_id, desired_state_ref="
            "EXCLUDED.desired_state_ref, artifact_ref=EXCLUDED.artifact_ref, "
            "runtime_config_ref=EXCLUDED.runtime_config_ref, "
            "schema_ref=EXCLUDED.schema_ref, mapping_refs=EXCLUDED.mapping_refs, "
            "integration_contract_ref=EXCLUDED.integration_contract_ref, "
            "policy_ref=EXCLUDED.policy_ref, "
            "provider_state_ref=EXCLUDED.provider_state_ref, "
            "verified_health_ref=EXCLUDED.verified_health_ref, "
            "established_at=EXCLUDED.established_at",
            view.lkg_id, view.managed_integration_ref, view.tenant_id,
            view.environment_id, view.desired_state_ref, view.artifact_ref,
            view.runtime_config_ref, view.schema_ref,
            _json.dumps(view.mapping_refs), view.integration_contract_ref,
            view.policy_ref, view.provider_state_ref, view.verified_health_ref,
            view.established_at,
        )
        return row

    async def get_for_integration(
        self, tenant_id: str, environment_id: str, managed_integration_ref: str
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            matches = [
                r
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
                and r.get("managed_integration_ref") == managed_integration_ref
            ]
            if not matches:
                return None
            newest = sorted(
                matches, key=lambda r: r.get("established_at") or "", reverse=True
            )[0]
            return dict(newest)
        record = await pool.fetchrow(
            "SELECT * FROM last_known_good "
            "WHERE tenant_id=$1 AND environment_id=$2 AND "
            "managed_integration_ref=$3",
            tenant_id, environment_id, managed_integration_ref,
        )
        return _lkg_row(dict(record)) if record is not None else None


def _lkg_row(row: dict) -> dict:
    row = dict(row)
    row["mapping_refs"] = _parse_json(row.get("mapping_refs"))
    row["established_at"] = _iso(row.get("established_at"))
    return row


# ── §12.11 change-set rollbacks ──────────────────────────────────────────────


class ChangeSetRollbackRepository(_ExecutionRepo):
    """Rollback records (§32 steps 20-21 / §12.11)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _ROLLBACK_STORE

    async def create(self, view: RollbackRecordView) -> dict:
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.rollback_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO change_set_rollbacks (rollback_id, changeset_ref, "
            "tenant_id, environment_id, last_known_good_ref, "
            "rollback_actions, queue_recovery_policy, replay_policy, "
            "validation_requirements, status, created_at, completed_at) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9::jsonb,$10,$11,$12)",
            view.rollback_id, view.changeset_ref, view.tenant_id,
            view.environment_id, view.last_known_good_ref,
            _json.dumps(view.rollback_actions), view.queue_recovery_policy,
            view.replay_policy, _json.dumps(view.validation_requirements),
            view.status, view.created_at, view.completed_at,
        )
        return row

    async def update_status(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        rollback_id: str,
        status: str,
        completed_at: Optional[datetime] = None,
    ) -> Optional[dict]:
        if status not in ROLLBACK_STATUSES:
            raise ValueError(f"unknown rollback status {status!r} (§12.11)")
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(rollback_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            row["status"] = status
            if completed_at is not None or status == "rolled_back":
                row["completed_at"] = (completed_at or _now()).isoformat()
            return dict(row)
        effective = completed_at or (
            _now() if status == "rolled_back" else None
        )
        result = await pool.execute(
            "UPDATE change_set_rollbacks SET status=$4, completed_at=$5 "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollback_id=$3",
            tenant_id, environment_id, rollback_id, status, effective,
        )
        if _rowcount(result) == 0:
            return None
        record = await pool.fetchrow(
            "SELECT * FROM change_set_rollbacks WHERE rollback_id=$1",
            rollback_id,
        )
        return _rollback_row(dict(record)) if record is not None else None

    async def get_for_changeset(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        changeset_ref: str,
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            matches = [
                r
                for r in self._store.values()
                if r.get("changeset_ref") == changeset_ref
                and r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
            ]
            if not matches:
                return None
            return dict(matches[0])
        record = await pool.fetchrow(
            "SELECT * FROM change_set_rollbacks "
            "WHERE tenant_id=$1 AND environment_id=$2 AND changeset_ref=$3",
            tenant_id, environment_id, changeset_ref,
        )
        return _rollback_row(dict(record)) if record is not None else None


def _rollback_row(row: dict) -> dict:
    row = dict(row)
    row["rollback_actions"] = _parse_json(row.get("rollback_actions"))
    row["validation_requirements"] = _parse_json(
        row.get("validation_requirements")
    )
    row["created_at"] = _iso(row.get("created_at"))
    row["completed_at"] = _iso(row.get("completed_at"))
    return row


# ── §21 change-set approvals ─────────────────────────────────────────────────


class ChangeSetApprovalRepository(_ExecutionRepo):
    """Durable §21 role-gated approvals for a ChangeSet."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _APPROVAL_STORE

    async def create(self, view: ChangeSetApprovalView) -> dict:
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.approval_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO change_set_approvals (approval_id, changeset_ref, "
            "tenant_id, environment_id, required_approval_ref, granted_role, "
            "granted_by_actor, decision, note, decided_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            view.approval_id, view.changeset_ref, view.tenant_id,
            view.environment_id, view.required_approval_ref, view.granted_role,
            view.granted_by_actor, view.decision, view.note, view.decided_at,
        )
        return row

    async def list_for_changeset(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        changeset_ref: str,
        decision: Optional[str] = None,
    ) -> list[dict]:
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("changeset_ref") == changeset_ref
                and r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
                and (decision is None or r.get("decision") == decision)
            ]
            rows.sort(key=lambda r: r.get("decided_at") or "", reverse=True)
            return [dict(r) for r in rows]
        where = "tenant_id=$1 AND environment_id=$2 AND changeset_ref=$3"
        args: list[Any] = [tenant_id, environment_id, changeset_ref]
        if decision is not None:
            args.append(decision)
            where += " AND decision=$4"
        records = await pool.fetch(
            f"SELECT * FROM change_set_approvals WHERE {where} "
            "ORDER BY decided_at DESC",
            *args,
        )
        return [_approval_row(dict(r)) for r in records]


def _approval_row(row: dict) -> dict:
    row = dict(row)
    row["decided_at"] = _iso(row.get("decided_at"))
    return row


# ── §12.14 action required ───────────────────────────────────────────────────


class ActionRequiredRepository(_ExecutionRepo):
    """Unresolved changes surfaced for action (§32 step 23 / §12.14)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _ACTION_STORE

    async def create(self, view: ActionRequiredView) -> dict:
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.action_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO action_required (action_id, tenant_ref, "
            "managed_integration_ref, environment_id, action_type, reason, "
            "impact, deadline, required_actor, required_action, "
            "continuity_state, data_loss_expected, resolution_ref, status, "
            "created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,"
            "$14,$15)",
            view.action_id, view.tenant_ref, view.managed_integration_ref,
            view.environment_id, view.action_type, view.reason, view.impact,
            view.deadline, view.required_actor, view.required_action,
            view.continuity_state, view.data_loss_expected, view.resolution_ref,
            view.status, view.created_at,
        )
        return row

    async def list(
        self,
        *,
        tenant_ref: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        if status is not None and status not in ACTION_REQUIRED_STATUSES:
            raise ValueError(
                f"unknown action-required status {status!r} (§12.14)"
            )
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if (tenant_ref is None or r.get("tenant_ref") == tenant_ref)
                and (status is None or r.get("status") == status)
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        where: list[str] = []
        args: list[Any] = []
        if tenant_ref is not None:
            args.append(tenant_ref)
            where.append(f"tenant_ref = ${len(args)}")
        if status is not None:
            args.append(status)
            where.append(f"status = ${len(args)}")
        sql_where = f"WHERE {' AND '.join(where)}" if where else ""
        args.append(limit)
        records = await pool.fetch(
            f"SELECT * FROM action_required {sql_where} "
            f"ORDER BY created_at DESC LIMIT ${len(args)}",
            *args,
        )
        return [_action_row(dict(r)) for r in records]

    async def resolve(
        self,
        *,
        tenant_ref: str,
        action_id: str,
        resolution_ref: str,
        at: Optional[datetime] = None,
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(action_id)
            # Mirror the SQL guard (WHERE ... AND status='open'): an absent,
            # cross-tenant, or already-resolved row resolves to None.
            if (
                row is None
                or row.get("tenant_ref") != tenant_ref
                or row.get("status") != "open"
            ):
                return None
            row["status"] = "resolved"
            row["resolution_ref"] = resolution_ref
            return dict(row)
        result = await pool.execute(
            "UPDATE action_required SET status='resolved', resolution_ref=$3 "
            "WHERE tenant_ref=$1 AND action_id=$2 AND status='open'",
            tenant_ref, action_id, resolution_ref,
        )
        if _rowcount(result) == 0:
            return None
        record = await pool.fetchrow(
            "SELECT * FROM action_required WHERE action_id=$1", action_id
        )
        return _action_row(dict(record)) if record is not None else None


def _action_row(row: dict) -> dict:
    row = dict(row)
    row["deadline"] = _iso(row.get("deadline"))
    row["created_at"] = _iso(row.get("created_at"))
    return row


# ── module singletons ────────────────────────────────────────────────────────

_event_repo: Optional[ChangeSetEventRepository] = None
_evidence_repo: Optional[ChangeEvidenceRepository] = None
_lkg_repo: Optional[LastKnownGoodRepository] = None
_rollback_repo: Optional[ChangeSetRollbackRepository] = None
_approval_repo: Optional[ChangeSetApprovalRepository] = None
_action_repo: Optional[ActionRequiredRepository] = None


def get_change_set_event_repository() -> ChangeSetEventRepository:
    global _event_repo
    if _event_repo is None:
        _event_repo = ChangeSetEventRepository()
    return _event_repo


def get_change_evidence_repository() -> ChangeEvidenceRepository:
    global _evidence_repo
    if _evidence_repo is None:
        _evidence_repo = ChangeEvidenceRepository()
    return _evidence_repo


def get_last_known_good_repository() -> LastKnownGoodRepository:
    global _lkg_repo
    if _lkg_repo is None:
        _lkg_repo = LastKnownGoodRepository()
    return _lkg_repo


def get_change_set_rollback_repository() -> ChangeSetRollbackRepository:
    global _rollback_repo
    if _rollback_repo is None:
        _rollback_repo = ChangeSetRollbackRepository()
    return _rollback_repo


def get_change_set_approval_repository() -> ChangeSetApprovalRepository:
    global _approval_repo
    if _approval_repo is None:
        _approval_repo = ChangeSetApprovalRepository()
    return _approval_repo


def get_action_required_repository() -> ActionRequiredRepository:
    global _action_repo
    if _action_repo is None:
        _action_repo = ActionRequiredRepository()
    return _action_repo
