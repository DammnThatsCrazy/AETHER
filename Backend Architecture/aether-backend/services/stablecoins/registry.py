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


# ─────────────────────────────────────────────────────────────────────────────
# Environment separation — mainnet is the canonical identity; staging/testnet
# are ADDITIVE deployment families so operators can prove the observer stack
# against test networks before touching mainnet.
#
# Every testnet entry is honestly labelled: ``testnet=True``,
# ``issuer_verified=False`` and a ``seed_reference`` metadata flag. The contract
# addresses are reference seeds that MUST be operator-verified before any
# environment is trusted; the connectors remain credential-waiting and
# observation-first regardless of which environment registry they are built
# from (they never assume a testnet address is live or authoritative).
# ─────────────────────────────────────────────────────────────────────────────

_MAINNET_STABLECOIN_DEPLOYMENTS = [
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
]

# Staging reference deployments (mainnet identity + staging test networks).
# Contract addresses are unverified reference seeds — see module docstring above.
_STAGING_STABLECOIN_DEPLOYMENTS = [
    StablecoinDeployment(
        deployment_id="usdc:ethereum:sepolia:0x1c7d4b196cb0c7b01d743fbc6116a902379c7238",
        canonical_asset_id="usdc",
        chain_id="11155111",
        network="ethereum-sepolia",
        token_standard="erc20",
        contract_or_mint="0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
        decimals=6,
        issuer_verified=False,
        testnet=True,
        metadata={"environment": "staging", "seed_reference": True, "verification_status": "operator_review_pending"},
    ),
    StablecoinDeployment(
        deployment_id="usdc:base:sepolia:0x036cbd53842c5426634e7929541ec2318f3dcf7e",
        canonical_asset_id="usdc",
        chain_id="84532",
        network="base-sepolia",
        token_standard="erc20",
        contract_or_mint="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        decimals=6,
        issuer_verified=False,
        testnet=True,
        metadata={"environment": "staging", "seed_reference": True, "verification_status": "operator_review_pending"},
    ),
]

# Testnet/devnet reference deployments (additive over staging; devnet mints are
# freely-fauceted and NOT authoritative — operators must verify before trust).
_TESTNET_STABLECOIN_DEPLOYMENTS = [
    StablecoinDeployment(
        deployment_id="usdc:solana:devnet:4zmmc9srt5ri5x14gagxhahii3gnpaeeerypjgzjdncdu",
        canonical_asset_id="usdc",
        chain_id="solana-devnet",
        network="solana-devnet",
        token_standard="spl-token",
        contract_or_mint="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
        decimals=6,
        issuer_verified=False,
        testnet=True,
        metadata={"environment": "testnet", "seed_reference": True, "verification_status": "operator_review_pending"},
    ),
]

PLATFORM_STABLECOIN_REGISTRY = StablecoinDeploymentRegistry.from_iterable(_MAINNET_STABLECOIN_DEPLOYMENTS)

# Staging = mainnet identity + staging test-network deployments. A staging
# deployment carries its own chain/network so ``resolve`` never confuses a
# staging observation with its mainnet twin.
PLATFORM_STABLECOIN_REGISTRY_STAGING = StablecoinDeploymentRegistry.from_iterable(
    [*_MAINNET_STABLECOIN_DEPLOYMENTS, *_STAGING_STABLECOIN_DEPLOYMENTS]
)

# Testnet = everything above + devnet mints (operator-verified before use).
PLATFORM_STABLECOIN_REGISTRY_TESTNET = StablecoinDeploymentRegistry.from_iterable(
    [*_MAINNET_STABLECOIN_DEPLOYMENTS, *_STAGING_STABLECOIN_DEPLOYMENTS, *_TESTNET_STABLECOIN_DEPLOYMENTS]
)

# ─────────────────────────────────────────────────────────────────────────────
# Per-environment resolver — which registry does THIS deployment environment
# observe? Mirrors the settings ``AETHER_ENV`` pattern: production observes
# mainnet identity only; staging observes mainnet+staging; every other
# environment (local/dev/integration) defaults to the mainnet registry so
# existing offline tests and local runs are unchanged. Testnet is selected
# explicitly (CI/devnet runs).
# ─────────────────────────────────────────────────────────────────────────────


def resolve_platform_registry(environment: Any = None) -> StablecoinDeploymentRegistry:
    """Select the deployment registry for a runtime environment.

    ``environment`` accepts the settings ``Environment`` enum (or its string
    value). Resolved lazily so importing this module never loads settings.
    """
    from config.settings import Environment, settings

    env = environment if environment is not None else settings.env
    value = env.value if hasattr(env, "value") else str(env)
    if value == Environment.PRODUCTION.value:
        return PLATFORM_STABLECOIN_REGISTRY
    if value == Environment.STAGING.value:
        return PLATFORM_STABLECOIN_REGISTRY_STAGING
    if value == "testnet":
        return PLATFORM_STABLECOIN_REGISTRY_TESTNET
    return PLATFORM_STABLECOIN_REGISTRY


# ─────────────────────────────────────────────────────────────────────────────
# Per-environment Chainlink feed config. Keyed by deployment_id (mainnet
# reference seeds are documented well-known feeds; staging/testnet feeds must
# be operator-provisioned — an empty feed is "not configured" and the price
# connector is always constructed with an explicit ``feed_address`` anyway).
# ─────────────────────────────────────────────────────────────────────────────

#: Reference-seed Chainlink feed addresses (operator-verified before release).
STABLECOIN_FEED_REFERENCE: dict[str, str] = {
    # USDC/USD — Ethereum mainnet (well-known Chainlink AggregatorV3).
    "usdc:ethereum:mainnet:0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
    # USDC/USD — Base mainnet.
    "usdc:base:mainnet:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "0x7e860098F58bBFC8648a4311b374B446D9ff32Ab",
}

#: Per-environment feed overrides — staging/testnet feeds are NOT invented;
#: operators provision them and add entries here (or pass ``feed_address``
#: explicitly when building the connector).
STABLECOIN_FEED_ENVIRONMENT_OVERRIDES: dict[str, dict[str, str]] = {
    "staging": {},
    "testnet": {},
}


def resolve_chainlink_feed_address(deployment_id: str, environment: Any = None) -> str:
    """Resolve the Chainlink feed address for a deployment in an environment.

    Returns ``""`` when no feed is provisioned — a caller MUST treat an empty
    feed as "not configured" (fail-closed), never fabricate one.
    """
    from config.settings import settings

    env = environment if environment is not None else settings.env
    value = env.value if hasattr(env, "value") else str(env)
    overrides = STABLECOIN_FEED_ENVIRONMENT_OVERRIDES.get(value, {})
    if deployment_id in overrides:
        return overrides[deployment_id]
    return STABLECOIN_FEED_REFERENCE.get(deployment_id, "")


# Platform-scoped connector factory bound to the canonical deployment registry.
# The polling scheduler builds scheduler-ready, credential-waiting connectors
# from this (see ``services/stablecoins/providers.py`` for the wiring helper).
PLATFORM_STABLECOIN_CONNECTOR_REGISTRY = StablecoinConnectorRegistry(
    deployments=PLATFORM_STABLECOIN_REGISTRY
)
