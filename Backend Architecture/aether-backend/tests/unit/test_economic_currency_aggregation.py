"""economic/routes: mixed native currencies are NEVER summed into one scalar
(program sec19).

``_aggregate_spend`` returns per-currency native amounts verbatim plus a
clearly-labeled FX-converted USD total. When any currency is unpriced the USD
total is explicitly None (an incomplete total is never presented as a complete
one) with the reason listed in a warning.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.economic.routes import _aggregate_spend, _spend_rows_to_usd_total


class TestAggregateSpendNeverMixes:
    def test_per_currency_native_amounts_returned_verbatim(self):
        spend, per_currency, warnings = _aggregate_spend({"EUR": "100", "GBP": "100"})

        assert per_currency["EUR"].native_amount == 100.0
        assert per_currency["EUR"].native_currency == "EUR"
        assert per_currency["GBP"].native_amount == 100.0
        assert per_currency["GBP"].native_currency == "GBP"

    def test_usd_total_converts_each_currency_via_fx(self):
        spend, per_currency, warnings = _aggregate_spend({"EUR": "100", "GBP": "100"})

        # 100 EUR × 1.08 + 100 GBP × 1.27 = 108 + 127 = 235 — never summed 1:1.
        assert spend is not None
        assert spend.usd_amount == pytest.approx(235.0)
        assert spend.normalized_currency == "USD"
        assert per_currency["EUR"].usd_amount == pytest.approx(108.0)
        assert per_currency["GBP"].usd_amount == pytest.approx(127.0)
        assert warnings == []

    def test_unpriced_currency_means_incomplete_total_is_none(self):
        spend, per_currency, warnings = _aggregate_spend({"USD": "50", "XYZ": "100"})

        # USD leg is priced; XYZ is unpriced → the total is incomplete → None.
        assert spend is not None
        assert spend.usd_amount is None
        assert spend.normalized_amount is None
        assert per_currency["USD"].usd_amount == pytest.approx(50.0)
        assert per_currency["XYZ"].usd_amount is None
        assert any("FX rate unavailable" in w for w in warnings)
        assert "XYZ" in warnings[0]

    def test_empty_input_yields_no_spend(self):
        spend, per_currency, warnings = _aggregate_spend({})
        assert spend is None
        assert per_currency == {}
        assert warnings == []

    def test_usd_identity_total(self):
        spend, per_currency, warnings = _aggregate_spend({"USD": "250"})
        assert spend is not None
        assert spend.usd_amount == pytest.approx(250.0)
        assert per_currency["USD"].usd_amount == pytest.approx(250.0)


class TestSpendRowsToUsdTotal:
    def test_native_rows_converted_via_recorded_rate(self):
        rows = [
            {"spend_record_id": "r1", "total_cost": "100", "normalized_currency": "USD", "exchange_rate": "1.08"},
            {"spend_record_id": "r2", "total_cost": "50", "normalized_currency": "USD", "exchange_rate": "1.27"},
            {"spend_record_id": "r3", "total_cost": "25", "normalized_currency": "USD", "exchange_rate": "1.0"},
        ]
        # 100×1.08 + 50×1.27 + 25×1.0 = 108 + 63.5 + 25 = 196.5 — never 1:1.
        assert _spend_rows_to_usd_total(rows) == Decimal("196.50")

    def test_usd_rows_without_rate_are_identity(self):
        rows = [{"total_cost": "100", "normalized_currency": "USD"}]
        assert _spend_rows_to_usd_total(rows) == Decimal("100")

    def test_mixed_normalization_raises_never_silently_sums(self):
        rows = [
            {"spend_record_id": "r1", "total_cost": "100", "normalized_currency": "USD", "exchange_rate": "1.0"},
            {"spend_record_id": "r2", "total_cost": "100", "normalized_currency": "EUR", "exchange_rate": "1.0"},
        ]
        with pytest.raises(ValueError):
            _spend_rows_to_usd_total(rows)
