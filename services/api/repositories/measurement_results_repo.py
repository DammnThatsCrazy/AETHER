"""
Aether Repository — Measurement Integrity Plane

Immutable, tenant-scoped storage for computed measurement results. Direct-SQL
repository over the ``measurement_results`` and ``measurement_restatements``
tables created by ``alembic/versions/20260716_measurement_integrity.py``.

Immutability contract
----------------------
A ``measurement_results`` row is never updated in place. Corrections are made
by *supersession*: :meth:`MeasurementResultsRepository.supersede` stamps the
prior row's ``superseded_by`` with the id of a fresh row, inserts that fresh
row, and records a ``measurement_restatements`` audit entry — atomically where
a Postgres pool exists (single transaction), step-by-step in local mode. This
is the ONLY sanctioned mutation of an existing row.

A partial UNIQUE index (``ux_measurement_results_active``) guarantees at most
one *active* (``superseded_by IS NULL``) result per
``(tenant_id, metric_name, metric_version, context_hash)``. Inserting a second
active result for the same key is rejected loudly (:class:`BadRequestError`) —
integrity over silent dedup.

DDL parity
----------
The alembic versions directory is not an importable package and alembic is not
a runtime dependency of the backend, so ``MEASUREMENT_RESULTS_DDL`` and
``MEASUREMENT_RESTATEMENTS_DDL`` below are duplicated VERBATIM from
``alembic/versions/20260716_measurement_integrity.py``.
``tests/unit/test_measurement_results_repo.py`` reads the migration text and
asserts the two match — edit the migration first, then mirror it here.

Backend selection mirrors repositories/artifacts.py:
- ``get_pool()`` returns None (AETHER_ENV=local without DATABASE_URL) → an
  in-memory dict store with semantics identical to the SQL paths.
- Otherwise asyncpg over the shared pool.

Dict-in / dict-out: this repository is intentionally decoupled from the
``shared.measurement`` pydantic models. A record is a plain dict with keys:
``id, tenant_id, metric_name, metric_version, context_hash, value,
value_state, unit, lineage, sufficiency, uncertainty, computed_at,
superseded_by`` (plus ``created_at`` stamped on insert).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import BadRequestError, NotFoundError, utc_now

# ─────────────────────────────────────────────────────────────────────────────
# DDL — duplicated VERBATIM from alembic migration
# 20260716_measurement_integrity.py (see module docstring; parity-tested). Each
# constant bundles the CREATE TABLE with its indexes; both asyncpg and psycopg2
# execute the multi-statement string in a single call.
# ─────────────────────────────────────────────────────────────────────────────

MEASUREMENT_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS measurement_results (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    value DOUBLE PRECISION,
    value_state TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count',
    lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    sufficiency JSONB NOT NULL DEFAULT '{}'::jsonb,
    uncertainty JSONB,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_measurement_results_active
    ON measurement_results (tenant_id, metric_name, metric_version, context_hash)
    WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS ix_measurement_results_tenant
    ON measurement_results (tenant_id, metric_name);
"""

MEASUREMENT_RESTATEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS measurement_restatements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    prior_result_id TEXT NOT NULL,
    new_result_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    restated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_measurement_restatements_tenant
    ON measurement_restatements (tenant_id, new_result_id);
"""

# Columns in insert order (kept next to the DDL so the two stay aligned).
_RESULT_COLUMNS = (
    "id", "tenant_id", "metric_name", "metric_version", "context_hash",
    "value", "value_state", "unit", "lineage", "sufficiency", "uncertainty",
    "computed_at", "superseded_by", "created_at",
)
_RESULT_TS_FIELDS = ("computed_at", "created_at")
_RESULT_JSON_FIELDS = ("lineage", "sufficiency", "uncertainty")
_REQUIRED_KEYS = ("tenant_id", "metric_name", "metric_version", "context_hash")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _to_dt(value: Any) -> Optional[datetime]:
    """Coerce ISO string / datetime / None to a tz-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    dt = _to_dt(value)
    return dt.isoformat() if dt is not None else None


def _json_load(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _result_row(record: dict) -> dict:
    """Normalize a stored record to the dict-out shape: ISO-8601 timestamps and
    parsed JSON for lineage/sufficiency/uncertainty on BOTH backends."""
    row = dict(record)
    for field in _RESULT_TS_FIELDS:
        if field in row:
            row[field] = _iso(row[field])
    for field in _RESULT_JSON_FIELDS:
        if field in row and row[field] is not None:
            row[field] = _json_load(row[field])
    return row


class MeasurementResultsRepository:
    """Immutable, tenant-scoped measurement-result store.

    Every read filters by ``tenant_id`` — a cross-tenant lookup returns None.
    Every write persists before returning: callers may treat a returned row as
    durably recorded (Postgres) or committed to the in-memory store (local).
    """

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._tables_ensured = False
        # Local fallback stores (id -> row dict), used when get_pool() is None.
        self._results: dict[str, dict] = {}
        self._restatements: dict[str, dict] = {}

    async def _backend(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._tables_ensured:
            await self._pool.execute(MEASUREMENT_RESULTS_DDL)
            await self._pool.execute(MEASUREMENT_RESTATEMENTS_DDL)
            self._tables_ensured = True
        return self._pool

    # ── record preparation ────────────────────────────────────────────────

    @staticmethod
    def _prepare(record: dict, *, tenant_id: Optional[str] = None) -> dict:
        """Return a stored-shape copy of ``record`` with ids/timestamps/defaults
        filled. ``id`` and ``created_at`` are assigned when absent; ``computed_at``
        defaults to now; ``superseded_by`` defaults to None. JSONB fields default
        to ``{}`` (lineage/sufficiency) or None (uncertainty). ``unit`` defaults
        to ``'count'`` and ``value_state`` to ``'measured'`` — mirroring the DDL
        defaults so a lean dict-in still satisfies the NOT NULL columns."""
        rec = dict(record)
        if tenant_id is not None:
            existing = rec.get("tenant_id")
            if existing is not None and existing != tenant_id:
                raise BadRequestError(
                    "record tenant_id does not match the supersede tenant scope"
                )
            rec["tenant_id"] = tenant_id
        for key in _REQUIRED_KEYS:
            if not rec.get(key):
                raise BadRequestError(f"measurement result requires '{key}'")
        now = utc_now()
        rec["id"] = rec.get("id") or _new_id("mr")
        rec["value"] = rec.get("value", None)
        rec["value_state"] = rec.get("value_state") or "measured"
        rec["unit"] = rec.get("unit") or "count"
        rec["lineage"] = rec.get("lineage") or {}
        rec["sufficiency"] = rec.get("sufficiency") or {}
        rec["uncertainty"] = rec.get("uncertainty", None)
        rec["computed_at"] = _iso(rec.get("computed_at")) or now.isoformat()
        rec["superseded_by"] = rec.get("superseded_by", None)
        rec["created_at"] = _iso(rec.get("created_at")) or now.isoformat()
        return rec

    # ── SQL insert helper (assumes the active-duplicate check already ran or
    #    is guaranteed to pass, e.g. inside supersede after the prior is
    #    stamped). Uses the connection/pool passed in so supersede can reuse a
    #    single transaction. ──────────────────────────────────────────────────

    @staticmethod
    async def _sql_insert(conn: Any, rec: dict) -> None:
        await conn.execute(
            """
            INSERT INTO measurement_results (
                id, tenant_id, metric_name, metric_version, context_hash,
                value, value_state, unit, lineage, sufficiency, uncertainty,
                computed_at, superseded_by, created_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12,$13,$14
            )
            """,
            rec["id"], rec["tenant_id"], rec["metric_name"], rec["metric_version"],
            rec["context_hash"], rec["value"], rec["value_state"], rec["unit"],
            json.dumps(rec["lineage"], default=str),
            json.dumps(rec["sufficiency"], default=str),
            json.dumps(rec["uncertainty"], default=str)
            if rec["uncertainty"] is not None else None,
            _to_dt(rec["computed_at"]), rec["superseded_by"], _to_dt(rec["created_at"]),
        )

    # ── writes ────────────────────────────────────────────────────────────

    async def insert_result(self, record: dict) -> dict:
        """Immutably insert a measurement result.

        Assigns ``id``/``created_at``/``computed_at`` when absent. Rejects a
        second *active* result (``superseded_by IS NULL``) for the same
        ``(tenant_id, metric_name, metric_version, context_hash)`` with a
        :class:`BadRequestError` — the partial unique index is the DB-level
        backstop; this explicit check gives a clean error message.
        """
        rec = self._prepare(record)
        pool = await self._backend()

        if pool is None:
            self._mem_reject_active_dup(rec)
            self._results[rec["id"]] = rec
            return _result_row(rec)

        existing = await pool.fetchrow(
            "SELECT id FROM measurement_results WHERE tenant_id = $1 "
            "AND metric_name = $2 AND metric_version = $3 AND context_hash = $4 "
            "AND superseded_by IS NULL",
            rec["tenant_id"], rec["metric_name"], rec["metric_version"],
            rec["context_hash"],
        )
        if existing is not None:
            raise BadRequestError(
                f"active measurement result already exists for "
                f"({rec['tenant_id']}, {rec['metric_name']}, "
                f"{rec['metric_version']}, {rec['context_hash']}) — supersede it"
            )
        await self._sql_insert(pool, rec)
        return _result_row(rec)

    def _mem_reject_active_dup(
        self, rec: dict, *, ignore_id: Optional[str] = None
    ) -> None:
        for other in self._results.values():
            if (
                other["tenant_id"] == rec["tenant_id"]
                and other["metric_name"] == rec["metric_name"]
                and other["metric_version"] == rec["metric_version"]
                and other["context_hash"] == rec["context_hash"]
                and other.get("superseded_by") is None
                and other["id"] != ignore_id
            ):
                raise BadRequestError(
                    f"active measurement result already exists for "
                    f"({rec['tenant_id']}, {rec['metric_name']}, "
                    f"{rec['metric_version']}, {rec['context_hash']}) — supersede it"
                )

    async def supersede(
        self,
        tenant_id: str,
        prior_result_id: str,
        new_record: dict,
        *,
        reason: str,
    ) -> dict:
        """Supersede ``prior_result_id`` with ``new_record`` — the only
        sanctioned mutation of an existing row.

        Stamps the prior row's ``superseded_by`` with the new row's id, inserts
        the new (active) row, and writes a ``measurement_restatements`` audit
        entry carrying ``reason``. Atomic in a single transaction under
        Postgres; sequential (no interleaved awaits) in local mode. Returns the
        newly-inserted active record.

        Raises :class:`NotFoundError` if the prior row is missing/cross-tenant,
        and :class:`BadRequestError` if the prior row is already superseded or
        ``reason`` is blank.
        """
        if not reason or not str(reason).strip():
            raise BadRequestError("supersede requires a non-empty reason")
        rec = self._prepare(new_record, tenant_id=tenant_id)
        restatement_id = _new_id("mrst")
        now = utc_now()
        pool = await self._backend()

        if pool is None:
            prior = self._results.get(prior_result_id)
            if prior is None or prior["tenant_id"] != tenant_id:
                raise NotFoundError("measurement result")
            if prior.get("superseded_by") is not None:
                raise BadRequestError(
                    "prior measurement result is already superseded"
                )
            # New row must not collide with a *different* active row.
            self._mem_reject_active_dup(rec, ignore_id=prior["id"])
            prior["superseded_by"] = rec["id"]
            self._results[rec["id"]] = rec
            self._restatements[restatement_id] = {
                "id": restatement_id,
                "tenant_id": tenant_id,
                "prior_result_id": prior_result_id,
                "new_result_id": rec["id"],
                "reason": reason,
                "restated_at": now.isoformat(),
            }
            return _result_row(rec)

        async with pool.acquire() as conn:
            async with conn.transaction():
                prior = await conn.fetchrow(
                    "SELECT id, superseded_by FROM measurement_results "
                    "WHERE id = $1 AND tenant_id = $2 FOR UPDATE",
                    prior_result_id, tenant_id,
                )
                if prior is None:
                    raise NotFoundError("measurement result")
                if prior["superseded_by"] is not None:
                    raise BadRequestError(
                        "prior measurement result is already superseded"
                    )
                await conn.execute(
                    "UPDATE measurement_results SET superseded_by = $3 "
                    "WHERE id = $1 AND tenant_id = $2",
                    prior_result_id, tenant_id, rec["id"],
                )
                await self._sql_insert(conn, rec)
                await conn.execute(
                    "INSERT INTO measurement_restatements (id, tenant_id, "
                    "prior_result_id, new_result_id, reason, restated_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    restatement_id, tenant_id, prior_result_id, rec["id"], reason, now,
                )
        return _result_row(rec)

    # ── reads ─────────────────────────────────────────────────────────────

    async def get(self, tenant_id: str, result_id: str) -> Optional[dict]:
        """Tenant-scoped fetch by id. None when missing or owned by another
        tenant."""
        pool = await self._backend()
        if pool is None:
            rec = self._results.get(result_id)
            if rec is None or rec["tenant_id"] != tenant_id:
                return None
            return _result_row(rec)
        row = await pool.fetchrow(
            "SELECT * FROM measurement_results WHERE id = $1 AND tenant_id = $2",
            result_id, tenant_id,
        )
        return _result_row(dict(row)) if row is not None else None

    async def get_active(
        self,
        tenant_id: str,
        metric_name: str,
        metric_version: str,
        context_hash: str,
    ) -> Optional[dict]:
        """Return the single active (``superseded_by IS NULL``) result for a
        metric+context, or None."""
        pool = await self._backend()
        if pool is None:
            for rec in self._results.values():
                if (
                    rec["tenant_id"] == tenant_id
                    and rec["metric_name"] == metric_name
                    and rec["metric_version"] == metric_version
                    and rec["context_hash"] == context_hash
                    and rec.get("superseded_by") is None
                ):
                    return _result_row(rec)
            return None
        row = await pool.fetchrow(
            "SELECT * FROM measurement_results WHERE tenant_id = $1 "
            "AND metric_name = $2 AND metric_version = $3 AND context_hash = $4 "
            "AND superseded_by IS NULL",
            tenant_id, metric_name, metric_version, context_hash,
        )
        return _result_row(dict(row)) if row is not None else None

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        metric_name: Optional[str] = None,
        include_superseded: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        """Newest-first results for a tenant. Active-only by default; pass
        ``include_superseded=True`` for the full history. Optionally narrow to a
        single ``metric_name``."""
        pool = await self._backend()
        if pool is None:
            rows = [
                _result_row(rec)
                for rec in self._results.values()
                if rec["tenant_id"] == tenant_id
                and (metric_name is None or rec["metric_name"] == metric_name)
                and (include_superseded or rec.get("superseded_by") is None)
            ]
            rows.sort(key=lambda r: r["computed_at"], reverse=True)
            return rows[:limit]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if metric_name is not None:
            params.append(metric_name)
            conditions.append(f"metric_name = ${len(params)}")
        if not include_superseded:
            conditions.append("superseded_by IS NULL")
        params.append(limit)
        rows = await pool.fetch(
            f"SELECT * FROM measurement_results WHERE {' AND '.join(conditions)} "
            f"ORDER BY computed_at DESC LIMIT ${len(params)}",
            *params,
        )
        return [_result_row(dict(r)) for r in rows]

    async def restatement_chain(
        self, tenant_id: str, result_id: str
    ) -> list[dict]:
        """Return the ordered version chain (oldest → newest/active) for the
        metric+context that ``result_id`` belongs to.

        Walks ``superseded_by`` backward to the root, then forward to the head,
        following tenant-scoped pointers. Returns [] when ``result_id`` is
        missing or cross-tenant."""
        start = await self.get(tenant_id, result_id)
        if start is None:
            return []

        # Walk backward: the prior row is the one whose superseded_by == root.id
        root = start
        seen: set[str] = {root["id"]}
        while True:
            prior = await self._find_prior(tenant_id, root["id"])
            if prior is None or prior["id"] in seen:
                break
            seen.add(prior["id"])
            root = prior

        # Walk forward from the root via superseded_by pointers.
        chain = [root]
        cursor = root
        forward_seen: set[str] = {root["id"]}
        while cursor.get("superseded_by"):
            nxt = await self.get(tenant_id, cursor["superseded_by"])
            if nxt is None or nxt["id"] in forward_seen:
                break
            forward_seen.add(nxt["id"])
            chain.append(nxt)
            cursor = nxt
        return chain

    async def _find_prior(
        self, tenant_id: str, result_id: str
    ) -> Optional[dict]:
        """The row (tenant-scoped) that was superseded BY ``result_id``."""
        pool = await self._backend()
        if pool is None:
            for rec in self._results.values():
                if (
                    rec["tenant_id"] == tenant_id
                    and rec.get("superseded_by") == result_id
                ):
                    return _result_row(rec)
            return None
        row = await pool.fetchrow(
            "SELECT * FROM measurement_results WHERE tenant_id = $1 "
            "AND superseded_by = $2",
            tenant_id, result_id,
        )
        return _result_row(dict(row)) if row is not None else None

    async def list_restatements(
        self, tenant_id: str, *, limit: int = 200
    ) -> list[dict]:
        """Newest-first restatement audit entries for a tenant."""
        pool = await self._backend()
        if pool is None:
            rows = [
                dict(rec)
                for rec in self._restatements.values()
                if rec["tenant_id"] == tenant_id
            ]
            rows.sort(key=lambda r: r["restated_at"], reverse=True)
            return rows[:limit]
        rows = await pool.fetch(
            "SELECT * FROM measurement_restatements WHERE tenant_id = $1 "
            "ORDER BY restated_at DESC LIMIT $2",
            tenant_id, limit,
        )
        out = []
        for r in rows:
            rec = dict(r)
            if isinstance(rec.get("restated_at"), datetime):
                rec["restated_at"] = rec["restated_at"].isoformat()
            out.append(rec)
        return out


_repo: Optional[MeasurementResultsRepository] = None


def get_measurement_results_repository() -> MeasurementResultsRepository:
    """Lazy process-wide singleton."""
    global _repo
    if _repo is None:
        _repo = MeasurementResultsRepository()
    return _repo
