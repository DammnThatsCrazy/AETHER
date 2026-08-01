"""Canonical stablecoin deployment registry utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Optional

from .models import StablecoinDeployment

if TYPE_CHECKING:  # avoid an import cycle — the connectors import this module
    from .connector_base import StablecoinRpcClient
    from .evm_connector import StablecoinEVMIngestionConnector
    from .price_feed import StablecoinChainlinkPriceConnector
    from .solana_connector import StablecoinSolanaIngestionConnector


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


def resolve_vm_type(deployment: StablecoinDeployment) -> str:
    """Which ingestion connector family a deployment needs: ``evm`` or ``solana``."""
    return "solana" if deployment.token_standard.lower().startswith("spl") else "evm"


@dataclass
class StablecoinConnectorRegistry:
    """Factory that builds concrete, credential-waiting ingestion + price
    connectors for registered deployments and hands them to the polling
    scheduler. Connector classes are imported lazily so importing the registry
    never pulls the connectors (which import the registry) — no import cycle.
    """

    deployments: StablecoinDeploymentRegistry = field(default_factory=StablecoinDeploymentRegistry)

    def _deployment(self, deployment_id: str) -> StablecoinDeployment:
        deployment = self.deployments.deployments.get(deployment_id)
        if deployment is None:
            raise ValueError(f"unknown stablecoin deployment: {deployment_id}")
        return deployment

    def build_ingestion_connector(
        self,
        deployment_id: str,
        *,
        rpc: "Optional[StablecoinRpcClient]" = None,
        **kwargs: Any,
    ) -> "StablecoinEVMIngestionConnector | StablecoinSolanaIngestionConnector":
        """Build the correct chain ingestion connector for a deployment.

        The injectable ``rpc`` client (any object with the ``RPCGateway.execute``
        shape) is threaded straight into the connector, so tests drive a mock
        RPC server with no live network.
        """
        deployment = self._deployment(deployment_id)
        if resolve_vm_type(deployment) == "solana":
            from .solana_connector import StablecoinSolanaIngestionConnector

            return StablecoinSolanaIngestionConnector(deployment=deployment, rpc=rpc, registry=self.deployments, **kwargs)
        from .evm_connector import StablecoinEVMIngestionConnector

        return StablecoinEVMIngestionConnector(deployment=deployment, rpc=rpc, registry=self.deployments, **kwargs)

    async def build_tenant_ingestion_connector(
        self,
        deployment_id: str,
        *,
        tenant_id: str,
        provider_gateway: Any = None,
        vault: Any = None,
        **kwargs: Any,
    ) -> "StablecoinEVMIngestionConnector | StablecoinSolanaIngestionConnector":
        """Build a chain ingestion connector whose RPC is scoped to the tenant's
        BYOK endpoint+key (resolved atomically) when tenant BYOK is enabled — so
        the connector, and its ``ConnectorCertificationMixin.preflight``, validate
        THAT tenant's endpoint. Observe-only; identity behavior (global endpoint)
        when ``AETHER_ONCHAIN_TENANT_BYOK_RPC_ENABLED`` is off.
        """
        deployment = self._deployment(deployment_id)
        from services.onchain.rpc_gateway import RPCGateway

        rpc = await RPCGateway.for_tenant(
            tenant_id, deployment.chain_id, provider_gateway=provider_gateway, vault=vault
        )
        return self.build_ingestion_connector(deployment_id, rpc=rpc, **kwargs)

    def build_price_connector(
        self,
        deployment_id: str,
        *,
        feed_address: str,
        rpc: "Optional[StablecoinRpcClient]" = None,
        **kwargs: Any,
    ) -> "StablecoinChainlinkPriceConnector":
        deployment = self._deployment(deployment_id)
        from .price_feed import StablecoinChainlinkPriceConnector

        return StablecoinChainlinkPriceConnector(deployment=deployment, feed_address=feed_address, rpc=rpc, **kwargs)


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
    StablecoinDeployment(
        deployment_id="usdc:solana:mainnet:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        canonical_asset_id="usdc",
        chain_id="solana-mainnet",
        network="solana-mainnet",
        token_standard="spl-token",
        contract_or_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        decimals=6,
        issuer_verified=True,
    ),
])

# Platform-scoped connector factory bound to the canonical deployment registry.
# The polling scheduler builds scheduler-ready, credential-waiting connectors
# from this (see ``services/stablecoins/providers.py`` for the wiring helper).
PLATFORM_STABLECOIN_CONNECTOR_REGISTRY = StablecoinConnectorRegistry(
    deployments=PLATFORM_STABLECOIN_REGISTRY
)
