"""Stablecoin → universal canonical-identity seam — DB-free in-memory run.

The seam maps the stablecoin canonical module's legacy ids / symbols /
deployments onto universal registry identity through alias resolution, NEVER
rewriting a legacy id and NEVER guessing a canonical id the universal registry
cannot verify. Typed repos fall back to the shared in-memory stores when no DB
pool is configured (AETHER_ENV=local), so the full seed -> resolve path runs
without a database.
"""

from __future__ import annotations

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.assets.registry import UniversalAssetRegistry
from services.stablecoin.canonical_identity import (
    StablecoinCanonicalIdentityResolver,
    resolve_canonical_identity,
    surface_on_read_row,
)
from services.stablecoin.models import StablecoinDeployment
from services.stablecoin.registry import StablecoinRegistry

_USDC_BASE_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
_USDC_BASE_LOWER = _USDC_BASE_CONTRACT.lower()
_USDC_BASE_UNIVERSAL_DEPLOYMENT = (
    f"deploy:stablecoin:USDC@eip155:8453:{_USDC_BASE_LOWER}"
)


@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


async def _seeded_resolver() -> StablecoinCanonicalIdentityResolver:
    """Seed the universal registry (in-memory) and build a seam resolver over it."""
    registry = UniversalAssetRegistry()
    await registry.seed_all()
    return StablecoinCanonicalIdentityResolver(universal_registry=registry)


# ── legacy asset id / symbol → canonical asset ───────────────────────────────

@pytest.mark.asyncio
async def test_legacy_usdc_asset_id_resolves_to_canonical_asset():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("usdc")
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id is None  # asset-only alias
    assert identity.reference == "usdc"  # original spelling preserved
    assert identity.resolution_method in {"asset_alias", "symbol_verified"}


@pytest.mark.asyncio
async def test_uppercase_symbol_resolves_case_insensitively():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("USDC")
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.reference == "USDC"


@pytest.mark.asyncio
async def test_already_universal_asset_id_is_verified_and_echoed():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("stablecoin:USDC")
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id is None
    assert identity.resolution_method == "namespaced_verified"


# ── legacy deployment id → canonical asset + deployment ──────────────────────

@pytest.mark.asyncio
async def test_legacy_deployment_id_resolves_through_alias_row():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("usdc:eip155:8453")
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id == _USDC_BASE_UNIVERSAL_DEPLOYMENT
    assert identity.reference == "usdc:eip155:8453"
    assert identity.resolution_method == "deployment_alias"


@pytest.mark.asyncio
async def test_already_universal_deployment_id_is_verified_and_echoed():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve(_USDC_BASE_UNIVERSAL_DEPLOYMENT)
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id == _USDC_BASE_UNIVERSAL_DEPLOYMENT
    assert identity.resolution_method == "namespaced_verified"


@pytest.mark.asyncio
async def test_unaliased_legacy_deployment_resolves_via_domain_deployment():
    """A module deployment id with no universal alias row (the display form
    used by the fault/stage suites) resolves through the module's own
    deployment registry: chain + contract are verified upstream."""
    await UniversalAssetRegistry().seed_all()
    await StablecoinRegistry().register_deployment(StablecoinDeployment(
        deployment_id=f"usdc:base:mainnet:{_USDC_BASE_LOWER}",
        canonical_asset_id="usdc",
        chain_id="eip155:8453",
        network="base-mainnet",
        token_standard="erc20",
        contract_or_mint=_USDC_BASE_LOWER,
        decimals=6,
        deployment_type="canonical",
        issuer_verified=True,
        testnet=False,
    ))
    identity = await resolve_canonical_identity(
        f"usdc:base:mainnet:{_USDC_BASE_LOWER}",
    )
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id == _USDC_BASE_UNIVERSAL_DEPLOYMENT
    assert identity.resolution_method == "domain_deployment_verified"


# ── unknown references stay unresolved — never guessed ───────────────────────

@pytest.mark.asyncio
async def test_unknown_symbol_stays_unresolved():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("doge")
    assert identity.resolved is False
    assert identity.canonical_asset_id is None
    assert identity.canonical_deployment_id is None
    assert identity.resolution_method == "unresolved"
    assert identity.reference == "doge"  # legacy id preserved, never invented


@pytest.mark.asyncio
async def test_unknown_deployment_id_stays_unresolved():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("usdc:oops:123")
    assert identity.resolved is False
    assert identity.canonical_asset_id is None
    assert identity.canonical_deployment_id is None


@pytest.mark.asyncio
async def test_unknown_namespaced_id_stays_unresolved():
    # stablecoin:USDT is NOT an x402-verified asset today — never guessed.
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("stablecoin:USDT")
    assert identity.resolved is False
    assert identity.canonical_asset_id is None


@pytest.mark.asyncio
async def test_empty_reference_stays_unresolved():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve("")
    assert identity.resolved is False
    assert identity.canonical_asset_id is None


# ── read-row surface (additive) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_row_surface_attaches_canonical_ids_additively():
    resolver = await _seeded_resolver()
    row = {"tenant_id": "t1", "deployment_id": "usdc:eip155:8453"}
    surfaced = surface_on_read_row(row, await resolver.resolve(row["deployment_id"]))
    assert surfaced["deployment_id"] == "usdc:eip155:8453"  # legacy preserved
    assert surfaced["canonical_asset_id"] == "stablecoin:USDC"
    assert surfaced["canonical_deployment_id"] == _USDC_BASE_UNIVERSAL_DEPLOYMENT


@pytest.mark.asyncio
async def test_read_row_surface_never_overwrites_legacy_spelling():
    # A pre-convergence row already carries the legacy spelling under
    # canonical_asset_id — surfacing must not rewrite it.
    resolver = await _seeded_resolver()
    row = {
        "tenant_id": "t1",
        "deployment_id": "usdc:eip155:8453",
        "canonical_asset_id": "usdc",
    }
    surfaced = surface_on_read_row(row, await resolver.resolve(row["deployment_id"]))
    assert surfaced["canonical_asset_id"] == "usdc"  # never rewritten
    assert surfaced["canonical_deployment_id"] == _USDC_BASE_UNIVERSAL_DEPLOYMENT


@pytest.mark.asyncio
async def test_resolve_read_row_resolves_by_legacy_deployment_id():
    resolver = await _seeded_resolver()
    identity = await resolver.resolve_read_row(
        {"tenant_id": "t1", "deployment_id": "usdc:eip155:8453"}
    )
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id == _USDC_BASE_UNIVERSAL_DEPLOYMENT


# ── registry version provenance ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolution_cites_deterministic_registry_version():
    resolver = await _seeded_resolver()
    expected = UniversalAssetRegistry.current_registry_version()
    identity = await resolver.resolve("usdc:eip155:8453")
    assert identity.registry_version == expected


@pytest.mark.asyncio
async def test_legacy_solana_deployment_resolves_via_alias():
    """USDC on solana:mainnet is also x402-verified and bridged via alias."""
    await UniversalAssetRegistry().seed_all()
    identity = await resolve_canonical_identity("usdc:solana:mainnet")
    assert identity.resolved is True
    assert identity.canonical_asset_id == "stablecoin:USDC"
    assert identity.canonical_deployment_id.startswith(
        "deploy:stablecoin:USDC@solana:mainnet:"
    )
