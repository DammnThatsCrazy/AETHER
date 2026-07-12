"""PR-B — price sources (FX / token / peg-aware stablecoin), ownership/inclusion
rules, and reconciliation. Root-suite coverage (make ci-check / python-tests).
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

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

from services.value import ownership_rules, price_sources, reconciliation  # noqa: E402
from services.value.models import to_decimal  # noqa: E402


# --- price sources --- #
def test_usd_identity_and_fx_and_token():
    assert price_sources.price(to_decimal("100"), "USD")["usd_value"] == "100"
    assert Decimal(price_sources.price(to_decimal("10"), "EUR")["usd_value"]) == Decimal("10.8")
    assert Decimal(price_sources.price(to_decimal("2"), "ETH")["usd_value"]) == Decimal("6000")


def test_stablecoin_is_peg_aware_not_assumed_one():
    v = price_sources.price(to_decimal("100"), "USDC")
    assert v["valuation_method"] == "stablecoin_peg_verified"
    assert Decimal(v["usd_value"]) == Decimal("100.0")
    assert v["confidence"] == "high"
    # A near-peg stablecoin (USDT 0.999) is still priced, at its peg-aware value.
    vt = price_sources.price(to_decimal("100"), "USDT")
    assert Decimal(vt["usd_value"]) == Decimal("99.9")


def test_unknown_asset_is_unpriced_not_zero():
    assert price_sources.price(to_decimal("5"), "UNKNOWNTOK") is None
    assert price_sources.price(to_decimal("5"), None) is None


# --- ownership / inclusion rules --- #
def test_liability_never_counted_as_asset():
    ok, reason = ownership_rules.rollup_inclusion({"currency": "USD"}, metric_kind="liability")
    assert ok is False and reason == "liability_not_asset"


def test_testnet_and_spam_excluded_by_default():
    ok, reason = ownership_rules.rollup_inclusion({"currency": "ETH", "chain": "sepolia-testnet"})
    assert ok is False and reason == "testnet_excluded"
    ok, reason = ownership_rules.rollup_inclusion({"currency": "ETH", "spam": True})
    assert ok is False and reason == "spam_or_untrusted_excluded"


def test_counterparty_excluded_from_owned_portfolio():
    ok, reason = ownership_rules.rollup_inclusion(
        {"currency": "USD"}, ownership_relationship="counterparty")
    assert ok is False and "counterparty" in reason


def test_owned_asset_included():
    ok, reason = ownership_rules.rollup_inclusion({"currency": "USD"})
    assert ok is True and reason is None


# --- reconciliation --- #
def test_reconciliation_states():
    assert reconciliation.reconcile(sdk_present=True, provider_present=True, amounts_match=True) == "matched"
    assert reconciliation.reconcile(sdk_present=True, provider_present=True, amounts_match=False) == "conflict"
    assert reconciliation.reconcile(sdk_present=True, provider_present=False) == "sdk_only"
    assert reconciliation.reconcile(sdk_present=False, provider_present=True) == "provider_only"
    assert reconciliation.reconcile(sdk_present=True, provider_present=True, stale=True) == "stale"
