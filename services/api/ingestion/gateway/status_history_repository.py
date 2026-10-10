"""Aether Gateway — durable per-component daily status rollups.

Direct-SQL repository over ``status_component_daily``, the table created by the
``20260927_status_component_daily`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim; the repository also executes it to self-ensure the
table, the same pattern as the managed-integration repositories).

One row per (UTC day, component) carries *sample counts*, not verdicts: how many
times this day a live API process evaluated the component as ``ok``,
``degraded``, ``down`` or ``unknown`` (see ``services/api/ingestion/gateway/status_history.py``
for where samples come from and how a day is scored). Counts are additive, so
any number of API processes can fold their samples into the same row with one
upsert and no coordination.

The table is platform-global and holds aggregate availability only: component
names from ``services/api/ingestion/gateway/component_status.py`` plus ``api``. It carries no
tenant identifier, hostname, request data or error text, which is what makes it
safe to serve from the unauthenticated ``GET /v1/status/history``.

Under ``AETHER_ENV=local`` with no ``DATABASE_URL`` (``get_pool()`` returns
None) the module-local in-memory store is used, so unit tests exercise the same
upsert/read semantics without a live Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

from repositories.repos import get_pool

# Must stay string-identical to the alembic migration
# ``20260927_status_component_daily.py`` (pinned by
# tests/unit/test_status_history.py).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS status_component_daily (
    day DATE NOT NULL,
    component TEXT NOT NULL,
    ok_samples INTEGER NOT NULL DEFAULT 0 CHECK (ok_samples >= 0),
    degraded_samples INTEGER NOT NULL DEFAULT 0 CHECK (degraded_samples >= 0),
    down_samples INTEGER NOT NULL DEFAULT 0 CHECK (down_samples >= 0),
    unknown_samples INTEGER NOT NULL DEFAULT 0 CHECK (unknown_samples >= 0),
    first_sample_at TIMESTAMPTZ NOT NULL,
    last_sample_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (day, component)
);
"""

# One statement per flush: every component's counts for the sample's day land
# atomically, and concurrent API processes add to (never overwrite) each other.
_UPSERT_SQL = """
INSERT INTO status_component_daily (
    day, component, ok_samples, degraded_samples, down_samples,
    unknown_samples, first_sample_at, last_sample_at
)
SELECT $1::date, t.component, t.ok, t.degraded, t.down, t.unknown, $6::timestamptz, $6::timestamptz
FROM unnest($2::text[], $3::int[], $4::int[], $5::int[], $7::int[])
    AS t(component, ok, degraded, down, unknown)
ON CONFLICT (day, component) DO UPDATE SET
    ok_samples = status_component_daily.ok_samples + EXCLUDED.ok_samples,
    degraded_samples = status_component_daily.degraded_samples + EXCLUDED.degraded_samples,
    down_samples = status_component_daily.down_samples + EXCLUDED.down_samples,
    unknown_samples = status_component_daily.unknown_samples + EXCLUDED.unknown_samples,
    first_sample_at = LEAST(status_component_daily.first_sample_at, EXCLUDED.first_sample_at),
    last_sample_at = GREATEST(status_component_daily.last_sample_at, EXCLUDED.last_sample_at)
"""

_READ_SQL = """
SELECT day, component, ok_samples, degraded_samples, down_samples, unknown_samples
FROM status_component_daily
WHERE day >= $1 AND day <= $2
ORDER BY component, day
"""

_PRUNE_SQL = "DELETE FROM status_component_daily WHERE day < $1"

# Sample vocabulary (mirrors component_status STATUS_* values).
SAMPLE_STATUSES: tuple[str, ...] = ("ok", "degraded", "down", "unknown")


@dataclass(frozen=True)
class DailyRollup:
    """Sample counts for one component on one UTC day."""

    day: date
    component: str
    ok: int = 0
    degraded: int = 0
    down: int = 0
    unknown: int = 0

    def add(self, status: str, count: int = 1) -> "DailyRollup":
        if status not in SAMPLE_STATUSES:
            raise ValueError(f"unknown status sample {status!r}")
        return replace(self, **{status: getattr(self, status) + count})


# Module-local in-memory backing store: (day, component) -> DailyRollup.
_MEMORY_STORE: dict[tuple[date, str], DailyRollup] = {}


def reset_status_history_store() -> None:
    """Test helper: empty the module-local in-memory store."""
    _MEMORY_STORE.clear()


def _count_vectors(samples: Mapping[str, str]) -> tuple[list[str], dict[str, list[int]]]:
    names = sorted(samples)
    vectors = {
        status: [1 if samples[name] == status else 0 for name in names]
        for status in SAMPLE_STATUSES
    }
    return names, vectors


class StatusHistoryRepository:
    """Platform-global store of per-component daily sample counts."""

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

    async def record(
        self,
        at: datetime,
        samples: Mapping[str, str],
        *,
        prune_before: Optional[date] = None,
    ) -> None:
        """Fold one sample per component into ``at``'s UTC day.

        ``samples`` maps component name to one of :data:`SAMPLE_STATUSES`.
        ``prune_before`` drops rollups older than that day (retention).
        """
        if at.tzinfo is None:
            raise ValueError("status samples must carry a timezone-aware timestamp")
        for name, status in samples.items():
            if status not in SAMPLE_STATUSES:
                raise ValueError(f"unknown status sample {status!r} for {name!r}")
        if not samples:
            return
        day = at.astimezone(timezone.utc).date()
        pool = await self._ensure()
        if pool is None:
            for name, status in samples.items():
                key = (day, name)
                current = _MEMORY_STORE.get(key) or DailyRollup(day=day, component=name)
                _MEMORY_STORE[key] = current.add(status)
            if prune_before is not None:
                for key in [k for k in _MEMORY_STORE if k[0] < prune_before]:
                    del _MEMORY_STORE[key]
            return
        names, vectors = _count_vectors(samples)
        await pool.execute(
            _UPSERT_SQL,
            day,
            names,
            vectors["ok"],
            vectors["degraded"],
            vectors["down"],
            at,
            vectors["unknown"],
        )
        if prune_before is not None:
            await pool.execute(_PRUNE_SQL, prune_before)

    async def read_window(self, start: date, end: date) -> list[DailyRollup]:
        """Every stored rollup with ``start <= day <= end``, by component then day."""
        pool = await self._ensure()
        if pool is None:
            rows = [r for (d, _), r in _MEMORY_STORE.items() if start <= d <= end]
            return sorted(rows, key=lambda r: (r.component, r.day))
        records = await pool.fetch(_READ_SQL, start, end)
        return [
            DailyRollup(
                day=record["day"],
                component=record["component"],
                ok=int(record["ok_samples"]),
                degraded=int(record["degraded_samples"]),
                down=int(record["down_samples"]),
                unknown=int(record["unknown_samples"]),
            )
            for record in records
        ]
