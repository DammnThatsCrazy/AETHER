"""A provider outcome routed to a notification is stored on that notification.

Runs against the in-memory backend and, when ``REPOSITORY_TEST_DATABASE_URL``
(or ``DATABASE_URL``) points at a migrated database, against PostgreSQL, where
``notification_intelligence_events`` only accepts its migrated columns.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

import repositories.repos as repos  # noqa: E402
from actions.delivery.models import ExternalOutcomeEvent, ExternalOutcomeType  # noqa: E402
from actions.delivery.outcome_processor import OutcomeRouter  # noqa: E402
from repositories.repos import NotificationIntelligenceRepository  # noqa: E402

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

PG_URL = os.getenv("REPOSITORY_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(params=["inmem", "pg"])
async def backend(request, monkeypatch):
    pool = None
    if request.param == "pg":
        if asyncpg is None or not PG_URL:
            pytest.skip("REPOSITORY_TEST_DATABASE_URL not set")
        try:
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=2)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"postgres unavailable: {exc}")

    async def _pool():
        return pool

    monkeypatch.setattr(repos, "get_pool", _pool)
    try:
        yield SimpleNamespace(pool=pool)
    finally:
        if pool is not None:
            await pool.close()


class _Rows:
    def __init__(self, *rows: dict):
        self.rows = list(rows)

    async def find_many(self, filters=None, limit=100, **kw):
        return [r for r in self.rows if all(r.get(k) == v for k, v in (filters or {}).items())]

    async def update(self, record_id, data):
        return data


async def test_outcome_is_stored_in_the_notification_operator_context(backend):
    token = uuid.uuid4().hex[:10]
    tenant, notification_id = f"tenant_{token}", f"notif-{token}"
    notifications = NotificationIntelligenceRepository()
    await notifications.insert(notification_id, {
        "tenant_id": tenant,
        "deduplication_key": f"dedup-{token}",
        "source_topic": "alerts",
        "severity": "P2",
        "notification_class": "alert",
        "operator_context": {"note": "kept"},
    })
    link = {
        "tenant_id": tenant, "provider": "jira", "external_id": f"OPS-{token}",
        "aether_object_type": "notification", "aether_object_id": notification_id,
    }
    outcome = ExternalOutcomeEvent(
        tenant_id=tenant, provider="jira", external_id=link["external_id"],
        outcome_type=ExternalOutcomeType.RESOLVED, raw_payload={"event_type": "resolved"},
    )

    await OutcomeRouter(
        outcome_repo=_Rows(), link_repo=_Rows(link), notification_repo=notifications,
    ).route(outcome)

    row = await notifications.find_by_id(notification_id)
    assert row["operator_context"] == {
        "note": "kept",
        "last_external_outcome": "resolved",
        "last_outcome_at": outcome.ingested_at,
    }
    if backend.pool is not None:
        stored = await backend.pool.fetchval(
            "SELECT operator_context->>'last_external_outcome' "
            "FROM notification_intelligence_events WHERE id = $1",
            notification_id,
        )
        assert stored == "resolved"
