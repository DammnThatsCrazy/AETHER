"""
Aether Backend — Typed Table Repository

Column-typed counterpart to repositories/repos.py BaseRepository for tables
whose DDL is owned by Alembic migrations (NUMERIC(38,18) money columns, CHECK
constraints, composite UNIQUE keys) rather than auto-created JSONB documents.

Why not BaseRepository: financial domains (derivatives, stablecoin, interop)
must never round-trip canonical amounts through JSON floats. asyncpg maps
PostgreSQL NUMERIC to decimal.Decimal natively in both directions; the
in-memory local backend stores Python objects as-is, so Decimal survives
end-to-end in every environment.

Backend selection mirrors BaseRepository:
- AETHER_ENV=local              -> shared in-memory dict stores (no database)
- AETHER_ENV=staging/production -> asyncpg PostgreSQL via the shared pool

Idempotency: writes go through ``insert(...)`` which is INSERT .. ON CONFLICT
DO NOTHING on the table's conflict key (default: (tenant_id, idempotency_key)).
Corrections are new rows, never destructive updates; only explicitly mutable
state tables use ``update_by_key``.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from typing import Any, Optional, Sequence

from repositories.repos import get_pool
from shared.logger.logger import get_logger

logger = get_logger("aether.repository.typed")

# Shared in-memory stores: table_name -> list[dict] (append-ordered facts).
# One list per table across all instances, mirroring _IN_MEMORY_STORES in
# repos.py so route singletons and composers observe one consistent view.
_TYPED_IN_MEMORY_STORES: dict[str, list[dict]] = {}
_STORE_LOCK = threading.Lock()


def reset_typed_in_memory_stores() -> None:
    """Test helper: clear every typed in-memory store in place."""
    for rows in _TYPED_IN_MEMORY_STORES.values():
        rows.clear()


def _jsonb(value: Any) -> str:
    """Serialize a JSONB parameter, stringifying Decimal (evidence/extension
    payloads only — canonical amounts live in typed NUMERIC columns)."""
    return json.dumps(value, default=str)


class TypedTableRepository:
    """Typed access to one Alembic-owned table.

    Subclasses declare:
      table_name: str
      columns: tuple[str, ...]        — insertable column names, in order
      jsonb_columns: frozenset[str]   — subset of columns serialized as JSONB
      conflict_key: tuple[str, ...]   — idempotency conflict target
    """

    table_name: str = ""
    columns: tuple[str, ...] = ()
    jsonb_columns: frozenset[str] = frozenset()
    conflict_key: tuple[str, ...] = ("tenant_id", "idempotency_key")

    def __init__(self) -> None:
        if not self.table_name or not self.columns:
            raise ValueError(f"{type(self).__name__} must declare table_name and columns")
        with _STORE_LOCK:
            self._rows: list[dict] = _TYPED_IN_MEMORY_STORES.setdefault(self.table_name, [])

    # ── backend plumbing ───────────────────────────────────────────────────

    async def _pool(self) -> Optional[Any]:
        return await get_pool()

    def _conflict_signature(self, record: dict) -> tuple:
        return tuple(record.get(col) for col in self.conflict_key)

    # ── writes ─────────────────────────────────────────────────────────────

    async def insert(self, record: dict) -> bool:
        """Idempotent insert. Returns True if the row was newly inserted,
        False when the conflict key already exists (replay-safe no-op)."""
        pool = await self._pool()
        if pool is None:
            signature = self._conflict_signature(record)
            if any(self._conflict_signature(r) == signature for r in self._rows):
                return False
            self._rows.append(dict(record))
            return True

        cols = [c for c in self.columns if c in record]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        params = [
            _jsonb(record[c]) if c in self.jsonb_columns and record[c] is not None
            else record[c]
            for c in cols
        ]
        conflict = ", ".join(self.conflict_key)
        query = (
            f"INSERT INTO {self.table_name} ({', '.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO NOTHING "
            f"RETURNING 1"
        )
        row = await pool.fetchrow(query, *params)
        return row is not None

    async def insert_many(self, records: Sequence[dict]) -> int:
        inserted = 0
        for record in records:
            if await self.insert(record):
                inserted += 1
        return inserted

    async def update_by_key(
        self, key_filters: dict, changes: dict,
    ) -> bool:
        """Update mutable state columns on rows matching key_filters exactly.

        Reserved for current-state tables (registries, checkpoints, message
        projections). Fact tables must append correction rows instead.
        """
        forbidden = set(changes) & set(self.conflict_key)
        if forbidden:
            raise ValueError(f"refusing to update conflict-key columns: {sorted(forbidden)}")
        pool = await self._pool()
        if pool is None:
            updated = False
            for row in self._rows:
                if all(row.get(k) == v for k, v in key_filters.items()):
                    row.update({k: v for k, v in changes.items()})
                    updated = True
            return updated

        set_clauses = []
        params: list[Any] = []
        idx = 1
        for col, value in changes.items():
            self._require_column(col)
            set_clauses.append(f"{col} = ${idx}")
            params.append(_jsonb(value) if col in self.jsonb_columns and value is not None else value)
            idx += 1
        set_clauses.append("updated_at = NOW()")
        where_clauses = []
        for col, value in key_filters.items():
            self._require_column(col)
            where_clauses.append(f"{col} = ${idx}")
            params.append(value)
            idx += 1
        query = (
            f"UPDATE {self.table_name} SET {', '.join(set_clauses)} "
            f"WHERE {' AND '.join(where_clauses)}"
        )
        status = await pool.execute(query, *params)
        return not status.endswith(" 0")

    # ── reads ──────────────────────────────────────────────────────────────

    def _require_column(self, col: str) -> None:
        if col not in self.columns and col not in ("created_at", "updated_at"):
            raise ValueError(f"unknown column for {self.table_name}: {col!r}")

    async def find_many(
        self,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> list[dict]:
        pool = await self._pool()
        if pool is None:
            results = [
                dict(r) for r in self._rows
                if not filters or all(r.get(k) == v for k, v in filters.items())
            ]
            results.sort(key=lambda r: (r.get(order_by) is None, r.get(order_by)), reverse=descending)
            return results[offset: offset + limit]

        conditions = ["1=1"]
        params: list[Any] = []
        idx = 1
        for col, value in (filters or {}).items():
            self._require_column(col)
            conditions.append(f"{col} = ${idx}")
            params.append(value)
            idx += 1
        self._require_column(order_by)
        direction = "DESC" if descending else "ASC"
        query = (
            f"SELECT {', '.join(self.columns)} FROM {self.table_name} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY {order_by} {direction} LIMIT ${idx} OFFSET ${idx + 1}"
        )
        params.extend([limit, offset])
        rows = await pool.fetch(query, *params)
        return [self._decode_row(dict(row)) for row in rows]

    async def find_one(self, filters: dict[str, Any]) -> Optional[dict]:
        rows = await self.find_many(filters, limit=1)
        return rows[0] if rows else None

    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        pool = await self._pool()
        if pool is None:
            return len([
                r for r in self._rows
                if not filters or all(r.get(k) == v for k, v in filters.items())
            ])
        conditions = ["1=1"]
        params: list[Any] = []
        idx = 1
        for col, value in (filters or {}).items():
            self._require_column(col)
            conditions.append(f"{col} = ${idx}")
            params.append(value)
            idx += 1
        row = await pool.fetchrow(
            f"SELECT COUNT(*) AS n FROM {self.table_name} WHERE {' AND '.join(conditions)}",
            *params,
        )
        return int(row["n"]) if row else 0

    async def distinct_tenant_ids(self, limit: int = 10000) -> list[str]:
        """Distinct tenant_ids present in this table (cross-tenant enumeration).

        Mirrors ``BaseRepository.distinct_tenant_ids`` for Alembic-owned typed
        tables (interop provider checkpoints, derivatives connector checkpoints):
        supervised workers that must scan/sweep *every* tenant (rather than a
        single process-wide default) discover their working set from real
        persisted state. Legacy unscoped rows (``tenant_id`` null/empty) are
        excluded — they are not tenants. Order is deterministic (ascending
        tenant_id) for reproducible passes.
        """
        pool = await self._pool()
        if pool is None:
            seen: list[str] = []
            for row in self._rows:
                tid = row.get("tenant_id")
                if tid and tid not in seen:
                    seen.append(tid)
            return seen[:limit]
        rows = await pool.fetch(
            f"SELECT DISTINCT tenant_id FROM {self.table_name} "
            "WHERE tenant_id IS NOT NULL AND tenant_id <> '' "
            "ORDER BY tenant_id LIMIT $1",
            limit,
        )
        return [r["tenant_id"] for r in rows]

    def _decode_row(self, row: dict) -> dict:
        for col in self.jsonb_columns:
            value = row.get(col)
            if isinstance(value, str):
                try:
                    row[col] = json.loads(value)
                except (TypeError, ValueError):
                    pass
        return row


def as_decimal(value: Any) -> Decimal:
    """Coerce an incoming canonical amount to Decimal without float transit.

    Accepts Decimal, int, and numeric strings. Rejects float outright —
    binary floating point is never a legal carrier for canonical finance.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a canonical amount")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise TypeError(
            "float is not a legal canonical amount — pass a Decimal or string"
        )
    if isinstance(value, str) and value.strip():
        return Decimal(value.strip())
    raise TypeError(f"cannot coerce {type(value).__name__} to Decimal")
