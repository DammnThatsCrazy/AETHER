"""Tests for the value-service financial rules modules (§4.8/4.9/4.13/4.14).

Priced cases use fixture symbols ETH(=3000)/USDC(peg ~1)/USD(identity)/EUR(=1.08);
unpriced cases use UNKNOWNTOK. Core invariant under test: unpriced => None, never 0.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from services.value import (
    account_rules,
    ltv_rules,
    portfolio_rules,
    price_sources,
    tvl_rules,
)


@pytest.fixture(autouse=True)
def observed_price_provider():
    rates = {
        "ETH": Decimal("3000"),
        "BTC": Decimal("60000"),
        "USDC": Decimal("1.000"),
        "EUR": Decimal("1.08"),
    }
    price_sources.register_price_provider(
        lambda symbol: (
            (rates[symbol], "test_observation", "observed", "high")
            if symbol in rates
            else None
        )
    )
    yield
    price_sources.clear_price_providers()


# --------------------------------------------------------------------------- TVL
def test_gross_and_net_tvl_with_borrowed_liability():
    positions = [
        {"amount": "2", "currency": "ETH", "chain": "ethereum"},      # 6000
        {"amount": "1000", "currency": "USD", "chain": "ethereum"},   # 1000
        {"amount": "1", "currency": "ETH", "is_borrowed": True},      # 3000 debt
    ]
    gross = tvl_rules.gross_tvl(positions)
    assert gross["total_usd"] == "7000"

    net = tvl_rules.net_tvl(positions)
    assert net["gross_usd"] == "7000"
    assert net["borrowed_usd"] == "3000"
    assert net["net_usd"] == "4000"


def test_by_chain_and_by_asset():
    positions = [
        {"amount": "2", "currency": "ETH", "chain": "ethereum"},   # 6000
        {"amount": "10", "currency": "USDC", "chain": "base"},     # ~10
        {"amount": "1", "currency": "ETH", "chain": "base"},       # 3000
    ]
    by_chain = tvl_rules.by_chain(positions)
    assert by_chain["ethereum"] == "6000"
    assert by_chain["base"] == "3010.000"  # 3000 + 10*1.000

    by_asset = tvl_rules.by_asset(positions)
    assert by_asset["ETH"] == "9000"
    assert by_asset["USDC"] == "10.000"


def test_dedupe_wrapped_and_lp_prevents_double_count():
    positions = [
        {"amount": "1", "currency": "ETH"},
        {"amount": "1", "currency": "WETH", "is_wrapped": True, "wrapped_of": "ETH"},
        {"amount": "5", "currency": "USDC"},
        {"amount": "1", "currency": "LP-ETH-USDC", "is_lp": True,
         "lp_underlying": ["ETH", "USDC"]},
    ]
    deduped = tvl_rules.dedupe_wrapped_and_lp(positions)
    symbols = [p.get("currency") for p in deduped]
    assert symbols == ["ETH", "USDC"]  # WETH dropped (ETH held), LP dropped (legs held)

    # A wrapper with no underlying held is retained (represents real value).
    kept = tvl_rules.dedupe_wrapped_and_lp(
        [{"amount": "1", "currency": "WBTC", "is_wrapped": True, "wrapped_of": "BTC"}]
    )
    assert [p["currency"] for p in kept] == ["WBTC"]


def test_testnet_and_spam_excluded_from_tvl():
    positions = [
        {"amount": "2", "currency": "ETH"},                          # 6000, counts
        {"amount": "5", "currency": "ETH", "testnet": True},         # excluded
        {"amount": "5", "currency": "ETH", "network": "sepolia"},    # excluded
        {"amount": "5", "currency": "ETH", "spam": True},            # excluded
    ]
    gross = tvl_rules.gross_tvl(positions)
    assert gross["total_usd"] == "6000"
    assert gross["excluded_count"] == 3


def test_tvl_unpriced_is_none_never_zero():
    gross = tvl_rules.gross_tvl([{"amount": "10", "currency": "UNKNOWNTOK"}])
    assert gross["total_usd"] is None
    net = tvl_rules.net_tvl([{"amount": "10", "currency": "UNKNOWNTOK"}])
    assert net["gross_usd"] is None
    assert net["net_usd"] is None


# --------------------------------------------------------------------------- LTV
def test_historical_ltv_usd_first():
    events = [
        {"value_usd": "12.50"},                       # explicit USD wins
        {"amount": "1", "currency": "ETH"},           # priced to 3000
        {"amount": "3", "currency": "UNKNOWNTOK"},    # unpriced
    ]
    result = ltv_rules.historical_ltv(events)
    assert result["usd_basis"] == "3012.50"
    assert result["source_event_count"] == 3
    assert result["excluded_unpriced"] == 1
    assert result["confidence"] == "medium"


def test_historical_ltv_window_filter():
    events = [
        {"value_usd": "10", "occurred_at": "2026-01-01T00:00:00Z"},
        {"value_usd": "20", "occurred_at": "2026-06-01T00:00:00Z"},
    ]
    windowed = ltv_rules.historical_ltv(
        events, window={"start": "2026-05-01T00:00:00Z", "end": "2026-12-31T00:00:00Z"}
    )
    assert windowed["usd_basis"] == "20"
    assert windowed["source_event_count"] == 1
    assert windowed["window"] == {"start": "2026-05-01T00:00:00Z", "end": "2026-12-31T00:00:00Z"}


def test_predicted_ltv_not_zero_on_absence():
    present = ltv_rules.predicted_ltv(
        model="ltv_v1", model_version="2026.07", predicted_usd="450.00", confidence="medium"
    )
    assert present["predicted_usd"] == "450.00"
    assert present["model"] == "ltv_v1"
    assert present["confidence"] == "medium"

    absent = ltv_rules.predicted_ltv(model="ltv_v1")
    assert absent["predicted_usd"] is None  # never 0
    assert absent["usd_basis"] is None


def test_net_ltv():
    assert ltv_rules.net_ltv("1000", "300") == "700"
    assert ltv_rules.net_ltv(None, "300") is None
    assert ltv_rules.net_ltv("1000", None) == "1000"


# --------------------------------------------------------------------- PORTFOLIO
def test_portfolio_buckets_net_worth_and_counterparty_excluded():
    holdings = [
        {"amount": "500", "currency": "USD"},                        # cash 500
        {"amount": "100", "currency": "USDC"},                       # stablecoin ~100
        {"amount": "2", "currency": "ETH"},                          # volatile 6000
        {"amount": "1", "currency": "ETH", "metric_kind": "liability"},  # liability 3000
        {"amount": "5", "currency": "ETH", "ownership_relationship": "counterparty"},  # excluded
    ]
    p = portfolio_rules.portfolio(holdings)
    assert p["cash_usd"] == "500"
    assert p["stablecoin_usd"] == "100.000"
    assert p["volatile_crypto_usd"] == "6000"
    assert p["liabilities_usd"] == "3000"

    # total = 500 + 100 + 6000 ; net worth = total - liabilities
    assert p["total_portfolio_usd"] == "6600.000"
    assert p["net_worth_usd"] == "3600.000"

    # counterparty holding excluded from owned totals but counted as excluded.
    assert p["excluded_count"] >= 1
    assert p["by_asset"].get("ETH") == "6000"  # counterparty ETH not in owned by_asset
    assert p["ownership_confidence"] in {"high", "medium"}


def test_portfolio_locked_staked_and_claimable_and_testnet_excluded():
    holdings = [
        {"amount": "1", "currency": "ETH", "staked": True},          # locked_staked 3000
        {"amount": "10", "currency": "USDC", "claimable": True},     # claimable ~10
        {"amount": "99", "currency": "ETH", "testnet": True},        # excluded
    ]
    p = portfolio_rules.portfolio(holdings)
    assert p["locked_staked_usd"] == "3000"
    assert p["claimable_rewards_usd"] == "10.000"
    assert p["volatile_crypto_usd"] is None  # nothing classified as plain volatile
    assert p["excluded_count"] >= 1


def test_portfolio_all_unpriced_is_none():
    p = portfolio_rules.portfolio([{"amount": "10", "currency": "UNKNOWNTOK"}])
    assert p["volatile_crypto_usd"] is None
    assert p["total_portfolio_usd"] is None
    assert p["net_worth_usd"] is None


# ----------------------------------------------------------------------- ACCOUNT
def test_account_asset_positive():
    acct = account_rules.account_value({
        "account_type": "checking", "current_balance": "1500.00",
        "available_balance": "1400.00", "currency": "USD", "provider": "plaid",
        "last_synced": "2026-07-12T00:00:00Z",
    })
    assert acct["classification"] == "asset"
    assert acct["usd_value"] == "1500.00"
    assert acct["current"] == "1500.00"
    assert acct["available"] == "1400.00"
    assert acct["display"]["primary"] == "$1500.00 USD"


def test_account_credit_card_liability_negative():
    acct = account_rules.account_value({
        "account_type": "credit_card", "current_balance": "800.00", "currency": "USD",
    })
    assert acct["classification"] == "liability"
    assert acct["usd_value"] == "-800.00"
    assert acct["display"]["primary"].startswith("-$")


def test_account_negative_balance_is_liability():
    acct = account_rules.account_value({
        "account_type": "depository", "current_balance": "-120.00", "currency": "USD",
    })
    assert acct["classification"] == "liability"
    assert acct["usd_value"] == "-120.00"


def test_account_fx_asset_and_unpriced():
    eur = account_rules.account_value({
        "account_type": "savings", "current_balance": "100", "currency": "EUR",
    })
    assert eur["usd_value"] == "108.00"  # 100 * 1.08
    assert eur["original_currency"] == "EUR"

    unknown = account_rules.account_value({
        "account_type": "checking", "current_balance": "100", "currency": "UNKNOWNTOK",
    })
    assert unknown["usd_value"] is None  # unpriced -> None, never 0
    assert unknown["display"]["primary"] == "Value unavailable"
