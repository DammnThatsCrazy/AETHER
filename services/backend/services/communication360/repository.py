"""Communication360FactsRepository — durable access to the Phase-3 canonical
``communication360_facts`` table.

This is the canonical-authority fact store for the read-only ``communication360``
projection (registry row ``communication360``): it persists the Phase-2 ratified
object families (``services/communication360/contracts.py``) as typed JSONB
rows and is consumed read-mostly by the Phase-4 provider and the Phase-5/6
logic (acts extraction, knowledge/context ladders, delegation authority,
provider capability/quality). The shipped message spine stays a typed read-over
of ``silver_comms_facts`` via ``services/comms`` — never duplicated here.

Production: asyncpg against PostgreSQL. Local/test: in-memory module store (same
interface, first-write-wins per ``(tenant_id, idempotency_key)`` mirroring
``ON CONFLICT ... DO NOTHING``), mirroring ``CommsFactsRepository``'s
established pattern. All queries are tenant-scoped; the fact spine is
``(tenant_id, kind, occurred_at)``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from repositories.repos import get_pool

# In-memory fallback (local/test only — production requires a pool). Keyed by
# ``{tenant_id}:{idempotency_key}`` so replay is idempotent just like the
# SQL ``ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`` path.
_local_facts: dict[str, dict[str, Any]] = {}


def reset_local_stores() -> None:
    """Test helper — clears the in-memory fallback store."""
    _local_facts.clear()


_FACT_COLUMNS: tuple[str, ...] = (
    "fact_id", "tenant_id", "kind", "source_event_id", "source_event_type",
    "actor_id", "agent_id", "occurred_at", "received_at", "idempotency_key",
    "run_id", "context_hash", "payload",
)

_JSON_COLUMNS = {"payload"}


class Communication360FactsRepository:
    """Durable storage over the ``communication360_facts`` canonical table."""

    async def _pool(self):
        return await get_pool()

    # ── Write ────────────────────────────────────────────────────────────────

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or ignore on ``(tenant_id, idempotency_key)`` conflict — replay safe.

        ``fact_id`` and ``received_at`` are defaulted when the caller omits them
        (mirroring the silver-fact repository); ``payload`` is JSON-encoded for
        the typed JSONB column. First write wins, matching
        ``ON CONFLICT ... DO NOTHING``.
        """
        row.setdefault("fact_id", str(uuid4()))
        row.setdefault("received_at", datetime.now(timezone.utc).isoformat())
        key = f"{row.get('tenant_id')}:{row.get('idempotency_key')}"

        pool = await self._pool()
        if pool is None:
            # Idempotent local write — first write wins, mirroring DO NOTHING.
            _local_facts.setdefault(key, row)
            return _local_facts[key]

        cols = [c for c in _FACT_COLUMNS if c in row]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        values = [
            json.dumps(row[c]) if c in _JSON_COLUMNS and row[c] is not None else row[c]
            for c in cols
        ]
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO communication360_facts ({', '.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                *values,
            )
        return row

    # ── Read ─────────────────────────────────────────────────────────────────

    async def query(
        self,
        tenant_id: str,
        kind: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped facts ordered by ``occurred_at`` (ascending).

        Filters compose on ``kind`` and ``occurred_at >= since`` (the Phase-5/6
        consumers scan the canonical spine chronologically); ``limit`` caps the
        page when given.
        """
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id
                and (kind is None or r.get("kind") == kind)
                and (since is None or str(r.get("occurred_at") or "") >= str(since))
            ]
            rows.sort(key=lambda r: (str(r.get("occurred_at") or ""), str(r.get("fact_id") or "")))
            if limit is not None:
                rows = rows[:limit]
            return rows

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if kind is not None:
            params.append(kind)
            conditions.append(f"kind = ${len(params)}")
        if since is not None:
            params.append(_parse_ts(since))
            conditions.append(f"occurred_at >= ${len(params)}")
        if limit is not None:
            params.append(int(limit))
            limit_clause = f" LIMIT ${len(params)}"
        else:
            limit_clause = ""
        sql = f"""
            SELECT * FROM communication360_facts
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC
            {limit_clause}
        """
        async with pool.acquire() as conn:
            records = await conn.fetch(sql, *params)
        return [dict(r) for r in records]

    async def get(self, tenant_id: str, fact_id: str) -> Optional[dict[str, Any]]:
        """Fetch one fact by its natural ``(tenant_id, fact_id)`` key."""
        pool = await self._pool()
        if pool is None:
            for r in _local_facts.values():
                if r.get("tenant_id") == tenant_id and r.get("fact_id") == fact_id:
                    return r
            return None
        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                SELECT * FROM communication360_facts
                WHERE tenant_id = $1 AND fact_id = $2
                """,
                tenant_id, fact_id,
            )
        return dict(rec) if rec else None


def _parse_ts(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value
