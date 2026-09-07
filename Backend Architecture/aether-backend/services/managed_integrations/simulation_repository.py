"""Reconciled Control Plane — simulation/shadow evidence records (Phase 3).

Direct-SQL repository over the ``simulation_runs`` table created by the
``20260906_rcp_simulation.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring the Phase-2
``execution_records_repository`` and its siblings).

One row per §37 simulation/shadow run or §20 digital-twin dry run: the
per-axis §37 comparison outcomes (schema acceptance, mapping coverage, policy
decisions, identity joinability, outcome continuity, metric reconciliation,
latency, drop rate, duplicates, cost/volume), the axis delta summaries, the
run's unknowns/warnings and the single §12.7 result (``pass`` |
``conditional`` | ``fail``).

These rows are evidence for later R1/R2 execution gates only. Nothing in this
module (or the engine that writes it) executes, applies or mutates canonical
graph state — the §37 no-mutation invariant holds because the engine is a pure
function over the snapshots it is handed.

Vocabularies are enforced at the write boundary, mirroring the other Phase
repositories:

* ``simulation_mode`` ∈ {``shadow``, ``digital_twin``} (§37).
* ``result`` ∈ :data:`SIMULATION_RESULT_VALUES` = {pass, conditional, fail}
  (§12.7).

``changeset_ref`` is nullable: digital-twin dry runs (§20) may legitimately
precede the ChangeSet they inform. Tenancy is always carried in the WHERE
clause — no cross-tenant read is possible through these APIs. The repository
keeps the module-local in-memory fallback (``get_pool()`` None under
``AETHER_ENV=local``), so unit tests exercise the same columnar path the
engine uses without a live Postgres.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import is_simulation_result

# Must stay string-identical to the alembic migration
# ``20260906_rcp_simulation.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_id TEXT PRIMARY KEY,
    changeset_ref TEXT,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    simulation_mode TEXT NOT NULL DEFAULT 'digital_twin',   -- digital_twin | shadow (§37)
    input_snapshot_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    fixture_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    axis_results JSONB NOT NULL DEFAULT '{}'::jsonb,        -- axis -> pass|conditional|fail
    deltas JSONB NOT NULL DEFAULT '{}'::jsonb,              -- axis -> delta summary
    unknowns JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    result TEXT NOT NULL,                                    -- pass|conditional|fail (§12.7)
    ran_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_simulation_runs_scope
    ON simulation_runs (tenant_id, environment_id, changeset_ref);
"""

# §37 simulation-mode vocabulary (shadow PRODUCTION branch / digital-twin §20
# dry run). The engine and this repository both enforce it.
SIMULATION_MODES: tuple[str, ...] = ("shadow", "digital_twin")

# Module-local in-memory backing store, shared by every repository instance
# (mirrors the Phase-0/1/2 repository modules).
_SIMULATION_STORE: dict[str, dict] = {}  # simulation_id -> row


def reset_simulation_stores() -> None:
    """Test helper: empty the module-local in-memory simulation-run store."""
    _SIMULATION_STORE.clear()


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


class SimulationRunView(BaseModel):
    """One durable ``simulation_runs`` row (§37/§20 evidence record).

    Mirrors the migration's columns 1:1. List/dict fields round-trip as parsed
    JSONB on both the SQL and in-memory paths; ``result`` follows the §12.7
    vocabulary (default ``conditional``) and ``simulation_mode`` the §37
    vocabulary (default ``digital_twin``). ``changeset_ref`` stays optional —
    twin dry runs may precede any ChangeSet.
    """

    simulation_id: str = Field(..., min_length=1)
    changeset_ref: Optional[str] = None
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    simulation_mode: str = "digital_twin"
    input_snapshot_refs: list[str] = Field(default_factory=list)
    fixture_refs: list[str] = Field(default_factory=list)
    axis_results: dict[str, str] = Field(default_factory=dict)
    deltas: dict[str, str] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    result: str = "conditional"
    ran_at: datetime


_SIMULATION_COLUMNS = (
    "simulation_id, changeset_ref, tenant_id, environment_id, simulation_mode, "
    "input_snapshot_refs, fixture_refs, axis_results, deltas, unknowns, "
    "warnings, result, ran_at"
)


def _sim_row(row: dict) -> dict:
    """Row → operator view dict (the ``SimulationRunView`` field shape).

    JSONB columns round-trip as their parsed objects and ``ran_at`` as an ISO
    string on both the SQL and in-memory paths (in-memory rows keep the same
    columnar keys, so there is no drift between the two).
    """
    out = dict(row)
    for col in ("input_snapshot_refs", "fixture_refs", "unknowns", "warnings"):
        out[col] = _parse_json(out.get(col))
    for col in ("axis_results", "deltas"):
        parsed = _parse_json(out.get(col))
        out[col] = parsed if isinstance(parsed, dict) else {}
    out["ran_at"] = _iso(out.get("ran_at"))
    return out


class SimulationRepository:
    """Tenant-scoped durable ``simulation_runs`` store (§37/§20 evidence)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        return _SIMULATION_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── write ─────────────────────────────────────────────────────────────

    async def create(self, view: SimulationRunView) -> dict:
        """Persist one simulation/shadow or digital-twin run.

        Enforces the §37 simulation-mode vocabulary and the §12.7 result
        vocabulary at the write boundary (fail closed on unknown tokens).
        Returns the row in the same normalized shape as the read APIs
        (timestamps ISO-formatted), so ``create`` and ``get`` always agree.
        """
        if view.simulation_mode not in SIMULATION_MODES:
            raise ValueError(
                f"unknown simulation mode {view.simulation_mode!r} "
                f"— §37 vocabulary is shadow | digital_twin"
            )
        if not is_simulation_result(view.result):
            raise ValueError(
                f"unknown simulation result {view.result!r} "
                f"— §12.7 vocabulary is pass | conditional | fail"
            )
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.simulation_id] = dict(row)
            return _sim_row(row)
        await pool.execute(
            "INSERT INTO simulation_runs (simulation_id, changeset_ref, "
            "tenant_id, environment_id, simulation_mode, input_snapshot_refs, "
            "fixture_refs, axis_results, deltas, unknowns, warnings, result, "
            "ran_at) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,"
            "$9::jsonb,$10::jsonb,$11::jsonb,$12,$13)",
            view.simulation_id,
            view.changeset_ref,
            view.tenant_id,
            view.environment_id,
            view.simulation_mode,
            _json.dumps(view.input_snapshot_refs),
            _json.dumps(view.fixture_refs),
            _json.dumps(view.axis_results),
            _json.dumps(view.deltas),
            _json.dumps(view.unknowns),
            _json.dumps(view.warnings),
            view.result,
            view.ran_at,
        )
        return _sim_row(row)

    # ── reads ─────────────────────────────────────────────────────────────

    async def get(
        self, *, tenant_id: str, environment_id: str, simulation_id: str
    ) -> Optional[dict]:
        """Return one run (None when absent); refuses cross-scope reads."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(simulation_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return _sim_row(row)
        record = await pool.fetchrow(
            f"SELECT {_SIMULATION_COLUMNS} FROM simulation_runs "
            "WHERE tenant_id = $1 AND environment_id = $2 AND "
            "simulation_id = $3",
            tenant_id,
            environment_id,
            simulation_id,
        )
        return _sim_row(dict(record)) if record is not None else None

    async def list_for_changeset(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        changeset_ref: str,
        limit: int = 200,
    ) -> list[dict]:
        """Runs for one ChangeSet, newest-ran first (None when absent)."""
        if changeset_ref is None:
            raise ValueError("changeset_ref is required for list_for_changeset")
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
            rows.sort(key=lambda r: r.get("ran_at") or "", reverse=True)
            return [_sim_row(r) for r in rows[:limit]]
        records = await pool.fetch(
            "SELECT * FROM simulation_runs "
            "WHERE tenant_id=$1 AND environment_id=$2 AND changeset_ref=$3 "
            "ORDER BY ran_at DESC LIMIT $4",
            tenant_id,
            environment_id,
            changeset_ref,
            limit,
        )
        return [_sim_row(dict(r)) for r in records]

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        mode: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Simulation runs, newest-ran first, optional ANDed filters.

        ``None`` filters are not applied. An operator may scope to one tenant
        or aggregate across tenants (the route owns that authorization
        decision). ``mode`` is enforced against the §37 vocabulary when given.
        """
        if mode is not None and mode not in SIMULATION_MODES:
            raise ValueError(
                f"unknown simulation mode {mode!r} "
                f"— §37 vocabulary is shadow | digital_twin"
            )
        limit = max(0, int(limit))
        pool = await self._ensure()

        def _matches(row: dict) -> bool:
            return (
                (tenant_id is None or row.get("tenant_id") == tenant_id)
                and (
                    environment_id is None
                    or row.get("environment_id") == environment_id
                )
                and (mode is None or row.get("simulation_mode") == mode)
            )

        if pool is None:
            rows = [r for r in self._store.values() if _matches(r)]
            rows.sort(key=lambda r: r.get("ran_at") or "", reverse=True)
            return [_sim_row(r) for r in rows[:limit]]

        clauses: list[str] = []
        args: list[Any] = []
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if environment_id is not None:
            args.append(environment_id)
            clauses.append(f"environment_id = ${len(args)}")
        if mode is not None:
            args.append(mode)
            clauses.append(f"simulation_mode = ${len(args)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        records = await pool.fetch(
            f"SELECT {_SIMULATION_COLUMNS} FROM simulation_runs "
            f"{where} ORDER BY ran_at DESC LIMIT ${len(args)}",
            *args,
        )
        return [_sim_row(dict(r)) for r in records]


_sim_repo: Optional[SimulationRepository] = None


def get_simulation_repository() -> SimulationRepository:
    """Module singleton mirroring ``get_change_set_repository()``."""
    global _sim_repo
    if _sim_repo is None:
        _sim_repo = SimulationRepository()
    return _sim_repo
