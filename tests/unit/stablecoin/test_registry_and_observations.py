"""Registry seeding/resolution + observation intake correctness."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.stablecoin.models import StablecoinObservationIngest
from services.stablecoin.registry import StablecoinRegistry
from services.stablecoin.service import StablecoinObservationService

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TENANT = "t-stable"


def _ingest(**overrides) -> StablecoinObservationIngest:
    payload = {
        "observation_type": "transfer",
        "chain_id": "eip155:8453",
        "transaction_hash": "0x" + "ab" * 32,
        "log_or_instruction_index": 3,
        "contract_or_mint": USDC_BASE,
        "amount_atomic": "1000000",
        "from_address": "0xfrom",
        "to_address": "0xto",
        "observed_at": "2026-07-08T12:00:00+00:00",
    }
    payload.update(overrides)
    return StablecoinObservationIngest(**payload)


async def test_seed_from_x402_contracts_is_idempotent():
    registry = StablecoinRegistry()
    first = await registry.seed_canonical_assets()
    assert first["inserted_assets"] >= 1
    assert first["inserted_deployments"] >= 3  # Base + Base Sepolia + Solana USDC
    again = await registry.seed_canonical_assets()
    assert again["inserted_assets"] == 0
    assert again["inserted_deployments"] == 0
    assert again["emitted_events"] == []


async def test_resolve_deployment_is_case_insensitive_for_evm():
    registry = StablecoinRegistry()
    await registry.seed_canonical_assets()
    resolved = await registry.resolve_deployment("eip155:8453", USDC_BASE.lower())
    assert resolved is not None
    assert resolved["canonical_asset_id"] == "usdc"
    assert resolved["decimals"] == 6


async def test_ingest_is_deterministic_and_replay_safe():
    service = StablecoinObservationService()
    await service.registry.seed_canonical_assets()

    first = await service.ingest_observation(TENANT, _ingest())
    assert first["inserted"] is True
    assert first["deployment_resolution"] == "by_contract"
    assert first["emitted_events"][0]["event_name"] == "stablecoin_transfer_observed"

    replay = await service.ingest_observation(TENANT, _ingest())
    assert replay["inserted"] is False
    assert replay["observation_id"] == first["observation_id"]
    assert replay["emitted_events"] == []


async def test_atomic_to_decimal_scaling_is_exact():
    service = StablecoinObservationService()
    await service.registry.seed_canonical_assets()
    await service.ingest_observation(TENANT, _ingest(amount_atomic="1000001"))
    rows = await service.observations.find_many({"tenant_id": TENANT})
    assert rows[0]["amount_decimal"] == Decimal("1.000001")
    assert isinstance(rows[0]["amount_decimal"], Decimal)


async def test_float_amounts_are_rejected():
    with pytest.raises(Exception):
        _ingest(amount_atomic=1000000.5)


async def test_unresolved_contract_keeps_observation_visible():
    service = StablecoinObservationService()
    result = await service.ingest_observation(
        TENANT, _ingest(contract_or_mint="0x0000000000000000000000000000000000000bad"),
    )
    assert result["deployment_resolution"] == "unresolved"
    rows = await service.observations.find_many({"tenant_id": TENANT})
    assert rows[0]["canonical_asset_id"] == "unresolved"
    assert rows[0]["classification_confidence"] == "0"


async def test_each_observation_type_maps_to_its_canonical_event():
    service = StablecoinObservationService()
    await service.registry.seed_canonical_assets()
    cases = {
        "payment": "stablecoin_payment_observed",
        "mint": "stablecoin_mint_observed",
        "bridge_outbound": "stablecoin_bridge_outbound_observed",
        "swap": "stablecoin_swap_observed",
        "x402_settlement": "stablecoin_x402_settlement_observed",
    }
    for index, (obs_type, event_name) in enumerate(cases.items()):
        result = await service.ingest_observation(
            TENANT, _ingest(observation_type=obs_type, log_or_instruction_index=100 + index),
        )
        assert result["emitted_events"][0]["event_name"] == event_name


async def test_unknown_observation_type_is_not_ingestable():
    with pytest.raises(Exception):
        _ingest(observation_type="unknown")
