"""Universal asset registry — deterministic seed content (pure, DB-free).

Covers seeds.py builders: reference rows, universal id scheme, alias bridging
of the stablecoin domain's legacy ids, and the deterministic registry_version
(never wall-clock: identical seed state hashes to one digest).
"""

from __future__ import annotations

from services.assets import seeds
from services.x402.verification import _ASSET_CONTRACT


# ── reference rows ───────────────────────────────────────────────────────────

def test_fiat_reference_seed_matches_iso_codes():
    currencies = seeds.fiat_currency_rows()
    assert len(currencies) == len(seeds.FIAT_CURRENCIES) == 16
    codes = [c["iso_code"] for c in currencies]
    assert len(codes) == len(set(codes))  # ISO codes are unique
    assert "USD" in codes and "EUR" in codes
    for row in currencies:
        # numeric_code keeps leading zeros (string of exactly three digits).
        assert len(row["numeric_code"]) == 3 and row["numeric_code"].isdigit()
        assert 0 <= row["minor_units"] <= 4


def test_fiat_assets_use_namespaced_ids_and_minor_units_as_display_decimals():
    assets = seeds.fiat_asset_rows()
    assert len(assets) == 16
    for asset in assets:
        assert asset["kind"] == "fiat"
        assert asset["id"].startswith("fiat:")
        assert asset["id"] == seeds.fiat_asset_id(asset["symbol"])
        assert asset["display_decimals"] >= 0


def test_chain_seed_covers_x402_network_map():
    chain_ids = {row["chain_id"] for row in seeds.chain_rows()}
    assert chain_ids == set(seeds._CHAIN_TO_NETWORK)
    for row in seeds.chain_rows():
        assert row["status"] == "active"
        assert row["native_currency"].startswith("crypto:")


def test_native_deployments_use_native_sentinel_and_are_canonical():
    deps = seeds.native_deployment_rows()
    assert len(deps) == len(seeds.chain_rows())
    for dep in deps:
        assert dep["contract_or_mint"] == "native"
        assert dep["token_standard"] == "native"
        assert dep["canonical_vs_bridged"] == "canonical"
        assert dep["deployment_id"].startswith("deploy:")


def test_stablecoin_seed_matches_x402_verified_surface():
    symbols = {s for s, _c in _ASSET_CONTRACT}
    asset_rows = seeds.stablecoin_asset_rows()
    assert {a["symbol"] for a in asset_rows} == symbols
    assert all(a["kind"] == "stablecoin" for a in asset_rows)

    deploy_rows = seeds.stablecoin_deployment_rows()
    assert len(deploy_rows) == len(_ASSET_CONTRACT)
    by_key = {(d["asset_id"], d["chain_id"]): d for d in deploy_rows}
    for (symbol, chain_id), contract in _ASSET_CONTRACT.items():
        dep = by_key[(f"stablecoin:{symbol}", chain_id)]
        assert dep["contract_or_mint"] == contract.lower() if contract.startswith("0x") else contract
        assert dep["decimals"] == 6
        assert dep["canonical_vs_bridged"] == "canonical"


def test_evm_contract_normalization_is_lowercase_and_svm_is_verbatim():
    assert seeds.normalize_contract_or_mint("0xABC123") == "0xabc123"
    # Solana base58 is case-sensitive — never lowercased.
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert seeds.normalize_contract_or_mint(mint) == mint


# ── alias bridging ───────────────────────────────────────────────────────────

def test_legacy_stablecoin_ids_are_bridged_not_rewritten():
    aliases = seeds.stablecoin_alias_rows()
    asset_aliases = [a for a in aliases if a["target_deployment_id"] is None]
    deployment_aliases = [a for a in aliases if a["target_deployment_id"] is not None]

    # One asset alias per symbol: symbol.lower() -> stablecoin:SYMBOL.
    symbols = sorted({s for s, _c in _ASSET_CONTRACT})
    assert {a["alias"] for a in asset_aliases} == {s.lower() for s in symbols}
    for a in asset_aliases:
        assert a["target_asset_id"] == f"stablecoin:{a['alias'].upper()}"

    # One deployment alias per (symbol, chain): symbol.lower():chain_id.
    assert len(deployment_aliases) == len(_ASSET_CONTRACT)
    for a in deployment_aliases:
        # alias = "<symbol.lower()>:<chain_id>" — the symbol is the first colon
        # segment (the chain id itself contains colons, e.g. eip155:8453).
        symbol = a["alias"].split(":", 1)[0]
        assert a["target_asset_id"] == f"stablecoin:{symbol.upper()}"
        assert a["target_deployment_id"].startswith("deploy:")

    for a in aliases:
        assert a["verification"] == "verified"


def test_native_symbol_aliases_exist():
    aliases = seeds.native_alias_rows()
    assert {a["alias"] for a in aliases} == {"ETH", "SOL"}
    for a in aliases:
        assert a["verification"] == "verified"


# ── deterministic registry_version ───────────────────────────────────────────

def test_registry_version_is_deterministic_and_never_wallclock():
    assert seeds.registry_version() == seeds.registry_version()
    assert seeds.registry_version() == seeds.current_registry_version()
    assert len(seeds.registry_version()) == 64  # sha256 hex
    assert seeds.registry_version().isalnum()


def test_registry_version_keys_are_sorted_unique_and_match_seed_rows():
    keys = seeds.seed_content_keys()
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))

    assets = seeds.fiat_asset_rows() + seeds.native_asset_rows() + seeds.stablecoin_asset_rows()
    chains = seeds.chain_rows()
    deps = seeds.native_deployment_rows() + seeds.stablecoin_deployment_rows()
    aliases = seeds.alias_rows()
    # Every key the digest covers maps to exactly one seeded row.
    assert len(keys) == len(assets) + len(chains) + len(deps) + len(aliases)
    for asset in assets:
        assert asset["id"] in keys


def test_seed_count_snapshot_is_internally_consistent():
    snap = seeds.seed_count_snapshot()
    assert snap["asset_count"] == (
        len(seeds.fiat_asset_rows()) + len(seeds.native_asset_rows()) + len(seeds.stablecoin_asset_rows())
    )
    assert snap["chain_count"] == len(seeds.chain_rows())
    assert snap["deployment_count"] == len(seeds.native_deployment_rows()) + len(seeds.stablecoin_deployment_rows())
    assert snap["fiat_count"] == len(seeds.fiat_currency_rows())
    assert snap["alias_count"] == len(seeds.alias_rows())


# ── id syntax helpers ────────────────────────────────────────────────────────

def test_is_namespaced_asset_id_syntax():
    assert seeds.is_namespaced_asset_id("fiat:USD")
    assert seeds.is_namespaced_asset_id("crypto:ETH")
    assert seeds.is_namespaced_asset_id("stablecoin:USDC")
    assert seeds.is_namespaced_asset_id("token:eip155:8453:0xabc")
    assert not seeds.is_namespaced_asset_id("usdc")  # legacy id, not namespaced
    assert not seeds.is_namespaced_asset_id("usdc:eip155:8453")
    assert not seeds.is_namespaced_asset_id("money:USD")
    assert not seeds.is_namespaced_asset_id("")
