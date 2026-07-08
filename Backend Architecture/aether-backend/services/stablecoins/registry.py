"""Canonical stablecoin deployment registry utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import StablecoinDeployment


@dataclass
class StablecoinDeploymentRegistry:
    deployments: dict[str, StablecoinDeployment] = field(default_factory=dict)

    @classmethod
    def from_iterable(cls, items: Iterable[StablecoinDeployment]) -> "StablecoinDeploymentRegistry":
        registry = cls()
        for item in items:
            registry.register(item)
        return registry

    def register(self, deployment: StablecoinDeployment) -> None:
        if deployment.deployment_id in self.deployments and self.deployments[deployment.deployment_id] != deployment:
            raise ValueError(f"conflicting deployment_id: {deployment.deployment_id}")
        self.deployments[deployment.deployment_id] = deployment

    def resolve(self, *, chain_id: str, network: str, contract_or_mint: str) -> StablecoinDeployment | None:
        normalized = contract_or_mint.lower()
        for deployment in self.deployments.values():
            if (
                deployment.chain_id == chain_id
                and deployment.network == network
                and deployment.contract_or_mint.lower() == normalized
            ):
                return deployment
        return None


PLATFORM_STABLECOIN_REGISTRY = StablecoinDeploymentRegistry.from_iterable([
    StablecoinDeployment(
        deployment_id="usdc:ethereum:mainnet:0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        canonical_asset_id="usdc",
        chain_id="1",
        network="ethereum-mainnet",
        token_standard="erc20",
        contract_or_mint="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        decimals=6,
        issuer_verified=True,
    ),
    StablecoinDeployment(
        deployment_id="usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        canonical_asset_id="usdc",
        chain_id="8453",
        network="base-mainnet",
        token_standard="erc20",
        contract_or_mint="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        decimals=6,
        issuer_verified=True,
    ),
    StablecoinDeployment(
        deployment_id="usdt:ethereum:mainnet:0xdac17f958d2ee523a2206206994597c13d831ec7",
        canonical_asset_id="usdt",
        chain_id="1",
        network="ethereum-mainnet",
        token_standard="erc20",
        contract_or_mint="0xdAC17F958D2ee523a2206206994597C13D831ec7",
        decimals=6,
        issuer_verified=True,
    ),
])
