"""New canonical activity recompiles its journey (flag JOURNEY_ACTIVITY_REBUILD_ENABLED)."""
from __future__ import annotations

import dataclasses

import pytest

from journeys.measurement import activity_rebuild
from journeys.measurement.activity_rebuild import ActivityJourneyRebuilder, identity_for_activity



@pytest.fixture
def compiled(monkeypatch):
    calls = []

    class FakeCompiler:
        async def compile_for_profile(self, tenant_id, identity_id, **kw):
            calls.append((tenant_id, kw["identity_type"], identity_id, kw["trigger_reason"]))
            return {"journey_id": f"j-{identity_id}"}

    from journeys.measurement.engine import journey_compiler

    monkeypatch.setattr(journey_compiler, "JourneyCompiler", FakeCompiler)
    return calls


@pytest.fixture
def flag(monkeypatch):
    from config.settings import settings

    def set_flag(value: bool):
        monkeypatch.setattr(
            settings, "identity_continuity",
            dataclasses.replace(settings.identity_continuity, journey_activity_rebuild_enabled=value),
        )
    return set_flag


def test_most_specific_identity_owns_the_activity():
    assert identity_for_activity({"profile_id": "p", "cluster_id": "c", "anonymous_id": "a"}) == ("profile", "p")
    assert identity_for_activity({"cluster_id": "c", "anonymous_id": "a"}) == ("cluster", "c")
    assert identity_for_activity({"anonymous_id": "a"}) == ("anonymous", "a")
    assert identity_for_activity({}) is None


@pytest.mark.asyncio
async def test_bursts_for_one_identity_compile_once(compiled):
    rebuilder = ActivityJourneyRebuilder(window_seconds=60)
    for _ in range(5):
        assert await rebuilder.request("t1", "anonymous", "a1")
    await rebuilder.request("t1", "profile", "p1")
    assert rebuilder.pending_count == 2
    assert await rebuilder.flush_all() == 2
    assert sorted(compiled) == [
        ("t1", "anonymous", "a1", "activity_received"),
        ("t1", "profile", "p1", "activity_received"),
    ]


@pytest.mark.asyncio
async def test_pending_set_is_bounded(compiled):
    rebuilder = ActivityJourneyRebuilder(window_seconds=60, max_pending=1)
    assert await rebuilder.request("t1", "anonymous", "a1")
    assert not await rebuilder.request("t1", "anonymous", "a2")
    await rebuilder.flush_all()


@pytest.mark.asyncio
async def test_compile_failure_is_contained(monkeypatch):
    class Boom:
        async def compile_for_profile(self, *a, **k):
            raise RuntimeError("db down")

    from journeys.measurement.engine import journey_compiler

    monkeypatch.setattr(journey_compiler, "JourneyCompiler", Boom)
    rebuilder = ActivityJourneyRebuilder(window_seconds=60)
    await rebuilder.request("t1", "anonymous", "a1")
    assert await rebuilder.flush_all() == 0
    assert rebuilder.pending_count == 0


@pytest.mark.asyncio
async def test_flag_off_requests_nothing(flag, monkeypatch):
    flag(False)
    monkeypatch.setattr(activity_rebuild, "_rebuilder", ActivityJourneyRebuilder(window_seconds=60))
    assert await activity_rebuild.request_for_activities([{"tenant_id": "t", "anonymous_id": "a"}]) == 0


@pytest.mark.asyncio
async def test_flag_on_requests_one_per_identity(flag, monkeypatch, compiled):
    flag(True)
    rebuilder = ActivityJourneyRebuilder(window_seconds=60)
    monkeypatch.setattr(activity_rebuild, "_rebuilder", rebuilder)
    n = await activity_rebuild.request_for_activities([
        {"tenant_id": "t", "anonymous_id": "a"},
        {"tenant_id": "t", "anonymous_id": "a"},
        {"tenant_id": "t", "anonymous_id": "a", "profile_id": "p"},
        {"anonymous_id": "no-tenant"},
    ])
    assert n == 2
    await rebuilder.flush_all()
    assert sorted(c[1:3] for c in compiled) == [("anonymous", "a"), ("profile", "p")]


@pytest.mark.asyncio
async def test_silver_emit_requests_a_rebuild_for_upserted_activity(flag, monkeypatch, compiled):
    from ingestion.silver.projectors.base import BaseProjector
    from journeys.measurement import silver_adapters
    from journeys.measurement.repositories import activity_repo

    flag(True)
    rebuilder = ActivityJourneyRebuilder(window_seconds=60)
    monkeypatch.setattr(activity_rebuild, "_rebuilder", rebuilder)
    monkeypatch.setattr(silver_adapters, "adapt_from_silver",
                        lambda table, row: {**row, "idempotency_key": row["id"]})

    async def no_pool(self):
        return None

    monkeypatch.setattr(activity_repo.ActivityRepository, "_pool", no_pool)
    await BaseProjector()._emit_to_canonical_activity(
        "silver_x", [{"id": "r1", "tenant_id": "t", "anonymous_id": "a"}],
    )
    assert rebuilder.pending_count == 1
    await rebuilder.flush_all()
    assert compiled == [("t", "anonymous", "a", "activity_received")]
    activity_repo._local_store.pop("t:r1", None)
