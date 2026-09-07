"""Reconciled Control Plane — §16 integration admission records (Phase 3).

Direct-SQL repository over the table created by the ``20260906_rcp_admission.py``
alembic migration (the migration lands ``SCHEMA_SQL`` verbatim — string-
identical, mirroring the Phase-1 ``change_sets_repository`` and Phase-2
``execution_records_repository``).

An ``admission_records`` row is the durable §16 lifecycle fact for one (tenant,
env, managed integration): where it is in the admission walk (discover ->
understand -> classify -> reconcile_source_authority -> authorize -> simulate
-> approve -> compile -> activate -> observe) and where it is in the
continuous lifecycle (monitor -> drift -> reconcile -> change / review /
suspend / revoke) once admission ends. Per CP-03 ("discovery never equals
authorization") the record is a *lifecycle fact, never an enablement*: nothing
in this module flips a provider connection or grants runtime capability —
``active`` only records that the §16 walk reached ``activate``. Stage *moves*
are vocabulary-checked here and legality-checked by the §16 engine
(``admission.py``); unknown values fail closed with a §16-citing ValueError.

The repository keeps the module-local in-memory fallback (``get_pool()`` None
under ``AETHER_ENV=local``), so unit tests exercise the same columnar path the
engine uses without a live Postgres. Tenancy is always carried in the WHERE
clause — no cross-tenant read is possible through these APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field
from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    ADMISSION_STAGES,
    CONTINUOUS_LIFECYCLE_ACTIONS,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_admission.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admission_records (
    admission_id TEXT PRIMARY KEY,
    managed_integration_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    integration_kind TEXT NOT NULL,
    source_origin TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT 'discover',
    lifecycle_state TEXT NOT NULL DEFAULT 'monitor',
    active BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_admission_integration
    ON admission_records (tenant_id, environment_id, managed_integration_ref);
"""

# Module-local in-memory backing store, shared by every repository instance.
# Keys are the row's primary key (mirrors change_sets_repository.py /
# execution_records_repository.py).
_ADMISSION_STORE: dict[str, dict] = {}


def reset_admission_record_stores() -> None:
    """Test helper: empty the module-local admission-record store."""
    _ADMISSION_STORE.clear()


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


def _rowcount(result: Any) -> int:
    """Asyncpg ``pool.execute`` returns a command-status *string* — parse the
    trailing count like every other repo."""
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


class AdmissionRecordView(BaseModel):
    """The typed storage view for one §16 admission record.

    ``current_stage``/``lifecycle_state`` default to the §16 entry position
    (``discover``/``monitor``); ``created_at``/``updated_at`` are Optional so a
    caller may leave them to the DDL defaults — the §16 engine always stamps
    both explicitly (deterministic, evidence-bearing).
    """

    admission_id: str
    managed_integration_ref: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    source_ref: str = Field(..., min_length=1)
    integration_kind: str = Field(..., min_length=1)
    source_origin: str
    current_stage: str = "discover"
    lifecycle_state: str = "monitor"
    active: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _admission_row(row: dict) -> dict:
    row = dict(row)
    row["created_at"] = _iso(row.get("created_at"))
    row["updated_at"] = _iso(row.get("updated_at"))
    return row


class AdmissionRecordRepository:
    """Tenant-scoped durable §16 admission-record store (lifecycle facts)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        return _ADMISSION_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── write ─────────────────────────────────────────────────────────────

    async def create(self, view: AdmissionRecordView) -> dict:
        """Persist one admission record (plain INSERT, values verbatim).

        §16 vocabulary is enforced on the row (unknown stage/action tokens
        raise, citing §16); the unique (tenant, env, integration) index is the
        SQL path's guard against duplicate admissions. ``get_or_create`` in the
        engine is the only idempotent way a row should be born. Returned rows
        carry the same canonical isoformat timestamps every other read path
        produces (``_admission_row``), so created and updated rows never mix
        representations.
        """
        if view.current_stage not in ADMISSION_STAGES:
            raise ValueError(
                f"unknown admission current_stage {view.current_stage!r} (§16)"
            )
        if view.lifecycle_state not in CONTINUOUS_LIFECYCLE_ACTIONS:
            raise ValueError(
                f"unknown admission lifecycle_state {view.lifecycle_state!r} (§16)"
            )
        row = _admission_row(view.model_dump(mode="json"))
        pool = await self._ensure()
        if pool is None:
            self._store[view.admission_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO admission_records (admission_id, "
            "managed_integration_ref, tenant_id, environment_id, source_ref, "
            "integration_kind, source_origin, current_stage, lifecycle_state, "
            "active, created_at, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
            view.admission_id, view.managed_integration_ref, view.tenant_id,
            view.environment_id, view.source_ref, view.integration_kind,
            view.source_origin, view.current_stage, view.lifecycle_state,
            view.active, view.created_at, view.updated_at,
        )
        return row

    async def update_stage(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        admission_id: str,
        current_stage: str,
        lifecycle_state: Optional[str] = None,
        active: Optional[bool] = None,
        at: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Move one admission record's §16 position; stamps ``updated_at``.

        Vocabulary (not legality) is enforced here — a move to any §16 stage /
        continuous action token persists, and transition *legality* is enforced
        by the engine (``admission.validate_stage_move`` /
        ``validate_lifecycle_move``) before a caller persists a move. Returns
        the updated row, or None when no row matches the scope (absent /
        cross-tenant / cross-environment).
        """
        if current_stage not in ADMISSION_STAGES:
            raise ValueError(f"unknown admission current_stage {current_stage!r} (§16)")
        if lifecycle_state is not None and lifecycle_state not in CONTINUOUS_LIFECYCLE_ACTIONS:
            raise ValueError(
                f"unknown admission lifecycle_state {lifecycle_state!r} (§16)"
            )
        at = at or _now()
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(admission_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            row["current_stage"] = current_stage
            if lifecycle_state is not None:
                row["lifecycle_state"] = lifecycle_state
            if active is not None:
                row["active"] = active
            row["updated_at"] = at.isoformat()
            return dict(row)
        result = await pool.execute(
            "UPDATE admission_records SET current_stage=$4, "
            "lifecycle_state=COALESCE($5, lifecycle_state), "
            "active=COALESCE($6, active), updated_at=$7 "
            "WHERE tenant_id=$1 AND environment_id=$2 AND admission_id=$3",
            tenant_id, environment_id, admission_id, current_stage,
            lifecycle_state, active, at,
        )
        if _rowcount(result) == 0:
            return None
        record = await pool.fetchrow(
            "SELECT * FROM admission_records WHERE admission_id=$1",
            admission_id,
        )
        return _admission_row(dict(record)) if record is not None else None

    # ── reads ──────────────────────────────────────────────────────────────

    async def get(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        admission_id: str,
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(admission_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM admission_records "
            "WHERE tenant_id=$1 AND environment_id=$2 AND admission_id=$3",
            tenant_id, environment_id, admission_id,
        )
        return _admission_row(dict(record)) if record is not None else None

    async def get_for_integration(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        managed_integration_ref: str,
    ) -> Optional[dict]:
        """The one admission record for an integration (unique index-backed)."""
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
                matches, key=lambda r: r.get("updated_at") or "", reverse=True
            )[0]
            return dict(newest)
        record = await pool.fetchrow(
            "SELECT * FROM admission_records "
            "WHERE tenant_id=$1 AND environment_id=$2 AND "
            "managed_integration_ref=$3",
            tenant_id, environment_id, managed_integration_ref,
        )
        return _admission_row(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        stage: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Admission records, newest-``updated_at`` first.

        With no tenant scope this is the operator-aggregate read (mirroring
        ``ManagedIntegrationRepository.get_by_key``); every scoped read keeps
        tenancy in the WHERE clause.
        """
        if stage is not None and stage not in ADMISSION_STAGES:
            raise ValueError(f"unknown admission current_stage {stage!r} (§16)")
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if (tenant_id is None or r.get("tenant_id") == tenant_id)
                and (environment_id is None or r.get("environment_id") == environment_id)
                and (stage is None or r.get("current_stage") == stage)
            ]
            rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        where: list[str] = []
        args: list[Any] = []
        for column, value in (
            ("tenant_id", tenant_id),
            ("environment_id", environment_id),
            ("current_stage", stage),
        ):
            if value is not None:
                args.append(value)
                where.append(f"{column} = ${len(args)}")
        sql_where = f"WHERE {' AND '.join(where)}" if where else ""
        args.append(limit)
        records = await pool.fetch(
            f"SELECT * FROM admission_records {sql_where} "
            f"ORDER BY updated_at DESC LIMIT ${len(args)}",
            *args,
        )
        return [_admission_row(dict(r)) for r in records]


# ── module singleton ─────────────────────────────────────────────────────────

_admission_repo: Optional[AdmissionRecordRepository] = None


def get_admission_record_repository() -> AdmissionRecordRepository:
    global _admission_repo
    if _admission_repo is None:
        _admission_repo = AdmissionRecordRepository()
    return _admission_repo
