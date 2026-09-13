"""Reconciled Control Plane — durable schema-mapping stores (Phase 3).

Direct-SQL repositories over the tables created by the
``20260906_rcp_schema_mapping.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring
``execution_records_repository.py`` and the earlier Phase-1/2 repos).

These stores hold the Phase-3 schema/mapping drift-automation artifacts:

* ``MappingCandidateRepository`` — one row per §8.1 semantic-mapping
  candidate (epistemic proposals, never truth — §18). The §8.1 mapping-method
  and review-state vocabularies are enforced at ``create`` (a candidate with
  unknown vocabulary is rejected with a §8.1 ``ValueError`` rather than
  stored); the §8.1 confidence→review-state policy itself lives in the
  ``schema_mapping`` engine, not here.
* ``SchemaMappingRunRepository`` — one row per §38 schema-mapping evaluation
  run: the observed/desired fingerprints that were compared (§25), the diff
  summary, the candidate ids it considered, the per-gate verdicts
  (``gate_results`` as ``dict[str, bool]``), whether the run promoted
  automatically, and the action/required ref when it did not.

Every repository keeps the module-local in-memory fallback (``get_pool()``
None under ``AETHER_ENV=local``), so unit tests exercise the same columnar
path the engine uses without a live Postgres. Tenancy is always carried in the
WHERE clause — no cross-tenant read is possible through these APIs.
"""

from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field
from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    MAPPING_METHOD_VALUES,
    MAPPING_REVIEW_STATES,
    is_mapping_method,
    is_mapping_review_state,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_schema_mapping.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mapping_candidates (
    candidate_id TEXT PRIMARY KEY,
    source_ref TEXT NOT NULL,
    source_path TEXT NOT NULL,
    canonical_target TEXT NOT NULL,
    mapping_method TEXT NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT,
    sensitivity_class TEXT,
    transform_ref TEXT,
    review_state TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mapping_candidates_review
    ON mapping_candidates (tenant_id, environment_id, review_state);

CREATE TABLE IF NOT EXISTS schema_mapping_runs (
    run_id TEXT PRIMARY KEY,
    managed_integration_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    observed_schema_fingerprint TEXT,
    desired_schema_fingerprint TEXT,
    diff_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    gate_results JSONB NOT NULL DEFAULT '{}'::jsonb,
    promoted BOOLEAN NOT NULL DEFAULT false,
    action_required_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_schema_mapping_runs_integration
    ON schema_mapping_runs (tenant_id, environment_id, managed_integration_ref, created_at);
"""


class MappingCandidateRow(BaseModel):
    """Typed storage row for ``mapping_candidates`` (§8.1 candidate fields).

    Mirrors the table columns one-to-one. The §8.1 vocabularies are enforced
    by the repository at ``create``, not by this model, so the model stays a
    plain column mirror.
    """

    candidate_id: str
    source_ref: str
    source_path: str
    canonical_target: str
    mapping_method: str = "heuristic"
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: Optional[str] = None
    sensitivity_class: Optional[str] = None
    transform_ref: Optional[str] = None
    review_state: str = "review"
    tenant_id: str
    environment_id: str
    created_at: datetime


class SchemaMappingRunRow(BaseModel):
    """Typed storage row for ``schema_mapping_runs`` (§38 run record).

    ``gate_results`` is a ``dict[str, bool]`` — one verdict per §38 gate —
    and ``candidate_ids`` references the §8.1 candidates this run considered.
    """

    run_id: str
    managed_integration_ref: str
    tenant_id: str
    environment_id: str
    observed_schema_fingerprint: Optional[str] = None
    desired_schema_fingerprint: Optional[str] = None
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_ids: list[str] = Field(default_factory=list)
    gate_results: dict[str, bool] = Field(default_factory=dict)
    promoted: bool = False
    action_required_ref: Optional[str] = None
    created_at: datetime


# Module-local in-memory backing stores, shared by every repository instance.
# Keys are the row's primary key (mirrors execution_records_repository.py).
_CANDIDATE_STORE: dict[str, dict] = {}
_RUN_STORE: dict[str, dict] = {}


def reset_schema_mapping_stores() -> None:
    """Test helper: empty every module-local schema-mapping store."""
    _CANDIDATE_STORE.clear()
    _RUN_STORE.clear()


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
        return {}
    if isinstance(value, str):
        try:
            return _json.loads(value)
        except ValueError:
            return {}
    return value


class _SchemaMappingRepo:
    """Shared pool/ensure plumbing for the schema-mapping repositories."""

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


# ── §8.1 mapping candidates ──────────────────────────────────────────────────


class MappingCandidateRepository(_SchemaMappingRepo):
    """One row per §8.1 semantic-mapping candidate.

    Candidates are epistemic proposals, never truth (§18). ``create`` enforces
    the §8.1 vocabularies (``mapping_method`` over ``MAPPING_METHOD_VALUES``,
    ``review_state`` over ``MAPPING_REVIEW_STATES``); the confidence→state
    policy that *chooses* the state lives in the ``schema_mapping`` engine.
    """

    def __init__(self) -> None:
        super().__init__()
        self._store = _CANDIDATE_STORE

    async def create(self, view: MappingCandidateRow) -> dict:
        if not is_mapping_method(view.mapping_method):
            raise ValueError(
                f"unknown mapping method {view.mapping_method!r} — §8.1 "
                f"methods are {list(MAPPING_METHOD_VALUES)}"
            )
        if not is_mapping_review_state(view.review_state):
            raise ValueError(
                f"unknown mapping review state {view.review_state!r} — §8.1 "
                f"states are {list(MAPPING_REVIEW_STATES)}"
            )
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.candidate_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO mapping_candidates (candidate_id, source_ref, "
            "source_path, canonical_target, mapping_method, confidence, "
            "rationale, sensitivity_class, transform_ref, review_state, "
            "tenant_id, environment_id, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
            view.candidate_id, view.source_ref, view.source_path,
            view.canonical_target, view.mapping_method, view.confidence,
            view.rationale, view.sensitivity_class, view.transform_ref,
            view.review_state, view.tenant_id, view.environment_id,
            view.created_at,
        )
        return row

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        review_state: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        if review_state is not None and not is_mapping_review_state(review_state):
            raise ValueError(
                f"unknown mapping review state {review_state!r} — §8.1 "
                f"states are {list(MAPPING_REVIEW_STATES)}"
            )
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if (tenant_id is None or r.get("tenant_id") == tenant_id)
                and (environment_id is None
                     or r.get("environment_id") == environment_id)
                and (review_state is None
                     or r.get("review_state") == review_state)
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        where: list[str] = []
        args: list[Any] = []
        if tenant_id is not None:
            args.append(tenant_id)
            where.append(f"tenant_id = ${len(args)}")
        if environment_id is not None:
            args.append(environment_id)
            where.append(f"environment_id = ${len(args)}")
        if review_state is not None:
            args.append(review_state)
            where.append(f"review_state = ${len(args)}")
        sql_where = f"WHERE {' AND '.join(where)}" if where else ""
        args.append(limit)
        records = await pool.fetch(
            f"SELECT * FROM mapping_candidates {sql_where} "
            f"ORDER BY created_at DESC LIMIT ${len(args)}",
            *args,
        )
        return [_candidate_row(dict(r)) for r in records]

    async def list_for_source(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        source_ref: str,
        limit: int = 200,
    ) -> list[dict]:
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
                and r.get("source_ref") == source_ref
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        records = await pool.fetch(
            "SELECT * FROM mapping_candidates "
            "WHERE tenant_id=$1 AND environment_id=$2 AND source_ref=$3 "
            "ORDER BY created_at DESC LIMIT $4",
            tenant_id, environment_id, source_ref, limit,
        )
        return [_candidate_row(dict(r)) for r in records]

    async def get(
        self, tenant_id: str, environment_id: str, candidate_id: str
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(candidate_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM mapping_candidates "
            "WHERE tenant_id=$1 AND environment_id=$2 AND candidate_id=$3",
            tenant_id, environment_id, candidate_id,
        )
        return _candidate_row(dict(record)) if record is not None else None


def _candidate_row(row: dict) -> dict:
    row = dict(row)
    row["created_at"] = _iso(row.get("created_at"))
    return row


# ── §38 schema-mapping evaluation runs ───────────────────────────────────────


class SchemaMappingRunRepository(_SchemaMappingRepo):
    """One row per §38 schema-mapping evaluation run.

    ``gate_results`` stores one bool verdict per §38 gate; ``promoted`` is the
    fail-closed verdict the ``schema_mapping`` engine derives from it (a run
    with any missing/false gate is never promoted).
    """

    def __init__(self) -> None:
        super().__init__()
        self._store = _RUN_STORE

    async def create(self, view: SchemaMappingRunRow) -> dict:
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.run_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO schema_mapping_runs (run_id, managed_integration_ref, "
            "tenant_id, environment_id, observed_schema_fingerprint, "
            "desired_schema_fingerprint, diff_summary, candidate_ids, "
            "gate_results, promoted, action_required_ref, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10,$11,"
            "$12)",
            view.run_id, view.managed_integration_ref, view.tenant_id,
            view.environment_id, view.observed_schema_fingerprint,
            view.desired_schema_fingerprint, _json.dumps(view.diff_summary),
            _json.dumps(view.candidate_ids), _json.dumps(view.gate_results),
            view.promoted, view.action_required_ref, view.created_at,
        )
        return row

    async def get(
        self, tenant_id: str, environment_id: str, run_id: str
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(run_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM schema_mapping_runs "
            "WHERE tenant_id=$1 AND environment_id=$2 AND run_id=$3",
            tenant_id, environment_id, run_id,
        )
        return _run_row(dict(record)) if record is not None else None

    async def list_for_integration(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        managed_integration_ref: str,
        limit: int = 50,
    ) -> list[dict]:
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("environment_id") == environment_id
                and r.get("managed_integration_ref") == managed_integration_ref
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        records = await pool.fetch(
            "SELECT * FROM schema_mapping_runs "
            "WHERE tenant_id=$1 AND environment_id=$2 AND "
            "managed_integration_ref=$3 "
            "ORDER BY created_at DESC LIMIT $4",
            tenant_id, environment_id, managed_integration_ref, limit,
        )
        return [_run_row(dict(r)) for r in records]


def _run_row(row: dict) -> dict:
    row = dict(row)
    row["diff_summary"] = _parse_json(row.get("diff_summary"))
    row["candidate_ids"] = _parse_json(row.get("candidate_ids"))
    row["gate_results"] = _parse_json(row.get("gate_results"))
    row["created_at"] = _iso(row.get("created_at"))
    return row


# ── module singletons ────────────────────────────────────────────────────────

_candidate_repo: Optional[MappingCandidateRepository] = None
_run_repo: Optional[SchemaMappingRunRepository] = None


def get_mapping_candidate_repository() -> MappingCandidateRepository:
    global _candidate_repo
    if _candidate_repo is None:
        _candidate_repo = MappingCandidateRepository()
    return _candidate_repo


def get_schema_mapping_run_repository() -> SchemaMappingRunRepository:
    global _run_repo
    if _run_repo is None:
        _run_repo = SchemaMappingRunRepository()
    return _run_repo
