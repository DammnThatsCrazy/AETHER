"""The entity Silver endpoints read what the Silver writer persisted.

``AnalyticsRepository.query_silver`` backs /v1/profile/{id}/exposures,
/revenue, /friction, /accounts, /integrations and /data-quality and the gold
metrics' Silver reads. It did not exist, and every caller swallowed the
resulting error, so those endpoints always reported the source as missing.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import AnalyticsRepository, reset_in_memory_stores
from services.silver import writer as silver_writer
from services.silver.projectors.base import ProjectionResult
from shared.cache.cache import CacheClient


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    yield
    silver_writer.reset_local_tables()


def _fact(tenant: str, user: str, event: str, occurred_at: str, **extra) -> dict:
    return {
        "tenant_id": tenant, "user_id": user, "source_event_id": event,
        "idempotency_key": event, "source_event_type": "track",
        "occurred_at": occurred_at, "payload": {}, **extra,
    }


async def _seed() -> None:
    await silver_writer.SilverFactWriter().persist([ProjectionResult("silver_friction_facts", [
        _fact("t1", "u1", "e1", "2026-09-01T00:00:00+00:00"),
        _fact("t1", "u1", "e2", "2026-09-03T00:00:00+00:00"),
        _fact("t1", "u2", "e3", "2026-09-02T00:00:00+00:00"),
        _fact("t2", "u1", "e4", "2026-09-04T00:00:00+00:00"),
    ])])


async def test_reads_the_tenants_rows_for_the_entity_newest_first():
    await _seed()
    rows = await AnalyticsRepository(CacheClient()).query_silver(
        "silver_friction_facts", {"tenant_id": "t1", "user_id": "u1"}, limit=10,
    )
    assert [row["source_event_id"] for row in rows] == ["e2", "e1"]


async def test_refuses_unscoped_or_non_silver_reads():
    repo = AnalyticsRepository(CacheClient())
    with pytest.raises(ValueError):
        await repo.query_silver("silver_friction_facts", {"user_id": "u1"})
    with pytest.raises(ValueError):
        await repo.query_silver("users; DROP TABLE users", {"tenant_id": "t1"})


async def test_friction_endpoint_reports_available_rows():
    from services.profile.routes import get_entity_friction

    await _seed()
    tenant = SimpleNamespace(tenant_id="t1", require_permission=lambda *_: None)
    result = await get_entity_friction("u1", SimpleNamespace(state=SimpleNamespace(tenant=tenant)), limit=10)

    assert result["data"]["source_status"] == "available"
    assert result["data"]["count"] == 2
