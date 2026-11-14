from decimal import Decimal

import pytest

from config.settings import PredictionMarketConfig
from value.prediction_markets.models import (
    MarketObservation,
    MarketStatus,
    MarketVenue,
    OutcomeQuote,
    PredictionMarketValidationError,
)
from value.prediction_markets.normalizers import (
    normalize_kalshi_market,
    normalize_polymarket_market,
)


def test_flags_default_off():
    cfg = PredictionMarketConfig()
    assert not (cfg.ingestion_enabled or cfg.polymarket_enabled or cfg.kalshi_enabled)


def test_polymarket_open_market():
    obs = normalize_polymarket_market({
        "conditionId": "0xabc", "question": "Will X happen?", "active": True,
        "closed": False, "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.62", "0.38"]', "volume": "1234.5", "endDate": "2026-12-31",
    })
    assert obs.venue is MarketVenue.POLYMARKET
    assert obs.market_ref == "0xabc"
    assert obs.status is MarketStatus.OPEN
    assert [q.price for q in obs.outcomes] == [Decimal("0.62"), Decimal("0.38")]
    assert obs.volume == Decimal("1234.5")
    assert obs.reported_resolution is None


def test_polymarket_length_mismatch_rejected():
    with pytest.raises(PredictionMarketValidationError):
        normalize_polymarket_market({
            "id": "1", "outcomes": '["Yes","No"]', "outcomePrices": '["0.5"]',
        })


def test_kalshi_cents_to_probability_and_resolution():
    obs = normalize_kalshi_market({
        "ticker": "KX-1", "title": "T", "status": "settled", "result": "yes",
        "last_price": 62, "volume": 10, "close_time": "2026-01-01T00:00:00Z",
    })
    assert obs.status is MarketStatus.RESOLVED
    assert obs.outcomes[0].price == Decimal("0.62")
    assert obs.outcomes[1].price == Decimal("0.38")
    assert obs.reported_resolution == "yes"


def test_missing_price_stays_unknown_not_zero():
    obs = normalize_kalshi_market({"ticker": "KX-2", "status": "open"})
    assert obs.outcomes[0].price is None and obs.outcomes[1].price is None


def test_rejects_floats_out_of_range_and_execution():
    with pytest.raises(PredictionMarketValidationError):
        OutcomeQuote("yes", 0.5)  # type: ignore[arg-type]
    with pytest.raises(PredictionMarketValidationError):
        OutcomeQuote("yes", Decimal("1.5"))
    with pytest.raises(PredictionMarketValidationError):
        MarketObservation(MarketVenue.KALSHI, "k", "t", MarketStatus.OPEN, execution_by_aether=True)
    with pytest.raises(PredictionMarketValidationError):
        MarketObservation(MarketVenue.KALSHI, "", "t", MarketStatus.OPEN)
