import sys
from decimal import Decimal
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from services.stablecoins.models import StablecoinMoney, StablecoinObservation, FinalityState, StablecoinEventType
from services.stablecoins.registry import PLATFORM_STABLECOIN_REGISTRY
from repositories.stablecoin_repos import StablecoinGoldIdentity
from repositories.lake import BronzeRepository, SilverRepository


def test_unlike_stablecoin_quantities_cannot_be_added():
    usdc = StablecoinMoney(1000000, 6, "usdc", "usdc:base", "8453", "base-mainnet")
    usdt = StablecoinMoney(1000000, 6, "usdt", "usdt:ethereum", "1", "ethereum-mainnet")
    with pytest.raises(ValueError):
        usdc.add(usdt)


def test_decimal_safe_atomic_conversion():
    amount = StablecoinMoney(1234567, 6, "usdc", "usdc:base", "8453", "base-mainnet")
    assert amount.amount_decimal == Decimal("1.234567")


def test_deployments_are_chain_specific():
    eth = PLATFORM_STABLECOIN_REGISTRY.resolve(chain_id="1", network="ethereum-mainnet", contract_or_mint="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    base = PLATFORM_STABLECOIN_REGISTRY.resolve(chain_id="8453", network="base-mainnet", contract_or_mint="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    assert eth and base
    assert eth.canonical_asset_id == base.canonical_asset_id == "usdc"
    assert eth.deployment_id != base.deployment_id


def test_observation_requires_tenant_and_execution_identity():
    with pytest.raises(ValueError):
        StablecoinObservation(observation_id="o", tenant_id="", source="dune", source_record_id="r", source_execution_id="exec", observed_at="2026-07-05T00:00:00Z", chain_id="1", network="ethereum-mainnet", transaction_hash="0xabc", finality_status=FinalityState.FINALIZED, event_type=StablecoinEventType.PAYMENT, deployment_id="d", canonical_asset_id="usdc", amount_atomic=1)
    with pytest.raises(ValueError):
        StablecoinObservation(observation_id="o", tenant_id="tenant", source="dune", source_record_id="r", source_execution_id="", observed_at="2026-07-05T00:00:00Z", chain_id="1", network="ethereum-mainnet", transaction_hash="0xabc", finality_status=FinalityState.FINALIZED, event_type=StablecoinEventType.PAYMENT, deployment_id="d", canonical_asset_id="usdc", amount_atomic=1)


def test_gold_identity_separates_tenant_date_asset_deployment_source():
    base = dict(tenant_id="t1", metric_name="finalized_payment_volume", metric_version="v1", entity_id="merchant1", entity_type="merchant", canonical_asset_id="usdc", deployment_id="usdc:base", chain_id="8453", window_start="2026-07-05T00:00:00Z", window_end="2026-07-06T00:00:00Z", dimensions={"direction":"inflow"}, source="silver")
    assert StablecoinGoldIdentity.key(**base) != StablecoinGoldIdentity.key(**{**base, "tenant_id":"t2"})
    assert StablecoinGoldIdentity.key(**base) != StablecoinGoldIdentity.key(**{**base, "deployment_id":"usdc:ethereum"})
    assert StablecoinGoldIdentity.key(**base) != StablecoinGoldIdentity.key(**{**base, "window_start":"2026-07-06T00:00:00Z"})
    with pytest.raises(ValueError):
        StablecoinGoldIdentity.key(**{**base, "tenant_id":""})

@pytest.mark.asyncio
async def test_bronze_repeated_executions_are_distinct_and_quarantine_blocks_silver():
    bronze = BronzeRepository("stablecoin_test")
    a, new_a = await bronze.ingest("dune", "tenant:t:stablecoin", "row-1", {"execution_id":"exec-a"}, tenant_id="t", schema_version="stablecoin.intelligence.v1", source_manifest_id="m", license_status="enterprise_contract", terms_status="approved")
    b, new_b = await bronze.ingest("dune", "tenant:t:stablecoin", "row-1", {"execution_id":"exec-b"}, tenant_id="t", schema_version="stablecoin.intelligence.v1:exec-b", source_manifest_id="m", license_status="enterprise_contract", terms_status="approved")
    assert new_a and new_b
    assert a["idempotency_key"] != b["idempotency_key"]

    quarantined, _ = await bronze.ingest("dune", "tenant:t:stablecoin", "row-q", {}, tenant_id="t")
    silver = SilverRepository("stablecoin_test")
    with pytest.raises(ValueError):
        await silver.upsert_record("e", "wallet", "dune", "tenant:t:stablecoin", {}, bronze_id=quarantined["id"], tenant_id="t", bronze_record=quarantined)
