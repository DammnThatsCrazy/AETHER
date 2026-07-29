"""PR-B (root-suite coverage) — TVL / LTV / portfolio / account rules key
invariants. Full behavior is covered in the backend tests/value suite; this
guarantees CI (make ci-check / python-tests) exercises the modules.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in ("jwt", "cryptography", "cryptography.hazmat"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from decimal import Decimal  # noqa: E402

from services.value import account_rules, ltv_rules, portfolio_rules, tvl_rules  # noqa: E402
from services.value import price_sources  # noqa: E402


@pytest.fixture(autouse=True)
def observed_prices():
    rates = {
        "ETH": (Decimal("3000"), "test_market", "fresh", "high"),
    }
    price_sources.clear_price_providers()
    price_sources.register_price_provider(rates.get)
    yield
    price_sources.clear_price_providers()


def test_net_tvl_subtracts_borrowed_liability():
    net = tvl_rules.net_tvl([
        {"amount": "2", "currency": "ETH"},              # 6000 asset
        {"amount": "1", "currency": "ETH", "is_borrowed": True},  # 3000 debt
    ])
    assert Decimal(net["gross_usd"]) == Decimal("6000")
    assert Decimal(net["borrowed_usd"]) == Decimal("3000")
    assert Decimal(net["net_usd"]) == Decimal("3000")


def test_tvl_wrapped_and_lp_double_count_prevented():
    deduped = tvl_rules.dedupe_wrapped_and_lp([
        {"amount": "1", "currency": "ETH"},
        {"amount": "1", "currency": "WETH", "is_wrapped": True, "wrapped_of": "ETH"},
    ])
    assert [p["currency"] for p in deduped] == ["ETH"]


def test_tvl_unpriced_is_none_never_zero():
    assert tvl_rules.gross_tvl([{"amount": "10", "currency": "UNKNOWNTOK"}])["total_usd"] is None


def test_ltv_net_and_predicted_not_zero():
    assert ltv_rules.net_ltv("1000", "300") == "700"
    assert ltv_rules.net_ltv(None, "300") is None
    assert ltv_rules.predicted_ltv(model="ltv_v1")["predicted_usd"] is None  # never 0


def test_portfolio_net_worth_excludes_liabilities_and_counterparty():
    p = portfolio_rules.portfolio([
        {"amount": "500", "currency": "USD"},
        {"amount": "2", "currency": "ETH"},                               # 6000
        {"amount": "1", "currency": "ETH", "metric_kind": "liability"},   # 3000 liability
        {"amount": "5", "currency": "ETH", "ownership_relationship": "counterparty"},
    ])
    assert Decimal(p["net_worth_usd"]) == Decimal("3500")  # 6500 assets - 3000 liab
    assert p["excluded_count"] >= 1


def test_account_credit_card_is_negative_liability():
    acct = account_rules.account_value({
        "account_type": "credit_card", "current_balance": "800.00", "currency": "USD",
    })
    assert acct["classification"] == "liability"
    assert acct["usd_value"] == "-800.00"
    # Unpriced account -> None, never 0.
    unk = account_rules.account_value({
        "account_type": "checking", "current_balance": "100", "currency": "UNKNOWNTOK",
    })
    assert unk["usd_value"] is None
