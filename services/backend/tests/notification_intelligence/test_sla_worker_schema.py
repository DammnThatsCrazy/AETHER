"""Regression: the notification SLA worker against the MIGRATED schema.

``notification_intelligence_events`` (``20260529_notification_intelligence``)
has ``detected_at`` / ``expires_at`` / ``updated_at`` but NO ``created_at``.
The lean-worker logged ``sla_worker_error: column "created_at" does not
exist`` every minute because ``BaseRepository.find_many`` defaulted
``sort_by="created_at"`` — a value in its allow-list, so the repository's
``_default_sort = "detected_at"`` override never applied. The expire path had
the same class of bug on write: ``update``/``insert`` stamped a ``created_at``
the table lacks and bound ISO-8601 *strings* to ``timestamptz`` columns,
which asyncpg rejects.

``_SchemaPool`` below enforces what Postgres + asyncpg enforce for the SQL
these paths issue: every referenced column must exist in the migrated table,
and ``timestamptz`` parameters must be ``datetime`` instances.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import repositories.repos as repos
from repositories.repos import NotificationIntelligenceRepository
from services.notification_intelligence import lifecycle

# Column → information_schema.data_type, exactly as
# alembic/versions/20260529_notification_intelligence.py creates the table.
_NIE_COLUMNS: dict[str, str] = {
    "id": "text",
    "tenant_id": "text",
    "deduplication_key": "text",
    "idempotency_key": "text",
    "source_topic": "text",
    "source_event_id": "text",
    "source_service": "text",
    "correlation_id": "text",
    "lifecycle_state": "text",
    "severity": "text",
    "notification_class": "text",
    "title": "text",
    "body": "text",
    "what": "text",
    "why": "text",
    "impact": "text",
    "recommended_action": "text",
    "reversible": "boolean",
    "deep_link": "text",
    "routing_policy": "jsonb",
    "slack_payload": "jsonb",
    "operator_context": "jsonb",
    "graph_propagation": "jsonb",
    "audit_trail": "jsonb",
    "detected_at": "timestamp with time zone",
    "expires_at": "timestamp with time zone",
    "updated_at": "timestamp with time zone",
}


class _UndefinedColumn(Exception):
    pass


class _SchemaPool:
    """Minimal asyncpg-pool double that enforces the migrated schema."""

    def __init__(self, table: str, columns: dict[str, str]) -> None:
        self.table = table
        self.columns = columns
        self.rows: dict[str, dict[str, Any]] = {}
        self.statements: list[str] = []

    def _check_param_types(self, cols: list[str], values: tuple) -> None:
        for col, value in zip(cols, values):
            if col not in self.columns:
                raise _UndefinedColumn(f'column "{col}" does not exist')
            if (
                self.columns[col] == "timestamp with time zone"
                and value is not None
                and not isinstance(value, datetime)
            ):
                raise TypeError(
                    f"invalid input for {col}: {value!r} (expected a "
                    "datetime.date or datetime.datetime instance, got "
                    f"{type(value).__name__!r})"
                )

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.statements.append(query)
        if "information_schema.columns" in query:
            if args[0] != self.table:
                return []
            return [
                {"column_name": c, "data_type": t} for c, t in self.columns.items()
            ]
        order = re.search(r"ORDER BY (\w+)", query)
        if order and order.group(1) not in self.columns:
            raise _UndefinedColumn(f'column "{order.group(1)}" does not exist')
        filters = re.findall(r"(\w+) = \$(\d+)", query)
        rows = []
        for row in self.rows.values():
            if all(str(row.get(col)) == str(args[int(i) - 1]) for col, i in filters):
                rows.append(dict(row))
        return rows

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.statements.append(query)
        row = self.rows.get(args[0])
        return dict(row) if row else None

    async def execute(self, query: str, *args: Any) -> str:
        self.statements.append(query)
        if query.lstrip().startswith("UPDATE"):
            assignments = re.findall(r"(\w+) = \$(\d+)", query.split("WHERE")[0])
            cols = [c for c, _ in assignments]
            self._check_param_types(cols, tuple(args[int(i) - 1] for _, i in assignments))
            row_id = args[-1]
            for col, i in assignments:
                self.rows[row_id][col] = args[int(i) - 1]
            return "UPDATE 1"
        if query.lstrip().startswith("INSERT"):
            cols = [
                c.strip()
                for c in re.search(r"\(([^)]*)\)\s*VALUES", query).group(1).split(",")
            ]
            self._check_param_types(cols, args)
            self.rows[args[cols.index("id")]] = dict(zip(cols, args))
            return "INSERT 0 1"
        return "OK"


@pytest.fixture
def schema_pool(monkeypatch):
    monkeypatch.setattr(repos, "_EXPLICIT_COLUMN_TYPES", {}, raising=False)
    return _SchemaPool("notification_intelligence_events", _NIE_COLUMNS)


def _repo(pool: _SchemaPool) -> NotificationIntelligenceRepository:
    repo = NotificationIntelligenceRepository()
    repo._pool = pool
    return repo


@pytest.mark.asyncio
async def test_unsorted_find_many_orders_by_detected_at(schema_pool):
    repo = _repo(schema_pool)

    await repo.find_many(filters={"lifecycle_state": "operator_review"})

    select = next(s for s in schema_pool.statements if "SELECT *" in s)
    assert "ORDER BY detected_at" in select
    assert "created_at" not in select


@pytest.mark.asyncio
async def test_explicit_created_at_sort_falls_back_to_default(schema_pool):
    repo = _repo(schema_pool)

    await repo.find_many(sort_by="created_at")

    select = next(s for s in schema_pool.statements if "SELECT *" in s)
    assert "ORDER BY detected_at" in select


@pytest.mark.asyncio
async def test_insert_and_update_bind_migrated_columns(schema_pool):
    repo = _repo(schema_pool)
    now = datetime.now(timezone.utc)

    await repo.create({
        "id": "n1",
        "tenant_id": "t1",
        "deduplication_key": "d1",
        "source_topic": "intel.anomaly",
        "lifecycle_state": "operator_review",
        "severity": "P1",
        "notification_class": "anomaly",
        "audit_trail": [],
        "detected_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
    })
    stored = schema_pool.rows["n1"]
    assert "created_at" not in stored
    assert isinstance(stored["detected_at"], datetime)
    assert isinstance(stored["updated_at"], datetime)

    await repo.update("n1", {"lifecycle_state": "expired"})
    assert schema_pool.rows["n1"]["lifecycle_state"] == "expired"
    assert isinstance(schema_pool.rows["n1"]["expires_at"], datetime)


@pytest.mark.asyncio
async def test_sla_worker_expires_overdue_review_without_errors(
    schema_pool, monkeypatch
):
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    schema_pool.rows["n-overdue"] = {
        "id": "n-overdue",
        "tenant_id": "t1",
        "deduplication_key": "d-overdue",
        "source_topic": "intel.anomaly",
        "lifecycle_state": "operator_review",
        "severity": "P1",
        "notification_class": "anomaly",
        "audit_trail": "[]",
        "detected_at": past - timedelta(minutes=5),
        "expires_at": past,
        "updated_at": past,
    }
    warnings: list[str] = []
    monkeypatch.setattr(
        lifecycle.logger, "warning", lambda msg, *a, **k: warnings.append(msg % a)
    )

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(lifecycle.asyncio, "sleep", _stop)

    with pytest.raises(asyncio.CancelledError):
        await lifecycle.start_sla_worker(repo=_repo(schema_pool))

    assert warnings == []
    assert schema_pool.rows["n-overdue"]["lifecycle_state"] == "expired"
