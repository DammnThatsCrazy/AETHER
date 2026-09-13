"""Silver fact writer — persists ProjectionResults on the durable write path.

The dispatcher produces rows; this writer stores them:

- ``silver_comms_facts``               → CommsFactsRepository
- ``silver_campaign_touchpoint_facts`` → TouchpointRepository
- the six ``silver_social_*_facts`` tables (M3 Social Silver plane, the
  ``social_*_observed`` projectors) → their named repositories in
  ``services/silver/repositories/social_facts.py``
- other silver tables                  → generic idempotent insert
  (column set introspected once per table and cached; unknown row keys are
  dropped rather than failing the write; ON CONFLICT DO NOTHING keeps
  replays safe).

Local/test (no pool): rows land in per-table in-memory stores with the same
first-write-wins semantics.
"""

from __future__ import annotations

import json
from typing import Any

from shared.logger.logger import get_logger, metrics
from repositories.repos import get_pool
from services.silver.projectors.base import ProjectionResult

logger = get_logger("aether.silver.writer")

_local_tables: dict[str, dict[str, dict[str, Any]]] = {}
_column_cache: dict[str, tuple[str, ...]] = {}

_JSON_LIKE_KEYS = {"payload", "provenance", "properties"}

# Social Silver (M3) tables routed to named repositories — the six tables the
# social_*_observed projectors write (see services/silver/repositories/social_facts.py).
_SOCIAL_FACT_TABLES = frozenset({
    "silver_social_identity_facts",
    "silver_social_connection_facts",
    "silver_social_interaction_facts",
    "silver_social_content_facts",
    "silver_social_community_facts",
    "silver_social_metric_facts",
})


def reset_local_tables() -> None:
    """Test helper — clears generic in-memory silver stores."""
    _local_tables.clear()


class SilverFactWriter:
    """Persists projector output rows idempotently."""

    async def persist(self, results: list[ProjectionResult]) -> int:
        written = 0
        for result in results:
            if result.skipped or not result.rows:
                continue
            try:
                written += await self._persist_result(result)
            except Exception as exc:
                metrics.increment(
                    "silver_write_failures_total", labels={"table": result.table}
                )
                logger.error(
                    "silver_write_failed table=%s error=%s", result.table, exc,
                )
        return written

    async def _persist_result(self, result: ProjectionResult) -> int:
        if result.table == "silver_comms_facts":
            from services.comms.repository import CommsFactsRepository
            repo = CommsFactsRepository()
            for row in result.rows:
                await repo.upsert(row)
            return len(result.rows)

        if result.table == "silver_campaign_touchpoint_facts":
            from services.measurement.repositories.touchpoint_repo import TouchpointRepository
            repo = TouchpointRepository()
            for row in result.rows:
                await repo.upsert(row)
            return len(result.rows)

        if result.table in _SOCIAL_FACT_TABLES:
            from services.silver.repositories.social_facts import (
                SOCIAL_FACT_REPOSITORY_BY_TABLE,
            )
            repo = SOCIAL_FACT_REPOSITORY_BY_TABLE[result.table]()
            for row in result.rows:
                await repo.upsert(row)
            return len(result.rows)

        return await self._persist_generic(result.table, result.rows)

    async def _persist_generic(self, table: str, rows: list[dict[str, Any]]) -> int:
        pool = await get_pool()
        if pool is None:
            store = _local_tables.setdefault(table, {})
            for row in rows:
                key = f"{row.get('tenant_id')}:{row.get('idempotency_key') or row.get('source_event_id')}"
                store.setdefault(key, row)
            return len(rows)

        columns = await self._table_columns(pool, table)
        if not columns:
            logger.warning("silver_write_unknown_table table=%s", table)
            return 0

        written = 0
        async with pool.acquire() as conn:
            for row in rows:
                cols = [c for c in columns if c in row]
                if not cols:
                    continue
                values = [
                    json.dumps(row[c]) if c in _JSON_LIKE_KEYS and row[c] is not None
                    else row[c]
                    for c in cols
                ]
                placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
                await conn.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
                    "ON CONFLICT DO NOTHING",
                    *values,
                )
                written += 1
        return written

    async def _table_columns(self, pool: Any, table: str) -> tuple[str, ...]:
        if table in _column_cache:
            return _column_cache[table]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = $1 AND table_schema = current_schema()
                """,
                table,
            )
        _column_cache[table] = tuple(r["column_name"] for r in records)
        return _column_cache[table]
