"""Concrete port adapters over the real registry + observation repo — DB-free.

The Wave-3 adapters (services/valuation/adapters.py) are tested against the real
UniversalAssetRegistry and the typed valuation_price_observations repo using the
AETHER_ENV=local in-memory fallback: idempotent observation appends, the
observed_at cut / deployment scoping the engine relies on, canonicalization of
namespaced assets, and exactly-once unresolved recording.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.valuation.adapters import (
    ValuationObservationStore,
    ValuationRegistryPort,
)
from services.valuation.price_providers import (
    PROVIDER_REPORTED,
    market_observation,
    seconds_before,
)

from ._persistence_helpers import (
    EFFECTIVE,
    ETH,
    USD,
    eth_observation,
    make_registry,
    native_payload,
)

DEPLOY = "deploy:crypto:ETH@eip155:8453:0x0000000000000000000000000000000000000000"


@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


# ── ObservationStorePort adapter ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observation_store_record_is_idempotent():
    store = ValuationObservationStore()
    obs = eth_observation("100.00")
    assert await store.record_observation(obs) is True
    assert await store.record_observation(obs) is False
    rows = await store.repo.find_many()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_observation_store_orders_desc_and_filters_observed_at():
    store = ValuationObservationStore()
    await store.record_observation(eth_observation("100.00", observed_at=seconds_before(EFFECTIVE, 7200)))
    await store.record_observation(eth_observation("105.00", observed_at=seconds_before(EFFECTIVE, 60)))
    # A future observation must be excluded (observed_at <= effective_at).
    await store.record_observation(eth_observation("999.00", observed_at="2026-09-02T12:10:00+00:00"))

    rows = await store.observations_for(ETH, None, PROVIDER_REPORTED, EFFECTIVE)
    assert [r.observation_id for r in rows] == [
        eth_observation("105.00", observed_at=seconds_before(EFFECTIVE, 60)).observation_id,
        eth_observation("100.00", observed_at=seconds_before(EFFECTIVE, 7200)).observation_id,
    ]


@pytest.mark.asyncio
async def test_observation_store_deployment_scoping():
    store = ValuationObservationStore()
    asset_level = eth_observation("100.00")
    scoped = eth_observation("99.00", observed_at=seconds_before(EFFECTIVE, 30),
                             source="venue:eth")
    scoped = scoped.model_copy(update={"deployment_id": DEPLOY, "observation_id": "obs_deploy"})
    await store.record_observation(asset_level)
    await store.record_observation(scoped)

    # Asset-level lookup must not surface deployment-scoped facts.
    level_rows = await store.observations_for(ETH, None, PROVIDER_REPORTED, EFFECTIVE)
    assert [r.observation_id for r in level_rows] == [asset_level.observation_id]

    # Deployment-scoped lookup returns only that deployment's fact.
    scoped_rows = await store.observations_for(ETH, DEPLOY, PROVIDER_REPORTED, EFFECTIVE)
    assert [r.observation_id for r in scoped_rows] == ["obs_deploy"]


@pytest.mark.asyncio
async def test_observation_store_decodes_decimal_price():
    store = ValuationObservationStore()
    await store.record_observation(eth_observation("100.5"))
    rows = await store.observations_for(ETH, None, PROVIDER_REPORTED, EFFECTIVE)
    assert isinstance(rows[0].price, Decimal)
    assert rows[0].price == Decimal("100.5")


# ── RegistryPort adapter ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_port_canonicalize_resolves_namespaced_asset():
    registry = await make_registry(USD, ETH)
    port = ValuationRegistryPort(registry, tenant_id="tenant_a")
    canonical = await port.canonicalize(
        native_payload("2", "ETH", canonical_asset_id=ETH),
    )
    assert canonical is not None
    assert canonical.canonical_asset_id == ETH
    assert canonical.amount == Decimal("2")
    assert canonical.currency == "ETH"
    assert port.registry_version  # deterministic digest surfaced on the port


@pytest.mark.asyncio
async def test_registry_port_canonicalize_returns_none_for_unknown():
    registry = await make_registry(USD)  # no DOGE
    port = ValuationRegistryPort(registry, tenant_id="tenant_a")
    canonical = await port.canonicalize(native_payload("5", "DOGE"))
    assert canonical is None
    # The resolver recorded the unresolved sighting explicitly.
    rows = await registry.unresolved.find_many({"tenant_id": "tenant_a"})
    assert len(rows) == 1
    assert rows[0]["raw_reference"] == "DOGE"


@pytest.mark.asyncio
async def test_record_unresolved_is_exactly_once_after_canonicalize():
    registry = await make_registry(USD)
    port = ValuationRegistryPort(registry, tenant_id="tenant_a")
    assert await port.canonicalize(native_payload("5", "DOGE")) is None
    # The engine calls record_unresolved after canonicalize returns None; the
    # sighting was already recorded by the resolver -> must not double-count.
    await port.record_unresolved(
        raw_reference="DOGE", tenant_id="tenant_a",
        reason="no_registry_entry", observed_at=EFFECTIVE,
    )
    rows = await registry.unresolved.find_many({"tenant_id": "tenant_a"})
    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 1


@pytest.mark.asyncio
async def test_registry_port_asset_for_returns_canonical_asset():
    registry = await make_registry(USD, ETH)
    port = ValuationRegistryPort(registry, tenant_id="tenant_a")
    asset = await port.asset_for(ETH)
    assert asset is not None
    assert asset.id == ETH and asset.kind == "crypto"
    assert await port.asset_for("fiat:EUR") is None


@pytest.mark.asyncio
async def test_registry_port_resolve_deployment_by_id():
    registry = await make_registry(USD, ETH)
    from services.assets.models import AssetDeployment

    await registry.register_deployment(AssetDeployment(
        deployment_id=DEPLOY,
        asset_id=ETH,
        chain_id="eip155:8453",
        contract_or_mint="0x0000000000000000000000000000000000000000",
        decimals=18,
    ))
    stored = await registry.deployments.find_one({"asset_id": ETH})
    stored_deploy_id = stored["deployment_id"]
    port = ValuationRegistryPort(registry, tenant_id="tenant_a")
    dep = await port.resolve_deployment(ETH, deployment_id=stored_deploy_id)
    assert dep is not None and dep.deployment_id == stored_deploy_id
    # Deployment of a different asset must not resolve under crypto:ETH.
    other = await port.resolve_deployment("stablecoin:USDC", deployment_id=stored_deploy_id)
    assert other is None


@pytest.mark.asyncio
async def test_observation_store_ignores_unknown_deployment_on_asset_level():
    store = ValuationObservationStore()
    market_obs = market_observation(
        ETH, USD, "100.00", PROVIDER_REPORTED, seconds_before(EFFECTIVE, 60),
        source="provider:eth",
    )
    await store.record_observation(market_obs)
    rows = await store.observations_for(ETH, "deploy:nope", PROVIDER_REPORTED, EFFECTIVE)
    assert rows == []
