"""Reconciled Control Plane — durable ChangeSet plans (Phase 1).

Direct-SQL repository over the ``change_sets`` table created by the
``20260906_rcp_change_sets.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring
``services/data_exchange/saved_mappings.py``).

A ``change_sets`` row is a **candidate** plan (blueprint §32 step 12): it
carries the §35 guard revisions, the typed ``changes``, the §32-13 blast
radius, the §39 risk assessment and the §34 ``status``. Phase-1 rows reach at
most ``planned`` — nothing here is ever executed (the actuator engine is a
later phase). ``update_status`` enforces the §34 vocabulary; transition
*legality* is enforced by ``change_planning.with_status`` before a caller
persists a move (illegal transitions fail closed).

Tenancy is always carried in the WHERE clause — no cross-tenant read is
possible through this API (``get_by_key`` is the operator-aggregate exception,
mirroring ``ManagedIntegrationRepository.get_by_key``). The repository keeps
the module-local in-memory fallback (``get_pool()`` None under
``AETHER_ENV=local``), so unit tests exercise the same columnar path the
operator surface uses without a live Postgres.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    ChangeSetPlanView,
    CHANGESET_STATUSES,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_change_sets.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS change_sets (
    changeset_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    integration_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
    desired_revision TEXT NOT NULL,
    observed_revision TEXT NOT NULL,
    reconcile_sequence TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT,
    initiator TEXT NOT NULL,
    policy_ref TEXT,
    risk JSONB NOT NULL DEFAULT '{}'::jsonb,
    blast_radius JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_change_sets_tenant_env_status
    ON change_sets (tenant_id, environment_id, status);
CREATE INDEX IF NOT EXISTS ix_change_sets_idempotency
    ON change_sets (tenant_id, idempotency_key);
"""

# Module-local in-memory backing store, shared by every repository instance
# (mirrors services/data_exchange/saved_mappings.py).
_CHANGE_SET_STORE: dict[str, dict] = {}  # changeset_id -> row


def reset_change_set_in_memory_store() -> None:
    """Test helper: empty the module-local in-memory ChangeSet store."""
    _CHANGE_SET_STORE.clear()


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


_CHANGE_SET_COLUMNS = (
    "changeset_id, tenant_id, environment_id, integration_scope, "
    "desired_revision, observed_revision, reconcile_sequence, idempotency_key, "
    "changes, reason, initiator, policy_ref, risk, blast_radius, status, "
    "created_at, superseded_at"
)


def _cs_from(row: dict) -> dict:
    """Row → operator view dict (the ``ChangeSetPlanView`` field shape).

    JSONB columns round-trip as their parsed objects on both the SQL and
    in-memory paths (in-memory rows keep the same columnar keys, so there is no
    drift between the two).
    """
    return {
        "changeset_id": row.get("changeset_id"),
        "tenant_id": row.get("tenant_id"),
        "environment_id": row.get("environment_id"),
        "integration_scope": _parse_json(row.get("integration_scope")),
        "desired_revision": row.get("desired_revision"),
        "observed_revision": row.get("observed_revision"),
        "reconcile_sequence": row.get("reconcile_sequence"),
        "idempotency_key": row.get("idempotency_key"),
        "changes": _parse_json(row.get("changes")),
        "reason": row.get("reason"),
        "initiator": row.get("initiator"),
        "policy_ref": row.get("policy_ref"),
        "risk": _parse_json(row.get("risk")),
        "blast_radius": _parse_json(row.get("blast_radius")),
        "status": row.get("status") or "draft",
        "created_at": _iso(row.get("created_at")),
        "superseded_at": _iso(row.get("superseded_at")),
    }


class ChangeSetRepository:
    """Tenant-scoped durable ``change_sets`` store (candidate plans)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        return _CHANGE_SET_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── write ─────────────────────────────────────────────────────────────

    async def create(self, view: ChangeSetPlanView) -> dict:
        """Persist one ChangeSet plan (candidate — never executed in Phase 1)."""
        pool = await self._ensure()
        row = {
            "changeset_id": view.changeset_id,
            "tenant_id": view.tenant_id,
            "environment_id": view.environment_id,
            "integration_scope": view.integration_scope,
            "desired_revision": view.desired_revision,
            "observed_revision": view.observed_revision,
            "reconcile_sequence": view.reconcile_sequence,
            "idempotency_key": view.idempotency_key,
            "changes": [c.model_dump(mode="json") for c in view.changes],
            "reason": view.reason,
            "initiator": view.initiator,
            "policy_ref": view.policy_ref,
            "risk": view.risk.model_dump(mode="json"),
            "blast_radius": view.blast_radius.model_dump(mode="json"),
            "status": view.status,
            "created_at": view.created_at.isoformat(),
            "superseded_at": _iso(view.superseded_at),
        }
        if pool is None:
            self._store[view.changeset_id] = dict(row)
        else:
            await pool.execute(
                "INSERT INTO change_sets (changeset_id, tenant_id, "
                "environment_id, integration_scope, desired_revision, "
                "observed_revision, reconcile_sequence, idempotency_key, "
                "changes, reason, initiator, policy_ref, risk, blast_radius, "
                "status, created_at, superseded_at) "
                "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,"
                "$13::jsonb,$14::jsonb,$15,$16,$17)",
                view.changeset_id,
                view.tenant_id,
                view.environment_id,
                _json.dumps(view.integration_scope),
                view.desired_revision,
                view.observed_revision,
                view.reconcile_sequence,
                view.idempotency_key,
                _json.dumps(row["changes"], default=str),
                view.reason,
                view.initiator,
                view.policy_ref,
                _json.dumps(row["risk"], default=str),
                _json.dumps(row["blast_radius"], default=str),
                view.status,
                view.created_at,
                _parse_ts(row["superseded_at"]),
            )
        return _cs_from(row)

    async def update_status(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        changeset_id: str,
        status: str,
        superseded_at: Optional[datetime] = None,
        at: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Move a plan to ``status`` (False-when-absent; returns updated row).

        Only the §34 vocabulary is enforced here; transition *legality* is
        enforced by ``change_planning.with_status`` before a caller persists a
        move. Returns None when no row matches the scope.
        """
        if status not in CHANGESET_STATUSES:
            raise ValueError(f"unknown ChangeSet status {status!r} (§34 vocabulary)")
        at = at or _now()
        # The superseded stamp honours an explicit superseded_at; otherwise a
        # move *to* superseded stamps now and any other move preserves the row's
        # existing stamp (a re-supersede is impossible — superseded is terminal).
        effective_superseded_at = (
            superseded_at
            if superseded_at is not None
            else (at if status == "superseded" else None)
        )
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(changeset_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            row["status"] = status
            if effective_superseded_at is not None:
                row["superseded_at"] = effective_superseded_at.isoformat()
            return _cs_from(row)
        status_result = await pool.execute(
            "UPDATE change_sets SET status=$4, "
            "superseded_at=CASE WHEN $5::timestamptz IS NOT NULL THEN $5 "
            "ELSE superseded_at END "
            "WHERE tenant_id=$1 AND environment_id=$2 AND changeset_id=$3",
            tenant_id,
            environment_id,
            changeset_id,
            status,
            effective_superseded_at,
        )
        if _rowcount(status_result) == 0:
            return None
        record = await pool.fetchrow(
            f"SELECT {_CHANGE_SET_COLUMNS} FROM change_sets "
            "WHERE changeset_id = $1",
            changeset_id,
        )
        return _cs_from(dict(record)) if record is not None else None

    # ── reads ─────────────────────────────────────────────────────────────

    async def get(
        self, tenant_id: str, environment_id: str, changeset_id: str
    ) -> Optional[dict]:
        """Return one plan (None when absent); refuses cross-scope reads."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(changeset_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return _cs_from(row)
        record = await pool.fetchrow(
            f"SELECT {_CHANGE_SET_COLUMNS} FROM change_sets "
            "WHERE tenant_id = $1 AND environment_id = $2 AND changeset_id = $3",
            tenant_id,
            environment_id,
            changeset_id,
        )
        return _cs_from(dict(record)) if record is not None else None

    async def get_by_key(self, changeset_id: str) -> Optional[dict]:
        """Return one plan by its global primary key.

        Intended for the *operator aggregate* surface only (a Kyber operator
        exercising ``reconciled_control.read`` may read any tenant's row).
        Tenant-scoped reads should use :meth:`get`, which refuses cross-scope
        rows.
        """
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(changeset_id)
            return _cs_from(dict(row)) if row is not None else None
        record = await pool.fetchrow(
            f"SELECT {_CHANGE_SET_COLUMNS} FROM change_sets "
            "WHERE changeset_id = $1",
            changeset_id,
        )
        return _cs_from(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """ChangeSet plans, newest-created first, optional ANDed filters.

        ``None`` filters are not applied. An operator may scope to one tenant or
        aggregate across tenants (the route owns that authorization decision).
        """
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        pool = await self._ensure()

        def _matches(row: dict) -> bool:
            return (
                (tenant_id is None or row.get("tenant_id") == tenant_id)
                and (
                    environment_id is None
                    or row.get("environment_id") == environment_id
                )
                and (status is None or row.get("status") == status)
            )

        if pool is None:
            rows = [r for r in self._store.values() if _matches(r)]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [_cs_from(r) for r in rows[offset : offset + limit]]

        clauses: list[str] = []
        args: list[Any] = []
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if environment_id is not None:
            args.append(environment_id)
            clauses.append(f"environment_id = ${len(args)}")
        if status is not None:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        args.append(offset)
        records = await pool.fetch(
            f"SELECT {_CHANGE_SET_COLUMNS} FROM change_sets "
            f"{where} ORDER BY created_at DESC LIMIT ${len(args) - 1} "
            f"OFFSET ${len(args)}",
            *args,
        )
        return [_cs_from(dict(r)) for r in records]


_cs_repo: Optional[ChangeSetRepository] = None


def get_change_set_repository() -> ChangeSetRepository:
    """Module singleton mirroring ``get_managed_integration_repository()``."""
    global _cs_repo
    if _cs_repo is None:
        _cs_repo = ChangeSetRepository()
    return _cs_repo
