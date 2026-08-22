"""Real-stack ingestion idempotency/concurrency tests — Phase-2 Program 4, M2.

See docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md, section
"4. A production-equivalent CI lane". M2 is: "Migrate the ingestion test suite
to run against the real stack; fix whatever concurrency assumptions the
in-memory-only tests were implicitly making."

WHAT THE IN-MEMORY SUITE PROVES — AND SILENTLY ASSUMES
------------------------------------------------------
``tests/unit/test_ingestion_v2.py`` exercises ``ingest_many``'s idempotency by
calling it SEQUENTIALLY (ingest, then re-ingest, assert 'duplicate'). Under
AETHER_ENV=local, ``repositories.repos.get_pool()`` returns ``None`` and
``ingest_many`` takes the in-memory ``_memory_commit`` branch, whose
"is this key already present? -> stage -> apply" critical section contains NO
``await``. On a single-threaded asyncio loop a non-awaiting section can never be
preempted, so the dict fallback gets exactly-once "right" for FREE: cooperative
scheduling — not any real concurrency control — is what serializes the writers.
The in-memory suite never races two writers, and implicitly ASSUMES it never
has to. That assumption is the concurrency assumption M2 names.

Production has no such guarantee. Two ``/v1/batch`` requests carrying the same
idempotency key land on DIFFERENT asyncpg pool connections in DIFFERENT
transactions that genuinely race. Exactly-once then depends entirely on the
REAL ``ux_bronze_sdk_events_key`` UNIQUE index + ``INSERT ... ON CONFLICT
(tenant_id, event_id, schema_version) DO NOTHING RETURNING`` (and the matching
``ux_event_outbox_key`` on the outbox) — the exact machinery the in-memory
branch bypasses. These tests remove the free serialization by launching
genuinely-concurrent ``ingest_many`` calls (``asyncio.gather``, one pooled
connection + transaction each) against real Postgres and asserting that the DB —
not a dict that never yields — is what enforces exactly-once.

COVERAGE (M2, honest bounds)
----------------------------
Covered here now (the WRITE side of the ingestion round-trip under real races):
  * Concurrent ingest of the SAME single idempotency key -> exactly one
    'accepted', the rest 'duplicate', exactly one durable bronze row + one
    outbox row (verified via an INDEPENDENT connection). Real ON CONFLICT.
  * Concurrent ingest of the SAME multi-key batch -> every key accepted exactly
    once across all racers, exactly K bronze + K outbox rows. Real ON CONFLICT
    generalized to the overlapping-batch (retry-storm) shape.
The sequential real-pool round-trip (write -> independent read-back -> cross-
request dedup) is already covered by tests/prod_equivalent/test_real_stack_smoke.py
(M1); this file adds only the under-concurrency property.

Deliberately NOT covered here (later, separately-scoped milestones — see the
program doc): the outbox RELAY / drain path and the kafka publish (M3), and the
measurement / attribution suites (M4).

Contract with the fast local lane: every test SKIPS (never fails, never errors)
when DATABASE_URL is unset, so AETHER_ENV=local / ``make ci-check`` is
unaffected. It runs only under .github/workflows/production-equivalent-ci.yml,
where postgres/redis are booted as real service containers.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)

_TOPIC = "aether.sdk.events.validated"

# Concurrency knobs, kept comfortably inside the asyncpg pool (min=5, max=20 —
# config/settings.py TimescaleDBConfig) so every racer gets its OWN connection
# and the transactions truly overlap rather than serializing at the pool.
_SAME_KEY_RACERS = 8
_BATCH_RACERS = 4
_BATCH_KEYS = 5


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def fresh_backend():
    """Freshly-imported backend modules, evicted again on exit.

    Mirrors tests/prod_equivalent/test_real_stack_smoke.py so a fresh
    ``repositories.repos._pool`` (module-level singleton) is built from the
    CURRENT environment's DATABASE_URL rather than a stale import.
    """
    _evict_backend()
    try:
        repos = importlib.import_module("repositories.repos")
        bulk = importlib.import_module("services.ingestion.bronze_bulk")
        yield repos, bulk
    finally:
        _evict_backend()


def _run(coro):
    return asyncio.run(coro)


def _make_event(bulk, tenant_id: str, event_id: str, schema_version: str = "1.0.0"):
    payload = {"event_id": event_id, "tenant_id": tenant_id, "properties": {"k": "v"}}
    rec = bulk.BronzeSDKEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        schema_version=schema_version,
        batch_id="prod-equiv-concurrency-batch",
        event_type="track",
        event_family="core",
        event_timestamp="2026-08-07T00:00:00Z",
        received_at="2026-08-07T00:00:01Z",
        session_id="s1",
        anonymous_id="anon1",
        user_id=None,
        entity_id="anon1",
        payload=payload,
        source="sdk",
        source_tag="prod-equivalent-concurrency",
    )
    ob = bulk.OutboxEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        topic=_TOPIC,
        partition_key="anon1",
        payload=payload,
    )
    return rec, ob


async def _count_direct(database_url: str, tenant_id: str) -> tuple[int, int]:
    """Return (bronze_count, outbox_count) for a tenant via a connection
    INDEPENDENT of get_pool()'s pool.

    Counting through a second, separately-opened asyncpg connection (not the
    pool ingest used) means exactly-once is asserted against durable storage —
    a bug that reported 'accepted' while writing nothing, or wrote duplicates,
    cannot pass by accident.
    """
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        bronze = await conn.fetchval(
            "SELECT count(*) FROM bronze_sdk_events WHERE tenant_id = $1", tenant_id
        )
        outbox = await conn.fetchval(
            "SELECT count(*) FROM event_outbox WHERE tenant_id = $1", tenant_id
        )
        return int(bronze), int(outbox)
    finally:
        await conn.close()


async def _cleanup_direct(database_url: str, tenant_id: str) -> None:
    """Best-effort teardown so a reused stack (e.g. local docker compose) stays clean."""
    import asyncpg

    try:
        conn = await asyncpg.connect(database_url)
    except Exception:
        return
    try:
        await conn.execute("DELETE FROM event_outbox WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM bronze_sdk_events WHERE tenant_id = $1", tenant_id)
    finally:
        await conn.close()


def _require_real_stack() -> str:
    """Skip guard: run ONLY against a real Postgres, so the local AETHER_ENV=local
    / make ci-check lane is never affected. Returns DATABASE_URL when present."""
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip(
            "DATABASE_URL not set — real-stack ingestion concurrency tests only "
            "run against a real Postgres (see "
            ".github/workflows/production-equivalent-ci.yml)"
        )
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        pytest.skip("asyncpg not installed — cannot exercise the real-pool path")
    return database_url


def test_concurrent_same_key_ingest_is_exactly_once():
    """N concurrent ingest_many of the SAME (tenant, event, schema) -> exactly once.

    Each racer is an independent ingest_many on its OWN pooled asyncpg
    connection + transaction; only the real ``ux_bronze_sdk_events_key`` UNIQUE
    index + ON CONFLICT DO NOTHING can make exactly one win. The in-memory dict
    branch appears to get this right only because its check-then-set never
    yields — a property this test refuses to rely on. Result is deterministic
    under every interleaving: whichever transaction inserts the row first
    RETURNs it ('accepted'); the rest wait on its row lock, then see the
    committed conflict and do nothing ('duplicate').
    """
    database_url = _require_real_stack()
    tenant_id = f"prod-equiv-cc-{uuid.uuid4().hex[:12]}"
    event_id = f"evt-{uuid.uuid4().hex}"

    with fresh_backend() as (repos, bulk):
        repos.reset_in_memory_stores()

        async def _one():
            rec, ob = _make_event(bulk, tenant_id, event_id)
            return await bulk.ingest_many([rec], [ob])

        # One event loop / one asyncio.run(): get_pool()'s pool is bound to the
        # loop that first creates it, so ingest, verify, and teardown must share
        # a single loop (see the smoke test's identical note).
        async def _scenario():
            try:
                results = await asyncio.gather(
                    *[_one() for _ in range(_SAME_KEY_RACERS)]
                )

                statuses = [s for r in results for s in r.statuses]
                assert statuses.count("accepted") == 1, (
                    f"expected exactly one 'accepted' across {_SAME_KEY_RACERS} "
                    f"concurrent racers of one key, got {statuses}"
                )
                assert statuses.count("duplicate") == _SAME_KEY_RACERS - 1, statuses
                assert sum(r.accepted_count for r in results) == 1
                # Only the winning racer enqueues an outbox row.
                assert sum(r.outbox_written for r in results) == 1

                # Real Postgres path executed, not the in-memory fallback.
                bronze_mem = repos._IN_MEMORY_STORES.get("bronze_sdk_events", {})
                assert not any(
                    row.get("tenant_id") == tenant_id for row in bronze_mem.values()
                ), "bronze row leaked into the in-memory store — real-pool path unused"

                # Independent connection: exactly one durable bronze + outbox row.
                bronze_count, outbox_count = await _count_direct(database_url, tenant_id)
                assert bronze_count == 1, (
                    f"idempotency violated: {bronze_count} bronze rows for one key "
                    f"under {_SAME_KEY_RACERS}-way concurrency (expected exactly 1)"
                )
                assert outbox_count == 1, (
                    f"outbox idempotency violated: {outbox_count} rows (expected 1)"
                )
            finally:
                await _cleanup_direct(database_url, tenant_id)
                await repos.close_pool()

        _run(_scenario())


def test_concurrent_same_batch_ingest_is_exactly_once():
    """M concurrent ingest_many of the SAME K-key batch -> each key accepted once.

    Generalizes the single-key race to overlapping MULTI-row batches — the shape
    a real /v1/batch retry storm takes. Every racer submits the IDENTICAL ordered
    batch, so all transactions acquire row locks in the same order: no
    lock-ordering cycle, hence no deadlock, while the UNIQUE index still admits
    each key exactly once. ``accepted_total == K`` holds under any interleaving
    because each key is inserted (and RETURNed) by exactly one transaction; every
    other racer sees it as a committed conflict.
    """
    database_url = _require_real_stack()
    tenant_id = f"prod-equiv-cc-{uuid.uuid4().hex[:12]}"
    event_ids = [f"evt-{uuid.uuid4().hex}" for _ in range(_BATCH_KEYS)]

    with fresh_backend() as (repos, bulk):
        repos.reset_in_memory_stores()

        def _batch():
            recs, obs = [], []
            for eid in event_ids:  # identical order across every racer
                r, o = _make_event(bulk, tenant_id, eid)
                recs.append(r)
                obs.append(o)
            return recs, obs

        async def _one():
            recs, obs = _batch()
            return await bulk.ingest_many(recs, obs)

        async def _scenario():
            try:
                results = await asyncio.gather(
                    *[_one() for _ in range(_BATCH_RACERS)]
                )

                accepted_ids = [eid for r in results for eid in r.accepted_event_ids]
                assert sorted(accepted_ids) == sorted(event_ids), (
                    "each key must be accepted exactly once across all racers — no "
                    f"key duplicated or dropped; got {sorted(accepted_ids)} vs "
                    f"{sorted(event_ids)}"
                )
                assert sum(r.accepted_count for r in results) == _BATCH_KEYS
                assert sum(r.outbox_written for r in results) == _BATCH_KEYS

                # Real Postgres path executed, not the in-memory fallback.
                bronze_mem = repos._IN_MEMORY_STORES.get("bronze_sdk_events", {})
                assert not any(
                    row.get("tenant_id") == tenant_id for row in bronze_mem.values()
                ), "bronze row leaked into the in-memory store — real-pool path unused"

                # Independent connection: exactly K durable bronze + K outbox rows.
                bronze_count, outbox_count = await _count_direct(database_url, tenant_id)
                assert bronze_count == _BATCH_KEYS, (
                    f"idempotency violated: {bronze_count} bronze rows for "
                    f"{_BATCH_KEYS} keys under {_BATCH_RACERS}-way batch concurrency "
                    f"(expected exactly {_BATCH_KEYS})"
                )
                assert outbox_count == _BATCH_KEYS, (
                    f"outbox idempotency violated: {outbox_count} rows "
                    f"(expected {_BATCH_KEYS})"
                )
            finally:
                await _cleanup_direct(database_url, tenant_id)
                await repos.close_pool()

        _run(_scenario())
