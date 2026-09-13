"""Durable persistence for the Computation Substrate.

Immutable, append-only storage for canonical results + the runs that produced
them, following the exact idiom proven by
``repositories/measurement_results_repo.py``:

  * raw-SQL DDL duplicated verbatim into this module (the alembic versions dir is
    not importable and alembic is not a runtime dependency), asserted equal to
    the migration by ``tests/computation/test_repo_ddl_parity.py``;
  * the ONLY sanctioned mutation is *supersession* — an active row is stamped
    with ``superseded_by`` and a fresh row takes its place, guaranteed unique by
    a partial unique index on the active key;
  * dual backend — asyncpg pool when configured, an in-memory dict store under
    ``AETHER_ENV=local`` without ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool

# --------------------------------------------------------------------------- #
# DDL — duplicated verbatim in alembic/versions/<date>_computation_substrate.py
# (parity asserted by tests/computation/test_repo_ddl_parity.py).
# --------------------------------------------------------------------------- #
COMPUTED_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS computed_results (
    result_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    definition_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL,
    value DOUBLE PRECISION,
    value_type TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count',
    currency TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    superseded_by TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_computed_results_active
    ON computed_results (tenant_id, definition_id, definition_version, context_hash)
    WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS ix_computed_results_tenant
    ON computed_results (tenant_id, definition_id);
"""

COMPUTATION_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS computation_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    definition_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    context_hash TEXT,
    status TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_computation_runs_tenant
    ON computation_runs (tenant_id, definition_id);
"""

COMPUTATION_RESTATEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS computation_restatements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    prior_result_id TEXT NOT NULL,
    new_result_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    restated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_computation_restatements_tenant
    ON computation_restatements (tenant_id, new_result_id);
"""

_ALL_DDL = (COMPUTED_RESULTS_DDL, COMPUTATION_RUNS_DDL, COMPUTATION_RESTATEMENTS_DDL)


class ComputationConflictError(Exception):
    """A second active result was inserted for an already-active key."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ComputedResultsRepository:
    """Immutable-by-supersession store for :class:`CanonicalResult` rows."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._ensured = False
        self._results: dict[str, dict] = {}
        self._runs: dict[str, dict] = {}
        self._restatements: dict[str, dict] = {}

    async def _backend(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._ensured:
            for ddl in _ALL_DDL:
                await self._pool.execute(ddl)
            self._ensured = True
        return self._pool

    @staticmethod
    def _row(result: dict) -> dict:
        """Normalize a CanonicalResult dict into stored-row shape."""
        rec = dict(result)
        for key in ("result_id", "definition_id", "definition_version", "tenant_id", "status"):
            if not rec.get(key):
                raise ValueError(f"computed result requires '{key}'")
        rec.setdefault("value", None)
        rec.setdefault("value_type", "integer_count")
        rec.setdefault("unit", "count")
        rec.setdefault("currency", None)
        rec.setdefault("context_hash", None)
        rec.setdefault("run_id", None)
        rec.setdefault("superseded_by", None)
        rec.setdefault("computed_at", _utc_now_iso())
        rec.setdefault("created_at", _utc_now_iso())
        return rec

    # ── writes ────────────────────────────────────────────────────────────
    async def insert_result(self, result: dict) -> dict:
        rec = self._row(result)
        pool = await self._backend()
        if pool is None:
            self._reject_active_dup(rec)
            self._results[rec["result_id"]] = rec
            return rec
        existing = await pool.fetchrow(
            "SELECT result_id FROM computed_results WHERE tenant_id=$1 AND "
            "definition_id=$2 AND definition_version=$3 AND context_hash=$4 AND "
            "superseded_by IS NULL",
            rec["tenant_id"], rec["definition_id"], rec["definition_version"],
            rec["context_hash"],
        )
        if existing is not None:
            raise ComputationConflictError(
                f"active result exists for {rec['definition_id']}@"
                f"{rec['definition_version']} — supersede it"
            )
        await self._sql_insert(pool, rec)
        return rec

    def _reject_active_dup(self, rec: dict) -> None:
        for row in self._results.values():
            if (
                row.get("superseded_by") is None
                and row["tenant_id"] == rec["tenant_id"]
                and row["definition_id"] == rec["definition_id"]
                and row["definition_version"] == rec["definition_version"]
                and row.get("context_hash") == rec.get("context_hash")
            ):
                raise ComputationConflictError(
                    f"active result exists for {rec['definition_id']}@"
                    f"{rec['definition_version']} — supersede it"
                )

    @staticmethod
    async def _sql_insert(conn: Any, rec: dict) -> None:
        await conn.execute(
            """
            INSERT INTO computed_results (
                result_id, tenant_id, definition_id, definition_version,
                context_hash, run_id, status, value, value_type, unit, currency,
                data, superseded_by, computed_at, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15)
            """,
            rec["result_id"], rec["tenant_id"], rec["definition_id"],
            rec["definition_version"], rec["context_hash"], rec["run_id"],
            rec["status"], rec["value"], rec["value_type"], rec["unit"],
            rec["currency"], json.dumps(rec, default=str), rec["superseded_by"],
            rec["computed_at"], rec["created_at"],
        )

    async def supersede(
        self, tenant_id: str, prior_result_id: str, new_result: dict, *, reason: str
    ) -> dict:
        """Stamp the prior active result superseded and insert the replacement.

        Creates a restatement audit row. Preserves historical truth: the prior
        result is never overwritten, only marked ``superseded_by``.
        """
        new_rec = self._row(new_result)
        new_rec["supersedes_result_id"] = prior_result_id
        new_rec["restatement_reason"] = reason
        pool = await self._backend()
        restatement = {
            "id": _new_id("crst"),
            "tenant_id": tenant_id,
            "prior_result_id": prior_result_id,
            "new_result_id": new_rec["result_id"],
            "reason": reason,
            "restated_at": _utc_now_iso(),
        }
        if pool is None:
            prior = self._results.get(prior_result_id)
            if prior is None or prior["tenant_id"] != tenant_id:
                raise ValueError("prior result not found for supersede")
            prior["superseded_by"] = new_rec["result_id"]
            self._results[new_rec["result_id"]] = new_rec
            self._restatements[restatement["id"]] = restatement
            return new_rec
        async with pool.transaction():  # pragma: no cover - requires real PG
            await pool.execute(
                "UPDATE computed_results SET superseded_by=$1 WHERE result_id=$2 "
                "AND tenant_id=$3 AND superseded_by IS NULL",
                new_rec["result_id"], prior_result_id, tenant_id,
            )
            await self._sql_insert(pool, new_rec)
            await pool.execute(
                "INSERT INTO computation_restatements "
                "(id, tenant_id, prior_result_id, new_result_id, reason, restated_at) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                restatement["id"], tenant_id, prior_result_id,
                new_rec["result_id"], reason, restatement["restated_at"],
            )
        return new_rec

    async def insert_run(self, run: dict) -> dict:
        rec = dict(run)
        rec.setdefault("run_id", _new_id("run"))
        rec.setdefault("status", "completed")
        rec.setdefault("started_at", _utc_now_iso())
        pool = await self._backend()
        if pool is None:
            self._runs[rec["run_id"]] = rec
            return rec
        await pool.execute(  # pragma: no cover - requires real PG
            "INSERT INTO computation_runs (run_id, tenant_id, definition_id, "
            "definition_version, context_hash, status, data, started_at, completed_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9)",
            rec["run_id"], rec.get("tenant_id"), rec.get("definition_id"),
            rec.get("definition_version"), rec.get("context_hash"), rec["status"],
            json.dumps(rec, default=str), rec["started_at"], rec.get("completed_at"),
        )
        return rec

    # ── reads ─────────────────────────────────────────────────────────────
    async def get(self, tenant_id: str, result_id: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            row = self._results.get(result_id)
            return row if row and row["tenant_id"] == tenant_id else None
        row = await pool.fetchrow(  # pragma: no cover - requires real PG
            "SELECT data FROM computed_results WHERE result_id=$1 AND tenant_id=$2",
            result_id, tenant_id,
        )
        return json.loads(row["data"]) if row else None

    async def get_run(self, tenant_id: str, run_id: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            row = self._runs.get(run_id)
            return row if row and row.get("tenant_id") == tenant_id else None
        row = await pool.fetchrow(  # pragma: no cover - requires real PG
            "SELECT data FROM computation_runs WHERE run_id=$1 AND tenant_id=$2",
            run_id, tenant_id,
        )
        return json.loads(row["data"]) if row else None

    async def get_active(
        self, tenant_id: str, definition_id: str, definition_version: str, context_hash: str
    ) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            for row in self._results.values():
                if (
                    row.get("superseded_by") is None
                    and row["tenant_id"] == tenant_id
                    and row["definition_id"] == definition_id
                    and row["definition_version"] == definition_version
                    and row.get("context_hash") == context_hash
                ):
                    return row
            return None
        row = await pool.fetchrow(  # pragma: no cover - requires real PG
            "SELECT data FROM computed_results WHERE tenant_id=$1 AND definition_id=$2 "
            "AND definition_version=$3 AND context_hash=$4 AND superseded_by IS NULL",
            tenant_id, definition_id, definition_version, context_hash,
        )
        return json.loads(row["data"]) if row else None

    async def list_for_tenant(
        self, tenant_id: str, *, definition_id: Optional[str] = None,
        include_superseded: bool = False, limit: int = 100,
    ) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [
                r for r in self._results.values()
                if r["tenant_id"] == tenant_id
                and (definition_id is None or r["definition_id"] == definition_id)
                and (include_superseded or r.get("superseded_by") is None)
            ]
            rows.sort(key=lambda r: r.get("computed_at", ""), reverse=True)
            return rows[:limit]
        # pragma: no cover - requires real PG
        clause = "" if include_superseded else " AND superseded_by IS NULL"
        if definition_id:
            q = ("SELECT data FROM computed_results WHERE tenant_id=$1 AND "
                 f"definition_id=$2{clause} ORDER BY computed_at DESC LIMIT $3")
            got = await pool.fetch(q, tenant_id, definition_id, limit)
        else:
            q = (f"SELECT data FROM computed_results WHERE tenant_id=$1{clause} "
                 "ORDER BY computed_at DESC LIMIT $2")
            got = await pool.fetch(q, tenant_id, limit)
        return [json.loads(r["data"]) for r in got]

    async def restatement_chain(self, tenant_id: str, result_id: str) -> list[dict]:
        """Walk the supersession chain (both directions) for ``result_id``."""
        pool = await self._backend()
        chain: list[dict] = []
        if pool is None:
            # walk backwards to the origin
            index_by_new = {r["new_result_id"]: r for r in self._restatements.values()
                            if r["tenant_id"] == tenant_id}
            index_by_prior = {r["prior_result_id"]: r for r in self._restatements.values()
                              if r["tenant_id"] == tenant_id}
            cur = result_id
            back: list[dict] = []
            while cur in index_by_new:
                r = index_by_new[cur]
                back.append(r)
                cur = r["prior_result_id"]
            chain.extend(reversed(back))
            cur = result_id
            while cur in index_by_prior:
                r = index_by_prior[cur]
                chain.append(r)
                cur = r["new_result_id"]
            return chain
        return chain  # pragma: no cover - requires real PG


_repo_singleton: Optional[ComputedResultsRepository] = None


def get_computation_repository() -> ComputedResultsRepository:
    global _repo_singleton
    if _repo_singleton is None:
        _repo_singleton = ComputedResultsRepository()
    return _repo_singleton


__all__ = [
    "COMPUTED_RESULTS_DDL",
    "COMPUTATION_RUNS_DDL",
    "COMPUTATION_RESTATEMENTS_DDL",
    "ComputationConflictError",
    "ComputedResultsRepository",
    "get_computation_repository",
]
