"""FX correctness on the conversion/spend upsert conflict + same-currency paths.

Three verified bugs are pinned here (Program 5 multi-currency):

* N5  — ``ConversionRepository.upsert``'s ``ON CONFLICT`` clause updated only
        gross/net/status/rank on an authority-ranked replay and DISCARDED the
        resolved FX fields (currency, normalized_currency, exchange_rate,
        provenance). A higher-authority replay could then update the monetary
        value while leaving the stored rate/source stale — incorrect normalized
        revenue. The conflict update must persist the FX fields under the same
        authority gate.
* N16 — ``SpendRepository.upsert``'s ``ON CONFLICT`` clause persisted the newly
        resolved ``exchange_rate`` but never ``provenance``, so a replayed row
        could carry the new rate with a stale/absent fx_conversion source.
        Provenance must be persisted in the same conflict update as the rate.
* N14 — an explicit non-1 ``exchange_rate`` on a SAME-currency row was preserved
        by ``setdefault`` and the FX branch skipped, so a USD->USD row could
        persist e.g. 2.0 with no provenance. Same-currency rows are real 1.0
        parity by definition — the rate must be forced to exactly 1.

The conflict-clause bugs (N5/N16) live only on the production asyncpg path — the
local in-memory fallback replaces the whole row, so they are exercised here with
a lightweight capturing connection that records the real ``INSERT ... ON
CONFLICT`` SQL and its bound parameters. N14 is observable on the local path and
is checked behaviorally.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.spend_repo import SpendRepository
from services.value import fx_provider, price_sources


@pytest.fixture(autouse=True)
def _fx_registry():
    """Register the M1 snapshot FX provider; isolate the registry per test."""
    fx_provider.register()
    yield
    price_sources.clear_price_providers()


# ── A capturing asyncpg-shaped connection/pool ───────────────────────────────

class _CapturingConn:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args):
        self.execute_calls.append((sql, args))
        return "INSERT 0 1"


class _AcquireCtx:
    def __init__(self, conn: _CapturingConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _CapturingConn:
        return self._conn

    async def __aexit__(self, *exc) -> bool:
        return False


class _CapturingPool:
    def __init__(self, conn: _CapturingConn) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


def _bind_capturing_pool(repo) -> _CapturingConn:
    conn = _CapturingConn()
    pool = _CapturingPool(conn)

    async def _fake_pool():
        return pool

    repo._pool = _fake_pool  # force the production (pool-backed) write path
    return conn


def _conflict_section(sql: str) -> str:
    normalized = " ".join(sql.split())
    assert "ON CONFLICT" in normalized, normalized
    return normalized.split("ON CONFLICT", 1)[1]


# ── N5: conversion conflict clause persists resolved FX fields ───────────────

@pytest.mark.asyncio
async def test_conversion_conflict_update_persists_fx_fields():
    repo = ConversionRepository()
    conn = _bind_capturing_pool(repo)

    await repo.upsert({
        "tenant_id": "t-fx",
        "conversion_type": "purchase",
        "currency": "EUR",
        "normalized_currency": "USD",
        "gross_value": "100",
        "net_value": "100",
        "occurred_at": "2026-08-08T00:00:00+00:00",
        "source_event_id": "evt-eur-conflict",
        "authority_rank": 90,
    })

    assert conn.execute_calls, "production INSERT path was not exercised"
    sql, args = conn.execute_calls[-1]
    conflict = _conflict_section(sql)

    # The FX fields must be updated on conflict, gated on the SAME authority
    # condition the monetary values use — not left stale.
    assert "exchange_rate = CASE WHEN EXCLUDED.authority_rank" in conflict, conflict
    assert "provenance = CASE WHEN EXCLUDED.authority_rank" in conflict, conflict
    assert "normalized_currency = CASE WHEN EXCLUDED.authority_rank" in conflict, conflict
    # Standalone `currency` (its CASE body is unambiguous vs normalized_currency).
    assert "THEN EXCLUDED.currency ELSE canonical_conversions.currency" in conflict, conflict

    # And the real resolved rate + provenance actually flow into the write.
    assert any(isinstance(a, Decimal) and a == Decimal("1.08") for a in args), args
    assert any(isinstance(a, str) and "fx_conversion" in a for a in args), args


# ── N16: spend conflict clause persists provenance with the rate ─────────────

@pytest.mark.asyncio
async def test_spend_conflict_update_persists_provenance_with_rate():
    repo = SpendRepository()
    conn = _bind_capturing_pool(repo)

    await repo.upsert({
        "tenant_id": "t-fx",
        "platform": "google_ads",
        "campaign_id": "c-1",
        "billing_currency": "GBP",
        "normalized_currency": "USD",
        "media_spend": "250",
        "total_cost": "250",
        "period_start": "2026-08-01T00:00:00+00:00",
        "period_end": "2026-08-02T00:00:00+00:00",
        "idempotency_key": "spend-gbp-conflict",
    })

    assert conn.execute_calls, "production INSERT path was not exercised"
    sql, args = conn.execute_calls[-1]
    conflict = _conflict_section(sql)

    # Provenance must move together with the exchange_rate on replay.
    assert "exchange_rate = EXCLUDED.exchange_rate" in conflict, conflict
    assert "provenance = EXCLUDED.provenance" in conflict, conflict

    assert any(isinstance(a, Decimal) and a == Decimal("1.27") for a in args), args
    assert any(isinstance(a, str) and "fx_conversion" in a for a in args), args


# ── N14: same-currency rows are forced to exact 1.0 parity ───────────────────

@pytest.mark.asyncio
async def test_conversion_same_currency_explicit_rate_forced_to_parity():
    repo = ConversionRepository()

    async def _no_pool():
        return None

    repo._pool = _no_pool  # local path; observe the persisted row directly

    row = await repo.upsert({
        "tenant_id": "t-fx",
        "conversion_type": "purchase",
        "currency": "USD",
        "normalized_currency": "USD",
        "exchange_rate": "2.0",  # bogus explicit rate on a same-currency row
        "gross_value": "100",
        "occurred_at": "2026-08-08T00:00:00+00:00",
        "source_event_id": "evt-usd-parity",
    })

    # Forced to real 1.0 parity; no fabricated same-currency FX provenance.
    assert row["exchange_rate"] == "1.0"
    assert "fx_conversion" not in (row.get("provenance") or {})


@pytest.mark.asyncio
async def test_spend_same_currency_explicit_rate_forced_to_parity():
    repo = SpendRepository()

    async def _no_pool():
        return None

    repo._pool = _no_pool

    row = await repo.upsert({
        "tenant_id": "t-fx",
        "platform": "google_ads",
        "billing_currency": "USD",
        "normalized_currency": "USD",
        "exchange_rate": "2.0",  # bogus explicit rate on a same-currency row
        "media_spend": "250",
        "total_cost": "250",
        "period_start": "2026-08-01T00:00:00+00:00",
        "period_end": "2026-08-02T00:00:00+00:00",
        "idempotency_key": "spend-usd-parity",
    })

    assert row["exchange_rate"] == "1.0"
    assert "fx_conversion" not in (row.get("provenance") or {})
