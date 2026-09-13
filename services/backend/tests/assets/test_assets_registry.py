"""Universal asset registry facade + seeder — DB-free in-memory run.

Typed repos fall back to shared in-memory stores when no DB pool is configured
(local env), so the full seed -> read -> canonicalize path runs without a
database. The observational tenant rule is exercised on record_unresolved.
"""

from __future__ import annotations

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.assets import seeds
from services.assets.registry import UniversalAssetRegistry

# Stablecoin domain's BaseRepository events, if any, are not needed here.

@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


@pytest.mark.asyncio
async def test_seed_all_is_idempotent_and_ledger_matches_snapshot():
    registry = UniversalAssetRegistry()
    summary = await registry.seed_all()

    expected = seeds.seed_count_snapshot()
    for key in ("asset_count", "chain_count", "deployment_count", "fiat_count", "alias_count"):
        assert summary[key] == expected[key]

    version = summary["registry_version"]
    assert version == registry.current_registry_version() == seeds.registry_version()

    meta = await registry.get_meta()
    assert meta is not None
    assert meta["registry_version"] == version
    assert meta["asset_count"] == expected["asset_count"]
    assert meta["deployment_count"] == expected["deployment_count"]

    # Second run inserts nothing and reproduces the identical digest.
    again = await registry.seed_all()
    assert again["registry_version"] == version
    for phase in again["inserted"].values():
        # Phase dicts also carry *_total counters; idempotency is about the
        # *_inserted counters (all zero on a replay).
        for key, value in phase.items():
            if key.endswith("_inserted"):
                assert value == 0, (key, value)


@pytest.mark.asyncio
async def test_seed_builds_seedable_reference_surface():
    registry = UniversalAssetRegistry()
    await registry.seed_all()

    assert len(await registry.resolve_asset("USD")) == 1
    usd = (await registry.resolve_asset("USD"))[0]
    assert usd["id"] == "fiat:USD" and usd["kind"] == "fiat" and usd["display_decimals"] == 2

    # Symbol matching is case-insensitive.
    assert (await registry.resolve_asset("usdc"))[0]["id"] == "stablecoin:USDC"
    assert (await registry.resolve_asset("USDC"))[0]["id"] == "stablecoin:USDC"

    # Chains resolve and their native currency asset exists.
    base = await registry.resolve_chain("eip155:8453")
    assert base is not None and base["native_currency"] == "crypto:ETH"
    assert await registry.get_asset("crypto:ETH") is not None
    assert await registry.get_asset("crypto:SOL") is not None

    # Legacy ids resolve via alias rows to universal ids (never rewritten).
    legacy_asset = await registry.resolve_alias("usdc")
    assert legacy_asset["target_asset_id"] == "stablecoin:USDC"
    legacy_dep = await registry.resolve_alias("usdc:eip155:8453")
    assert legacy_dep["target_asset_id"] == "stablecoin:USDC"
    assert legacy_dep["target_deployment_id"].startswith("deploy:stablecoin:USDC@eip155:8453:")


@pytest.mark.asyncio
async def test_resolve_deployment_evm_case_insensitive_svm_case_sensitive():
    registry = UniversalAssetRegistry()
    await registry.seed_all()

    usdc_contract = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    dep = await registry.resolve_deployment("eip155:8453", usdc_contract)
    assert dep is not None and dep["asset_id"] == "stablecoin:USDC"
    # Checksummed address resolves to the same row as the stored lowercase one.
    assert dep["contract_or_mint"] == usdc_contract.lower()

    sol_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert await registry.resolve_deployment("solana:mainnet", sol_mint) is not None
    # Solana mints are case-sensitive — the case-twisted mint must NOT resolve.
    assert await registry.resolve_deployment("solana:mainnet", sol_mint.lower()) is None


@pytest.mark.asyncio
async def test_record_unresolved_is_tenant_scoped_and_aggregates():
    registry = UniversalAssetRegistry()
    await registry.seed_all()

    first = await registry.record_unresolved(
        "DOGE", "unknown_symbol", tenant_id="tenant-alpha",
        evidence={"native": {"amount": "1", "currency": "DOGE"}},
    )
    assert first["inserted"] is True and first["occurrence_count"] == 1

    second = await registry.record_unresolved(
        "DOGE", "unknown_symbol", tenant_id="tenant-alpha",
    )
    assert second["inserted"] is False and second["occurrence_count"] == 2

    # Same raw reference under another tenant is its own row (tenant-scoped).
    other = await registry.record_unresolved("DOGE", "unknown_symbol", tenant_id="tenant-beta")
    assert other["inserted"] is True

    rows_alpha = await registry.unresolved.find_many({"tenant_id": "tenant-alpha"})
    assert len(rows_alpha) == 1
    assert rows_alpha[0]["execution_by_aether"] is False


@pytest.mark.asyncio
async def test_register_asset_maps_id_contract_to_asset_id_column():
    registry = UniversalAssetRegistry()
    # register a brand-new token asset (symbol unique to avoid alias ambiguity).
    result = await registry.register_asset({
        "id": "token:eip155:8453:0xdeadbeef",
        "kind": "token",
        "symbol": "AETHTOKEN",
        "display_decimals": 18,
        "status": "active",
    })
    assert result["inserted"] is True
    # idempotent on canonical identity
    again = await registry.register_asset({
        "id": "token:eip155:8453:0xdeadbeef",
        "kind": "token",
        "symbol": "AETHTOKEN",
        "display_decimals": 18,
        "status": "active",
    })
    assert again["inserted"] is False

    row = await registry.assets.find_one({"asset_id": "token:eip155:8453:0xdeadbeef"})
    assert row is not None and row["asset_id"] == "token:eip155:8453:0xdeadbeef"
    # Contract shape exposes the canonical ``id`` (not the DB column).
    asset = await registry.get_asset("token:eip155:8453:0xdeadbeef")
    assert asset is not None and asset["id"] == "token:eip155:8453:0xdeadbeef"
