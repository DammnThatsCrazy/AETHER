"""Olympus market reference fills the global market registry from public venue data."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from value.derivatives.market_reference import (
    MarketReferenceError,
    MarketReferenceService,
    OlympusMarketSourceProvisioner,
)

FIXTURES = (
    Path(__file__).parents[3]
    / "services" / "api" / "tests" / "fixtures" / "provider_payloads" / "derivatives"
)
PM = json.loads((FIXTURES / "polymarket_live_capture.json").read_text())

META = {"universe": [
    {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
    {"name": "HYPE", "szDecimals": 2, "maxLeverage": 10},
]}


def _client():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.hyperliquid.xyz":
            assert json.loads(request.content) == {"type": "meta"}
            return httpx.Response(200, json=META, request=request)
        if request.url.host == "gamma-api.polymarket.com":
            return httpx.Response(200, json=PM["gamma_markets"], request=request)
        return httpx.Response(404, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clean():
    from connectors.provider_runtime.connection import ProviderConnectionRepository

    reset_typed_in_memory_stores()
    ProviderConnectionRepository()._store.clear()


async def test_olympus_source_is_a_public_reference_grant_without_tenant_rights():
    from connectors.integrations.data_rights.service import data_rights_service

    source = await OlympusMarketSourceProvisioner().provision(venue="hyperliquid", actor="op_1")
    assert source["tenant_id"] == "olympus" and source["state"] == "connected"
    assert source["provider_identity"] == "hyperliquid.markets.market_data"
    grant = await data_rights_service.get_grant(source["grant_id"], tenant_id="olympus")
    assert grant.source_relationship == "public_reference" and grant.raw_data_owner == "public"
    assert grant.connector_class == "olympus_provider"
    # Public reference never licenses tenant, cross-tenant, training or commercial use.
    assert not (grant.tenant_lake_allowed or grant.tenant_graph_allowed or grant.tenant_insights_allowed)
    assert not (grant.cross_tenant_aggregate_allowed or grant.model_training_allowed
                or grant.commercial_reuse_allowed)
    # Provisioning again returns the same source.
    assert (await OlympusMarketSourceProvisioner().provision(venue="hyperliquid", actor="op_1"))[
        "connection_id"] == source["connection_id"]


async def test_unsupported_venue_has_no_market_source():
    with pytest.raises(MarketReferenceError) as exc:
        await OlympusMarketSourceProvisioner().provision(venue="gmx", actor="op_1")
    assert exc.value.reason == "market_reference_not_supported"


async def test_missing_markets_are_fetched_admitted_and_written():
    from repositories.derivatives_repos import InstrumentRepo, MarketRepo

    await OlympusMarketSourceProvisioner().provision(venue="hyperliquid", actor="op_1")
    service = MarketReferenceService(client_factory=_client)
    result = await service.ensure({"hyperliquid:mainnet:HYPE", "hyperliquid:mainnet:NOPE"})
    assert result.written == {"hyperliquid:mainnet:HYPE"}
    assert result.missing == {"hyperliquid:mainnet:NOPE"}
    assert "market_reference_not_found:hyperliquid" in result.reasons
    market = await MarketRepo().find_one({"canonical_market_id": "hyperliquid:mainnet:HYPE"})
    assert market["price_precision"] == Decimal("0.0001") and market["size_precision"] == Decimal("0.01")
    assert market["canonical_instrument_id"] == "perpetual_future:HYPE:USD"
    assert await InstrumentRepo().find_one({"canonical_instrument_id": "perpetual_future:HYPE:USD"})
    # Present rows are not fetched again.
    again = await service.ensure({"hyperliquid:mainnet:HYPE"})
    assert again.present == {"hyperliquid:mainnet:HYPE"} and not again.written


async def test_polymarket_outcome_tokens_become_event_contract_markets():
    from repositories.derivatives_repos import MarketRepo

    await OlympusMarketSourceProvisioner().provision(venue="polymarket", actor="op_1")
    tokens = json.loads(PM["gamma_markets"][0]["clobTokenIds"]) \
        if isinstance(PM["gamma_markets"][0]["clobTokenIds"], str) else PM["gamma_markets"][0]["clobTokenIds"]
    wanted = {f"polymarket:mainnet:{t}" for t in tokens}
    result = await MarketReferenceService(client_factory=_client).ensure(wanted)
    assert result.written == wanted
    row = await MarketRepo().find_one({"canonical_market_id": sorted(wanted)[0]})
    assert row["instrument_type"] == "event_contract" and row["contract_type"] == "binary_outcome"


async def test_no_olympus_source_means_no_reference_rows():
    result = await MarketReferenceService(client_factory=_client).ensure({"hyperliquid:mainnet:HYPE"})
    assert result.missing == {"hyperliquid:mainnet:HYPE"} and not result.written
    assert "market_reference_source_missing:hyperliquid" in result.reasons


async def test_revoked_olympus_grant_stops_reference_writes():
    from connectors.integrations.data_rights.models import DataRightsGrantRevoke
    from connectors.integrations.data_rights.service import data_rights_service
    source = await OlympusMarketSourceProvisioner().provision(venue="hyperliquid", actor="op_1")
    await data_rights_service.revoke_grant(
        source["grant_id"], DataRightsGrantRevoke(revocation_reason="t", revoked_by_user_id="op_1"),
        tenant_id="olympus",
    )
    # The revoked source no longer counts, so nothing is fetched or written.
    result = await MarketReferenceService(client_factory=_client).ensure({"hyperliquid:mainnet:BTC"})
    assert "market_reference_source_missing:hyperliquid" in result.reasons and not result.written
    # Provisioning again creates a fresh source.
    fresh = await OlympusMarketSourceProvisioner().provision(venue="hyperliquid", actor="op_1")
    assert fresh["grant_id"] != source["grant_id"]


async def test_grant_revoked_mid_fetch_denies_the_raw_write():
    from connectors.provider_runtime.rights_admission import ProviderRawRightsDenied

    source = await OlympusMarketSourceProvisioner().provision(venue="hyperliquid", actor="op_1")

    class LateRevocation:
        async def ingest(self, records, *, tenant_id=None):
            raise ProviderRawRightsDenied()

    service = MarketReferenceService(client_factory=_client, raw_store=LateRevocation())
    with pytest.raises(ProviderRawRightsDenied):
        await service.ensure({"hyperliquid:mainnet:BTC"})
    from repositories.derivatives_repos import MarketRepo

    assert await MarketRepo().find_one({"canonical_market_id": "hyperliquid:mainnet:BTC"}) is None
    assert source["grant_id"]
