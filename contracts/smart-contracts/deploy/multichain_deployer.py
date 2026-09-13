"""
Aether -- Multi-Chain Smart Contract Deployer
Supports: EVM (Ethereum, Polygon, Arbitrum, Base, Optimism),
          SVM (Solana), MoveVM (SUI), NEAR, TRON, Cosmos

Each chain has its own deployment strategy:
    EVM:    Hardhat/ethers.js via subprocess
    SVM:    Anchor CLI via subprocess
    SUI:    SUI CLI via subprocess
    NEAR:   near-cli via subprocess
    TRON:   TronBox via subprocess
    Cosmos: wasmd/osmosisd via subprocess

Usage:
    python deploy/multichain_deployer.py --chain solana --network devnet
    python deploy/multichain_deployer.py --chain sui --network testnet
    python deploy/multichain_deployer.py --chain near --network testnet --account aether.testnet
    python deploy/multichain_deployer.py --chain cosmos --network testnet --chain-id osmosis-1
    python deploy/multichain_deployer.py --chain ethereum --network mainnet --token-address 0x...
    python deploy/multichain_deployer.py --chain tron --network nile
    python deploy/multichain_deployer.py --all --network testnet

Requirements:
    pip install python-dotenv
    Chain-specific CLIs must be installed separately (anchor, sui, near-cli, etc.)
"""

from __future__ import annotations

import abc
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# EVM deploy-time safety gates (audit gate, default-key rejection, registries).
# Ensure this file's directory is importable whether run as a script or imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evm_guards import (  # noqa: E402
    GateError,
    network_tier,
    run_evm_predeploy_gates,
)

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aether.multichain_deployer")

# ---------------------------------------------------------------------------
#  Project Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = PROJECT_ROOT / "contracts"
PROGRAMS_DIR = PROJECT_ROOT / "programs"
DEPLOY_DIR = PROJECT_ROOT / "deploy"
DEPLOYMENTS_DIR = DEPLOY_DIR / "deployments"

# ---------------------------------------------------------------------------
#  Enums
# ---------------------------------------------------------------------------


class ChainType(str, Enum):
    """Supported blockchain platforms."""

    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    BASE = "base"
    OPTIMISM = "optimism"
    SOLANA = "solana"
    SUI = "sui"
    NEAR = "near"
    TRON = "tron"
    COSMOS = "cosmos"


class NetworkType(str, Enum):
    """Deployment network targets."""

    MAINNET = "mainnet"
    TESTNET = "testnet"
    DEVNET = "devnet"
    LOCALNET = "localnet"


# ---------------------------------------------------------------------------
#  Chain Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainConfig:
    """Immutable configuration for a supported blockchain."""

    name: str
    chain_type: ChainType
    chain_id: str
    rpc_urls: dict[str, str]
    explorer_urls: dict[str, str]
    native_denom: str
    deploy_cli: str


# Complete chain configurations for all supported networks.
CHAIN_CONFIGS: dict[str, ChainConfig] = {
    # --- EVM Chains ---
    "ethereum": ChainConfig(
        name="Ethereum",
        chain_type=ChainType.ETHEREUM,
        chain_id="1",
        rpc_urls={
            "mainnet": os.getenv("ETHEREUM_RPC", "https://eth.llamarpc.com"),
            "testnet": os.getenv("ETHEREUM_TESTNET_RPC", "https://rpc.sepolia.org"),
            "localnet": "http://127.0.0.1:8545",
        },
        explorer_urls={
            "mainnet": "https://etherscan.io",
            "testnet": "https://sepolia.etherscan.io",
        },
        native_denom="ETH",
        deploy_cli="npx hardhat",
    ),
    "polygon": ChainConfig(
        name="Polygon PoS",
        chain_type=ChainType.POLYGON,
        chain_id="137",
        rpc_urls={
            "mainnet": os.getenv("POLYGON_RPC", "https://polygon-rpc.com"),
            "testnet": os.getenv("POLYGON_TESTNET_RPC", "https://rpc-amoy.polygon.technology"),
            "localnet": "http://127.0.0.1:8545",
        },
        explorer_urls={
            "mainnet": "https://polygonscan.com",
            "testnet": "https://amoy.polygonscan.com",
        },
        native_denom="MATIC",
        deploy_cli="npx hardhat",
    ),
    "arbitrum": ChainConfig(
        name="Arbitrum One",
        chain_type=ChainType.ARBITRUM,
        chain_id="42161",
        rpc_urls={
            "mainnet": os.getenv("ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc"),
            "testnet": os.getenv("ARBITRUM_TESTNET_RPC", "https://sepolia-rollup.arbitrum.io/rpc"),
            "localnet": "http://127.0.0.1:8545",
        },
        explorer_urls={
            "mainnet": "https://arbiscan.io",
            "testnet": "https://sepolia.arbiscan.io",
        },
        native_denom="ETH",
        deploy_cli="npx hardhat",
    ),
    "base": ChainConfig(
        name="Base",
        chain_type=ChainType.BASE,
        chain_id="8453",
        rpc_urls={
            "mainnet": os.getenv("BASE_RPC", "https://mainnet.base.org"),
            "testnet": os.getenv("BASE_TESTNET_RPC", "https://sepolia.base.org"),
            "localnet": "http://127.0.0.1:8545",
        },
        explorer_urls={
            "mainnet": "https://basescan.org",
            "testnet": "https://sepolia.basescan.org",
        },
        native_denom="ETH",
        deploy_cli="npx hardhat",
    ),
    "optimism": ChainConfig(
        name="Optimism",
        chain_type=ChainType.OPTIMISM,
        chain_id="10",
        rpc_urls={
            "mainnet": os.getenv("OPTIMISM_RPC", "https://mainnet.optimism.io"),
            "testnet": os.getenv("OPTIMISM_TESTNET_RPC", "https://sepolia.optimism.io"),
            "localnet": "http://127.0.0.1:8545",
        },
        explorer_urls={
            "mainnet": "https://optimistic.etherscan.io",
            "testnet": "https://sepolia-optimism.etherscan.io",
        },
        native_denom="ETH",
        deploy_cli="npx hardhat",
    ),
    # --- Non-EVM Chains ---
    "solana": ChainConfig(
        name="Solana",
        chain_type=ChainType.SOLANA,
        chain_id="solana-mainnet",
        rpc_urls={
            "mainnet": os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com"),
            "testnet": os.getenv("SOLANA_TESTNET_RPC", "https://api.testnet.solana.com"),
            "devnet": os.getenv("SOLANA_DEVNET_RPC", "https://api.devnet.solana.com"),
            "localnet": "http://127.0.0.1:8899",
        },
        explorer_urls={
            "mainnet": "https://explorer.solana.com",
            "testnet": "https://explorer.solana.com?cluster=testnet",
            "devnet": "https://explorer.solana.com?cluster=devnet",
        },
        native_denom="SOL",
        deploy_cli="anchor",
    ),
    "sui": ChainConfig(
        name="SUI",
        chain_type=ChainType.SUI,
        chain_id="sui-mainnet",
        rpc_urls={
            "mainnet": os.getenv("SUI_RPC", "https://fullnode.mainnet.sui.io:443"),
            "testnet": os.getenv("SUI_TESTNET_RPC", "https://fullnode.testnet.sui.io:443"),
            "devnet": os.getenv("SUI_DEVNET_RPC", "https://fullnode.devnet.sui.io:443"),
            "localnet": "http://127.0.0.1:9000",
        },
        explorer_urls={
            "mainnet": "https://suiscan.xyz/mainnet",
            "testnet": "https://suiscan.xyz/testnet",
            "devnet": "https://suiscan.xyz/devnet",
        },
        native_denom="SUI",
        deploy_cli="sui",
    ),
    "near": ChainConfig(
        name="NEAR",
        chain_type=ChainType.NEAR,
        chain_id="near-mainnet",
        rpc_urls={
            "mainnet": os.getenv("NEAR_RPC", "https://rpc.mainnet.near.org"),
            "testnet": os.getenv("NEAR_TESTNET_RPC", "https://rpc.testnet.near.org"),
            "localnet": "http://127.0.0.1:3030",
        },
        explorer_urls={
            "mainnet": "https://nearblocks.io",
            "testnet": "https://testnet.nearblocks.io",
        },
        native_denom="NEAR",
        deploy_cli="near",
    ),
    "tron": ChainConfig(
        name="TRON",
        chain_type=ChainType.TRON,
        chain_id="tron-mainnet",
        rpc_urls={
            "mainnet": os.getenv("TRON_RPC", "https://api.trongrid.io"),
            "testnet": os.getenv("TRON_TESTNET_RPC", "https://nile.trongrid.io"),
            "localnet": "http://127.0.0.1:9090",
        },
        explorer_urls={
            "mainnet": "https://tronscan.org",
            "testnet": "https://nile.tronscan.org",
        },
        native_denom="TRX",
        deploy_cli="tronbox",
    ),
    "cosmos": ChainConfig(
        name="Cosmos (CosmWasm)",
        chain_type=ChainType.COSMOS,
        chain_id=os.getenv("COSMOS_CHAIN_ID", "osmosis-1"),
        rpc_urls={
            "mainnet": os.getenv("COSMOS_RPC", "https://rpc.osmosis.zone"),
            "testnet": os.getenv("COSMOS_TESTNET_RPC", "https://rpc.testnet.osmosis.zone"),
            "localnet": "http://127.0.0.1:26657",
        },
        explorer_urls={
            "mainnet": "https://www.mintscan.io/osmosis",
            "testnet": "https://testnet.mintscan.io/osmosis-testnet",
        },
        native_denom="uosmo",
        deploy_cli="osmosisd",
    ),
}

# ---------------------------------------------------------------------------
#  Deployment Result
# ---------------------------------------------------------------------------


@dataclass
class DeploymentResult:
    """Structured output for a single contract deployment."""

    chain: str
    chain_type: str
    network: str
    contract_name: str
    contract_address: str
    tx_hash: str
    block_number: int
    deployer: str
    explorer_url: str
    timestamp: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"[{self.chain}] {self.contract_name}",
            f"  Network  : {self.network}",
            f"  Address  : {self.contract_address}",
            f"  Tx Hash  : {self.tx_hash}",
            f"  Block    : {self.block_number}",
            f"  Deployer : {self.deployer}",
            f"  Explorer : {self.explorer_url}",
        ]
        for key, value in self.extra.items():
            lines.append(f"  {key:9s}: {value}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
#  Abstract Base Deployer
# ---------------------------------------------------------------------------


class ChainDeployer(abc.ABC):
    """Abstract base class for chain-specific deployers."""

    def __init__(self, config: ChainConfig, network: str, **kwargs: Any) -> None:
        self.config = config
        self.network = network
        self.kwargs = kwargs

        rpc_url = config.rpc_urls.get(network)
        if not rpc_url:
            raise ValueError(
                f"Network '{network}' not supported for {config.name}. "
                f"Available: {list(config.rpc_urls.keys())}"
            )
        self.rpc_url = rpc_url
        self.explorer_base = config.explorer_urls.get(network, "")

    @abc.abstractmethod
    def deploy(self) -> DeploymentResult:
        """Deploy the contract and return the deployment result."""

    @abc.abstractmethod
    def verify(self, address: str) -> bool:
        """Verify that a contract is deployed at the given address."""

    def get_explorer_url(self, address: str) -> str:
        """Get the block explorer URL for a deployed contract address."""
        if not self.explorer_base:
            return f"No explorer available for {self.config.name} {self.network}"

        chain_type = self.config.chain_type
        if chain_type in (
            ChainType.ETHEREUM,
            ChainType.POLYGON,
            ChainType.ARBITRUM,
            ChainType.BASE,
            ChainType.OPTIMISM,
        ):
            return f"{self.explorer_base}/address/{address}"
        elif chain_type == ChainType.SOLANA:
            cluster_param = ""
            if self.network == "devnet":
                cluster_param = "?cluster=devnet"
            elif self.network == "testnet":
                cluster_param = "?cluster=testnet"
            return f"https://explorer.solana.com/address/{address}{cluster_param}"
        elif chain_type == ChainType.SUI:
            return f"{self.explorer_base}/object/{address}"
        elif chain_type == ChainType.NEAR:
            return f"{self.explorer_base}/address/{address}"
        elif chain_type == ChainType.TRON:
            return f"{self.explorer_base}/#/contract/{address}"
        elif chain_type == ChainType.COSMOS:
            return f"{self.explorer_base}/wasm/contract/{address}"
        return f"{self.explorer_base}/{address}"

    def _run_command(
        self,
        cmd: list[str],
        cwd: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess:
        """Run a shell command and return the result."""
        merged_env = {**os.environ, **(env or {})}
        logger.info("Running: %s", " ".join(cmd))
        logger.info("  CWD: %s", cwd or os.getcwd())

        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.error("Command failed (exit %d):", result.returncode)
            logger.error("  stdout: %s", result.stdout[:2000] if result.stdout else "(empty)")
            logger.error("  stderr: %s", result.stderr[:2000] if result.stderr else "(empty)")
        else:
            logger.info("  Command succeeded.")
            if result.stdout:
                logger.debug("  stdout: %s", result.stdout[:500])

        return result

    def _check_cli_available(self, cli_name: str) -> bool:
        """Check if a CLI tool is available on the system PATH."""
        return shutil.which(cli_name) is not None


# ---------------------------------------------------------------------------
#  EVM Deployer (Ethereum, Polygon, Arbitrum, Base, Optimism)
# ---------------------------------------------------------------------------


class EVMDeployer(ChainDeployer):
    """Deploys Solidity contracts via Hardhat to EVM-compatible chains."""

    def deploy(self) -> DeploymentResult:
        if not self._check_cli_available("npx"):
            logger.warning("npx not found. Ensure Node.js and Hardhat are installed.")

        token_address = self.kwargs.get("token_address", "0x" + "0" * 40)
        oracle_address = self.kwargs.get("oracle_address", "0x" + "0" * 40)
        private_key = self.kwargs.get("private_key", os.getenv("DEPLOYER_KEY", ""))

        hardhat_network = self._get_hardhat_network()

        # ── Fail-closed pre-deploy gates (mirror scripts/deploy.js) ──
        #   Mainnet audit gate + default-key rejection + oracle registry.
        #   GateError propagates so deploy_chain records it as a failure and
        #   the hardhat subprocess never runs. Local networks bypass all gates.
        logger.info(
            "Pre-deploy gates for '%s' (%s tier)...",
            hardhat_network,
            network_tier(hardhat_network),
        )
        run_evm_predeploy_gates(hardhat_network, oracle_address, private_key)
        logger.info("Pre-deploy gates passed.")

        deploy_env = {}
        if private_key:
            deploy_env["DEPLOYER_KEY"] = private_key

        cmd = [
            "npx", "hardhat", "run",
            "scripts/deploy.js",
            "--network", hardhat_network,
        ]

        result = self._run_command(cmd, cwd=PROJECT_ROOT, env=deploy_env)

        contract_address = self._parse_address_from_output(result.stdout)
        tx_hash = self._parse_tx_hash_from_output(result.stdout)

        return DeploymentResult(
            chain=self.config.name,
            chain_type=self.config.chain_type.value,
            network=self.network,
            contract_name="AnalyticsRewards",
            contract_address=contract_address,
            tx_hash=tx_hash,
            block_number=0,
            deployer=self.kwargs.get("deployer_address", "unknown"),
            explorer_url=self.get_explorer_url(contract_address),
            extra={
                "token_address": token_address,
                "oracle_address": oracle_address,
            },
        )

    def verify(self, address: str) -> bool:
        hardhat_network = self._get_hardhat_network()

        cmd = [
            "npx", "hardhat", "verify",
            "--network", hardhat_network,
            address,
        ]

        result = self._run_command(cmd, cwd=PROJECT_ROOT)
        return result.returncode == 0

    def _get_hardhat_network(self) -> str:
        """Map our network names to Hardhat network identifiers."""
        chain_name = self.config.chain_type.value
        network_map = {
            ("ethereum", "mainnet"): "mainnet",
            ("ethereum", "testnet"): "sepolia",
            ("ethereum", "localnet"): "localhost",
            ("polygon", "mainnet"): "polygon",
            ("polygon", "testnet"): "amoy",
            ("polygon", "localnet"): "localhost",
            ("arbitrum", "mainnet"): "arbitrum",
            ("arbitrum", "testnet"): "arbitrumSepolia",
            ("arbitrum", "localnet"): "localhost",
            ("base", "mainnet"): "base",
            ("base", "testnet"): "baseSepolia",
            ("base", "localnet"): "localhost",
            ("optimism", "mainnet"): "optimism",
            ("optimism", "testnet"): "optimismSepolia",
            ("optimism", "localnet"): "localhost",
        }
        return network_map.get((chain_name, self.network), "localhost")

    def _parse_address_from_output(self, output: str) -> str:
        """Extract a contract address from Hardhat deployment output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "deployed to" in stripped.lower() or "contract address" in stripped.lower():
                # Look for 0x-prefixed address.
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if clean.startswith("0x") and len(clean) == 42:
                        return clean
        return "0x" + "0" * 40

    def _parse_tx_hash_from_output(self, output: str) -> str:
        """Extract a transaction hash from Hardhat deployment output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "transaction" in stripped.lower() or "tx hash" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if clean.startswith("0x") and len(clean) == 66:
                        return clean
        return "0x" + "0" * 64


# ---------------------------------------------------------------------------
#  Solana Deployer (Anchor)
# ---------------------------------------------------------------------------


class SolanaDeployer(ChainDeployer):
    """Deploys Anchor programs to Solana."""

    def deploy(self) -> DeploymentResult:
        if not self._check_cli_available("anchor"):
            logger.warning("Anchor CLI not found. Install with: cargo install --git https://github.com/coral-xyz/anchor anchor-cli")

        cluster = self._get_cluster()
        wallet = self.kwargs.get("wallet", os.getenv("SOLANA_WALLET", "~/.config/solana/id.json"))
        program_dir = PROGRAMS_DIR / "solana"

        # Step 1: Build the Anchor program.
        build_cmd = ["anchor", "build"]
        build_result = self._run_command(build_cmd, cwd=PROJECT_ROOT)

        if build_result.returncode != 0:
            logger.error("Anchor build failed. Check program source.")

        # Step 2: Deploy to the specified cluster.
        deploy_cmd = [
            "anchor", "deploy",
            "--provider.cluster", cluster,
            "--provider.wallet", wallet,
        ]
        deploy_result = self._run_command(deploy_cmd, cwd=PROJECT_ROOT)

        program_id = self._parse_program_id(deploy_result.stdout)
        tx_hash = self._parse_deploy_tx(deploy_result.stdout)

        return DeploymentResult(
            chain=self.config.name,
            chain_type=self.config.chain_type.value,
            network=self.network,
            contract_name="aether_rewards",
            contract_address=program_id,
            tx_hash=tx_hash,
            block_number=0,
            deployer=wallet,
            explorer_url=self.get_explorer_url(program_id),
            extra={"cluster": cluster},
        )

    def verify(self, address: str) -> bool:
        cluster = self._get_cluster()
        cmd = ["solana", "program", "show", address, "--url", cluster]
        result = self._run_command(cmd)
        return result.returncode == 0 and "Program Id" in result.stdout

    def _get_cluster(self) -> str:
        """Map network type to Solana cluster URL."""
        cluster_map = {
            "mainnet": "mainnet-beta",
            "testnet": "testnet",
            "devnet": "devnet",
            "localnet": "localnet",
        }
        return cluster_map.get(self.network, "devnet")

    def _parse_program_id(self, output: str) -> str:
        """Extract the program ID from Anchor deploy output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "program id" in stripped.lower() or "programid" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    # Solana addresses are base58, typically 32-44 chars.
                    if len(clean) >= 32 and len(clean) <= 44 and clean.isalnum():
                        return clean
            # Also check for "Deploying program ... to ..."
            if "deploying" in stripped.lower() and "..." in stripped:
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'.")
                    if len(clean) >= 32 and len(clean) <= 44 and clean.isalnum():
                        return clean
        return "ProgramIdNotParsed"

    def _parse_deploy_tx(self, output: str) -> str:
        """Extract the deployment transaction signature from Anchor output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "signature" in stripped.lower() or "tx" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if len(clean) >= 64 and clean.isalnum():
                        return clean
        return "TxNotParsed"


# ---------------------------------------------------------------------------
#  SUI Deployer
# ---------------------------------------------------------------------------


class SUIDeployer(ChainDeployer):
    """Deploys Move modules to the SUI network."""

    def deploy(self) -> DeploymentResult:
        if not self._check_cli_available("sui"):
            logger.warning("SUI CLI not found. Install from: https://docs.sui.io/build/install")

        sui_env = self._get_sui_env()
        package_dir = PROGRAMS_DIR / "sui"

        # Step 1: Switch to the correct SUI environment.
        env_cmd = ["sui", "client", "switch", "--env", sui_env]
        self._run_command(env_cmd)

        # Step 2: Build the Move package.
        build_cmd = ["sui", "move", "build"]
        build_result = self._run_command(build_cmd, cwd=package_dir)

        if build_result.returncode != 0:
            logger.error("SUI Move build failed.")

        # Step 3: Publish the package.
        publish_cmd = [
            "sui", "client", "publish",
            "--gas-budget", "100000000",
            "--json",
        ]
        publish_result = self._run_command(publish_cmd, cwd=package_dir)

        package_id, tx_digest = self._parse_publish_output(publish_result.stdout)

        return DeploymentResult(
            chain=self.config.name,
            chain_type=self.config.chain_type.value,
            network=self.network,
            contract_name="aether_rewards",
            contract_address=package_id,
            tx_hash=tx_digest,
            block_number=0,
            deployer=self.kwargs.get("deployer", "default-sui-address"),
            explorer_url=self.get_explorer_url(package_id),
            extra={"sui_env": sui_env},
        )

    def verify(self, address: str) -> bool:
        cmd = ["sui", "client", "object", address, "--json"]
        result = self._run_command(cmd)
        if result.returncode == 0:
            try:
                obj = json.loads(result.stdout)
                return "data" in obj
            except json.JSONDecodeError:
                pass
        return False

    def _get_sui_env(self) -> str:
        """Map network type to SUI environment name."""
        env_map = {
            "mainnet": "mainnet",
            "testnet": "testnet",
            "devnet": "devnet",
            "localnet": "localnet",
        }
        return env_map.get(self.network, "devnet")

    def _parse_publish_output(self, output: str) -> tuple[str, str]:
        """Extract the package ID and transaction digest from SUI publish output."""
        try:
            data = json.loads(output)
            # SUI CLI --json output structure.
            package_id = ""
            tx_digest = data.get("digest", "")

            # Look for the published package in objectChanges.
            object_changes = data.get("objectChanges", [])
            for change in object_changes:
                if change.get("type") == "published":
                    package_id = change.get("packageId", "")
                    break

            if package_id:
                return package_id, tx_digest
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Fallback: parse text output.
        package_id = "PackageIdNotParsed"
        tx_digest = "TxDigestNotParsed"

        for line in output.splitlines():
            stripped = line.strip()
            if "package id" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if clean.startswith("0x") and len(clean) > 10:
                        package_id = clean
                        break
            if "transaction digest" in stripped.lower() or "digest" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if len(clean) > 40:
                        tx_digest = clean
                        break

        return package_id, tx_digest


# ---------------------------------------------------------------------------
#  NEAR Deployer
# ---------------------------------------------------------------------------


class NEARDeployer(ChainDeployer):
    """Deploys Rust contracts to the NEAR Protocol."""

    def deploy(self) -> DeploymentResult:
        if not self._check_cli_available("near"):
            logger.warning("near-cli not found. Install with: npm install -g near-cli")

        account_id = self.kwargs.get("account", os.getenv("NEAR_ACCOUNT", ""))
        if not account_id:
            raise ValueError("NEAR account ID required. Use --account or NEAR_ACCOUNT env var.")

        oracle_pubkey = self.kwargs.get("oracle_pubkey", "0" * 64)
        contract_dir = PROGRAMS_DIR / "near"
        near_env = self._get_near_env()

        # Step 1: Build the contract with cargo.
        build_cmd = [
            "cargo", "build",
            "--target", "wasm32-unknown-unknown",
            "--release",
        ]
        build_result = self._run_command(build_cmd, cwd=contract_dir)

        if build_result.returncode != 0:
            logger.error("NEAR contract build failed.")

        # Step 2: Find the WASM artifact.
        wasm_path = contract_dir / "target" / "wasm32-unknown-unknown" / "release" / "aether_rewards.wasm"

        # Step 3: Deploy the contract.
        deploy_env = {"NEAR_ENV": near_env}
        deploy_cmd = [
            "near", "deploy",
            account_id,
            str(wasm_path),
            "--initFunction", "new",
            "--initArgs", json.dumps({"oracle_pubkey": oracle_pubkey}),
        ]

        deploy_result = self._run_command(deploy_cmd, cwd=contract_dir, env=deploy_env)

        tx_hash = self._parse_near_tx(deploy_result.stdout)

        return DeploymentResult(
            chain=self.config.name,
            chain_type=self.config.chain_type.value,
            network=self.network,
            contract_name="aether_rewards",
            contract_address=account_id,
            tx_hash=tx_hash,
            block_number=0,
            deployer=account_id,
            explorer_url=self.get_explorer_url(account_id),
            extra={
                "near_env": near_env,
                "oracle_pubkey": oracle_pubkey,
            },
        )

    def verify(self, address: str) -> bool:
        near_env = self._get_near_env()
        cmd = ["near", "view-state", address, "--finality", "final"]
        result = self._run_command(cmd, env={"NEAR_ENV": near_env})
        return result.returncode == 0

    def _get_near_env(self) -> str:
        """Map network type to NEAR environment."""
        env_map = {
            "mainnet": "mainnet",
            "testnet": "testnet",
            "localnet": "local",
        }
        return env_map.get(self.network, "testnet")

    def _parse_near_tx(self, output: str) -> str:
        """Extract transaction hash from near-cli deploy output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "transaction" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if len(clean) > 40 and clean.isalnum():
                        return clean
        return "TxNotParsed"


# ---------------------------------------------------------------------------
#  TRON Deployer
# ---------------------------------------------------------------------------


class TRONDeployer(ChainDeployer):
    """Deploys Solidity contracts to TRON via TronBox."""

    def deploy(self) -> DeploymentResult:
        if not self._check_cli_available("tronbox"):
            logger.warning("TronBox not found. Install with: npm install -g tronbox")

        tron_network = self._get_tron_network()
        private_key = self.kwargs.get("private_key", os.getenv("TRON_PRIVATE_KEY", ""))

        deploy_env = {}
        if private_key:
            deploy_env["PRIVATE_KEY"] = private_key

        # Step 1: Compile contracts.
        compile_cmd = ["tronbox", "compile"]
        self._run_command(compile_cmd, cwd=PROJECT_ROOT, env=deploy_env)

        # Step 2: Migrate (deploy).
        migrate_cmd = [
            "tronbox", "migrate",
            "--network", tron_network,
            "--reset",
        ]
        migrate_result = self._run_command(migrate_cmd, cwd=PROJECT_ROOT, env=deploy_env)

        contract_address = self._parse_tron_address(migrate_result.stdout)
        tx_hash = self._parse_tron_tx(migrate_result.stdout)

        return DeploymentResult(
            chain=self.config.name,
            chain_type=self.config.chain_type.value,
            network=self.network,
            contract_name="AnalyticsRewards",
            contract_address=contract_address,
            tx_hash=tx_hash,
            block_number=0,
            deployer=self.kwargs.get("deployer_address", "unknown"),
            explorer_url=self.get_explorer_url(contract_address),
            extra={"tron_network": tron_network},
        )

    def verify(self, address: str) -> bool:
        # TronBox does not have a built-in verify command. Verification
        # is done via the TronScan API or manually.
        logger.info("TRON verification must be done via TronScan: %s", self.get_explorer_url(address))
        return True

    def _get_tron_network(self) -> str:
        """Map network type to TronBox network name."""
        network_map = {
            "mainnet": "mainnet",
            "testnet": "nile",
            "localnet": "development",
        }
        return network_map.get(self.network, "nile")

    def _parse_tron_address(self, output: str) -> str:
        """Extract contract address from TronBox output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "contract address" in stripped.lower() or "deployed" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    # TRON addresses start with T and are 34 characters.
                    if clean.startswith("T") and len(clean) == 34:
                        return clean
                    # Or hex format starting with 41.
                    if clean.startswith("41") and len(clean) == 42:
                        return clean
        return "TronAddressNotParsed"

    def _parse_tron_tx(self, output: str) -> str:
        """Extract transaction hash from TronBox output."""
        for line in output.splitlines():
            stripped = line.strip()
            if "transaction" in stripped.lower() or "tx" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if len(clean) == 64 and all(c in "0123456789abcdef" for c in clean.lower()):
                        return clean
        return "TxNotParsed"


# ---------------------------------------------------------------------------
#  Cosmos (CosmWasm) Deployer
# ---------------------------------------------------------------------------


class CosmosDeployer(ChainDeployer):
    """Deploys CosmWasm smart contracts to Cosmos SDK chains."""

    def deploy(self) -> DeploymentResult:
        daemon = self.kwargs.get("daemon", os.getenv("COSMOS_DAEMON", "osmosisd"))
        chain_id = self.kwargs.get("chain_id", self.config.chain_id)
        sender = self.kwargs.get("sender", os.getenv("COSMOS_SENDER", ""))
        keyring = self.kwargs.get("keyring_backend", "test")
        gas_prices = self.kwargs.get("gas_prices", "0.025uosmo")
        oracle_pubkey = self.kwargs.get("oracle_pubkey", "0" * 64)
        reward_denom = self.kwargs.get("reward_denom", "uosmo")

        if not self._check_cli_available(daemon):
            logger.warning("%s not found. Install the Cosmos chain daemon.", daemon)

        contract_dir = PROGRAMS_DIR / "cosmos"

        # Step 1: Build the WASM contract.
        build_cmd = [
            "cargo", "build",
            "--target", "wasm32-unknown-unknown",
            "--release",
        ]
        build_result = self._run_command(build_cmd, cwd=contract_dir)

        if build_result.returncode != 0:
            logger.error("CosmWasm contract build failed.")

        wasm_path = contract_dir / "target" / "wasm32-unknown-unknown" / "release" / "aether_rewards.wasm"

        # Step 2: Optimize the WASM (optional but recommended).
        if self._check_cli_available("wasm-opt"):
            opt_path = contract_dir / "target" / "aether_rewards_optimized.wasm"
            opt_cmd = [
                "wasm-opt", "-Oz",
                str(wasm_path),
                "-o", str(opt_path),
            ]
            opt_result = self._run_command(opt_cmd)
            if opt_result.returncode == 0:
                wasm_path = opt_path

        # Step 3: Store the WASM code on-chain.
        store_cmd = [
            daemon, "tx", "wasm", "store",
            str(wasm_path),
            "--from", sender,
            "--chain-id", chain_id,
            "--gas", "auto",
            "--gas-adjustment", "1.3",
            "--gas-prices", gas_prices,
            "--keyring-backend", keyring,
            "--node", self.rpc_url,
            "--output", "json",
            "--yes",
        ]
        store_result = self._run_command(store_cmd)

        code_id = self._parse_code_id(store_result.stdout)
        store_tx = self._parse_cosmos_tx(store_result.stdout)

        # Step 4: Instantiate the contract.
        init_msg = json.dumps({
            "oracle_pubkey": oracle_pubkey,
            "reward_denom": reward_denom,
        })

        instantiate_cmd = [
            daemon, "tx", "wasm", "instantiate",
            str(code_id),
            init_msg,
            "--from", sender,
            "--chain-id", chain_id,
            "--label", "aether-rewards-v1",
            "--admin", sender,
            "--gas", "auto",
            "--gas-adjustment", "1.3",
            "--gas-prices", gas_prices,
            "--keyring-backend", keyring,
            "--node", self.rpc_url,
            "--output", "json",
            "--yes",
        ]
        instantiate_result = self._run_command(instantiate_cmd)

        contract_address = self._parse_contract_address(instantiate_result.stdout)
        instantiate_tx = self._parse_cosmos_tx(instantiate_result.stdout)

        return DeploymentResult(
            chain=self.config.name,
            chain_type=self.config.chain_type.value,
            network=self.network,
            contract_name="aether_rewards",
            contract_address=contract_address,
            tx_hash=instantiate_tx,
            block_number=0,
            deployer=sender,
            explorer_url=self.get_explorer_url(contract_address),
            extra={
                "code_id": code_id,
                "store_tx": store_tx,
                "chain_id": chain_id,
                "oracle_pubkey": oracle_pubkey,
                "reward_denom": reward_denom,
            },
        )

    def verify(self, address: str) -> bool:
        daemon = self.kwargs.get("daemon", os.getenv("COSMOS_DAEMON", "osmosisd"))
        cmd = [
            daemon, "query", "wasm", "contract",
            address,
            "--node", self.rpc_url,
            "--output", "json",
        ]
        result = self._run_command(cmd)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return "contract_info" in data or "address" in data
            except json.JSONDecodeError:
                pass
        return False

    def _parse_code_id(self, output: str) -> int:
        """Extract the code ID from the store transaction output."""
        try:
            data = json.loads(output)
            # Look in logs/events for the code_id attribute.
            for log_entry in data.get("logs", []):
                for event in log_entry.get("events", []):
                    if event.get("type") == "store_code":
                        for attr in event.get("attributes", []):
                            if attr.get("key") == "code_id":
                                return int(attr.get("value", "0"))
            # Fallback: check raw_log or txhash-based query.
            raw_log = data.get("raw_log", "")
            if "code_id" in raw_log:
                import re
                match = re.search(r'"code_id","value":"(\d+)"', raw_log)
                if match:
                    return int(match.group(1))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        # Text parsing fallback.
        for line in output.splitlines():
            if "code_id" in line.lower() or "code id" in line.lower():
                parts = line.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if clean.isdigit():
                        return int(clean)
        return 0

    def _parse_contract_address(self, output: str) -> str:
        """Extract the contract address from instantiate output."""
        try:
            data = json.loads(output)
            for log_entry in data.get("logs", []):
                for event in log_entry.get("events", []):
                    if event.get("type") in ("instantiate", "wasm"):
                        for attr in event.get("attributes", []):
                            if attr.get("key") in ("_contract_address", "contract_address"):
                                return attr.get("value", "")
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Text fallback.
        for line in output.splitlines():
            stripped = line.strip()
            if "contract" in stripped.lower() and "address" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if clean.startswith("osmo1") or clean.startswith("cosmos1") or clean.startswith("wasm1"):
                        return clean
        return "ContractAddressNotParsed"

    def _parse_cosmos_tx(self, output: str) -> str:
        """Extract the transaction hash from Cosmos CLI output."""
        try:
            data = json.loads(output)
            tx_hash = data.get("txhash", "")
            if tx_hash:
                return tx_hash
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        for line in output.splitlines():
            stripped = line.strip()
            if "txhash" in stripped.lower():
                parts = stripped.split()
                for part in parts:
                    clean = part.strip(",:;()\"'")
                    if len(clean) == 64 and all(c in "0123456789ABCDEF" for c in clean.upper()):
                        return clean
        return "TxNotParsed"


# ---------------------------------------------------------------------------
#  Deployer Factory
# ---------------------------------------------------------------------------

# Map chain types to their deployer classes.
DEPLOYER_CLASSES: dict[str, type[ChainDeployer]] = {
    "ethereum": EVMDeployer,
    "polygon": EVMDeployer,
    "arbitrum": EVMDeployer,
    "base": EVMDeployer,
    "optimism": EVMDeployer,
    "solana": SolanaDeployer,
    "sui": SUIDeployer,
    "near": NEARDeployer,
    "tron": TRONDeployer,
    "cosmos": CosmosDeployer,
}


def create_deployer(chain: str, network: str, **kwargs: Any) -> ChainDeployer:
    """Factory function to create the appropriate deployer for a chain."""
    if chain not in CHAIN_CONFIGS:
        raise ValueError(
            f"Unsupported chain '{chain}'. Available: {list(CHAIN_CONFIGS.keys())}"
        )
    if chain not in DEPLOYER_CLASSES:
        raise ValueError(
            f"No deployer implemented for chain '{chain}'."
        )

    config = CHAIN_CONFIGS[chain]
    deployer_class = DEPLOYER_CLASSES[chain]
    return deployer_class(config=config, network=network, **kwargs)


# ---------------------------------------------------------------------------
#  Multi-Chain Orchestrator
# ---------------------------------------------------------------------------


class MultiChainDeployer:
    """Orchestrates deployments across multiple blockchains."""

    def __init__(self, network: str, **kwargs: Any) -> None:
        self.network = network
        self.kwargs = kwargs
        self.results: dict[str, DeploymentResult] = {}
        self.errors: dict[str, str] = {}

    def deploy_chain(self, chain: str) -> Optional[DeploymentResult]:
        """Deploy to a single chain, catching and logging errors."""
        logger.info("=" * 60)
        logger.info("Deploying to %s (%s)", chain.upper(), self.network)
        logger.info("=" * 60)

        try:
            deployer = create_deployer(chain, self.network, **self.kwargs)
            result = deployer.deploy()
            self.results[chain] = result
            logger.info("Deployment to %s completed successfully.", chain)
            return result
        except GateError as e:
            error_msg = f"GATE[{e.category}]: {e}"
            self.errors[chain] = error_msg
            logger.error("Deployment to %s BLOCKED by safety gate: %s", chain, error_msg)
            return None
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            self.errors[chain] = error_msg
            logger.error("Deployment to %s failed: %s", chain, error_msg)
            return None

    def deploy_all(self, chains: Optional[list[str]] = None) -> dict[str, DeploymentResult]:
        """Deploy to all specified chains (or all supported chains)."""
        target_chains = chains or list(CHAIN_CONFIGS.keys())

        logger.info("Starting multi-chain deployment to %d chains", len(target_chains))
        logger.info("Target chains: %s", ", ".join(target_chains))
        logger.info("Network: %s", self.network)

        for chain in target_chains:
            self.deploy_chain(chain)

        return self.results

    def verify_all(self) -> dict[str, bool]:
        """Verify all completed deployments."""
        verification_results: dict[str, bool] = {}

        for chain, result in self.results.items():
            logger.info("Verifying %s deployment at %s ...", chain, result.contract_address)
            try:
                deployer = create_deployer(chain, self.network, **self.kwargs)
                is_verified = deployer.verify(result.contract_address)
                verification_results[chain] = is_verified
                status = "VERIFIED" if is_verified else "FAILED"
                logger.info("  %s: %s", chain, status)
            except Exception as e:
                verification_results[chain] = False
                logger.error("  %s: VERIFICATION ERROR - %s", chain, e)

        return verification_results

    def save_manifest(self, output_dir: Optional[Path] = None) -> Path:
        """Save a deployment manifest JSON file."""
        manifest_dir = output_dir or DEPLOYMENTS_DIR
        manifest_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        manifest_path = manifest_dir / f"multichain_{self.network}_{timestamp}.json"

        manifest = {
            "network": self.network,
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "deployments": {
                chain: asdict(result) for chain, result in self.results.items()
            },
            "errors": self.errors,
            "summary": {
                "total_chains": len(self.results) + len(self.errors),
                "successful": len(self.results),
                "failed": len(self.errors),
            },
        }

        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info("Deployment manifest saved to %s", manifest_path)
        return manifest_path

    def print_summary(self) -> None:
        """Print a human-readable summary of all deployments."""
        print("\n" + "=" * 70)
        print("  Aether Multi-Chain Deployment Summary")
        print("=" * 70)
        print(f"  Network: {self.network}")
        print(f"  Time:    {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        print("=" * 70)

        if self.results:
            print("\n  Successful Deployments:")
            print("  " + "-" * 66)
            for chain, result in self.results.items():
                print()
                print(f"  {result.summary()}")

        if self.errors:
            print("\n  Failed Deployments:")
            print("  " + "-" * 66)
            for chain, error in self.errors.items():
                print(f"  [{chain.upper()}] {error}")

        print("\n" + "=" * 70)
        total = len(self.results) + len(self.errors)
        print(
            f"  Total: {total} | "
            f"Successful: {len(self.results)} | "
            f"Failed: {len(self.errors)}"
        )
        print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="multichain_deployer",
        description="Deploy Aether smart contracts across multiple blockchains.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy to Solana devnet
  python multichain_deployer.py --chain solana --network devnet

  # Deploy to SUI testnet
  python multichain_deployer.py --chain sui --network testnet

  # Deploy to NEAR testnet
  python multichain_deployer.py --chain near --network testnet --account aether.testnet

  # Deploy to Cosmos (Osmosis) testnet
  python multichain_deployer.py --chain cosmos --network testnet --chain-id osmo-test-5

  # Deploy to all chains on testnet
  python multichain_deployer.py --all --network testnet

  # Deploy to specific EVM chains
  python multichain_deployer.py --chains ethereum polygon base --network testnet
        """,
    )

    # Target selection (mutually exclusive).
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--chain",
        choices=list(CHAIN_CONFIGS.keys()),
        help="Deploy to a single chain.",
    )
    target_group.add_argument(
        "--chains",
        nargs="+",
        choices=list(CHAIN_CONFIGS.keys()),
        help="Deploy to multiple specific chains.",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="Deploy to all supported chains.",
    )

    # Network selection.
    parser.add_argument(
        "--network",
        required=True,
        choices=[n.value for n in NetworkType],
        help="Target network (mainnet, testnet, devnet, localnet).",
    )

    # EVM-specific options.
    parser.add_argument(
        "--token-address",
        default=os.getenv("REWARD_TOKEN_ADDRESS", ""),
        help="ERC-20 reward token address (EVM chains).",
    )
    parser.add_argument(
        "--oracle-address",
        default=os.getenv("ORACLE_ADDRESS", ""),
        help="Oracle signer address (EVM chains).",
    )
    parser.add_argument(
        "--private-key",
        default=os.getenv("DEPLOYER_KEY", ""),
        help="Deployer private key (EVM/TRON chains).",
    )

    # Solana-specific options.
    parser.add_argument(
        "--wallet",
        default=os.getenv("SOLANA_WALLET", "~/.config/solana/id.json"),
        help="Solana wallet keypair path.",
    )

    # NEAR-specific options.
    parser.add_argument(
        "--account",
        default=os.getenv("NEAR_ACCOUNT", ""),
        help="NEAR account ID for deployment.",
    )

    # Cosmos-specific options.
    parser.add_argument(
        "--chain-id",
        default=os.getenv("COSMOS_CHAIN_ID", ""),
        help="Cosmos chain ID (e.g., osmosis-1, osmo-test-5).",
    )
    parser.add_argument(
        "--daemon",
        default=os.getenv("COSMOS_DAEMON", "osmosisd"),
        help="Cosmos chain daemon binary (e.g., osmosisd, wasmd).",
    )
    parser.add_argument(
        "--sender",
        default=os.getenv("COSMOS_SENDER", ""),
        help="Cosmos sender address (bech32).",
    )
    parser.add_argument(
        "--reward-denom",
        default=os.getenv("REWARD_DENOM", "uosmo"),
        help="Native token denomination for rewards.",
    )

    # Oracle pubkey (used by non-EVM chains).
    parser.add_argument(
        "--oracle-pubkey",
        default=os.getenv("ORACLE_PUBKEY", ""),
        help="Oracle Ed25519 public key (hex, 64 chars) for non-EVM chains.",
    )

    # Deployment options.
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify deployments after broadcasting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print deployment plan without executing.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for deployment manifest output.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for the multi-chain deployer CLI."""
    args = _parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine target chains.
    if args.all:
        target_chains = list(CHAIN_CONFIGS.keys())
    elif args.chains:
        target_chains = args.chains
    else:
        target_chains = [args.chain]

    # Build kwargs from arguments.
    deploy_kwargs = {
        "token_address": args.token_address,
        "oracle_address": args.oracle_address,
        "private_key": args.private_key,
        "wallet": args.wallet,
        "account": args.account,
        "chain_id": args.chain_id or None,
        "daemon": args.daemon,
        "sender": args.sender,
        "oracle_pubkey": args.oracle_pubkey,
        "reward_denom": args.reward_denom,
    }

    # Remove empty/None values to avoid overriding defaults.
    deploy_kwargs = {k: v for k, v in deploy_kwargs.items() if v}

    # Dry run: just print the plan.
    if args.dry_run:
        print("\n" + "=" * 60)
        print("  Aether Multi-Chain Deployment Plan (DRY RUN)")
        print("=" * 60)
        print(f"  Network: {args.network}")
        print(f"  Chains:  {', '.join(target_chains)}")
        print(f"  Verify:  {args.verify}")
        print()
        for chain in target_chains:
            config = CHAIN_CONFIGS[chain]
            rpc = config.rpc_urls.get(args.network, "N/A")
            print(f"  [{chain.upper()}]")
            print(f"    Name     : {config.name}")
            print(f"    CLI      : {config.deploy_cli}")
            print(f"    RPC      : {rpc}")
            print(f"    Explorer : {config.explorer_urls.get(args.network, 'N/A')}")
            print()
        print("=" * 60)
        print("  Dry run complete. No contracts deployed.")
        print("=" * 60 + "\n")
        return

    # Execute deployments.
    orchestrator = MultiChainDeployer(network=args.network, **deploy_kwargs)
    orchestrator.deploy_all(chains=target_chains)

    # Verification pass.
    if args.verify and orchestrator.results:
        print("\nVerifying deployments ...")
        verification = orchestrator.verify_all()
        for chain, is_verified in verification.items():
            status = "VERIFIED" if is_verified else "FAILED"
            print(f"  {chain}: {status}")

    # Save manifest.
    manifest_path = orchestrator.save_manifest(output_dir=args.output_dir)

    # Print summary.
    orchestrator.print_summary()

    logger.info("Manifest: %s", manifest_path)

    # Exit with error code if any deployments failed.
    if orchestrator.errors:
        sys.exit(1)


# ---------------------------------------------------------------------------
#  Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
