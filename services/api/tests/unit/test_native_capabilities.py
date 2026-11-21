"""Native capabilities: public reference data, catalog relationships, Coinbase split, Dune dual use."""

from __future__ import annotations

import pytest

from connectors.integrations.data_rights.models import DataRightsGrantCreate
from connectors.integrations.data_rights.service import (
    DataRightsService,
    GrantClassificationError,
    validate_grant_classification,
)
from connectors.provider_catalog.catalog import PROVIDER_CATALOG
from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID


def _catalog(provider_id: str):
    entries = PROVIDER_CATALOG.values() if isinstance(PROVIDER_CATALOG, dict) else PROVIDER_CATALOG
    return next(e for e in entries if e.provider_id == provider_id)


def _olympus(connector_id: str, relationship: str, **uses) -> DataRightsGrantCreate:
    return DataRightsGrantCreate(
        tenant_id=OLYMPUS_SOURCE_TENANT_ID, source_id=f"{connector_id}:markets", connector_id=connector_id,
        connector_class="olympus_provider", data_category="market",
        raw_data_owner="public" if relationship == "public_reference" else "olympus_labs",
        source_relationship=relationship, **uses,
    )


# ── #9 public reference ─────────────────────────────────────────────────────

@pytest.mark.parametrize("use", ["commercial_reuse_allowed", "model_training_allowed", "cross_tenant_aggregate_allowed"])
def test_public_reference_grants_cannot_allow_reuse(use):
    with pytest.raises(GrantClassificationError, match="public_reference_reuse_forbidden"):
        validate_grant_classification(_olympus("coingecko", "public_reference", **{use: True}))


def test_a_plain_public_reference_grant_is_valid():
    validate_grant_classification(_olympus("coingecko", "public_reference"))


# ── catalog relationships ──────────────────────────────────────────────────

def test_catalogued_reference_providers_are_public_reference():
    for provider_id in ("coingecko", "coinmarketcap", "coinbase_exchange", "binance_public"):
        assert _catalog(provider_id).source_relationship == "public_reference", provider_id


def test_an_olympus_grant_must_carry_the_catalog_relationship():
    with pytest.raises(GrantClassificationError, match="catalog_relationship_mismatch"):
        validate_grant_classification(_olympus("coingecko", "olympus_source"))
    validate_grant_classification(_olympus("dune_api", "olympus_source"))


# ── Dune dual use ──────────────────────────────────────────────────────────

def test_dune_is_olympus_sourced_and_tenant_connectable():
    for provider_id in ("dune_api", "dune_datashare", "dune_sim"):
        entry = _catalog(provider_id)
        assert entry.source_relationship == "olympus_source" and entry.tenant_connectable is True


@pytest.mark.asyncio
async def test_a_tenant_dune_grant_is_organization_system_in_its_own_scope():
    grant = await DataRightsService().create_grant(DataRightsGrantCreate(
        tenant_id="t1", source_id="dune:eth_flows", connector_id="dune_api",
        connector_class="tenant_byod_data", data_category="onchain", raw_data_owner="tenant",
        source_relationship="organization_system", tenant_lake_allowed=True,
    ), granted_by_user_id="u1")
    assert grant.tenant_id == "t1" and not grant.olympus_baseline_allowed


# ── Coinbase split ─────────────────────────────────────────────────────────

def test_coinbase_is_three_separate_capabilities():
    from connectors.integrations.providers.payment_rails.coinbase import CoinbaseAdapter
    from value.derivatives.venue_sources import VENUE_SOURCE_PROFILES

    # Payments: a payment-rail provider (tenant's own Coinbase payments account).
    assert CoinbaseAdapter.provider_name == "coinbase"
    # Exchange account: the regulated futures venue a member links (personal account).
    venue = VENUE_SOURCE_PROFILES["coinbase_futures"]
    assert venue.account_capability == "futures_read"
    # Public market data: Olympus reference data, never a tenant source.
    exchange = _catalog("coinbase_exchange")
    assert exchange.source_relationship == "public_reference" and not exchange.tenant_connectable
