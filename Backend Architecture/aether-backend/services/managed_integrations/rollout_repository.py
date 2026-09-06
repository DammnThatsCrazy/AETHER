"""Reconciled Control Plane — §40 universal progressive delivery records (Phase 4).

Direct-SQL repository over the ``rollouts`` table created by the
``20260906_rcp_rollouts.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring the Phase-2
``execution_records_repository`` and Phase-3 ``source_authority_repository``).

``rollouts`` is the durable record of one §40 universal progressive-delivery
rollout of a managed artifact kind (§12.8 RolloutContract fields +
coordinator-approved operational ``paused_reason`` / ``end_state`` columns).
The §40 canonical ring sequence is law — ``olympus_internal -> test_tenants ->
1% -> 5% -> 20% -> 50% -> 100%`` — and this repository refuses any stage
transition that skips a ring (§40): a stage index increase must be exactly +1
and a stage index decrease contradicts §40 order (the sole exception is a
rollback marking, ``end_state='rolled_back'``, which is legal from any stage).

This store records delivery facts — it never applies changes and never grants
approvals. Rings above 0% deliver to real tenants only under tenant update
policy + approvals; turning rings on for real traffic sits behind the §41+
review gate, and the rollout engine (§39 R2 canary + health-gated automatic)
is exercised by tests only in Phase 4.

The module keeps the module-local in-memory fallback (``get_pool()`` None
under ``AETHER_ENV=local``), so unit tests exercise the same columnar path the
engine uses without a live Postgres. Tenancy is always carried in the WHERE
clause — no cross-tenant read is possible through these APIs.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    ROLLOUT_ARTIFACT_KINDS,
    ROLLOUT_RINGS,
    is_rollout_artifact_kind,
    is_rollout_ring,
    ring_percentage,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_rollouts.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rollouts (
    rollout_id TEXT PRIMARY KEY,
    changeset_ref TEXT,
    artifact_kind TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'canary',
    cohorts JSONB NOT NULL DEFAULT '[]'::jsonb,   -- cohort ids are rollout ring values (a cohort string "1%" means the 1% cohort)
    current_stage TEXT NOT NULL DEFAULT 'olympus_internal',
    percentage REAL NOT NULL DEFAULT 0.0,
    health_gates JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{axis, operator, threshold}] §12.9 gate config
    advance_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,   -- policy/approval tokens (strings)
    pause_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    rollback_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    paused_reason TEXT NULL,   -- coordinator-approved operational column: §12.9 auto-pause must be durable; NULL = not paused
    end_state TEXT NULL,       -- coordinator-approved terminal column; vocab {'completed','rolled_back'} enforced at update; NULL = in flight
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    last_transition_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rollouts_scope
    ON rollouts (tenant_id, environment_id, artifact_kind, created_at);
"""

# Terminal end states for a §12.8 rollout record (NULL = in flight). Vocab is
# enforced at every write; ``completed`` means the rollout finished at 100%,
# ``rolled_back`` means it was stopped and reverted under §12.11 governance.
ROLLOUT_END_STATES: tuple[str, ...] = ("completed", "rolled_back")

# Module-local in-memory backing store, shared by every repository instance.
# Keys are the row's primary key (mirrors services/data_exchange/saved_mappings.py).
_ROLLOUT_STORE: dict[str, dict] = {}


def reset_rollout_stores() -> None:
    """Test helper: empty the module-local rollout store."""
    _ROLLOUT_STORE.clear()


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


def _ring_index(ring: str) -> int:
    """Position of a ring in the canonical §40 sequence (order is law)."""
    try:
        return ROLLOUT_RINGS.index(ring)
    except ValueError:
        raise ValueError(
            f"unknown §40 rollout ring {ring!r} — expected one of "
            f"{ROLLOUT_RINGS}"
        ) from None


def _validate_transition(existing: dict, current_stage: str, end_state: Optional[str]) -> None:
    """Enforce the §40 ring law on a proposed stage write.

    A stage index decrease contradicts §40 order and is rejected — the sole
    exception is a rollback marking (``end_state='rolled_back'``), which §40
    permits from any stage. A stage index increase must be exactly +1: a
    rollout advances one ring at a time and never skips a stage. An unchanged
    stage is not a §40 transition at all (pause/resume/terminal writes keep
    the stage and only move ``paused_reason`` / ``end_state``).
    """
    old = existing["current_stage"]
    i = _ring_index(old)
    j = _ring_index(current_stage)
    if j < i and end_state != "rolled_back":
        raise ValueError(
            f"§40 rollout ring order is law: {current_stage!r} (stage {j}) "
            f"cannot follow {old!r} (stage {i}) — a rollout never moves "
            "backward except as a governed rollback"
        )
    if j > i + 1:
        raise ValueError(
            f"§40 rollouts advance one ring at a time: {old!r} (stage {i}) "
            f"cannot jump to {current_stage!r} (stage {j})"
        )


# ── typed storage view (mirrors the table columns) ───────────────────────────


class RolloutRecordRow(BaseModel):
    """A durable §12.8 rollout-record row (all ``rollouts`` columns).

    Vocabulary validated on construction — a bad ``artifact_kind`` /
    ``current_stage`` / cohort / ``end_state`` is a config error that must
    surface loudly (§40 / §12.8), and the §40 percentage law holds: a row's
    ``percentage`` always equals ``ring_percentage(current_stage)`` (0.0 for
    the ``olympus_internal`` / ``test_tenants`` stage-zero/one rings).
    """

    rollout_id: str
    changeset_ref: Optional[str] = None
    artifact_kind: str
    strategy: str = "canary"
    cohorts: list[str] = Field(default_factory=list)
    current_stage: str = "olympus_internal"
    percentage: float = 0.0
    health_gates: list[dict] = Field(default_factory=list)
    advance_conditions: list[str] = Field(default_factory=list)
    pause_conditions: list[str] = Field(default_factory=list)
    rollback_conditions: list[str] = Field(default_factory=list)
    paused_reason: Optional[str] = None
    end_state: Optional[str] = None
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    started_at: Optional[datetime] = None
    last_transition_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not is_rollout_artifact_kind(self.artifact_kind):
            raise ValueError(
                f"unknown §40 rollout artifact kind {self.artifact_kind!r} — "
                f"expected one of {ROLLOUT_ARTIFACT_KINDS}"
            )
        if not is_rollout_ring(self.current_stage):
            raise ValueError(
                f"unknown §40 rollout ring {self.current_stage!r} — expected "
                f"one of {ROLLOUT_RINGS}"
            )
        expected = ring_percentage(self.current_stage)
        if abs(float(self.percentage) - expected) > 1e-6:
            raise ValueError(
                f"rollout percentage {self.percentage} does not match §40 "
                f"ring_percentage({self.current_stage!r}) = {expected} — "
                "percentages always track current_stage"
            )
        for cohort in self.cohorts:
            if not is_rollout_ring(cohort):
                raise ValueError(
                    f"unknown §40 cohort {cohort!r} — cohort ids are rollout "
                    f"ring values: {ROLLOUT_RINGS}"
                )
        if self.end_state is not None and self.end_state not in ROLLOUT_END_STATES:
            raise ValueError(
                f"unknown rollout end_state {self.end_state!r} — expected one "
                f"of {ROLLOUT_END_STATES} or None (§12.8)"
            )


class _RolloutRepo:
    """Shared pool/ensure plumbing for the rollout repository."""

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


class RolloutRepository(_RolloutRepo):
    """Durable §40/§12.8 rollout records (in-flight + terminal)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = _ROLLOUT_STORE

    async def create(self, view: RolloutRecordRow) -> dict:
        """Persist one rollout record. The storage row validates the §40
        vocabularies (artifact kind, ring, cohorts) and the §40 percentage law
        on construction; ``created_at`` is DB-default-equivalent (view value
        honored when given, else now — same pattern as the Phase-2 rollback
        records)."""
        row = {
            **view.model_dump(mode="json"),
            "created_at": (view.created_at or _now()).isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            self._store[view.rollout_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO rollouts (rollout_id, changeset_ref, artifact_kind, "
            "strategy, cohorts, current_stage, percentage, health_gates, "
            "advance_conditions, pause_conditions, rollback_conditions, "
            "paused_reason, end_state, tenant_id, environment_id, started_at, "
            "last_transition_at, completed_at, created_at) "
            "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8::jsonb,$9::jsonb,"
            "$10::jsonb,$11::jsonb,$12,$13,$14,$15,$16,$17,$18,$19)",
            view.rollout_id, view.changeset_ref, view.artifact_kind,
            view.strategy, _json.dumps(view.cohorts), view.current_stage,
            view.percentage, _json.dumps(view.health_gates),
            _json.dumps(view.advance_conditions),
            _json.dumps(view.pause_conditions),
            _json.dumps(view.rollback_conditions), view.paused_reason,
            view.end_state, view.tenant_id, view.environment_id,
            view.started_at, view.last_transition_at, view.completed_at,
            view.created_at or _now(),
        )
        return dict(row)

    async def get(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        rollout_id: str,
    ) -> Optional[dict]:
        """Scoped read: a rollout is visible only inside its own (tenant,
        environment) scope — cross-scope and absent reads are None."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(rollout_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM rollouts "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollout_id=$3",
            tenant_id, environment_id, rollout_id,
        )
        return _rollout_row(dict(record)) if record is not None else None

    async def start(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        rollout_id: str,
        at: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Stamp ``started_at`` on an in-flight record (stage zero stays
        ``olympus_internal``; §40 start does not move the ring).

        Idempotent: an already-started record keeps its original
        ``started_at``. Returns None when the record is absent or
        cross-scope."""
        effective = at or _now()
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(rollout_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            if row.get("started_at") is None:
                row["started_at"] = effective.isoformat()
                row["last_transition_at"] = effective.isoformat()
            return dict(row)
        await pool.execute(
            "UPDATE rollouts SET started_at=$4, last_transition_at=$4 "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollout_id=$3 "
            "AND started_at IS NULL",
            tenant_id, environment_id, rollout_id, effective,
        )
        record = await pool.fetchrow(
            "SELECT * FROM rollouts "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollout_id=$3",
            tenant_id, environment_id, rollout_id,
        )
        return _rollout_row(dict(record)) if record is not None else None

    async def update_stage(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        rollout_id: str,
        current_stage: str,
        percentage: float,
        paused_reason: Optional[str] = None,
        end_state: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        at: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Write one §40 stage/pause/terminal transition and stamp
        ``last_transition_at`` (``at`` or now).

        Guards (every path, before any write): ``current_stage`` must be a
        §40 ring and ``end_state`` must be None or a
        :data:`ROLLOUT_END_STATES` member; ``percentage`` must equal
        ``ring_percentage(current_stage)`` (the §40 percentage law is total);
        the §40 ring law runs through :func:`_validate_transition` — stage
        index increases must be exactly +1 and decreases are rejected except
        as a governed rollback marking. ``paused_reason`` is the new pause
        marker (None clears it); a terminal ``end_state`` stamps
        ``completed_at`` (explicit value, else ``at``, else now). Absent or
        cross-scope records return None."""
        if not is_rollout_ring(current_stage):
            raise ValueError(
                f"unknown §40 rollout ring {current_stage!r} — expected one "
                f"of {ROLLOUT_RINGS}"
            )
        if end_state is not None and end_state not in ROLLOUT_END_STATES:
            raise ValueError(
                f"unknown rollout end_state {end_state!r} — expected one of "
                f"{ROLLOUT_END_STATES} or None (§12.8)"
            )
        percentage = float(percentage)
        expected = ring_percentage(current_stage)
        if abs(percentage - expected) > 1e-6:
            raise ValueError(
                f"rollout percentage {percentage} does not match §40 "
                f"ring_percentage({current_stage!r}) = {expected} — "
                "percentages always track current_stage"
            )
        effective_at = at or _now()
        if end_state is not None:
            effective_completed = completed_at or effective_at
        else:
            effective_completed = completed_at
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(rollout_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            _validate_transition(row, current_stage, end_state)
            row["current_stage"] = current_stage
            row["percentage"] = percentage
            row["paused_reason"] = paused_reason
            row["end_state"] = end_state
            row["last_transition_at"] = effective_at.isoformat()
            # SQL parity: the write always re-states completed_at (None
            # clears); a terminal end_state auto-stamps it.
            row["completed_at"] = (
                effective_completed.isoformat()
                if effective_completed is not None
                else None
            )
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM rollouts "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollout_id=$3",
            tenant_id, environment_id, rollout_id,
        )
        if record is None:
            return None
        existing = _rollout_row(dict(record))
        _validate_transition(existing, current_stage, end_state)
        result = await pool.execute(
            "UPDATE rollouts SET current_stage=$4, percentage=$5, "
            "paused_reason=$6, end_state=$7, last_transition_at=$8, "
            "completed_at=$9 "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollout_id=$3",
            tenant_id, environment_id, rollout_id, current_stage, percentage,
            paused_reason, end_state, effective_at, effective_completed,
        )
        if _rowcount(result) == 0:
            return None
        record = await pool.fetchrow(
            "SELECT * FROM rollouts "
            "WHERE tenant_id=$1 AND environment_id=$2 AND rollout_id=$3",
            tenant_id, environment_id, rollout_id,
        )
        return _rollout_row(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        artifact_kind: Optional[str] = None,
        end_state: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """List rollout records, newest-created first, newest within a scope.

        Filters are ANDed; ``tenant_id`` / ``environment_id`` are deliberately
        optional so the Olympus operator can read the aggregate. ``end_state``
        filters to one terminal state — None means no end-state filter (both
        in-flight and terminal rows), matching the terminal-column NULL
        semantics. Ordering is deterministic and SQL-parity: ``created_at
        DESC`` then ``rollout_id ASC`` on ties."""
        if artifact_kind is not None and not is_rollout_artifact_kind(artifact_kind):
            raise ValueError(
                f"unknown §40 rollout artifact kind {artifact_kind!r} — "
                f"expected one of {ROLLOUT_ARTIFACT_KINDS}"
            )
        if end_state is not None and end_state not in ROLLOUT_END_STATES:
            raise ValueError(
                f"unknown rollout end_state {end_state!r} — expected one of "
                f"{ROLLOUT_END_STATES} or None (§12.8)"
            )
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                dict(r)
                for r in self._store.values()
                if (tenant_id is None or r.get("tenant_id") == tenant_id)
                and (environment_id is None
                     or r.get("environment_id") == environment_id)
                and (artifact_kind is None
                     or r.get("artifact_kind") == artifact_kind)
                and (end_state is None or r.get("end_state") == end_state)
            ]
            rows.sort(key=lambda r: r.get("rollout_id") or "")
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return rows[:limit]
        where: list[str] = []
        args: list[Any] = []
        for col, value in (
            ("tenant_id", tenant_id),
            ("environment_id", environment_id),
            ("artifact_kind", artifact_kind),
            ("end_state", end_state),
        ):
            if value is not None:
                args.append(value)
                where.append(f"{col} = ${len(args)}")
        args.append(limit)
        sql_where = f"WHERE {' AND '.join(where)}" if where else ""
        records = await pool.fetch(
            f"SELECT * FROM rollouts {sql_where} "
            "ORDER BY created_at DESC, rollout_id ASC LIMIT " + str(len(args)),
            *args,
        )
        return [_rollout_row(dict(r)) for r in records]


def _rollout_row(row: dict) -> dict:
    row = dict(row)
    for col in (
        "cohorts",
        "health_gates",
        "advance_conditions",
        "pause_conditions",
        "rollback_conditions",
    ):
        row[col] = _parse_json(row.get(col))
    for col in ("started_at", "last_transition_at", "completed_at", "created_at"):
        row[col] = _iso(row.get(col))
    return row


# ── module singleton ─────────────────────────────────────────────────────────

_rollout_repo: Optional[RolloutRepository] = None


def get_rollout_repository() -> RolloutRepository:
    global _rollout_repo
    if _rollout_repo is None:
        _rollout_repo = RolloutRepository()
    return _rollout_repo
