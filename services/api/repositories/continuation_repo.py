"""Aether Repositories — Cross-Device Continuation Plane.

Direct-SQL repository for the ``continuations`` and ``continuation_selections``
tables created by alembic migration 20260820_continuation_plane. These tables
need semantics the JSONB BaseRepository cannot express: compare-and-swap on
``state_revision`` (optimistic concurrency), a partial unique idempotency index,
and ``expires_at`` TTL sweeps — hence real columns and hand-written SQL.

DDL parity
----------
The DDL constants below are duplicated VERBATIM from
``alembic/versions/20260820_continuation_plane.py`` and asserted equal by
``tests/unit/test_continuation_ddl_parity.py`` (the alembic versions directory
is not importable at runtime). Edit the migration first, then mirror here.

Backend selection mirrors repositories/jobs_repo.py:
- ``get_pool()`` returns None (AETHER_ENV=local without DATABASE_URL) → shared
  in-memory dicts guarded by an asyncio.Lock, with semantics identical to SQL.
- Otherwise asyncpg over the shared pool.

The full ContinuationContext / ContinuationSelection payload lives in the ``data``
JSONB column; the real columns mirror the queryable + authoritative fields. The
repository OWNS ``state_revision`` and ``updated_at`` — callers never set them.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import ConflictError, utc_now
from shared.logger.logger import get_logger
from shared.temporal.instant import ensure_aware_utc, to_iso_utc, try_parse_instant

logger = get_logger("aether.repository.continuation")

# ─────────────────────────────────────────────────────────────────────────────
# DDL — duplicated verbatim from alembic migration 20260820_continuation_plane.py
# (parity-tested). See module docstring.
# ─────────────────────────────────────────────────────────────────────────────

CONTINUATIONS_DDL = """
CREATE TABLE IF NOT EXISTS continuations (
    id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    app_kind TEXT NOT NULL,
    source_client TEXT NOT NULL,
    surface TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'standard',
    freshness TEXT,
    state_revision INT NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CONTINUATION_SELECTIONS_DDL = """
CREATE TABLE IF NOT EXISTS continuation_selections (
    token TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    as_of TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CONTINUATION_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_continuations_scope_idem "
    "ON continuations (tenant_scope, idempotency_key) WHERE idempotency_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_continuations_recent "
    "ON continuations (tenant_scope, principal_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_continuations_expiry "
    "ON continuations (expires_at) WHERE expires_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_continuation_selections_scope "
    "ON continuation_selections (tenant_scope, principal_id)",
    "CREATE INDEX IF NOT EXISTS ix_continuation_selections_expiry "
    "ON continuation_selections (expires_at) WHERE expires_at IS NOT NULL",
]

# ─────────────────────────────────────────────────────────────────────────────
# In-memory backing stores (local mode). Shared across instances so route
# singletons and sweepers observe one consistent view.
# ─────────────────────────────────────────────────────────────────────────────

_MEM_CONTINUATIONS: dict[str, dict] = {}
_MEM_SELECTIONS: dict[str, dict] = {}

_MEM_LOCK: Optional[asyncio.Lock] = None
_MEM_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _mem_lock() -> asyncio.Lock:
    global _MEM_LOCK, _MEM_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEM_LOCK is None or _MEM_LOCK_LOOP is not loop:
        _MEM_LOCK = asyncio.Lock()
        _MEM_LOCK_LOOP = loop
    return _MEM_LOCK


def reset_continuation_memory() -> None:
    """Test helper: clear every in-memory continuation store."""
    _MEM_CONTINUATIONS.clear()
    _MEM_SELECTIONS.clear()


def new_token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _to_dt(value: Any) -> Optional[datetime]:
    """Coerce a datetime / ISO string / None to a tz-aware UTC datetime, via the
    canonical shared/temporal helpers (no ad-hoc naive-datetime parsing)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_aware_utc(value)
    dt, _err = try_parse_instant(str(value))
    return dt


def _iso(value: Any) -> Optional[str]:
    dt = _to_dt(value)
    return to_iso_utc(dt) if dt is not None else None


def _json_load(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _continuation_row(record: dict) -> dict:
    """Return the stored context payload with authoritative columns overlaid."""
    data = dict(_json_load(record.get("data")) or {})
    data["state_revision"] = record["state_revision"]
    data["updated_at"] = _iso(record.get("updated_at"))
    if record.get("expires_at") is not None:
        data["expires_at"] = _iso(record.get("expires_at"))
    return data


def _selection_row(record: dict) -> dict:
    data = dict(_json_load(record.get("data")) or {})
    return data


class ContinuationRepository:
    """Durable access to continuations + continuation_selections.

    Isolation is by ``tenant_scope`` (``t:{tenant_id}`` for Aether tenants,
    ``o:{operator_id}`` for Kyber operators). An id unknown in scope and an id
    that exists in another scope both read as absent — no cross-scope leak.
    """

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._tables_ensured = False

    async def _ensure_pool(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        return self._pool

    async def _ensure_tables(self, pool: Any) -> None:
        if self._tables_ensured or pool is None:
            return
        await pool.execute(CONTINUATIONS_DDL)
        await pool.execute(CONTINUATION_SELECTIONS_DDL)
        for idx in CONTINUATION_INDEXES:
            await pool.execute(idx)
        self._tables_ensured = True

    async def _backend(self) -> Optional[Any]:
        pool = await self._ensure_pool()
        if pool is not None:
            await self._ensure_tables(pool)
        return pool

    # ── Continuations: create (idempotent) ───────────────────────────────

    async def create(
        self,
        *,
        tenant_scope: str,
        continuation_id: str,
        principal_id: str,
        app_kind: str,
        source_client: str,
        surface: str,
        sensitivity: str,
        freshness: Optional[str],
        context: dict,
        idempotency_key: Optional[str] = None,
        expires_at: Any = None,
    ) -> dict:
        """Insert a continuation at state_revision 0.

        Idempotency contract for (tenant_scope, idempotency_key): an existing row
        is returned with ``replayed=True`` and no new row is written.
        """
        now = utc_now()
        expires_dt = _to_dt(expires_at)
        payload = copy.deepcopy(context or {})
        payload["state_revision"] = 0
        payload["updated_at"] = to_iso_utc(now)
        payload["expires_at"] = _iso(expires_dt)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                if idempotency_key:
                    for rec in _MEM_CONTINUATIONS.values():
                        if rec["tenant_scope"] == tenant_scope and rec.get("idempotency_key") == idempotency_key:
                            return {**_continuation_row(rec), "replayed": True}
                record = {
                    "id": continuation_id,
                    "tenant_scope": tenant_scope,
                    "principal_id": principal_id,
                    "app_kind": app_kind,
                    "source_client": source_client,
                    "surface": surface,
                    "sensitivity": sensitivity,
                    "freshness": freshness,
                    "state_revision": 0,
                    "idempotency_key": idempotency_key,
                    "data": payload,
                    "expires_at": _iso(expires_dt),
                    "created_at": to_iso_utc(now),
                    "updated_at": to_iso_utc(now),
                }
                _MEM_CONTINUATIONS[continuation_id] = record
                return {**_continuation_row(record), "replayed": False}

        inserted = await pool.fetchrow(
            """
            INSERT INTO continuations (
                id, tenant_scope, principal_id, app_kind, source_client, surface,
                sensitivity, freshness, state_revision, idempotency_key, data,
                expires_at, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,0,$9,$10::jsonb,$11,$12,$12)
            ON CONFLICT (tenant_scope, idempotency_key) WHERE idempotency_key IS NOT NULL
            DO NOTHING
            RETURNING *
            """,
            continuation_id, tenant_scope, principal_id, app_kind, source_client,
            surface, sensitivity, freshness, idempotency_key,
            json.dumps(payload, default=str), expires_dt, now,
        )
        if inserted is not None:
            return {**_continuation_row(dict(inserted)), "replayed": False}
        existing = await pool.fetchrow(
            "SELECT * FROM continuations WHERE tenant_scope = $1 AND idempotency_key = $2",
            tenant_scope, idempotency_key,
        )
        return {**_continuation_row(dict(existing)), "replayed": True}

    # ── Continuations: compare-and-swap update ───────────────────────────

    async def cas_update(
        self,
        *,
        tenant_scope: str,
        continuation_id: str,
        expected_revision: int,
        context: dict,
        surface: Optional[str] = None,
        sensitivity: Optional[str] = None,
        freshness: Optional[str] = None,
        expires_at: Any = "__unset__",
    ) -> Optional[dict]:
        """Optimistic-concurrency update. Returns the new row, None when the id
        is absent in scope, or raises ConflictError on a state_revision mismatch.
        """
        now = utc_now()
        new_rev = expected_revision + 1
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_CONTINUATIONS.get(continuation_id)
                if rec is None or rec["tenant_scope"] != tenant_scope:
                    return None
                if rec["state_revision"] != expected_revision:
                    raise ConflictError(
                        f"continuation {continuation_id} revision is {rec['state_revision']}, "
                        f"expected {expected_revision}"
                    )
                payload = copy.deepcopy(context or {})
                payload["state_revision"] = new_rev
                payload["updated_at"] = to_iso_utc(now)
                if expires_at != "__unset__":
                    rec["expires_at"] = _iso(_to_dt(expires_at))
                payload["expires_at"] = rec.get("expires_at")
                rec["data"] = payload
                rec["state_revision"] = new_rev
                rec["updated_at"] = to_iso_utc(now)
                if surface is not None:
                    rec["surface"] = surface
                if sensitivity is not None:
                    rec["sensitivity"] = sensitivity
                if freshness is not None:
                    rec["freshness"] = freshness
                return _continuation_row(rec)

        current = await pool.fetchrow(
            "SELECT state_revision, expires_at FROM continuations WHERE id = $1 AND tenant_scope = $2",
            continuation_id, tenant_scope,
        )
        if current is None:
            return None
        if current["state_revision"] != expected_revision:
            raise ConflictError(
                f"continuation {continuation_id} revision is {current['state_revision']}, "
                f"expected {expected_revision}"
            )
        payload = copy.deepcopy(context or {})
        payload["state_revision"] = new_rev
        payload["updated_at"] = to_iso_utc(now)
        new_expiry = _to_dt(expires_at) if expires_at != "__unset__" else current["expires_at"]
        payload["expires_at"] = _iso(new_expiry)
        row = await pool.fetchrow(
            """
            UPDATE continuations
            SET data = $4::jsonb, state_revision = state_revision + 1, updated_at = $5,
                surface = COALESCE($6, surface), sensitivity = COALESCE($7, sensitivity),
                freshness = COALESCE($8, freshness), expires_at = $9
            WHERE id = $1 AND tenant_scope = $2 AND state_revision = $3
            RETURNING *
            """,
            continuation_id, tenant_scope, expected_revision,
            json.dumps(payload, default=str), now, surface, sensitivity, freshness, new_expiry,
        )
        if row is None:
            # Lost a concurrent CAS race between the read and the write.
            raise ConflictError(f"continuation {continuation_id} was concurrently updated")
        return _continuation_row(dict(row))

    # ── Continuations: reads / delete / sweep ────────────────────────────

    async def get_scoped(self, tenant_scope: str, continuation_id: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            rec = _MEM_CONTINUATIONS.get(continuation_id)
            if rec is None or rec["tenant_scope"] != tenant_scope:
                return None
            return _continuation_row(rec)
        row = await pool.fetchrow(
            "SELECT * FROM continuations WHERE id = $1 AND tenant_scope = $2",
            continuation_id, tenant_scope,
        )
        return _continuation_row(dict(row)) if row is not None else None

    async def list_recent(self, tenant_scope: str, principal_id: str, limit: int = 25) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [
                _continuation_row(rec) for rec in _MEM_CONTINUATIONS.values()
                if rec["tenant_scope"] == tenant_scope and rec["principal_id"] == principal_id
            ]
            rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
            return rows[:limit]
        rows = await pool.fetch(
            "SELECT * FROM continuations WHERE tenant_scope = $1 AND principal_id = $2 "
            "ORDER BY updated_at DESC LIMIT $3",
            tenant_scope, principal_id, limit,
        )
        return [_continuation_row(dict(r)) for r in rows]

    async def delete_scoped(self, tenant_scope: str, continuation_id: str) -> bool:
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                rec = _MEM_CONTINUATIONS.get(continuation_id)
                if rec is None or rec["tenant_scope"] != tenant_scope:
                    return False
                del _MEM_CONTINUATIONS[continuation_id]
                return True
        result = await pool.execute(
            "DELETE FROM continuations WHERE id = $1 AND tenant_scope = $2",
            continuation_id, tenant_scope,
        )
        return bool(result) and result.endswith("1")

    async def sweep_expired(self) -> int:
        """Delete continuations + selections whose expires_at passed. Returns count."""
        now = utc_now()
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                cont = [k for k, r in _MEM_CONTINUATIONS.items()
                        if _to_dt(r.get("expires_at")) is not None and _to_dt(r["expires_at"]) < now]
                sel = [k for k, r in _MEM_SELECTIONS.items()
                       if _to_dt(r.get("expires_at")) is not None and _to_dt(r["expires_at"]) < now]
                for k in cont:
                    del _MEM_CONTINUATIONS[k]
                for k in sel:
                    del _MEM_SELECTIONS[k]
                return len(cont) + len(sel)
        r1 = await pool.execute("DELETE FROM continuations WHERE expires_at IS NOT NULL AND expires_at < $1", now)
        r2 = await pool.execute("DELETE FROM continuation_selections WHERE expires_at IS NOT NULL AND expires_at < $1", now)
        return _rowcount(r1) + _rowcount(r2)

    async def delete_by_principal(self, tenant_scope: str, principal_id: str) -> int:
        """DSR erasure hook — remove every continuation + selection for a subject."""
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                cont = [k for k, r in _MEM_CONTINUATIONS.items()
                        if r["tenant_scope"] == tenant_scope and r["principal_id"] == principal_id]
                sel = [k for k, r in _MEM_SELECTIONS.items()
                       if r["tenant_scope"] == tenant_scope and r["principal_id"] == principal_id]
                for k in cont:
                    del _MEM_CONTINUATIONS[k]
                for k in sel:
                    del _MEM_SELECTIONS[k]
                return len(cont) + len(sel)
        r1 = await pool.execute(
            "DELETE FROM continuations WHERE tenant_scope = $1 AND principal_id = $2",
            tenant_scope, principal_id,
        )
        r2 = await pool.execute(
            "DELETE FROM continuation_selections WHERE tenant_scope = $1 AND principal_id = $2",
            tenant_scope, principal_id,
        )
        return _rowcount(r1) + _rowcount(r2)

    # ── Selections (the backend selection token) ─────────────────────────

    async def create_selection(
        self,
        *,
        tenant_scope: str,
        principal_id: str,
        mode: str,
        selection: dict,
        as_of: Any = None,
        expires_at: Any = None,
    ) -> dict:
        now = utc_now()
        token = new_token("sel")
        as_of_dt = _to_dt(as_of)
        expires_dt = _to_dt(expires_at)
        payload = copy.deepcopy(selection or {})
        payload.update({
            "token": token,
            "tenant_scope": tenant_scope,
            "principal_id": principal_id,
            "mode": mode,
            "as_of": _iso(as_of_dt),
            "expires_at": _iso(expires_dt),
            "created_at": to_iso_utc(now),
        })
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                _MEM_SELECTIONS[token] = {
                    "token": token, "tenant_scope": tenant_scope, "principal_id": principal_id,
                    "mode": mode, "as_of": _iso(as_of_dt), "expires_at": _iso(expires_dt),
                    "data": payload, "created_at": to_iso_utc(now),
                }
                return _selection_row(_MEM_SELECTIONS[token])
        row = await pool.fetchrow(
            "INSERT INTO continuation_selections (token, tenant_scope, principal_id, mode, "
            "as_of, expires_at, data, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8) RETURNING *",
            token, tenant_scope, principal_id, mode, as_of_dt, expires_dt,
            json.dumps(payload, default=str), now,
        )
        return _selection_row(dict(row))

    async def get_selection(self, tenant_scope: str, token: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            rec = _MEM_SELECTIONS.get(token)
            if rec is None or rec["tenant_scope"] != tenant_scope:
                return None
            return _selection_row(rec)
        row = await pool.fetchrow(
            "SELECT * FROM continuation_selections WHERE token = $1 AND tenant_scope = $2",
            token, tenant_scope,
        )
        return _selection_row(dict(row)) if row is not None else None


def _rowcount(result: Any) -> int:
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


_repo: Optional[ContinuationRepository] = None


def get_continuation_repository() -> ContinuationRepository:
    """Lazy process-wide singleton."""
    global _repo
    if _repo is None:
        _repo = ContinuationRepository()
    return _repo
