"""Pattern discovery against PostgreSQL with the real migration.

Runs when ``PATTERN_DISCOVERY_TEST_DSN`` is set (skips otherwise). Applies the
``20261114_pattern_discovery_stores`` migration's own SQL, points the four
repositories at the pool, and drives the service end to end: indexed queue
and entity reads, compare-and-set reviews, promotion and DSR erasure.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

from intelligence.pattern_discovery.baselines import PatternBaselineRepository
from intelligence.pattern_discovery.contracts import KIND_SHARED_ATTRIBUTE
from intelligence.pattern_discovery.erasure import erase_pattern_discovery
from intelligence.pattern_discovery.registry import (
    PatternDiscoveryRunRepository, PatternFeedbackRepository, PatternRegistryRepository,
)
from intelligence.pattern_discovery.service import PatternDiscoveryService

from .scenarios import T, FakeEventReader, FakeRiskStore, consent_reader, fraud_ring, normal_traffic

DSN = os.environ.get("PATTERN_DISCOVERY_TEST_DSN")
MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261114_pattern_discovery_stores.py"
pytestmark = pytest.mark.skipif(not DSN, reason="PATTERN_DISCOVERY_TEST_DSN not set")


def _statements() -> tuple[list[str], list[str]]:
    captured: dict[str, list[str]] = {"up": [], "down": []}

    class _Op:
        current = "up"

        @staticmethod
        def execute(sql: str) -> None:
            captured[_Op.current].append(sql)

    fake = types.ModuleType("alembic")
    fake.op = _Op
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = fake
    try:
        spec = importlib.util.spec_from_file_location("pd_migration", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            del sys.modules["alembic"]
    module.upgrade()
    _Op.current = "down"
    module.downgrade()
    return captured["up"], captured["down"]


@pytest.fixture
async def pool():
    import asyncpg

    up, down = _statements()
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4)
    async with pool.acquire() as conn:
        for sql in down:
            await conn.execute(sql)
        for sql in up:
            await conn.execute(sql)
    yield pool
    await pool.close()


def _service(pool, rows, risk_store=None):
    repos = [PatternRegistryRepository(), PatternBaselineRepository(), PatternFeedbackRepository(),
             PatternDiscoveryRunRepository()]
    for repo in repos:
        repo._pool = pool
        repo._table_ensured = True  # the migration created the tables

    async def resolver(tenant_id, key):
        return ("entity", key.split(":", 1)[1])

    return PatternDiscoveryService(
        registry=repos[0], baselines=repos[1], feedback=repos[2], runs=repos[3],
        event_reader=FakeEventReader(rows), risk_store=risk_store or FakeRiskStore(),
        subject_resolver=resolver, consent_reader=consent_reader(),
    )


async def test_end_to_end_on_postgres(pool, monkeypatch):
    svc = _service(pool, normal_traffic(1, 1))
    await svc.run(T)
    svc._event_reader = FakeEventReader(normal_traffic(2, 2) + fraud_ring(2))
    run = await svc.run(T)
    assert run["patterns_detected"] >= 5

    queue = await svc.list_patterns(T, queue=True)
    assert queue["total"] >= 5
    async with pool.acquire() as conn:
        stored = await conn.fetchval("SELECT count(*) FROM discovered_patterns WHERE tenant_id = $1", T)
        plan = "\n".join(r[0] for r in await conn.fetch(
            "EXPLAIN SELECT data FROM discovered_patterns WHERE tenant_id = 'x' "
            "AND data->'affected_entity_keys' ? 'user:r0'"))
    assert stored == run["patterns_detected"]
    assert "discovered_patterns" in plan

    ctx = await svc.entity_context(T, "user:r0")
    assert ctx["withheld"] is False and ctx["counts"]["open"] >= 4

    pid = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]["pattern_id"]
    reviewed = await svc.review(T, pid, reviewer_id="a", verdict="malicious", reason="card farm confirmed on pg")
    assert reviewed["revision"] >= 2
    promoted = await svc.promote(T, pid, reviewer_id="a", reason="standing risk signal on postgres")
    assert promoted["status"] == "promoted"
    assert (await svc.stats(T))["feedback"]["total"] == 1

    # Re-detection merges into the same rows (no duplicates) and keeps the promotion.
    await svc.run(T)
    async with pool.acquire() as conn:
        again = await conn.fetchval("SELECT count(*) FROM discovered_patterns WHERE tenant_id = $1", T)
    assert again == stored
    assert (await svc.registry.get(T, pid))["status"] == "promoted"

    monkeypatch.setattr("intelligence.pattern_discovery.erasure.PatternRegistryRepository",
                        lambda: svc.registry, raising=False)
    from intelligence.pattern_discovery import registry as reg_mod

    monkeypatch.setattr(reg_mod, "PatternRegistryRepository", lambda: svc.registry)
    monkeypatch.setattr(reg_mod, "PatternDiscoveryRunRepository", lambda: svc.runs)
    out = await erase_pattern_discovery(T, frozenset({"r0"}))
    assert out["status"] == "completed" and out["records_impacted"] >= 1
    assert (await svc.registry.for_entity(T, "user:r0")) == []


async def test_check_constraint_rejects_cross_tenant_rows(pool):
    import asyncpg

    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO discovered_patterns (id, data, tenant_id) VALUES ('x', '{\"tenant_id\": \"a\"}', 'b')"
            )
