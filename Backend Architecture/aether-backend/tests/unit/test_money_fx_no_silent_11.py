"""Canonical money semantics (program sec19): no silent USD default and no
silent 1:1 FX.

Under test:
- ``billing_currency`` is REQUIRED — a missing value raises instead of being
  silently recorded as USD.
- A non-USD currency is converted through the FX snapshot seam
  (``services.value.fx_provider``); an unpriced currency raises instead of
  being recorded 1:1.
- ``normalized_currency`` is never hardcoded to USD by the repository.
- ``total_spend`` converts native amounts via the recorded rate and raises on
  un-normalized (mixed) rows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.measurement.repositories import conversion_repo as conv_mod
from services.measurement.repositories import spend_repo as spend_mod
from services.measurement.repositories.spend_repo import (
    SpendRepository,
    normalize_currency_for_usd,
)


@pytest.fixture(autouse=True)
def isolate_stores():
    spend_mod._local_store.clear()
    conv_mod._local_store.clear()
    yield
    spend_mod._local_store.clear()
    conv_mod._local_store.clear()


# ── normalize_currency_for_usd ──────────────────────────────────────────────

class TestNormalizeCurrencyForUsd:
    def test_usd_is_identity(self):
        norm, rate = normalize_currency_for_usd("USD")
        assert norm == "USD"
        assert rate == Decimal("1")

    def test_eur_converts_through_fx_seam(self):
        norm, rate = normalize_currency_for_usd("EUR")
        assert norm == "USD"
        assert rate == Decimal("1.08")

    def test_lowercase_currency_uppercased(self):
        norm, rate = normalize_currency_for_usd("gbp")
        assert norm == "USD"
        assert rate == Decimal("1.27")

    def test_missing_currency_raises(self):
        with pytest.raises(ValueError):
            normalize_currency_for_usd(None)
        with pytest.raises(ValueError):
            normalize_currency_for_usd("")
        with pytest.raises(ValueError):
            normalize_currency_for_usd("   ")

    def test_unpriced_currency_raises_never_11(self):
        # Not covered by the FX snapshot → unpriced → refuse 1:1, don't 1:1.
        with pytest.raises(ValueError):
            normalize_currency_for_usd("XYZ")


# ── SpendRepository.upsert ──────────────────────────────────────────────────

class TestSpendRepoMoney:
    async def test_non_usd_spend_is_converted_not_11(self):
        repo = SpendRepository()
        row = await repo.upsert({
            "tenant_id": "t1",
            "campaign_id": "c1",
            "platform": "meta",
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-01T23:59:59Z",
            "billing_currency": "EUR",
            "total_cost": "100",
            "idempotency_key": "spend-eur-1",
        })
        assert row["normalized_currency"] == "USD"
        # 100 EUR must NOT be recorded as $100 — rate 1.08 recorded, not 1.0.
        assert str(row["exchange_rate"]) == "1.08"

    async def test_missing_billing_currency_raises(self):
        repo = SpendRepository()
        with pytest.raises(ValueError):
            await repo.upsert({
                "tenant_id": "t1",
                "campaign_id": "c1",
                "total_cost": "100",
                "idempotency_key": "spend-nocurr-1",
            })

    async def test_unpriced_billing_currency_raises(self):
        repo = SpendRepository()
        with pytest.raises(ValueError):
            await repo.upsert({
                "tenant_id": "t1",
                "campaign_id": "c1",
                "billing_currency": "XYZ",
                "total_cost": "100",
                "idempotency_key": "spend-xyz-1",
            })

    async def test_total_spend_converts_via_recorded_rate(self):
        repo = SpendRepository()
        await repo.upsert({
            "tenant_id": "t2",
            "campaign_id": "c2",
            "platform": "google",
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-01T23:59:59Z",
            "billing_currency": "EUR",
            "total_cost": "100",
            "idempotency_key": "spend-eur-2",
        })
        from datetime import datetime

        total = await repo.total_spend(
            "t2", "c2",
            period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
            period_end=datetime.fromisoformat("2026-08-01T23:59:59+00:00"),
        )
        # 100 EUR × 1.08 = 108 USD — never 1:1.
        assert total == Decimal("108.00")

    async def test_total_spend_rejects_mixed_normalization(self):
        # A row normalized to anything other than USD must not be silently summed.
        bad_row = {
            "tenant_id": "t3",
            "campaign_id": "c3",
            "total_cost": "100",
            "normalized_currency": "EUR",
            "exchange_rate": "1.0",
        }
        with pytest.raises(ValueError):
            spend_mod._usd_total_cost(bad_row)


# ── ConversionRepository.upsert ─────────────────────────────────────────────

class TestConversionRepoMoney:
    async def test_non_usd_conversion_converts(self):
        repo = conv_mod.ConversionRepository()
        row = await repo.upsert({
            "tenant_id": "t4",
            "conversion_type": "purchase",
            "currency": "GBP",
            "gross_value": "50",
            "net_value": "45",
            "occurred_at": "2026-08-01T00:00:00Z",
            "deduplication_key": "conv-gbp-1",
        })
        assert row["normalized_currency"] == "USD"
        assert str(row["exchange_rate"]) == "1.27"

    async def test_missing_currency_raises(self):
        repo = conv_mod.ConversionRepository()
        with pytest.raises(ValueError):
            await repo.upsert({
                "tenant_id": "t4",
                "conversion_type": "purchase",
                "gross_value": "50",
                "occurred_at": "2026-08-01T00:00:00Z",
                "deduplication_key": "conv-nocurr-1",
            })

    async def test_unpriced_currency_raises(self):
        repo = conv_mod.ConversionRepository()
        with pytest.raises(ValueError):
            await repo.upsert({
                "tenant_id": "t4",
                "conversion_type": "purchase",
                "currency": "XYZ",
                "gross_value": "50",
                "occurred_at": "2026-08-01T00:00:00Z",
                "deduplication_key": "conv-xyz-1",
            })
