"""Pure event-time valuation engine tests (no DB, no registry lane, no network)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from services.valuation.engine import value_at
from services.valuation.models import TenantValuePolicy
from services.valuation.price_providers import (
    FALLBACK,
    ORACLE,
    PROVIDER_REPORTED,
    PriceFixtures,
    market_observation,
    seconds_before,
)

from ._fakes import FakeObservationStore, FakeRegistry, native_payload

EFFECTIVE = "2026-09-02T12:00:00+00:00"
USD = "fiat:USD"
GBP = "fiat:GBP"
ETH = "crypto:ETH"
USDC = "stablecoin:USDC"


def _policy(
    *,
    tenant: str = "tenant_a",
    allowed=(USD,),
    chain: str = "default",
    fallback: bool = False,
    stale: int | None = None,
    version: str = "pol-v1",
) -> TenantValuePolicy:
    return TenantValuePolicy(
        tenant_id=tenant,
        allowed_reporting_asset_ids=list(allowed),
        provider_chain_policy=chain,
        stale_threshold_seconds=stale,
        fallback_allowed=fallback,
        policy_version=version,
    )


# ── USD fiat identity ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usd_fiat_identity():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD}, registry_version="reg-1")
    snap = await value_at(
        native_payload("42.50", "USD", canonical_asset_id=USD),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "normal"
    assert snap.valuation_method == "fiat_identity"
    assert snap.reporting_amount == Decimal("42.50")
    assert snap.reporting_asset_id == USD
    assert snap.native_currency == "USD"
    assert snap.provider is None
    assert snap.price_observation_ids == []
    assert snap.tenant_id == "tenant_a"
    assert snap.economic_role == "unknown"


# ── FX fiat conversion ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fx_gbp_to_usd_conversion():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().fx_gbp_to_usd(EFFECTIVE))
    registry = FakeRegistry(known_ids={GBP})
    snap = await value_at(
        native_payload("100", "GBP", canonical_asset_id=GBP),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "normal"
    assert snap.valuation_method == "fx_rate"
    assert snap.reporting_amount == Decimal("125.00")
    assert len(snap.price_observation_ids) == 1


@pytest.mark.asyncio
async def test_fx_jpy_to_usd_conversion():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().fx_jpy_to_usd(EFFECTIVE))
    registry = FakeRegistry(known_ids={"fiat:JPY"})
    snap = await value_at(
        native_payload("10000", "JPY", canonical_asset_id="fiat:JPY"),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "normal"
    assert snap.valuation_method == "fx_rate"
    assert snap.reporting_amount == Decimal("100.00")


@pytest.mark.asyncio
async def test_fx_inverse_quote_usd_in_gbp_values_gbp_native():
    # FX provider only quotes the inverse pair (fiat:USD -> fiat:GBP); native GBP
    # to USD reporting must invert (1 / 0.80 = 1.25).
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().fx_usd_quoted_in_gbp(EFFECTIVE))
    registry = FakeRegistry(known_ids={GBP})
    snap = await value_at(
        native_payload("100", "GBP", canonical_asset_id=GBP),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "normal"
    assert snap.valuation_method == "fx_rate"
    assert snap.reporting_amount == Decimal("125.00")


# ── Stablecoin peg-aware valuation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_stablecoin_healthy_peg_uses_observed_price_not_one():
    # Never assume $1: the healthy-peg observation 1.0001 flows through classify
    # as on_peg -> stablecoin_peg_verified, and the amount reflects 1.0001.
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().usdc_in_usd("1.0001", EFFECTIVE, provider=ORACLE))
    registry = FakeRegistry(known_ids={USDC}, registry_version="reg-1")
    snap = await value_at(
        native_payload("1000", "USDC", canonical_asset_id=USDC),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "normal"
    assert snap.valuation_method == "stablecoin_peg_verified"
    assert snap.reporting_amount == Decimal("1000.1")


@pytest.mark.asyncio
async def test_stablecoin_depeg_is_reflected():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().usdc_in_usd("0.98", EFFECTIVE, provider=ORACLE))
    registry = FakeRegistry(known_ids={USDC})
    snap = await value_at(
        native_payload("1000", "USDC", canonical_asset_id=USDC),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "normal"
    assert snap.valuation_method == "stablecoin_peg"
    assert snap.reporting_amount == Decimal("980.00")


# ── Provider conflict / outlier / stale / missing ───────────────────────────


@pytest.mark.asyncio
async def test_provider_conflict_is_surfaced_not_silently_picked():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().provider_conflict(EFFECTIVE))
    registry = FakeRegistry(known_ids={ETH})
    snap = await value_at(
        native_payload("2", "ETH", canonical_asset_id=ETH),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "provider_conflict"
    assert snap.reporting_amount is None
    assert snap.valuation_method == "unavailable"
    assert len(snap.price_observation_ids) == 2


@pytest.mark.asyncio
async def test_outlier_top_feed_is_not_silently_picked():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().outlier_eth(EFFECTIVE))
    registry = FakeRegistry(known_ids={ETH})
    snap = await value_at(
        native_payload("2", "ETH", canonical_asset_id=ETH),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "outlier"
    assert snap.reporting_amount is None


@pytest.mark.asyncio
async def test_stale_observation_yields_stale_rate_with_value():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().stale_eth(EFFECTIVE))
    registry = FakeRegistry(known_ids={ETH})
    snap = await value_at(
        native_payload("2", "ETH", canonical_asset_id=ETH),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "stale_rate"
    assert snap.reporting_amount == Decimal("200.00")


@pytest.mark.asyncio
async def test_missing_rate_has_null_reporting():
    store = FakeObservationStore()  # no observations at all
    registry = FakeRegistry(known_ids={ETH})
    snap = await value_at(
        native_payload("2", "ETH", canonical_asset_id=ETH),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "missing_rate"
    assert snap.valuation_method == "unavailable"
    assert snap.reporting_amount is None
    assert snap.provider is None


@pytest.mark.asyncio
async def test_conflict_with_fallback_allowed_degrades_to_fallback():
    store = FakeObservationStore()
    store.add_observations(PriceFixtures().provider_conflict(EFFECTIVE))
    store.add_observations([
        market_observation(
            ETH, USD, "99.00", FALLBACK, seconds_before(EFFECTIVE, 10),
            source="fallback:eth", freshness_window_seconds=3600,
        )
    ])
    registry = FakeRegistry(known_ids={ETH})
    snap = await value_at(
        native_payload("2", "ETH", canonical_asset_id=ETH),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(fallback=True),
    )
    assert snap.price_status == "fallback"
    assert snap.valuation_method == "market_price"
    assert snap.reporting_amount == Decimal("198.00")


# ── Unknown asset / unresolved ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_asset_is_recorded_and_reporting_null():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids=set())  # resolves nothing
    snap = await value_at(
        native_payload("5", "DOGE"),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.price_status == "missing_rate"
    assert snap.reporting_amount is None
    assert snap.canonical_asset_id is None
    assert snap.economic_role == "unknown"
    assert len(registry.unresolved) == 1
    assert registry.unresolved[0]["raw_reference"] == "DOGE"
    assert registry.unresolved[0]["reason"] == "no_registry_entry"
    assert registry.unresolved[0]["tenant_id"] == "tenant_a"


# ── Economic role ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_economic_role_defaults_to_unknown():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    snap = await value_at(
        native_payload("10", "USD", canonical_asset_id=USD),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.economic_role == "unknown"


@pytest.mark.asyncio
async def test_economic_role_explicit_payment_is_preserved():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    snap = await value_at(
        native_payload("10", "USD", canonical_asset_id=USD),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
        economic_role="payment",
    )
    assert snap.economic_role == "payment"


@pytest.mark.asyncio
async def test_economic_role_from_native_payload_hint():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    snap = await value_at(
        native_payload("10", "USD", canonical_asset_id=USD, economic_role="fee"),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_policy=_policy(),
    )
    assert snap.economic_role == "fee"


# ── Tenant policy enforcement ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_policy_rejects_disallowed_reporting_asset():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    with pytest.raises(ValueError):
        await value_at(
            native_payload("10", "USD", canonical_asset_id=USD),
            effective_at=EFFECTIVE,
            reporting_asset_id="fiat:EUR",
            registry=registry,
            observations=store,
            tenant_policy=_policy(allowed=(USD,)),
        )


@pytest.mark.asyncio
async def test_unknown_policy_chain_fails_closed():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    with pytest.raises(ValueError):
        await value_at(
            native_payload("10", "USD", canonical_asset_id=USD),
            effective_at=EFFECTIVE,
            reporting_asset_id=USD,
            registry=registry,
            observations=store,
            tenant_policy=_policy(chain="not_a_real_policy"),
        )


@pytest.mark.asyncio
async def test_tenant_id_required_without_policy():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    with pytest.raises(ValueError):
        await value_at(
            native_payload("10", "USD", canonical_asset_id=USD),
            effective_at=EFFECTIVE,
            reporting_asset_id=USD,
            registry=registry,
            observations=store,
        )


@pytest.mark.asyncio
async def test_tenant_id_kwarg_supplies_tenant_without_policy():
    store = FakeObservationStore()
    registry = FakeRegistry(known_ids={USD})
    snap = await value_at(
        native_payload("10", "USD", canonical_asset_id=USD),
        effective_at=EFFECTIVE,
        reporting_asset_id=USD,
        registry=registry,
        observations=store,
        tenant_id="route_tenant",
    )
    assert snap.tenant_id == "route_tenant"
