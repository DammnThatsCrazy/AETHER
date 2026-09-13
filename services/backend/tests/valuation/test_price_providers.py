"""Pure unit tests for the deterministic price-provider vocabulary + fixtures."""
from __future__ import annotations

from decimal import Decimal

import pytest

from services.valuation.models import PRICE_STATUSES
from services.valuation.price_providers import (
    DEFAULT_PROVIDER_CHAIN,
    FX,
    FALLBACK,
    ORACLE,
    PROVIDER_REPORTED,
    PROVIDER_VALUATION_METHODS,
    PriceFixtures,
    make_observation,
    provider_chain_for,
)

EFFECTIVE = "2026-09-02T12:00:00+00:00"


def test_make_observation_returns_validated_decimal_price():
    obs = make_observation(
        asset_id="crypto:ETH",
        quote_asset_id="fiat:USD",
        price="2500.50",
        provider=ORACLE,
        observed_at=EFFECTIVE,
        source="test",
    )
    assert isinstance(obs.price, Decimal)
    assert obs.price == Decimal("2500.50")
    assert obs.observation_id.startswith("obs_")
    assert obs.freshness_window_seconds is not None


def test_make_observation_rejects_binary_float_price():
    with pytest.raises(TypeError):
        make_observation(
            asset_id="crypto:ETH",
            quote_asset_id="fiat:USD",
            price=1.5,
            provider=ORACLE,
            observed_at=EFFECTIVE,
            source="test",
        )


def test_make_observation_rejects_unknown_provider():
    with pytest.raises(ValueError):
        make_observation(
            asset_id="crypto:ETH",
            quote_asset_id="fiat:USD",
            price="1",
            provider="not_a_provider",
            observed_at=EFFECTIVE,
            source="test",
        )


def test_default_chain_and_policy_registry():
    assert PROVIDER_REPORTED in DEFAULT_PROVIDER_CHAIN
    assert FALLBACK in DEFAULT_PROVIDER_CHAIN
    assert provider_chain_for("default") == DEFAULT_PROVIDER_CHAIN
    with pytest.raises(ValueError):
        provider_chain_for("not_a_real_policy")


def test_provider_method_mapping_is_valid():
    for provider, method in PROVIDER_VALUATION_METHODS.items():
        assert method in {
            "provider_reported", "venue_exec", "primary_market", "fx_rate",
            "stablecoin_peg", "oracle", "market_price", "manual",
        }
    assert PROVIDER_VALUATION_METHODS[FX] == "fx_rate"


def test_fixture_provider_conflict_has_two_independent_providers():
    fixtures = PriceFixtures()
    observations = fixtures.provider_conflict(EFFECTIVE)
    assert len(observations) == 2
    assert {o.provider for o in observations} == {PROVIDER_REPORTED, ORACLE}


def test_fixture_outlier_has_an_outlier_top_feed():
    fixtures = PriceFixtures()
    observations = fixtures.outlier_eth(EFFECTIVE)
    assert len(observations) == 3
    top = next(o for o in observations if o.provider == PROVIDER_REPORTED)
    assert top.price == Decimal("180.00")


def test_fixture_statuses_are_pricestatus_members():
    # Every status the fixtures / engine can emit is a legal PriceStatus member.
    assert {"normal", "provider_conflict", "stale_rate", "missing_rate",
            "outlier", "fallback", "unavailable"} <= PRICE_STATUSES
