"""Real-stack ingestion smoke test — Phase-2 Program 4, M1.

See docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md, section
"4. A production-equivalent CI lane". M1 is: boot postgres + redis as real
service containers and run ONE existing-or-new smoke test against them to
prove the harness works — not a migration of the whole ingestion suite
(that is M2+).

``services/ingestion/bronze_bulk.py`` has two backends selected purely by
whether ``repositories.repos.get_pool()`` returns a real asyncpg pool
(DATABASE_URL set) or ``None`` (AETHER_ENV=local, in-memory dict fallback).
Every other ingestion test in this repo (e.g. tests/unit/test_ingestion_v2.py)
exercises the in-memory branch only. This test is the first one that, when
DATABASE_URL is set, forces and verifies the REAL Postgres branch
(``_pg_commit``) — the transactional Bronze+outbox insert, the
``ON CONFLICT ... DO NOTHING`` idempotency, all under a real asyncpg pool.

Contract with the fast local lane: this file must SKIP (not fail, not error)
whenever DATABASE_URL is unset, so it never affects AETHER_ENV=local runs or
``make ci-check``. It is only meant to run under
``.github/workflows/production-equivalent-ci.yml``, where postgres/redis are
booted as real service containers and DATABASE_URL points at the postgres
service (see that workflow for exact env / migration setup).
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


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def fresh_backend():
    """Freshly-imported backend modules, evicted again on exit.

    Mirrors the pattern already used by tests/unit/test_ingestion_v2.py, so a
    fresh ``repositories.repos._pool`` (module-level singleton) is built from
    the CURRENT environment's DATABASE_URL rather than a stale import.
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


def _make_event(bulk, tenant_id: str, event_id: str):
    payload = {"event_id": event_id, "tenant_id": tenant_id, "properties": {"k": "v"}}
    rec = bulk.BronzeSDKEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        schema_version="1.0.0",
        batch_id="prod-equiv-smoke-batch",
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
        source_tag="prod-equivalent-smoke",
    )
    ob = bulk.OutboxEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        topic="aether.sdk.events.validated",
        partition_key="anon1",
        payload=payload,
    )
    return rec, ob


async def _fetch_direct(database_url: str, tenant_id: str, event_id: str):
    """Verify persistence via a connection INDEPENDENT of get_pool()'s pool.

    Using a second, separately-opened asyncpg connection (rather than trusting
    get_pool()'s own pool) means a hypothetical bug where ingest_many silently
    used the in-memory store while still reporting "accepted" cannot pass this
    check by accident.
    """
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        bronze_row = await conn.fetchrow(
            "SELECT tenant_id, event_id, schema_version, event_type "
            "FROM bronze_sdk_events WHERE tenant_id = $1 AND event_id = $2",
            tenant_id, event_id,
        )
        outbox_row = await conn.fetchrow(
            "SELECT tenant_id, event_id, topic, status "
            "FROM event_outbox WHERE tenant_id = $1 AND event_id = $2",
            tenant_id, event_id,
        )
        return bronze_row, outbox_row
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


def test_ingest_many_real_pool_round_trip():
    """``ingest_many`` against a REAL asyncpg pool proves the real-stack path.

    Skips cleanly when DATABASE_URL is absent (the AETHER_ENV=local / make
    ci-check lane). When DATABASE_URL is set:

      1. A new event is reported "accepted" by ingest_many.
      2. The row is independently visible in real Postgres (bronze_sdk_events
         + event_outbox), via a connection get_pool() never touched.
      3. The in-memory fallback store stays empty for this tenant — proving
         the Postgres branch (_pg_commit), not the in-memory branch
         (_memory_commit), executed.
      4. Re-ingesting the same event is reported "duplicate", enforced by the
         real (tenant_id, event_id, schema_version) UNIQUE index — not an
         in-process dict.
    """
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip(
            "DATABASE_URL not set — real-stack smoke test only runs against a "
            "real Postgres (see .github/workflows/production-equivalent-ci.yml)"
        )

    try:
        import asyncpg  # noqa: F401
    except ImportError:
        pytest.skip("asyncpg not installed — cannot exercise the real-pool path")

    tenant_id = f"prod-equiv-smoke-{uuid.uuid4().hex[:12]}"
    event_id = f"evt-{uuid.uuid4().hex}"

    with fresh_backend() as (repos, bulk):
        repos.reset_in_memory_stores()
        rec, ob = _make_event(bulk, tenant_id, event_id)

        # Everything below runs inside ONE event loop / one asyncio.run() call.
        # get_pool()'s asyncpg pool is bound to whichever loop first creates it;
        # tearing it down (close_pool()) from a DIFFERENT loop raises "Event
        # loop is closed", so ingest, verify, re-ingest, and cleanup must all
        # share a single loop rather than each getting its own asyncio.run().
        async def _scenario():
            try:
                result = await bulk.ingest_many([rec], [ob])
                assert result.statuses == ["accepted"], (
                    f"expected 'accepted' on first ingest, got {result.statuses}"
                )
                assert result.accepted_count == 1
                assert result.outbox_written == 1

                # The in-memory fallback must NOT have received this tenant's
                # rows — proves the real Postgres branch executed, not
                # _memory_commit.
                bronze_mem = repos._IN_MEMORY_STORES.get("bronze_sdk_events", {})
                outbox_mem = repos._IN_MEMORY_STORES.get("event_outbox", {})
                assert not any(row.get("tenant_id") == tenant_id for row in bronze_mem.values()), (
                    "bronze row leaked into the in-memory store — real-pool path was not used"
                )
                assert not any(row.get("tenant_id") == tenant_id for row in outbox_mem.values()), (
                    "outbox row leaked into the in-memory store — real-pool path was not used"
                )

                # Verify against Postgres directly (independent connection).
                bronze_row, outbox_row = await _fetch_direct(database_url, tenant_id, event_id)
                assert bronze_row is not None, (
                    "bronze_sdk_events row not found via an independent connection — "
                    "ingest_many reported 'accepted' but nothing is durably persisted"
                )
                assert bronze_row["event_type"] == "track"
                assert outbox_row is not None, (
                    "event_outbox row not found via an independent connection"
                )
                assert outbox_row["status"] == "pending"

                # Re-ingest: DB uniqueness (not Redis, not a dict) must dedupe.
                dup = await bulk.ingest_many([rec], [ob])
                assert dup.statuses == ["duplicate"], (
                    f"expected 'duplicate' on re-ingest, got {dup.statuses}"
                )
                assert dup.accepted_count == 0
            finally:
                await _cleanup_direct(database_url, tenant_id)
                await repos.close_pool()

        _run(_scenario())
