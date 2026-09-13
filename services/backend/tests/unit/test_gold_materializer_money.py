"""gold_materializer: native spend is converted to USD via the recorded
exchange_rate before it lands in ``spend_usd`` — never a silent 1:1 for non-USD
(program sec19).

Under test:
- ``materialize_campaign_performance_daily`` writes the FX-converted spend into
  ``gold_ad_spend.spend_usd`` (EUR 100 × 1.08 + USD 50 = 158, not 150).
- A spend row not normalized to USD raises loudly instead of being written 1:1.
- Legacy USD rows without a rate remain identity.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from services.measurement import repositories
from services.measurement.engine import gold_materializer
from services.measurement.repositories.spend_repo import SpendRepository


@pytest.fixture(autouse=True)
async def isolate_state():
    repositories.spend_repo._local_store.clear()
    repositories.attribution_run_repo._local_credits.clear()
    repositories.attribution_run_repo._local_runs.clear()
    if gold_materializer._ch_client is not None:
        await gold_materializer._ch_client.close()
        gold_materializer._ch_client = None
    yield
    repositories.spend_repo._local_store.clear()
    repositories.attribution_run_repo._local_credits.clear()
    repositories.attribution_run_repo._local_runs.clear()
    if gold_materializer._ch_client is not None:
        await gold_materializer._ch_client.close()
        gold_materializer._ch_client = None


async def _seed_spend(rows: list[dict]) -> None:
    repo = SpendRepository()
    for row in rows:
        await repo.upsert(row)


def _period(day: date, end: bool = False) -> str:
    ts = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc) if end \
        else datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=timezone.utc)
    return ts.isoformat()


class TestSpendUsdIsConverted:
    async def test_non_usd_spend_converts_not_11(self):
        day = date(2026, 8, 1)
        await _seed_spend([
            {
                "tenant_id": "t-gold", "campaign_id": "c-gold",
                "platform": "meta",
                "period_start": _period(day), "period_end": _period(day, end=True),
                "billing_currency": "EUR", "total_cost": "100",
                "idempotency_key": "gold-eur-1",
            },
            {
                "tenant_id": "t-gold", "campaign_id": "c-gold",
                "platform": "meta",
                "period_start": _period(day), "period_end": _period(day, end=True),
                "billing_currency": "USD", "total_cost": "50",
                "idempotency_key": "gold-usd-1",
            },
        ])

        await gold_materializer.materialize_campaign_performance_daily("t-gold", day)

        ch = await gold_materializer._ch()
        rows = ch.get_table("gold_ad_spend")
        assert rows, "expected a materialized gold_ad_spend row"
        # 100 EUR × 1.08 + 50 USD = 158 USD — never 150 (1:1).
        assert rows[0]["spend_usd"] == pytest.approx(158.0)

    async def test_legacy_usd_row_without_rate_is_identity(self):
        day = date(2026, 8, 2)
        await _seed_spend([
            {
                "tenant_id": "t-gold2", "campaign_id": "c-gold2",
                "platform": "google",
                "period_start": _period(day), "period_end": _period(day, end=True),
                "billing_currency": "USD", "total_cost": "25",
                "idempotency_key": "gold-usd-2",
            },
        ])

        await gold_materializer.materialize_campaign_performance_daily("t-gold2", day)

        ch = await gold_materializer._ch()
        rows = ch.get_table("gold_ad_spend")
        assert rows[0]["spend_usd"] == pytest.approx(25.0)


class TestUnnormalizedSpendRaises:
    async def test_non_usd_normalized_row_raises_not_11(self):
        day = date(2026, 8, 3)
        # Directly seed a row the repo would never produce: normalized to EUR.
        repositories.spend_repo._local_store["bad:1"] = {
            "tenant_id": "t-gold3", "campaign_id": "c-gold3",
            "platform": "meta",
            "period_start": _period(day), "period_end": _period(day, end=True),
            "billing_currency": "EUR", "normalized_currency": "EUR",
            "exchange_rate": "1.0", "total_cost": "100",
        }

        with pytest.raises(ValueError):
            await gold_materializer.materialize_campaign_performance_daily("t-gold3", day)
