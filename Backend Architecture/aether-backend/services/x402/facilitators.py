"""
Aether Service — Facilitator Registry + Asset Registry
Tracks approved payment facilitators, their health, and approved stablecoin
assets. Day-1 seeds: local facilitator for Aether-native, USDC/Base, USDC/Solana.
"""

from __future__ import annotations

import os
from typing import Optional

from shared.logger.logger import get_logger

from .commerce_models import Facilitator, FacilitatorMode, StablecoinAsset
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.facilitators")


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


# ─── Day-1 Seeds ──────────────────────────────────────────────────────

USDC_BASE_ASSET = StablecoinAsset(
    asset_id="ast_usdc_base",
    symbol="USDC",
    chain="eip155:8453",
    network="base-mainnet",
    issuer="Circle",
    contract_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    decimals=6,
    settlement_scheme="hybrid",
    facilitator_ids=["fac_local_aether", "fac_circle_v2"],
    active=True,
    risk_score=None,
)

USDC_SOLANA_ASSET = StablecoinAsset(
    asset_id="ast_usdc_solana",
    symbol="USDC",
    chain="solana:mainnet",
    network="solana-mainnet",
    issuer="Circle",
    contract_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    decimals=6,
    settlement_scheme="hybrid",
    facilitator_ids=["fac_local_aether", "fac_circle_v2"],
    active=True,
    risk_score=None,
)

LOCAL_AETHER_FACILITATOR = Facilitator(
    facilitator_id="fac_local_aether",
    name="Aether Local Facilitator",
    endpoint_url="internal://aether/verify",
    mode=FacilitatorMode.LOCAL,
    supported_assets=["USDC"],
    supported_chains=["eip155:8453", "solana:mainnet"],
    health_status="unknown",
    success_rate=None,
    active=True,
)

CIRCLE_V2_FACILITATOR = Facilitator(
    facilitator_id="fac_circle_v2",
    name="Circle x402 v2 Facilitator",
    endpoint_url="https://facilitator.circle.com/v2",
    mode=FacilitatorMode.FACILITATOR,
    supported_assets=["USDC"],
    supported_chains=["eip155:8453", "solana:mainnet"],
    health_status="unknown",
    success_rate=None,
    active=True,
)


class FacilitatorRegistry:
    """Manages approved facilitators and routes payments."""

    def __init__(self) -> None:
        self._store = get_commerce_store()

    async def register(self, tenant_id: str, facilitator: Facilitator) -> Facilitator:
        if tenant_id and tenant_id not in facilitator.approved_by_tenants:
            facilitator.approved_by_tenants.append(tenant_id)
        result = await self._store.put_facilitator(tenant_id, facilitator)
        logger.info(f"Facilitator registered: {facilitator.facilitator_id} for tenant={tenant_id}")
        return result

    async def get(self, tenant_id: str, facilitator_id: str) -> Optional[Facilitator]:
        return await self._store.get_facilitator(tenant_id, facilitator_id)

    async def list(self, tenant_id: str) -> list[Facilitator]:
        return await self._store.list_facilitators(tenant_id, active=True)

    async def select_for(
        self,
        tenant_id: str,
        asset_symbol: str,
        chain: str,
        environment: Optional[str] = None,
    ) -> Optional[Facilitator]:
        """Select best facilitator for an asset/chain(/environment). Prefers healthiest.

        Health is a derived signal — verification outcomes feed update_health;
        there is no standalone prober — so a freshly seeded facilitator is
        "unknown". Selection therefore excludes only facilitators known to be
        down and ranks healthy ahead of unprobed ahead of degraded; requiring
        "healthy" here made a new tenant's payments structurally unroutable.

        Outside the local environment, LOCAL-mode facilitators (the internal
        Aether verifier seed) are never auto-selected: they have no chain
        access, and selecting one for a fresh tenant used to confer
        verification on every payment. Non-local selection is restricted to
        external facilitators; with none configured, verification falls to the
        on-chain RPC verifier.

        When ``environment`` is supplied it MUST appear in the facilitator's
        ``supported_environments``: a live authorization may never route through
        a sandbox-only facilitator (the default for every facilitator that does
        not override the field), nor a sandbox authorization through a live-only
        one. The caller resolves the environment server-side before routing.
        """
        health_rank = {"healthy": 0, "unknown": 1, "degraded": 2}
        facilitators = await self.list(tenant_id)
        local_env = _is_local_env()
        candidates = [
            f for f in facilitators
            if asset_symbol in f.supported_assets
            and chain in f.supported_chains
            and f.health_status != "down"
            and (local_env or f.mode != FacilitatorMode.LOCAL)
            and (environment is None or environment in (f.supported_environments or []))
        ]
        if not candidates:
            return None
        # Within a health rank, prefer highest success rate, lowest latency
        candidates.sort(
            key=lambda f: (
                health_rank.get(f.health_status, 2),
                -(f.success_rate if f.success_rate is not None else -1.0),
                f.avg_latency_ms if f.avg_latency_ms is not None else float("inf"),
            )
        )
        return candidates[0]

    async def update_health(
        self,
        tenant_id: str,
        facilitator_id: str,
        status: str,
        latency_ms: Optional[float] = None,
        success: Optional[bool] = None,
    ) -> None:
        facilitator = await self.get(tenant_id, facilitator_id)
        if not facilitator:
            return
        facilitator.health_status = status
        if latency_ms is not None:
            # Simple EMA
            prior_latency = facilitator.avg_latency_ms
            facilitator.avg_latency_ms = (
                prior_latency * 0.8 + latency_ms * 0.2
                if prior_latency is not None
                else latency_ms
            )
        if success is not None:
            prior_rate = facilitator.success_rate
            facilitator.success_rate = (
                prior_rate * 0.95 + (1.0 if success else 0.0) * 0.05
                if prior_rate is not None
                else (1.0 if success else 0.0)
            )
        await self._store.put_facilitator(tenant_id, facilitator)


class AssetRegistry:
    """Approved stablecoin asset registry."""

    def __init__(self) -> None:
        self._store = get_commerce_store()

    async def register(self, tenant_id: str, asset: StablecoinAsset) -> StablecoinAsset:
        return await self._store.put_asset(tenant_id, asset)

    async def list(self, tenant_id: str) -> list[StablecoinAsset]:
        return await self._store.list_assets(tenant_id, active=True)

    async def find(
        self, tenant_id: str, symbol: str, chain: str
    ) -> Optional[StablecoinAsset]:
        for a in await self.list(tenant_id):
            if a.symbol == symbol and a.chain == chain:
                return a
        return None


async def seed_facilitators_and_assets(tenant_id: str) -> None:
    """Day-1 seed: USDC on Base + Solana with local + Circle facilitators."""
    facilitator_registry = FacilitatorRegistry()
    asset_registry = AssetRegistry()

    # Clone seeds per-tenant
    await facilitator_registry.register(tenant_id, LOCAL_AETHER_FACILITATOR.model_copy(deep=True))
    await facilitator_registry.register(tenant_id, CIRCLE_V2_FACILITATOR.model_copy(deep=True))
    await asset_registry.register(tenant_id, USDC_BASE_ASSET.model_copy(deep=True))
    await asset_registry.register(tenant_id, USDC_SOLANA_ASSET.model_copy(deep=True))

    logger.info(f"Seeded facilitators + assets for tenant={tenant_id}")


_facilitator_registry: Optional[FacilitatorRegistry] = None
_asset_registry: Optional[AssetRegistry] = None


def get_facilitator_registry() -> FacilitatorRegistry:
    global _facilitator_registry
    if _facilitator_registry is None:
        _facilitator_registry = FacilitatorRegistry()
    return _facilitator_registry


def get_asset_registry() -> AssetRegistry:
    global _asset_registry
    if _asset_registry is None:
        _asset_registry = AssetRegistry()
    return _asset_registry
