"""Silver fact writer — persists ProjectionResults on the durable write path.

The dispatcher produces rows; this writer stores them:

- ``silver_comms_facts``               → CommsFactsRepository
- ``silver_campaign_touchpoint_facts`` → TouchpointRepository
- the six ``silver_social_*_facts`` tables (M3 Social Silver plane, the
  ``social_*_observed`` projectors) → their named repositories in
  ``services/silver/repositories/social_facts.py``
- other silver tables                  → generic idempotent insert
  (column set AND column types introspected once per table and cached;
  unknown row keys are dropped rather than failing the write; ON CONFLICT DO
  NOTHING keeps replays safe).

Type coercion at the generic-insert boundary: projectors build rows from the
Bronze event dict, so timestamps arrive as ISO-8601 strings, JSON-shaped
values as Python lists/dicts and money as strings/floats. asyncpg binds
parameters by the *column* type and rejects those shapes outright ("expected
a datetime.date or datetime.datetime instance, got 'str'", "expected str, got
list"). ``_coerce_value`` therefore converts each value to the representation
its introspected Postgres type requires — aware ``datetime`` for
``timestamptz``, JSON text for ``json``/``jsonb``, ``Decimal`` for
``numeric`` (via ``str()``, never binary float), ``int``/``bool`` for
integer/boolean columns — and raises a ``ValueError`` naming the column for a
value that cannot be represented, so a bad row fails loudly instead of being
persisted with a fabricated value.

Local/test (no pool): rows land in per-table in-memory stores with the same
first-write-wins semantics.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.logger.logger import get_logger, metrics
from repositories.repos import get_pool
from services.silver.projectors.base import ProjectionResult
from shared.temporal.instant import coerce_utc_lenient

logger = get_logger("aether.silver.writer")

_local_tables: dict[str, dict[str, dict[str, Any]]] = {}
# table -> ((column_name, data_type), ...) in ordinal order.
_column_cache: dict[str, tuple[tuple[str, str], ...]] = {}

_JSON_TYPES = frozenset({"json", "jsonb"})
_TIMESTAMPTZ_TYPES = frozenset({"timestamp with time zone"})
_INTEGER_TYPES = frozenset({"smallint", "integer", "bigint"})
_NUMERIC_TYPES = frozenset({"numeric", "decimal"})
_FLOAT_TYPES = frozenset({"real", "double precision"})
_TEXT_TYPES = frozenset({"text", "character varying", "character"})
_TRUE_STRINGS = frozenset({"true", "t", "1", "yes", "y", "on"})
_FALSE_STRINGS = frozenset({"false", "f", "0", "no", "n", "off"})

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
                typed = [(c, t) for c, t in columns if c in row]
                if not typed:
                    continue
                cols = [c for c, _ in typed]
                values = [_coerce_value(table, c, t, row[c]) for c, t in typed]
                placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
                await conn.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
                    "ON CONFLICT DO NOTHING",
                    *values,
                )
                written += 1
        return written

    async def _table_columns(
        self, pool: Any, table: str
    ) -> tuple[tuple[str, str], ...]:
        if table in _column_cache:
            return _column_cache[table]
        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_name = $1 AND table_schema = current_schema()
                ORDER BY ordinal_position
                """,
                table,
            )
        _column_cache[table] = tuple(
            (r["column_name"], r["data_type"]) for r in records
        )
        return _column_cache[table]


def _parse_timestamp(value: Any) -> datetime:
    """ISO-8601 string / ``datetime`` → timezone-aware UTC ``datetime``.

    Delegates to the temporal kernel's lenient event-time rule
    (:func:`shared.temporal.instant.coerce_utc_lenient`) — the same
    accept/reject rule ``BaseEvent.validate_timestamp`` applies at ingestion
    (naive values are assumed UTC) — so Silver accepts exactly what Bronze
    accepted. Unparseable input raises instead of fabricating ``now()``.
    """
    if isinstance(value, bool) or not isinstance(value, (str, datetime)):
        raise ValueError(f"{type(value).__name__} is not an ISO-8601 timestamp")
    parsed = coerce_utc_lenient(value)
    if parsed is None:
        raise ValueError(f"{value!r} is not an ISO-8601 timestamp")
    return parsed


def _coerce_value(table: str, column: str, data_type: str, value: Any) -> Any:
    """Convert ``value`` to the Python type asyncpg binds for ``data_type``.

    Raises ``ValueError`` (naming the table/column) when the value cannot be
    represented in the column type; ``None`` always passes through as NULL.
    """
    if value is None:
        return None
    try:
        if data_type in _JSON_TYPES:
            return json.dumps(value, default=str)
        if data_type in _TIMESTAMPTZ_TYPES:
            return _parse_timestamp(value)
        if data_type == "date":
            if isinstance(value, date):
                return value.date() if isinstance(value, datetime) else value
            return date.fromisoformat(str(value).strip()[:10])
        if data_type in _NUMERIC_TYPES:
            if isinstance(value, bool):
                raise ValueError("boolean is not numeric")
            if isinstance(value, Decimal):
                return value
            # str() — never Decimal(float) — so 0.1 stays 0.1, not a binary
            # float artefact (docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md).
            return Decimal(str(value).strip())
        if data_type in _FLOAT_TYPES:
            if isinstance(value, bool):
                raise ValueError("boolean is not numeric")
            return float(value)
        if data_type in _INTEGER_TYPES:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            number = Decimal(str(value).strip())
            if number != number.to_integral_value():
                raise ValueError(f"{value!r} is not an integer")
            return int(number)
        if data_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float, Decimal)):
                return bool(value)
            lowered = str(value).strip().lower()
            if lowered in _TRUE_STRINGS:
                return True
            if lowered in _FALSE_STRINGS:
                return False
            raise ValueError(f"{value!r} is not a boolean")
        if data_type in _TEXT_TYPES:
            if isinstance(value, str):
                return value
            if isinstance(value, (dict, list, tuple)):
                return json.dumps(value, default=str)
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            return str(value)
        if data_type == "uuid":
            # Validate here so a non-UUID id fails with a coercion error that
            # names the column, not an opaque driver DataError.
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value).strip())
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise ValueError(
            f"cannot coerce {table}.{column} ({data_type}) from "
            f"{type(value).__name__} {value!r}: {exc}"
        ) from exc
    # ARRAY / other types: asyncpg binds the Python value directly.
    return value
