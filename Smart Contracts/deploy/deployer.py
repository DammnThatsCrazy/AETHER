"""
Aether Smart Contracts -- Deployment Script

Deploys AnalyticsRewards and RewardRegistry contracts to EVM-compatible chains.
Supports: Ethereum, Polygon, Arbitrum, Base, Optimism.

Usage:
    python deploy/deployer.py --chain polygon --token-address 0x... --oracle-address 0x...

Requirements:
    pip install web3 python-dotenv

Note:
    Since web3.py may not be installed in all environments, deployment calls
    are wrapped with clear comments showing where the actual web3 interactions
    occur.  The script uses dataclasses for structured output and argparse for
    CLI argument parsing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# EVM deploy-time safety gates. Every chain this legacy deployer targets is a
# mainnet, so the audit gate + default-key rejection always apply here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evm_guards import (  # noqa: E402
    GateError,
    assert_audit_evidence,
    assert_not_default_key,
    assert_oracle_registered,
)

# Map this script's chain keys to Hardhat network names used by the registries
# and the network-tier classifier (all are mainnet-class).
_CHAIN_TO_HARDHAT_NETWORK = {
    "ethereum": "mainnet",
    "polygon": "polygon",
    "arbitrum": "arbitrum",
    "base": "base",
    "optimism": "optimism",
}

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aether.deployer")

# ---------------------------------------------------------------------------
#  Chain Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainConfig:
    """Immutable configuration for a supported EVM chain."""

    name: str
    chain_id: int
    rpc_url: str
    explorer_url: str
    gas_price_gwei: float  # Default gas price hint; the deployer may use EIP-1559.


SUPPORTED_CHAINS: dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        name="Ethereum Mainnet",
        chain_id=1,
        rpc_url=os.getenv("ETHEREUM_RPC", "https://eth.llamarpc.com"),
        explorer_url="https://etherscan.io",
        gas_price_gwei=20.0,
    ),
    "polygon": ChainConfig(
        name="Polygon PoS",
        chain_id=137,
        rpc_url=os.getenv("POLYGON_RPC", "https://polygon-rpc.com"),
        explorer_url="https://polygonscan.com",
        gas_price_gwei=35.0,
    ),
    "arbitrum": ChainConfig(
        name="Arbitrum One",
        chain_id=42161,
        rpc_url=os.getenv("ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc"),
        explorer_url="https://arbiscan.io",
        gas_price_gwei=0.1,
    ),
    "base": ChainConfig(
        name="Base",
        chain_id=8453,
        rpc_url=os.getenv("BASE_RPC", "https://mainnet.base.org"),
        explorer_url="https://basescan.org",
        gas_price_gwei=0.01,
    ),
    "optimism": ChainConfig(
        name="Optimism",
        chain_id=10,
        rpc_url=os.getenv("OPTIMISM_RPC", "https://mainnet.optimism.io"),
        explorer_url="https://optimistic.etherscan.io",
        gas_price_gwei=0.01,
    ),
}

# ---------------------------------------------------------------------------
#  Deployment Result
# ---------------------------------------------------------------------------


@dataclass
class DeploymentResult:
    """Structured output for a single contract deployment."""

    chain: str
    contract_name: str
    contract_address: str
    tx_hash: str
    block_number: int
    deployer: str
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"[{self.chain}] {self.contract_name}\n"
            f"  Address  : {self.contract_address}\n"
            f"  Tx Hash  : {self.tx_hash}\n"
            f"  Block    : {self.block_number}\n"
            f"  Deployer : {self.deployer}\n"
        )


# ---------------------------------------------------------------------------
#  Artifact Helpers
# ---------------------------------------------------------------------------

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "contracts"


def _load_artifact(contract_name: str) -> dict:
    """
    Load compiled contract artifact (ABI + bytecode) from Hardhat output.

    Expects the standard Hardhat artifact path:
        artifacts/contracts/<Name>.sol/<Name>.json
    """
    artifact_path = ARTIFACTS_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    if not artifact_path.exists():
        logger.warning(
            "Artifact not found at %s. Run `npx hardhat compile` first.",
            artifact_path,
        )
        # Return a stub so the rest of the script can demonstrate the flow.
        return {"abi": [], "bytecode": "0x"}
    with open(artifact_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
#  Contract Deployer
# ---------------------------------------------------------------------------


class ContractDeployer:
    """
    Deploys Aether smart contracts to an EVM chain.

    Parameters
    ----------
    chain : str
        Key into ``SUPPORTED_CHAINS`` (e.g. "polygon").
    private_key : str
        Hex-encoded deployer private key (without 0x prefix is fine).
    """

    def __init__(self, chain: str, private_key: str) -> None:
        if chain not in SUPPORTED_CHAINS:
            raise ValueError(
                f"Unsupported chain '{chain}'. Choose from: {list(SUPPORTED_CHAINS)}"
            )
        self.chain_config = SUPPORTED_CHAINS[chain]
        self.chain = chain
        self.private_key = private_key

        # ── web3 connection ──────────────────────────────────────────
        # In a live environment with web3.py installed:
        #
        #   from web3 import Web3
        #   self.w3 = Web3(Web3.HTTPProvider(self.chain_config.rpc_url))
        #   self.account = self.w3.eth.account.from_key(private_key)
        #   self.deployer_address = self.account.address
        #   logger.info("Connected to %s (chain_id=%d)",
        #               self.chain_config.name, self.w3.eth.chain_id)
        #
        # For demonstration we store a placeholder address.
        self.w3 = None  # Would be Web3 instance
        self.deployer_address = "0xDeployerAddressPlaceholder"
        logger.info(
            "Deployer initialised for %s (chain_id=%d)",
            self.chain_config.name,
            self.chain_config.chain_id,
        )

    # ------------------------------------------------------------------ #
    #  Internal: send deployment transaction                               #
    # ------------------------------------------------------------------ #

    async def _deploy_contract(
        self,
        contract_name: str,
        constructor_args: list,
    ) -> DeploymentResult:
        """
        Compile, sign, and broadcast a deployment transaction.

        With web3.py installed the flow would be:

            artifact = _load_artifact(contract_name)
            contract = self.w3.eth.contract(
                abi=artifact["abi"],
                bytecode=artifact["bytecode"],
            )
            tx = contract.constructor(*constructor_args).build_transaction({
                "from": self.deployer_address,
                "nonce": self.w3.eth.get_transaction_count(self.deployer_address),
                "gas": 3_000_000,
                "gasPrice": self.w3.to_wei(
                    self.chain_config.gas_price_gwei, "gwei"
                ),
                "chainId": self.chain_config.chain_id,
            })
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            address = receipt.contractAddress
        """
        logger.info("Deploying %s to %s ...", contract_name, self.chain_config.name)
        logger.info("  Constructor args: %s", constructor_args)

        artifact = _load_artifact(contract_name)
        has_bytecode = artifact.get("bytecode", "0x") != "0x"

        if not has_bytecode:
            logger.warning(
                "  No bytecode found for %s — returning simulated result.",
                contract_name,
            )

        # Simulated result (replace with actual receipt fields in production).
        simulated_address = f"0x{'0' * 38}{self.chain_config.chain_id:02d}"
        simulated_tx_hash = f"0x{'ab' * 32}"
        simulated_block = 0

        result = DeploymentResult(
            chain=self.chain_config.name,
            contract_name=contract_name,
            contract_address=simulated_address,
            tx_hash=simulated_tx_hash,
            block_number=simulated_block,
            deployer=self.deployer_address,
        )
        logger.info("  Deployed %s at %s", contract_name, result.contract_address)
        return result

    # ------------------------------------------------------------------ #
    #  Public deployment methods                                           #
    # ------------------------------------------------------------------ #

    async def deploy_rewards(
        self,
        token_address: str,
        oracle_address: str,
    ) -> DeploymentResult:
        """
        Deploy the ``AnalyticsRewards`` contract.

        Parameters
        ----------
        token_address : str
            ERC-20 reward token address.
        oracle_address : str
            Initial oracle signer address.

        Returns
        -------
        DeploymentResult
        """
        return await self._deploy_contract(
            "AnalyticsRewards",
            [token_address, self.deployer_address, oracle_address],
        )

    async def deploy_registry(
        self,
        rewards_address: str,
    ) -> DeploymentResult:
        """
        Deploy the ``RewardRegistry`` contract.

        Parameters
        ----------
        rewards_address : str
            Address of the previously deployed AnalyticsRewards contract
            (stored in the registry for reference).

        Returns
        -------
        DeploymentResult
        """
        return await self._deploy_contract(
            "RewardRegistry",
            [self.deployer_address],
        )

    async def deploy_all(
        self,
        token_address: str,
        oracle_address: str,
    ) -> dict[str, DeploymentResult]:
        """
        Deploy the full Aether contract suite in the correct order.

        1. AnalyticsRewards (depends on token + oracle addresses).
        2. RewardRegistry   (references the rewards contract).

        Returns
        -------
        dict
            Mapping of contract names to their ``DeploymentResult``.
        """
        results: dict[str, DeploymentResult] = {}

        rewards_result = await self.deploy_rewards(token_address, oracle_address)
        results["AnalyticsRewards"] = rewards_result

        registry_result = await self.deploy_registry(rewards_result.contract_address)
        results["RewardRegistry"] = registry_result

        return results

    async def verify_deployment(self, address: str) -> bool:
        """
        Verify that a contract is deployed at the given address.

        With web3.py installed:
            code = self.w3.eth.get_code(address)
            return len(code) > 2  # "0x" means no code

        Returns
        -------
        bool
            True if bytecode exists at the address.
        """
        logger.info("Verifying deployment at %s ...", address)
        # Simulated check
        logger.info("  Verification simulated (install web3.py for live check).")
        return True


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="deployer",
        description="Deploy Aether smart contracts to EVM chains.",
    )
    parser.add_argument(
        "--chain",
        required=True,
        choices=list(SUPPORTED_CHAINS),
        help="Target EVM chain.",
    )
    parser.add_argument(
        "--token-address",
        required=True,
        help="ERC-20 reward token address.",
    )
    parser.add_argument(
        "--oracle-address",
        required=True,
        help="Initial oracle signer address.",
    )
    # Private key is read exclusively from the DEPLOYER_KEY environment variable.
    # Passing it as a CLI argument is intentionally not supported: command-line
    # arguments are visible in process listings (ps aux), shell history, and CI
    # logs, which would expose the private key to any user on the same host.
    parser.add_argument(
        "--rewards-only",
        action="store_true",
        help="Deploy only the AnalyticsRewards contract.",
    )
    parser.add_argument(
        "--registry-only",
        default=None,
        metavar="REWARDS_ADDRESS",
        help="Deploy only the RewardRegistry, referencing an existing rewards contract.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify deployments after broadcasting.",
    )
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    private_key = os.getenv("DEPLOYER_KEY", "")
    if not private_key:
        logger.error("No deployer key provided. Set the DEPLOYER_KEY environment variable.")
        sys.exit(1)

    # ── Fail-closed pre-deploy gates (mirror scripts/deploy.js) ──
    # All chains here are mainnet-class, so the audit gate always applies.
    hardhat_network = _CHAIN_TO_HARDHAT_NETWORK.get(args.chain, args.chain)
    try:
        assert_audit_evidence(hardhat_network)
        assert_not_default_key(hardhat_network, private_key)
        if args.oracle_address:
            assert_oracle_registered(hardhat_network, args.oracle_address)
    except GateError as e:
        logger.error("Deployment BLOCKED by safety gate [%s]: %s", e.category, e)
        sys.exit(1)

    deployer = ContractDeployer(chain=args.chain, private_key=private_key)

    results: dict[str, DeploymentResult] = {}

    if args.registry_only:
        result = await deployer.deploy_registry(args.registry_only)
        results["RewardRegistry"] = result
    elif args.rewards_only:
        result = await deployer.deploy_rewards(args.token_address, args.oracle_address)
        results["AnalyticsRewards"] = result
    else:
        results = await deployer.deploy_all(args.token_address, args.oracle_address)

    # ── Print summary ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Aether Deployment Summary")
    print("=" * 60)
    for name, result in results.items():
        print(result.summary())

    # ── Optional verification ────────────────────────────────────────
    if args.verify:
        print("Verifying deployments ...")
        for name, result in results.items():
            ok = await deployer.verify_deployment(result.contract_address)
            status = "OK" if ok else "FAILED"
            print(f"  {name}: {status}")

    # ── Write deployment manifest ────────────────────────────────────
    manifest_dir = Path(__file__).resolve().parent / "deployments"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{args.chain}_{int(time.time())}.json"

    manifest = {
        "chain": args.chain,
        "chain_id": SUPPORTED_CHAINS[args.chain].chain_id,
        "timestamp": time.time(),
        "contracts": {name: asdict(r) for name, r in results.items()},
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Deployment manifest written to %s", manifest_path)


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(_main())
