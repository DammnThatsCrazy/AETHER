"""Real FX conversion in conversion_repo / spend_repo upsert (Program 5, M2).

docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §5 (multi-currency), M2:
    "Call price_sources.py from conversion_repo.upsert / spend_repo.upsert when
     currency != normalized_currency, replacing the hardcoded '1.0' default
     with a real conversion_rate + conversion_source recorded per row."

M1 (services/value/fx_provider.py) already registers a snapshot FX
``PriceProvider`` into ``services/value/price_sources.py`` for the ten fiat
symbols in ``price_sources._FX_FIAT_SYMBOLS``. These tests pin the M2 wiring:

- a non-USD KNOWN fiat row gets a REAL (!= 1.0) exchange_rate plus recorded
  provenance (provider source + as-of), not the hardcoded default;
- a same-currency (USD -> USD) row keeps a real 1.0 parity and grows no FX
  provenance (behavior unchanged — parity is correct, not a fabrication);
- an unknown / unpriced currency does NOT get a fabricated foreign 1.0: it is
  recorded as unpriced / None-sourced (M1 "unpriced, never silent parity"),
  explicitly distinguishable from a real same-currency 1.0. Making rollups
  exclude such rows is M3 and is intentionally NOT exercised here.

Everything runs in local (in-memory) mode: ``get_pool`` is monkeypatched to
None on both repo modules so no database is required, mirroring the sibling
``test_touchpoint_persist.py`` technique.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from services.measurement.repositories import conversion_repo as conv_mod
from services.measurement.repositories import spend_repo as spend_mod
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.spend_repo import SpendRepository
from services.value import fx_provider, price_sources


@pytest.fixture(autouse=True)
def local_mode_and_clean_registry(monkeypatch: pytest.MonkeyPatch):
    """Force in-memory mode, reset module stores, isolate the price registry."""

    async def no_pool():
        return None

    monkeypatch.setattr(conv_mod, "get_pool", no_pool)
    monkeypatch.setattr(spend_mod, "get_pool", no_pool)
    conv_mod._local_store.clear()
    spend_mod._local_store.clear()
    # The upsert path self-registers the snapshot provider, but register here
    # too so intent is explicit and the file is hermetic; register is idempotent.
    fx_provider.register()
    yield
    conv_mod._local_store.clear()
    spend_mod._local_store.clear()
    price_sources.clear_price_providers()


# ── conversion_repo ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_conversion_foreign_currency_gets_real_rate_and_source():
    row = await ConversionRepository().upsert(
        {
            "tenant_id": "t-fx",
            "conversion_type": "purchase",
            "currency": "EUR",
            "normalized_currency": "USD",
            "gross_value": "100",
            "net_value": "100",
            "occurred_at": "2026-08-08T00:00:00+00:00",
            "source_event_id": "evt-eur-1",
        }
    )

    # Real snapshot rate (1 EUR = 1.08 USD), NOT the hardcoded "1.0" default.
    assert row["exchange_rate"] == "1.08"
    assert row["exchange_rate"] != "1.0"

    fx = row["provenance"]["fx_conversion"]
    assert fx["priced"] is True
    assert fx["conversion_source"] == fx_provider._SNAPSHOT_SOURCE
    assert fx["method"] == "fx_rate"
    assert fx["base_currency"] == "USD"
    assert fx["quote_currency"] == "EUR"
    assert fx["exchange_rate"] == "1.08"
    assert fx["as_of"]  # a real as-of timestamp was recorded


@pytest.mark.asyncio
async def test_conversion_foreign_currency_rate_is_decimal_valued_never_float():
    row = await ConversionRepository().upsert(
        {
            "tenant_id": "t-fx",
            "conversion_type": "purchase",
            "currency": "JPY",
            "normalized_currency": "USD",
            "gross_value": "5000",
            "occurred_at": "2026-08-08T00:00:00+00:00",
            "source_event_id": "evt-jpy-1",
        }
    )
    # Recorded as a text-decimal; parses to the exact snapshot Decimal, no float.
    assert isinstance(row["exchange_rate"], str)
    assert Decimal(row["exchange_rate"]) == Decimal("0.0067")
    assert not isinstance(row["exchange_rate"], float)


@pytest.mark.asyncio
async def test_conversion_same_currency_keeps_real_parity_no_fabrication():
    row = await ConversionRepository().upsert(
        {
            "tenant_id": "t-fx",
            "conversion_type": "purchase",
            "currency": "USD",
            "normalized_currency": "USD",
            "gross_value": "100",
            "occurred_at": "2026-08-08T00:00:00+00:00",
            "source_event_id": "evt-usd-1",
        }
    )
    # Same currency -> real 1.0 parity, and no FX resolution/provenance added.
    assert row["exchange_rate"] == "1.0"
    assert "fx_conversion" not in (row.get("provenance") or {})


@pytest.mark.asyncio
async def test_conversion_unknown_currency_not_silently_parity():
    row = await ConversionRepository().upsert(
        {
            "tenant_id": "t-fx",
            "conversion_type": "purchase",
            "currency": "ZZZ",  # not a known/priced fiat symbol
            "normalized_currency": "USD",
            "gross_value": "100",
            "occurred_at": "2026-08-08T00:00:00+00:00",
            "source_event_id": "evt-zzz-1",
        }
    )
    # An unavailable rate is NOT fabricated as a sourced foreign 1.0. It is
    # explicitly recorded as unpriced / None-sourced so a consumer (and M3) can
    # tell it apart from a real same-currency parity, which carries no
    # fx_conversion block at all.
    fx = row["provenance"]["fx_conversion"]
    assert fx["priced"] is False
    assert fx["conversion_source"] is None
    assert fx["method"] == "unpriced"
    assert fx["quote_currency"] == "ZZZ"
    # The distinguishing marker exists — the row is not silently parity.
    assert "fx_conversion" in row["provenance"]


# ── spend_repo ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_spend_foreign_currency_gets_real_rate_and_source():
    row = await SpendRepository().upsert(
        {
            "tenant_id": "t-fx",
            "platform": "google_ads",
            "campaign_id": "c-1",
            "billing_currency": "GBP",
            "normalized_currency": "USD",
            "media_spend": "250",
            "total_cost": "250",
            "period_start": "2026-08-01T00:00:00+00:00",
            "period_end": "2026-08-02T00:00:00+00:00",
            "idempotency_key": "spend-gbp-1",
        }
    )

    # Real snapshot rate (1 GBP = 1.27 USD), NOT the hardcoded "1.0" default.
    assert row["exchange_rate"] == "1.27"
    assert row["exchange_rate"] != "1.0"

    fx = row["provenance"]["fx_conversion"]
    assert fx["priced"] is True
    assert fx["conversion_source"] == fx_provider._SNAPSHOT_SOURCE
    assert fx["method"] == "fx_rate"
    assert fx["base_currency"] == "USD"
    assert fx["quote_currency"] == "GBP"
    assert fx["as_of"]


@pytest.mark.asyncio
async def test_spend_same_currency_keeps_real_parity_no_fabrication():
    row = await SpendRepository().upsert(
        {
            "tenant_id": "t-fx",
            "platform": "google_ads",
            "billing_currency": "USD",
            "normalized_currency": "USD",
            "media_spend": "250",
            "total_cost": "250",
            "period_start": "2026-08-01T00:00:00+00:00",
            "period_end": "2026-08-02T00:00:00+00:00",
            "idempotency_key": "spend-usd-1",
        }
    )
    assert row["exchange_rate"] == "1.0"
    assert "fx_conversion" not in (row.get("provenance") or {})


@pytest.mark.asyncio
async def test_spend_unknown_currency_not_silently_parity():
    row = await SpendRepository().upsert(
        {
            "tenant_id": "t-fx",
            "platform": "google_ads",
            "billing_currency": "ZZZ",  # not a known/priced fiat symbol
            "normalized_currency": "USD",
            "media_spend": "250",
            "total_cost": "250",
            "period_start": "2026-08-01T00:00:00+00:00",
            "period_end": "2026-08-02T00:00:00+00:00",
            "idempotency_key": "spend-zzz-1",
        }
    )
    fx = row["provenance"]["fx_conversion"]
    assert fx["priced"] is False
    assert fx["conversion_source"] is None
    assert fx["method"] == "unpriced"
    assert fx["quote_currency"] == "ZZZ"
    assert "fx_conversion" in row["provenance"]


@pytest.mark.asyncio
async def test_foreign_rate_resolves_even_without_explicit_registration():
    """The write path itself wires the M1 provider — no external import needed.

    Clearing the registry first proves conversion_repo.upsert re-registers the
    snapshot provider on demand, so M2 is real end-to-end rather than depending
    on some other module having imported fx_provider first.
    """
    price_sources.clear_price_providers()
    assert price_sources._providers == []

    row = await ConversionRepository().upsert(
        {
            "tenant_id": "t-fx",
            "conversion_type": "purchase",
            "currency": "CAD",
            "normalized_currency": "USD",
            "gross_value": "100",
            "occurred_at": "2026-08-08T00:00:00+00:00",
            "source_event_id": "evt-cad-1",
        }
    )
    assert row["exchange_rate"] == "0.73"
    assert row["provenance"]["fx_conversion"]["priced"] is True
