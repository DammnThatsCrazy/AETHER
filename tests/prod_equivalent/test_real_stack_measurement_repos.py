"""Real-stack measurement/attribution repository tests — Phase-2 Program 4, M4.

See docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md, section
"4. A production-equivalent CI lane". M4 is: extend the lane (M1 boots real
postgres + redis and runs an ingestion smoke test) to the
measurement/attribution suites —
``services/measurement/repositories/conversion_repo.py``,
``spend_repo.py`` and ``attribution_run_repo.py`` — which share the exact same
in-memory-fallback branch pattern as ingestion: each method calls
``repositories.repos.get_pool()`` and takes a module-level ``dict`` fallback
when it returns ``None`` (AETHER_ENV=local / no DATABASE_URL), or the REAL
asyncpg/Postgres branch when a pool exists.

Every OTHER measurement test in this repo exercises only the in-memory ``dict``
branch, so real-SQL properties are never proven. These tests force and verify
the REAL Postgres branch and assert properties the in-memory dict structurally
cannot:

  * ``conversion_repo.upsert`` — the real ``ON CONFLICT (tenant_id,
    deduplication_key) DO UPDATE`` authority-ranked merge (higher/equal
    authority overwrites gross/net/status, lower authority is ignored,
    ``authority_rank = GREATEST(...)``), collapsed onto exactly one row by the
    ``cc_dedup_key`` UNIQUE index; and tenant isolation of a shared dedup key,
    which the local store (keyed by ``deduplication_key`` alone) cannot model —
    a second tenant's write clobbers the first tenant's entry in local mode.
  * ``spend_repo.upsert`` — real ``ON CONFLICT (tenant_id, idempotency_key)``
    idempotent replay: exactly one row (no double count) via the
    ``sr_idempotency`` UNIQUE index, mutable spend columns updated from
    ``EXCLUDED`` while the surrogate ``spend_record_id`` PK stays at its
    first-insert value — where the local store wholesale-replaces the row and
    so would swap the PK.
  * CURRENCY FX provenance — a non-default ``exchange_rate`` and a
    ``provenance["fx_conversion"]`` sub-object persist to and read back from the
    real ``exchange_rate NUMERIC(18,8)`` and ``provenance JSONB`` columns
    (round-trip that the in-memory dict, which holds the Python object by
    reference and never serializes/coerces, cannot prove).
  * ``attribution_run_repo`` — create / deactivate-prior / get-active against
    real rows, and the re-attribution invariant "exactly one active run per
    (tenant_id, conversion_id)" enforced by the
    ``ux_attribution_runs_active_conversion`` partial UNIQUE index. The local
    ``_local_runs`` dict has no such constraint and would silently allow two
    active runs.

Contract with the fast local lane (mirrors test_real_stack_smoke.py): every
test SKIPs (never fails, never errors) when DATABASE_URL is unset via
``_require_real_stack()``, so this file never affects AETHER_ENV=local runs or
``make ci-check``. It is only meant to run under
``.github/workflows/production-equivalent-ci.yml``, where postgres/redis are
booted as real service containers and DATABASE_URL points at the postgres
service (that workflow runs ``alembic upgrade head`` first, provisioning the
canonical_conversions / spend_records / attribution_runs tables + indexes).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

# Repo-root tests/prod_equivalent/ -> parents[2] is the repo root (identical to
# test_real_stack_smoke.py). The backend package lives under a spaced dir.
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
    """Freshly-imported backend + measurement repo modules, evicted on exit.

    Mirrors test_real_stack_smoke.py's fresh_backend(): a fresh
    ``repositories.repos._pool`` singleton is built from the CURRENT
    environment's DATABASE_URL, and each measurement repo module rebinds its
    module-level ``get_pool`` import to that fresh ``repositories.repos``.
    """
    _evict_backend()
    try:
        repos = importlib.import_module("repositories.repos")
        conversion_repo = importlib.import_module(
            "services.measurement.repositories.conversion_repo"
        )
        spend_repo = importlib.import_module(
            "services.measurement.repositories.spend_repo"
        )
        attribution_run_repo = importlib.import_module(
            "services.measurement.repositories.attribution_run_repo"
        )
        yield repos, conversion_repo, spend_repo, attribution_run_repo
    finally:
        _evict_backend()


def _require_real_stack() -> str:
    """Skip guard shared by every test here (same semantics as the smoke test).

    Returns the DATABASE_URL when a real stack is available; otherwise skips so
    the AETHER_ENV=local / ``make ci-check`` lane stays green. Also skips when
    asyncpg is not importable (the real-pool branch cannot be exercised).
    """
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip(
            "DATABASE_URL not set — real-stack measurement/attribution tests "
            "only run against a real Postgres (see "
            ".github/workflows/production-equivalent-ci.yml)"
        )
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        pytest.skip("asyncpg not installed — cannot exercise the real-pool path")
    return database_url


def _run(coro):
    return asyncio.run(coro)


def _jsonb(value):
    """Independent asyncpg connections return JSONB as text — decode to dict."""
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


async def _connect(database_url: str):
    import asyncpg

    return await asyncpg.connect(database_url)


async def _cleanup(database_url: str, table: str, tenant_ids: list[str]) -> None:
    """Best-effort teardown so a reused stack (local docker compose) stays clean."""
    try:
        conn = await _connect(database_url)
    except Exception:
        return
    try:
        for tenant_id in tenant_ids:
            await conn.execute(f"DELETE FROM {table} WHERE tenant_id = $1", tenant_id)
    finally:
        await conn.close()


# ── conversion_repo ───────────────────────────────────────────────────────────

def _conversion_row(tenant_id: str, conversion_id: str, dedup_key: str, **over):
    row = {
        "tenant_id": tenant_id,
        "conversion_id": conversion_id,
        "deduplication_key": dedup_key,
        "conversion_type": "purchase",
        "conversion_name": "checkout",
        "conversion_source": "commerce_webhook",
        "gross_value": "100.00",
        "net_value": "90.00",
        "authority_rank": 30,
        "occurred_at": "2026-08-07T00:00:00Z",
        "currency": "USD",
        "normalized_currency": "USD",
    }
    row.update(over)
    return row


def test_conversion_repo_upsert_authority_conflict_and_fx_provenance():
    """conversion_repo.upsert real ON CONFLICT authority merge + tenant scope + FX.

    Skips without DATABASE_URL. With a real Postgres:

      1. Lower-authority re-upsert of the same (tenant, dedup_key) does NOT
         overwrite gross_value; authority_rank stays GREATEST — proven by an
         independent connection, and the row count stays exactly 1 (cc_dedup_key
         UNIQUE index). Higher-authority re-upsert DOES overwrite.
      2. The SAME dedup_key under a DIFFERENT tenant is a SEPARATE real row
         (composite unique), leaving tenant A's row untouched and invisible to a
         tenant-B-scoped ``get`` — the property the dedup-key-only local store
         cannot model.
      3. A conversion carrying currency=EUR + exchange_rate=0.92341567 +
         provenance.fx_conversion round-trips through the real
         exchange_rate NUMERIC(18,8) and provenance JSONB columns.
      4. The in-memory fallback store stays empty for both tenants — proving the
         real Postgres branch executed, not the dict fallback.
    """
    database_url = _require_real_stack()

    tenant_a = f"pe-m4-conv-a-{uuid.uuid4().hex[:12]}"
    tenant_b = f"pe-m4-conv-b-{uuid.uuid4().hex[:12]}"
    dedup_shared = f"pe-m4-dedup-{uuid.uuid4().hex}"
    dedup_fx = f"pe-m4-dedup-fx-{uuid.uuid4().hex}"
    conv_a = str(uuid.uuid4())
    conv_b = str(uuid.uuid4())
    conv_fx = str(uuid.uuid4())

    with fresh_backend() as (repos, conversion_repo, _spend, _attr):
        repos.reset_in_memory_stores()
        repo = conversion_repo.ConversionRepository()

        async def _scenario():
            try:
                # 1. First insert (authority 30, gross 100).
                await repo.upsert(
                    _conversion_row(tenant_a, conv_a, dedup_shared,
                                    authority_rank=30, gross_value="100.00")
                )
                conn = await _connect(database_url)
                try:
                    row = await conn.fetchrow(
                        "SELECT gross_value, authority_rank FROM canonical_conversions "
                        "WHERE tenant_id=$1 AND deduplication_key=$2",
                        tenant_a, dedup_shared,
                    )
                    assert row is not None, (
                        "conversion not found via independent connection — upsert "
                        "reported success but nothing durably persisted"
                    )
                    assert row["gross_value"] == Decimal("100")
                    assert row["authority_rank"] == 30

                    # 2. Lower-authority re-upsert MUST NOT overwrite.
                    await repo.upsert(
                        _conversion_row(tenant_a, conv_a, dedup_shared,
                                        authority_rank=10, gross_value="999.00")
                    )
                    row = await conn.fetchrow(
                        "SELECT gross_value, authority_rank FROM canonical_conversions "
                        "WHERE tenant_id=$1 AND deduplication_key=$2",
                        tenant_a, dedup_shared,
                    )
                    assert row["gross_value"] == Decimal("100"), (
                        "lower-authority upsert overwrote gross_value — real "
                        "ON CONFLICT CASE semantics not applied"
                    )
                    assert row["authority_rank"] == 30

                    # 3. Higher-authority re-upsert DOES overwrite.
                    await repo.upsert(
                        _conversion_row(tenant_a, conv_a, dedup_shared,
                                        authority_rank=90, gross_value="250.00")
                    )
                    row = await conn.fetchrow(
                        "SELECT gross_value, authority_rank FROM canonical_conversions "
                        "WHERE tenant_id=$1 AND deduplication_key=$2",
                        tenant_a, dedup_shared,
                    )
                    assert row["gross_value"] == Decimal("250")
                    assert row["authority_rank"] == 90

                    # Exactly one row for (tenant_a, dedup_shared) across 3 upserts.
                    count_a = await conn.fetchval(
                        "SELECT COUNT(*) FROM canonical_conversions "
                        "WHERE tenant_id=$1 AND deduplication_key=$2",
                        tenant_a, dedup_shared,
                    )
                    assert count_a == 1, (
                        "cc_dedup_key UNIQUE index did not collapse re-upserts onto "
                        f"one row (found {count_a})"
                    )

                    # 4. Tenant isolation: same dedup_key, different tenant -> its
                    #    own row; tenant A's row is untouched.
                    await repo.upsert(
                        _conversion_row(tenant_b, conv_b, dedup_shared,
                                        authority_rank=50, gross_value="500.00")
                    )
                    b_row = await conn.fetchrow(
                        "SELECT gross_value FROM canonical_conversions "
                        "WHERE tenant_id=$1 AND deduplication_key=$2",
                        tenant_b, dedup_shared,
                    )
                    assert b_row is not None and b_row["gross_value"] == Decimal("500")
                    a_still = await conn.fetchrow(
                        "SELECT gross_value FROM canonical_conversions "
                        "WHERE tenant_id=$1 AND deduplication_key=$2",
                        tenant_a, dedup_shared,
                    )
                    assert a_still["gross_value"] == Decimal("250"), (
                        "tenant B's shared-dedup-key write bled into tenant A — "
                        "real composite (tenant_id, deduplication_key) isolation failed"
                    )
                finally:
                    await conn.close()

                # tenant-scoped read via the repo: A's conversion is invisible
                # under tenant B.
                assert await repo.get(tenant_a, conv_a) is not None
                assert await repo.get(tenant_b, conv_a) is None

                # 5. FX provenance round-trip through real JSONB + NUMERIC columns.
                fx_provenance = {
                    "fx_conversion": {
                        "conversion_rate": "0.92341567",
                        "conversion_source": "ecb_reference",
                        "method": "fiat_fx",
                        "as_of_date": "2026-08-07",
                    },
                    "ingest_source": "commerce_webhook",
                }
                await repo.upsert(
                    _conversion_row(
                        tenant_a, conv_fx, dedup_fx,
                        authority_rank=90, gross_value="200.00",
                        currency="EUR", normalized_currency="USD",
                        exchange_rate="0.92341567", provenance=fx_provenance,
                    )
                )
                conn = await _connect(database_url)
                try:
                    fx_row = await conn.fetchrow(
                        "SELECT currency, normalized_currency, exchange_rate, provenance "
                        "FROM canonical_conversions WHERE tenant_id=$1 AND conversion_id=$2::uuid",
                        tenant_a, conv_fx,
                    )
                    assert fx_row is not None
                    assert fx_row["currency"] == "EUR"
                    assert fx_row["normalized_currency"] == "USD"
                    assert fx_row["exchange_rate"] == Decimal("0.92341567"), (
                        "exchange_rate did not persist as the observed rate — the "
                        f"real NUMERIC(18,8) column holds {fx_row['exchange_rate']!r} "
                        "(would be 1.0 if the default clobbered it)"
                    )
                    prov = _jsonb(fx_row["provenance"])
                    assert prov["fx_conversion"]["conversion_rate"] == "0.92341567"
                    assert prov["fx_conversion"]["conversion_source"] == "ecb_reference"
                    assert prov["fx_conversion"]["method"] == "fiat_fx"
                    assert prov["ingest_source"] == "commerce_webhook"
                finally:
                    await conn.close()

                # Real branch executed: the in-memory fallback stayed empty.
                assert not any(
                    r.get("tenant_id") in (tenant_a, tenant_b)
                    for r in conversion_repo._local_store.values()
                ), "conversion leaked into the in-memory store — real-pool path not used"
            finally:
                await _cleanup(database_url, "canonical_conversions", [tenant_a, tenant_b])
                await repos.close_pool()

        _run(_scenario())


# ── spend_repo ────────────────────────────────────────────────────────────────

def _spend_row(tenant_id: str, idempotency_key: str, **over):
    row = {
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "platform": "google_ads",
        "campaign_id": "camp-m4",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-02T00:00:00Z",
        "impressions": 1000,
        "clicks": 10,
        "media_spend": "45.00",
        "total_cost": "50.00",
        "billing_currency": "USD",
        "normalized_currency": "USD",
        "exchange_rate": "1.0",
    }
    row.update(over)
    return row


def test_spend_repo_idempotent_upsert_and_fx_provenance():
    """spend_repo.upsert real ON CONFLICT idempotent replay + stable PK + FX.

    Skips without DATABASE_URL. With a real Postgres:

      1. Replaying the same (tenant, idempotency_key) yields exactly ONE row
         (sr_idempotency UNIQUE index — no double count).
      2. The replay updates mutable columns (impressions, total_cost,
         exchange_rate) from EXCLUDED, but the surrogate spend_record_id PK
         stays at its FIRST-insert value even though the replay generated a new
         one — a real ON CONFLICT DO UPDATE property the local store (which
         wholesale-replaces the row) cannot hold.
      3. First insert carries billing_currency=GBP + exchange_rate=1.27193846 +
         provenance.fx_conversion, round-tripped through the real
         exchange_rate NUMERIC(18,8) and provenance JSONB columns.
      4. The in-memory fallback store stays empty for the tenant.
    """
    database_url = _require_real_stack()

    tenant = f"pe-m4-spend-{uuid.uuid4().hex[:12]}"
    idem = f"pe-m4-idem-{uuid.uuid4().hex}"
    sr_first = str(uuid.uuid4())

    with fresh_backend() as (repos, _conv, spend_repo, _attr):
        repos.reset_in_memory_stores()
        repo = spend_repo.SpendRepository()

        async def _scenario():
            try:
                fx_provenance = {
                    "fx_conversion": {
                        "conversion_rate": "1.27193846",
                        "conversion_source": "ecb_reference",
                        "method": "fiat_fx",
                    },
                    "connector": "google_ads",
                }
                # 1. First insert with an explicit surrogate PK + FX provenance.
                await repo.upsert(
                    _spend_row(
                        tenant, idem, spend_record_id=sr_first,
                        impressions=1000, clicks=10, total_cost="50.00",
                        billing_currency="GBP", normalized_currency="USD",
                        exchange_rate="1.27193846", provenance=fx_provenance,
                    )
                )
                conn = await _connect(database_url)
                try:
                    row = await conn.fetchrow(
                        "SELECT spend_record_id, impressions, total_cost, exchange_rate, "
                        "billing_currency, provenance FROM spend_records "
                        "WHERE tenant_id=$1 AND idempotency_key=$2",
                        tenant, idem,
                    )
                    assert row is not None, (
                        "spend record not found via independent connection — upsert "
                        "reported success but nothing durably persisted"
                    )
                    assert str(row["spend_record_id"]) == sr_first
                    assert row["impressions"] == 1000
                    assert row["total_cost"] == Decimal("50")
                    assert row["exchange_rate"] == Decimal("1.27193846")
                    assert row["billing_currency"] == "GBP"
                    prov = _jsonb(row["provenance"])
                    assert prov["fx_conversion"]["conversion_rate"] == "1.27193846"
                    assert prov["fx_conversion"]["conversion_source"] == "ecb_reference"

                    # 2. Replay the SAME idempotency_key WITHOUT a spend_record_id
                    #    (repo mints a new one) and with changed mutable metrics.
                    replay = _spend_row(
                        tenant, idem,
                        impressions=2000, clicks=20, total_cost="60.00",
                        billing_currency="GBP", normalized_currency="USD",
                        exchange_rate="1.30000000",
                    )
                    returned = await repo.upsert(replay)
                    sr_replay = returned["spend_record_id"]
                    assert sr_replay != sr_first, (
                        "test setup error: replay should generate a distinct "
                        "surrogate id so PK-stability is meaningful"
                    )

                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM spend_records "
                        "WHERE tenant_id=$1 AND idempotency_key=$2",
                        tenant, idem,
                    )
                    assert count == 1, (
                        "sr_idempotency UNIQUE index did not dedupe the replay "
                        f"(found {count} rows — double count)"
                    )
                    row2 = await conn.fetchrow(
                        "SELECT spend_record_id, impressions, total_cost, exchange_rate "
                        "FROM spend_records WHERE tenant_id=$1 AND idempotency_key=$2",
                        tenant, idem,
                    )
                    # Mutable columns updated from EXCLUDED ...
                    assert row2["impressions"] == 2000
                    assert row2["total_cost"] == Decimal("60")
                    assert row2["exchange_rate"] == Decimal("1.3")
                    # ... but the surrogate PK is STILL the first-insert value.
                    assert str(row2["spend_record_id"]) == sr_first, (
                        "spend_record_id changed on replay — real ON CONFLICT DO "
                        "UPDATE must not touch the PK (the local store would swap it)"
                    )
                finally:
                    await conn.close()

                # Real branch executed: the in-memory fallback stayed empty.
                assert not any(
                    k.startswith(f"{tenant}:") for k in spend_repo._local_store
                ), "spend record leaked into the in-memory store — real-pool path not used"
            finally:
                await _cleanup(database_url, "spend_records", [tenant])
                await repos.close_pool()

        _run(_scenario())


# ── attribution_run_repo ──────────────────────────────────────────────────────

def _run_row(tenant_id: str, conversion_id: str, **over):
    row = {
        "tenant_id": tenant_id,
        "conversion_id": conversion_id,
        "model_type": "last_touch",
        "model_version": "1.0",
        "currency": "USD",
    }
    row.update(over)
    return row


def test_attribution_run_repo_single_active_run_invariant():
    """attribution_run_repo create/deactivate-prior/get-active + one-active-run.

    Skips without DATABASE_URL. With a real Postgres:

      1. create_run persists a real (default-inactive) row; get_active_run is
         None until a run is activated.
      2. Activating run A, then deactivate_prior_runs + activating run B, leaves
         exactly one active run (B) for the (tenant, conversion) key.
      3. Re-activating A while B is active RAISES asyncpg.UniqueViolationError
         on the ux_attribution_runs_active_conversion partial UNIQUE index —
         the DB-enforced re-attribution invariant. State is unharmed: exactly
         one active run (still B) remains. The in-memory _local_runs dict has no
         such constraint and would allow two active runs.
      4. get_active_run / get_run are tenant-scoped against real SQL.
    """
    database_url = _require_real_stack()
    import asyncpg

    tenant = f"pe-m4-attr-{uuid.uuid4().hex[:12]}"
    other_tenant = f"pe-m4-other-{uuid.uuid4().hex[:12]}"
    conv = str(uuid.uuid4())

    with fresh_backend() as (repos, _conv, _spend, attribution_run_repo):
        repos.reset_in_memory_stores()
        repo = attribution_run_repo.AttributionRunRepository()

        async def _active_count(conn) -> int:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM attribution_runs "
                "WHERE tenant_id=$1 AND conversion_id=$2::uuid AND is_active=TRUE",
                tenant, conv,
            )

        async def _scenario():
            try:
                # 1. Create run A (inactive by default).
                created_a = await repo.create_run(_run_row(tenant, conv))
                run_a = created_a["attribution_run_id"]
                assert await repo.get_run(run_a, tenant_id=tenant) is not None
                assert await repo.get_active_run(tenant, conv) is None

                conn = await _connect(database_url)
                try:
                    a_active = await conn.fetchval(
                        "SELECT is_active FROM attribution_runs "
                        "WHERE tenant_id=$1 AND attribution_run_id=$2::uuid",
                        tenant, run_a,
                    )
                    assert a_active is False
                    assert await _active_count(conn) == 0

                    # 2. Activate A.
                    await repo.update_run(
                        run_a, {"is_active": True, "status": "complete"},
                        tenant_id=tenant,
                    )
                    active = await repo.get_active_run(tenant, conv)
                    assert active is not None
                    assert str(active["attribution_run_id"]) == run_a
                    assert await _active_count(conn) == 1

                    # Create run B, deactivate prior (A), activate B.
                    created_b = await repo.create_run(_run_row(tenant, conv))
                    run_b = created_b["attribution_run_id"]
                    deactivated = await repo.deactivate_prior_runs(tenant, conv)
                    assert deactivated == 1, (
                        f"deactivate_prior_runs should deactivate exactly A (got {deactivated})"
                    )
                    assert await repo.get_active_run(tenant, conv) is None
                    assert await _active_count(conn) == 0

                    await repo.update_run(
                        run_b, {"is_active": True, "status": "complete"},
                        tenant_id=tenant,
                    )
                    active = await repo.get_active_run(tenant, conv)
                    assert str(active["attribution_run_id"]) == run_b
                    assert await _active_count(conn) == 1

                    # 3. Re-attribution invariant: activating A again while B is
                    #    active violates the partial UNIQUE index.
                    err: Exception | None = None
                    try:
                        await repo.update_run(
                            run_a, {"is_active": True}, tenant_id=tenant,
                        )
                    except Exception as exc:  # noqa: BLE001 - asserting the type below
                        err = exc
                    assert isinstance(err, asyncpg.UniqueViolationError), (
                        "activating a second run for the same conversion did not "
                        f"raise a UNIQUE violation (got {err!r}) — the "
                        "ux_attribution_runs_active_conversion invariant is not enforced"
                    )
                    # State unharmed: still exactly one active run, still B.
                    assert await _active_count(conn) == 1
                    active = await repo.get_active_run(tenant, conv)
                    assert str(active["attribution_run_id"]) == run_b
                finally:
                    await conn.close()

                # 4. Tenant-scoped reads.
                assert await repo.get_active_run(other_tenant, conv) is None
                assert await repo.get_run(run_b, tenant_id=other_tenant) is None

                # Real branch executed: the in-memory fallback stayed empty.
                assert not any(
                    r.get("tenant_id") == tenant
                    for r in attribution_run_repo._local_runs.values()
                ), "attribution run leaked into the in-memory store — real-pool path not used"
            finally:
                await _cleanup(database_url, "attribution_runs", [tenant, other_tenant])
                await repos.close_pool()

        _run(_scenario())
