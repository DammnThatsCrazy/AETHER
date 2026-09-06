"""Universal asset resolver — §8 priority table (DB-free, in-memory typed repos).

Exercises every priority rung over a freshly seeded registry:
chain+contract (authoritative), namespaced id, legacy alias, verified symbol,
symbol+context, collision, and the recorded-unresolved tail. Unknown references
are always recorded on the caller's tenant and never silently guessed.
"""

from __future__ import annotations

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.assets import seeds
from services.assets.registry import UniversalAssetRegistry

BASE_USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
SOL_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


async def _seeded() -> UniversalAssetRegistry:
    registry = UniversalAssetRegistry()
    await registry.seed_all()
    return registry


async def _canonicalize(native: dict, tenant_id: str = "tenant-resolver"):
    registry = await _seeded()
    return await registry.canonicalize(native, tenant_id=tenant_id)


# ── §8.1 chain + contract (authoritative) ────────────────────────────────────

@pytest.mark.asyncio
async def test_resolved_chain_contract_evm_is_case_insensitive():
    report = await _canonicalize({
        "amount": "5.00",
        "currency": "USDC",
        "chain": "eip155:8453",
        "contract_or_mint": BASE_USDC_CONTRACT,  # checksummed
    })
    assert report["resolution_status"] == "resolved_chain_contract"
    assert report["canonical_asset_id"] == "stablecoin:USDC"
    expected_dep = seeds.asset_deployment_id(
        "stablecoin:USDC", "eip155:8453", BASE_USDC_CONTRACT.lower(),
    )
    assert report["deployment_id"] == expected_dep
    assert report["verified"] is True
    assert report["resolved_asset"]["symbol"] == "USDC"

    lower_report = await _canonicalize({
        "amount": "5.00", "currency": "USDC",
        "chain": "eip155:8453", "contract_or_mint": BASE_USDC_CONTRACT.lower(),
    })
    assert lower_report["deployment_id"] == expected_dep


@pytest.mark.asyncio
async def test_resolved_chain_contract_svm_is_case_sensitive():
    report = await _canonicalize({
        "amount": "7", "currency": "USDC",
        "chain": "solana:mainnet", "contract_or_mint": SOL_USDC_MINT,
    })
    assert report["resolution_status"] == "resolved_chain_contract"
    assert report["canonical_asset_id"] == "stablecoin:USDC"
    assert report["deployment_id"].startswith("deploy:stablecoin:USDC@solana:mainnet:")


@pytest.mark.asyncio
async def test_unknown_contract_on_known_chain_is_recorded_not_symbol_resolved():
    # A concrete-but-unknown deployment assertion must NOT be re-interpreted
    # through the payload's symbol (the contract is the strongest signal).
    report = await _canonicalize({
        "amount": "1", "currency": "USDC",
        "chain": "eip155:8453",
        "contract_or_mint": "0x1111111111111111111111111111111111111111",
    })
    assert report["resolution_status"] == "unresolved_recorded"
    assert report["verified"] is False
    assert report["canonical_asset_id"] is None
    assert report["unresolved"]["reason"] == "unknown_contract"
    assert report["unresolved"]["recorded"]["inserted"] is True


@pytest.mark.asyncio
async def test_unknown_chain_is_recorded_unknown_chain():
    report = await _canonicalize({
        "amount": "1", "currency": "USDC",
        "chain": "eip155:999999",
        "contract_or_mint": "0x1111111111111111111111111111111111111111",
    })
    assert report["resolution_status"] == "unresolved_recorded"
    assert report["unresolved"]["reason"] == "unknown_chain"


# ── §8.2 namespaced asset id ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolved_namespaced_id():
    report = await _canonicalize({
        "amount": "12.5", "currency": "USDC",
        "asset_id": "stablecoin:USDC",
    })
    assert report["resolution_status"] == "resolved_namespaced_id"
    assert report["canonical_asset_id"] == "stablecoin:USDC"
    assert report["verified"] is True


@pytest.mark.asyncio
async def test_unregistered_namespaced_id_is_recorded_no_registry_entry():
    report = await _canonicalize({
        "amount": "1", "currency": "NOPE",
        "asset_id": "stablecoin:NOPE",
    })
    assert report["resolution_status"] == "unresolved_recorded"
    assert report["unresolved"]["reason"] == "no_registry_entry"
    assert report["canonical_asset_id"] is None


# ── §8.3 legacy canonical id -> alias bridge (never rewritten) ───────────────

@pytest.mark.asyncio
async def test_resolved_legacy_alias_bridges_stablecoin_domain_ids():
    asset_report = await _canonicalize({
        "amount": "3", "currency": "usdc", "asset_id": "usdc",
    })
    assert asset_report["resolution_status"] == "resolved_legacy_alias"
    assert asset_report["canonical_asset_id"] == "stablecoin:USDC"

    dep_report = await _canonicalize({
        "amount": "3", "currency": "usdc", "asset_id": "usdc:eip155:8453",
    })
    assert dep_report["resolution_status"] == "resolved_legacy_alias"
    assert dep_report["canonical_asset_id"] == "stablecoin:USDC"
    assert dep_report["deployment_id"].startswith("deploy:stablecoin:USDC@eip155:8453:")


# ── §8.4/8.5 verified symbol / symbol + context ──────────────────────────────

@pytest.mark.asyncio
async def test_resolved_symbol_verified_for_unique_symbols():
    usd = await _canonicalize({"amount": "10", "currency": "USD"})
    assert usd["resolution_status"] == "resolved_symbol_verified"
    assert usd["canonical_asset_id"] == "fiat:USD"

    eth = await _canonicalize({"amount": "0.5", "currency": "ETH"})
    assert eth["resolution_status"] == "resolved_symbol_verified"
    assert eth["canonical_asset_id"] == "crypto:ETH"

    usdc = await _canonicalize({"amount": "9", "currency": "USDC"})
    assert usdc["resolution_status"] == "resolved_symbol_verified"
    assert usdc["canonical_asset_id"] == "stablecoin:USDC"


@pytest.mark.asyncio
async def test_symbol_with_chain_enriches_single_active_deployment():
    report = await _canonicalize({
        "amount": "9", "currency": "USDC", "chain": "solana:mainnet",
    })
    assert report["resolution_status"] == "resolved_symbol_verified"
    assert report["canonical_asset_id"] == "stablecoin:USDC"
    # USDC has exactly one deployment on solana:mainnet -> deterministic anchor.
    assert report["deployment_id"].startswith("deploy:stablecoin:USDC@solana:mainnet:")
    assert report["resolved_deployment"]["contract_or_mint"] == SOL_USDC_MINT


# ── §8.6 collision + recorded unresolved tail ────────────────────────────────

@pytest.mark.asyncio
async def test_ambiguous_symbol_is_collision_and_is_recorded():
    registry = await _seeded()
    # Two distinct assets sharing one symbol -> bare symbol is ambiguous.
    await registry.register_asset({
        "id": "token:eip155:1:0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "kind": "token", "symbol": "DUPE", "status": "active",
    })
    await registry.register_asset({
        "id": "token:eip155:1:0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "kind": "token", "symbol": "DUPE", "status": "active",
    })

    report = await registry.canonicalize(
        {"amount": "1", "currency": "DUPE"}, tenant_id="tenant-collision",
    )
    assert report["resolution_status"] == "collision_unresolvable"
    assert report["verified"] is False
    assert report["unresolved"]["reason"] == "ambiguous_symbol"

    rows = await registry.unresolved.find_many({"tenant_id": "tenant-collision"})
    assert len(rows) == 1
    assert rows[0]["reason"] == "ambiguous_symbol"
    assert rows[0]["execution_by_aether"] is False


@pytest.mark.asyncio
async def test_unknown_symbol_is_recorded_on_callers_tenant():
    report = await _canonicalize(
        {"amount": "1", "currency": "DOGE"}, tenant_id="tenant-doge",
    )
    assert report["resolution_status"] == "unresolved_recorded"
    assert report["unresolved"]["reason"] == "unknown_symbol"
    registry = UniversalAssetRegistry()
    rows = await registry.unresolved.find_many({"tenant_id": "tenant-doge"})
    assert len(rows) == 1
    assert rows[0]["raw_reference"] == "DOGE"
    # Re-canonicalizing the same unknown reference aggregates in place.
    again = await registry.canonicalize(
        {"amount": "2", "currency": "DOGE"}, tenant_id="tenant-doge",
    )
    assert again["unresolved"]["recorded"]["occurrence_count"] == 2


@pytest.mark.asyncio
async def test_canonicalize_preserves_native_and_reports_stable_version():
    native = {"amount": "5.00", "currency": "USDC", "chain": "eip155:8453",
              "contract_or_mint": BASE_USDC_CONTRACT}
    report = await _canonicalize(native)
    assert report["native"] == native  # never rewritten
    assert report["registry_version"] == UniversalAssetRegistry.current_registry_version()


@pytest.mark.asyncio
async def test_resolver_never_guesses_decimals_for_unknown():
    report = await _canonicalize({"amount": "1", "currency": "ZZZ"})
    assert report["canonical_decimals"] is None
    assert report["unresolved"]["reason"] == "unknown_symbol"
