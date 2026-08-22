"""Tests for services.value.fx_provider (Program 5 / multi-currency, M1).

Scope is exactly the M1 increment described in
docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §5: register a real FX
PriceProvider covering price_sources._FX_FIAT_SYMBOLS, backed by a documented
snapshot rate table, with zero behavior change to measurement (nothing in
measurement calls price_sources yet). These tests exercise the provider
directly and through the public price_sources.price() entry point, and pin
the "unpriced, never fabricated 0/1:1" invariant for unsupported symbols.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from services.value import fx_provider, price_sources


@pytest.fixture(autouse=True)
def registered_fx_provider():
    # fx_provider self-registers on import (module-level `register()` call),
    # but call it again explicitly here to (a) document the dependency and
    # (b) stay correct even if import order ever changes; register_price_provider
    # is idempotent (dedupes by identity), so this never double-registers.
    fx_provider.register()
    yield
    price_sources.clear_price_providers()


# --------------------------------------------------------------- direct provider
def test_provider_returns_decimal_rate_for_known_fiat_symbol():
    observation = fx_provider.fx_snapshot_provider("EUR")
    assert observation is not None
    rate, source, freshness, confidence = observation
    assert isinstance(rate, Decimal)
    assert rate == Decimal("1.08")
    assert source == fx_provider._SNAPSHOT_SOURCE
    assert freshness == "recent"
    assert confidence in {"high", "medium", "low"}


@pytest.mark.parametrize(
    "symbol",
    ["EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "BRL", "MXN"],
)
def test_provider_covers_every_fx_fiat_symbol(symbol):
    # Every symbol price_sources._FX_FIAT_SYMBOLS names must resolve to a
    # real Decimal rate from this provider, never None.
    observation = fx_provider.fx_snapshot_provider(symbol)
    assert observation is not None, f"{symbol} should be priced by fx_provider"
    rate = observation[0]
    assert isinstance(rate, Decimal)
    assert rate > 0


def test_provider_yields_unpriced_never_zero_for_unsupported_symbol():
    # Never a fabricated 0 or 1:1 default for a symbol this snapshot doesn't cover.
    assert fx_provider.fx_snapshot_provider("XYZ") is None
    assert fx_provider.fx_snapshot_provider("BTC") is None  # token, not fiat — out of scope here


# ------------------------------------------------------------ via price_sources
def test_price_sources_prices_known_fiat_symbol_with_provenance():
    result = price_sources.price(Decimal("100"), "EUR")
    assert result is not None
    assert result["usd_value"] == format(Decimal("100") * Decimal("1.08"), "f")
    assert result["valuation_method"] == "fx_rate"
    assert result["conversion_rate"] == format(Decimal("1.08"), "f")
    assert result["conversion_source"] == fx_provider._SNAPSHOT_SOURCE


def test_price_sources_prices_known_fiat_symbol_case_insensitively():
    # price_sources.price() upcases before calling providers.
    result = price_sources.price(Decimal("10"), "eur")
    assert result is not None
    assert result["conversion_rate"] == format(Decimal("1.08"), "f")


def test_price_sources_unpriced_for_unsupported_symbol_never_zero():
    result = price_sources.price(Decimal("100"), "XYZ")
    assert result is None  # unpriced, not a fabricated 0 or 1:1 value


def test_price_sources_still_prices_usd_as_identity():
    # Registering the FX provider must not disturb the pre-existing USD
    # identity path.
    result = price_sources.price(Decimal("50"), "USD")
    assert result is not None
    assert result["valuation_method"] == "fiat_identity"
    assert result["usd_value"] == format(Decimal("50"), "f")


# --------------------------------------------------------------------- registry
def test_provider_is_discoverable_via_the_registry():
    assert fx_provider.fx_snapshot_provider in price_sources._providers


def test_register_is_idempotent():
    before = len(price_sources._providers)
    fx_provider.register()
    fx_provider.register()
    after = len(price_sources._providers)
    assert after == before
