"""Aether Repositories — Client-Sync Feed.

Direct-SQL repository for ``sync_change_log`` + ``sync_cursor_counter`` (alembic
20260821_client_sync). A gapless per-scope monotonic sequence (allocated in the
same statement that appends) and a unique (scope_key, source_event_id)
idempotency index are semantics the JSONB BaseRepository cannot express.

DDL parity: constants duplicated verbatim from the migration and asserted equal
by tests/unit/test_client_sync_ddl_parity.py.

Backend selection mirrors repositories/jobs_repo.py: get_pool() None → in-memory
dicts under an asyncio.Lock; otherwise asyncpg. Change rows carry ids + a
revision only — never a resource body, so the graph is never replicated.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.temporal.instant import to_iso_utc

logger = get_logger("aether.repository.client_sync")

SYNC_CHANGE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS sync_change_log (
    id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    device_id TEXT,
    seq BIGINT NOT NULL,
    change_type TEXT NOT NULL,
    resource_kind TEXT,
    resource_id TEXT,
    revision TEXT,
    source_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

SYNC_CURSOR_COUNTER_DDL = """
CREATE TABLE IF NOT EXISTS sync_cursor_counter (
    scope_key TEXT PRIMARY KEY,
    next_seq BIGINT NOT NULL DEFAULT 0
)
"""

SYNC_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_sync_change_log_source "
    "ON sync_change_log (scope_key, source_event_id) WHERE source_event_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sync_change_log_cursor "
    "ON sync_change_log (scope_key, seq)",
    "CREATE INDEX IF NOT EXISTS ix_sync_change_log_created "
    "ON sync_change_log (created_at)",
]

_MEM_LOG: dict[str, dict] = {}
_MEM_COUNTER: dict[str, int] = {}

_MEM_LOCK: Optional[asyncio.Lock] = None
_MEM_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _mem_lock() -> asyncio.Lock:
    global _MEM_LOCK, _MEM_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEM_LOCK is None or _MEM_LOCK_LOOP is not loop:
        _MEM_LOCK = asyncio.Lock()
        _MEM_LOCK_LOOP = loop
    return _MEM_LOCK


def reset_client_sync_memory() -> None:
    _MEM_LOG.clear()
    _MEM_COUNTER.clear()


def _new_id() -> str:
    return f"chg_{uuid.uuid4().hex}"


def _event_row(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "scope_key": rec["scope_key"],
        "seq": rec["seq"],
        "change_type": rec["change_type"],
        "resource_kind": rec.get("resource_kind"),
        "resource_id": rec.get("resource_id"),
        "revision": rec.get("revision"),
        "created_at": rec.get("created_at"),
    }


class ClientSyncRepository:
    """Append-only per-scope change log with a gapless monotonic cursor."""

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
        await pool.execute(SYNC_CHANGE_LOG_DDL)
        await pool.execute(SYNC_CURSOR_COUNTER_DDL)
        for idx in SYNC_INDEXES:
            await pool.execute(idx)
        self._tables_ensured = True

    async def _backend(self) -> Optional[Any]:
        pool = await self._ensure_pool()
        if pool is not None:
            await self._ensure_tables(pool)
        return pool

    async def enqueue(
        self,
        *,
        scope_key: str,
        principal_id: str,
        change_type: str,
        resource_kind: Optional[str] = None,
        resource_id: Optional[str] = None,
        revision: Optional[str] = None,
        source_event_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Append a change, idempotently on (scope_key, source_event_id).

        Returns the appended row, or None when the source_event_id was already
        logged (a no-op dedupe). Clients dedupe on ``seq`` regardless.
        """
        now = utc_now()
        row_id = _new_id()
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                if source_event_id is not None:
                    for rec in _MEM_LOG.values():
                        if rec["scope_key"] == scope_key and rec.get("source_event_id") == source_event_id:
                            return None
                seq = _MEM_COUNTER.get(scope_key, 0) + 1
                _MEM_COUNTER[scope_key] = seq
                rec = {
                    "id": row_id, "scope_key": scope_key, "principal_id": principal_id,
                    "device_id": device_id, "seq": seq, "change_type": change_type,
                    "resource_kind": resource_kind, "resource_id": resource_id,
                    "revision": revision, "source_event_id": source_event_id,
                    "created_at": to_iso_utc(now),
                }
                _MEM_LOG[row_id] = rec
                return _event_row(rec)

        seq_row = await pool.fetchrow(
            "INSERT INTO sync_cursor_counter (scope_key, next_seq) VALUES ($1, 1) "
            "ON CONFLICT (scope_key) DO UPDATE SET next_seq = sync_cursor_counter.next_seq + 1 "
            "RETURNING next_seq",
            scope_key,
        )
        seq = seq_row["next_seq"]
        inserted = await pool.fetchrow(
            """
            INSERT INTO sync_change_log (
                id, scope_key, principal_id, device_id, seq, change_type,
                resource_kind, resource_id, revision, source_event_id, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (scope_key, source_event_id) WHERE source_event_id IS NOT NULL
            DO NOTHING
            RETURNING *
            """,
            row_id, scope_key, principal_id, device_id, seq, change_type,
            resource_kind, resource_id, revision, source_event_id, now,
        )
        if inserted is None:
            return None  # dup source_event_id (seq is skipped — a harmless gap)
        rec = dict(inserted)
        rec["created_at"] = to_iso_utc(rec.get("created_at"))
        return _event_row(rec)

    async def read_since(self, scope_key: str, cursor_seq: int, limit: int = 200) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [
                _event_row(rec) for rec in _MEM_LOG.values()
                if rec["scope_key"] == scope_key and rec["seq"] > cursor_seq
            ]
            rows.sort(key=lambda r: r["seq"])
            return rows[:limit]
        rows = await pool.fetch(
            "SELECT * FROM sync_change_log WHERE scope_key = $1 AND seq > $2 "
            "ORDER BY seq ASC LIMIT $3",
            scope_key, cursor_seq, limit,
        )
        out = []
        for r in rows:
            rec = dict(r)
            rec["created_at"] = to_iso_utc(rec.get("created_at"))
            out.append(_event_row(rec))
        return out

    async def max_seq(self, scope_key: str) -> int:
        pool = await self._backend()
        if pool is None:
            return _MEM_COUNTER.get(scope_key, 0)
        row = await pool.fetchrow("SELECT next_seq FROM sync_cursor_counter WHERE scope_key = $1", scope_key)
        return row["next_seq"] if row is not None else 0

    async def min_seq(self, scope_key: str) -> int:
        """Smallest retained seq (for reset detection). 0 when the log is empty."""
        pool = await self._backend()
        if pool is None:
            seqs = [r["seq"] for r in _MEM_LOG.values() if r["scope_key"] == scope_key]
            return min(seqs) if seqs else 0
        row = await pool.fetchrow("SELECT MIN(seq) AS m FROM sync_change_log WHERE scope_key = $1", scope_key)
        return (row["m"] or 0) if row is not None else 0

    async def delete_by_principal(self, scope_key: str, principal_id: str) -> int:
        """DSR erasure — remove every ``sync_change_log`` row for a subject.

        Only the subject-identifying change rows are deleted. The
        ``sync_cursor_counter`` row is per-scope (not principal-identifying) and
        is left intact so the scope's monotonic sequence never rewinds — a reused
        seq would corrupt other principals' cursors in the same scope.
        """
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                keys = [k for k, r in _MEM_LOG.items()
                        if r["scope_key"] == scope_key and r["principal_id"] == principal_id]
                for k in keys:
                    del _MEM_LOG[k]
                return len(keys)
        result = await pool.execute(
            "DELETE FROM sync_change_log WHERE scope_key = $1 AND principal_id = $2",
            scope_key, principal_id,
        )
        return _rowcount(result)


def _rowcount(result: Any) -> int:
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


_repo: Optional[ClientSyncRepository] = None


def get_client_sync_repository() -> ClientSyncRepository:
    global _repo
    if _repo is None:
        _repo = ClientSyncRepository()
    return _repo
