"""
Aether — Multi-VM Chain Monitor Agent v2
Enhanced chain monitor for tracking wallet activity across all supported VMs.

Supports: EVM (13 chains), Solana, Bitcoin, SUI, NEAR, TRON, Cosmos/SEI
Features: Block scanning, whale detection, DeFi protocol identification,
          cross-VM correlation, token price feeds
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("aether.chain_monitor_v2")


# ---------------------------------------------------------------------------
# VM Configuration
# ---------------------------------------------------------------------------

class VMType(str, Enum):
    EVM = "evm"
    SVM = "svm"
    BITCOIN = "bitcoin"
    MOVEVM = "movevm"
    NEAR = "near"
    TVM = "tvm"
    COSMOS = "cosmos"


@dataclass
class ChainMonitorConfig:
    """Configuration for multi-VM chain monitoring."""
    # Enabled VMs
    enabled_vms: list[VMType] = field(default_factory=lambda: [VMType.EVM, VMType.SVM])

    # EVM chains to monitor (by chainId)
    evm_chains: list[int] = field(default_factory=lambda: [1, 137, 42161, 10, 8453, 56])

    # Polling intervals (seconds)
    evm_poll_interval: int = 12
    svm_poll_interval: int = 2
    btc_poll_interval: int = 60
    move_poll_interval: int = 3
    near_poll_interval: int = 2
    tron_poll_interval: int = 3
    cosmos_poll_interval: int = 6

    # Whale thresholds
    whale_threshold_eth: float = 100.0
    whale_threshold_sol: float = 10000.0
    whale_threshold_btc: float = 10.0
    whale_threshold_sui: float = 100000.0
    whale_threshold_near: float = 100000.0
    whale_threshold_trx: float = 10000000.0

    # Max tracked addresses per VM
    max_tracked_addresses: int = 10000

    # Alert callbacks
    on_whale_alert: Optional[Callable] = None
    on_defi_interaction: Optional[Callable] = None
    on_bridge_detection: Optional[Callable] = None
    on_cex_flow: Optional[Callable] = None


# ---------------------------------------------------------------------------
# Chain Monitor Agent
# ---------------------------------------------------------------------------

class ChainMonitorV2:
    """
    Multi-VM chain monitoring agent.

    Responsibilities:
    - Scan blocks/slots for tracked address activity
    - Detect whale transactions across all VMs
    - Identify DeFi protocol interactions
    - Track bridge transfers across chains
    - Monitor CEX deposit/withdrawal flows
    - Correlate activity across VMs for the same user
    """

    def __init__(self, config: ChainMonitorConfig):
        self.config = config
        self.tracked_addresses: dict[VMType, set[str]] = {vm: set() for vm in VMType}
        self.running = False
        self._tasks: list[asyncio.Task] = []

    def track_address(self, address: str, vm: VMType) -> None:
        """Add an address to the monitoring set."""
        if len(self.tracked_addresses[vm]) < self.config.max_tracked_addresses:
            normalized = address.lower() if vm in (VMType.EVM, VMType.MOVEVM, VMType.COSMOS) else address
            self.tracked_addresses[vm].add(normalized)
            logger.info(f"Tracking {vm.value} address: {normalized[:12]}...")

    def untrack_address(self, address: str, vm: VMType) -> None:
        """Remove an address from the monitoring set."""
        normalized = address.lower() if vm in (VMType.EVM, VMType.MOVEVM, VMType.COSMOS) else address
        self.tracked_addresses[vm].discard(normalized)

    async def start(self) -> None:
        """Start monitoring all enabled VMs."""
        self.running = True
        logger.info(f"Chain Monitor v2 starting — VMs: {[v.value for v in self.config.enabled_vms]}")

        for vm in self.config.enabled_vms:
            task = asyncio.create_task(self._monitor_vm(vm))
            self._tasks.append(task)

        # Cross-VM correlation task
        self._tasks.append(asyncio.create_task(self._cross_vm_correlation()))

    async def stop(self) -> None:
        """Stop all monitoring tasks."""
        self.running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("Chain Monitor v2 stopped")

    # -----------------------------------------------------------------------
    # VM-specific monitoring loops
    # -----------------------------------------------------------------------

    async def _monitor_vm(self, vm: VMType) -> None:
        """Generic VM monitoring loop."""
        intervals = {
            VMType.EVM: self.config.evm_poll_interval,
            VMType.SVM: self.config.svm_poll_interval,
            VMType.BITCOIN: self.config.btc_poll_interval,
            VMType.MOVEVM: self.config.move_poll_interval,
            VMType.NEAR: self.config.near_poll_interval,
            VMType.TVM: self.config.tron_poll_interval,
            VMType.COSMOS: self.config.cosmos_poll_interval,
        }
        interval = intervals.get(vm, 10)

        while self.running:
            try:
                await self._scan_vm(vm)
            except Exception as e:
                logger.error(f"Error scanning {vm.value}: {e}")
            await asyncio.sleep(interval)

    async def _scan_vm(self, vm: VMType) -> None:
        """Scan for new activity on a specific VM."""
        tracked = self.tracked_addresses.get(vm, set())
        if not tracked:
            return

        scanners = {
            VMType.EVM: self._scan_evm,
            VMType.SVM: self._scan_svm,
            VMType.BITCOIN: self._scan_bitcoin,
            VMType.MOVEVM: self._scan_sui,
            VMType.NEAR: self._scan_near,
            VMType.TVM: self._scan_tron,
            VMType.COSMOS: self._scan_cosmos,
        }
        scanner = scanners.get(vm)
        if scanner is not None:
            await scanner(tracked)

    async def _scan_evm(self, addresses: set[str]) -> None:
        """Scan EVM chains for tracked address activity."""
        for chain_id in self.config.evm_chains:
            # In production: use eth_getBlockByNumber + filter for tracked addresses
            # Check transaction logs for DeFi protocol interactions
            # Detect whale transfers above threshold
            pass

    async def _scan_svm(self, addresses: set[str]) -> None:
        """Scan Solana for tracked address activity."""
        # Use getSignaturesForAddress for each tracked address
        # Parse transaction instructions for program interactions
        # Detect Jupiter/Raydium/Marinade/Drift interactions
        pass

    async def _scan_bitcoin(self, addresses: set[str]) -> None:
        """Scan Bitcoin mempool and blocks for tracked addresses."""
        # Use mempool.space API for address activity
        # Detect large UTXO movements (whale detection)
        # Track inscription/ordinal activity
        pass

    async def _scan_sui(self, addresses: set[str]) -> None:
        """Scan SUI for tracked address activity."""
        # Use suix_queryTransactionBlocks for address queries
        # Detect Move call interactions with known protocols
        pass

    async def _scan_near(self, addresses: set[str]) -> None:
        """Scan NEAR for tracked account activity."""
        # Use NEAR Indexer for account activity
        # Detect FunctionCall actions to known DeFi contracts
        pass

    async def _scan_tron(self, addresses: set[str]) -> None:
        """Scan TRON for tracked address activity."""
        # Use TronGrid API for account transactions
        # Monitor TRC-20 token transfers
        pass

    async def _scan_cosmos(self, addresses: set[str]) -> None:
        """Scan Cosmos/SEI for tracked address activity."""
        # Use REST API for tx search by sender
        # Detect IBC transfers, staking, governance
        pass

    # -----------------------------------------------------------------------
    # Cross-VM correlation
    # -----------------------------------------------------------------------

    async def _cross_vm_correlation(self) -> None:
        """
        Correlate activity across VMs for the same user.
        Detects patterns like:
        - Withdraw from CEX on EVM → Bridge to Solana → Swap on Jupiter
        - Stake ETH on Lido → Bridge stETH to Arbitrum → Supply on AAVE
        """
        while self.running:
            try:
                # Check for users active on multiple VMs
                multi_vm_users = self._find_multi_vm_users()
                if multi_vm_users:
                    logger.info(f"Cross-VM users detected: {len(multi_vm_users)}")
            except Exception as e:
                logger.error(f"Cross-VM correlation error: {e}")
            await asyncio.sleep(60)  # Run every minute

    def _find_multi_vm_users(self) -> list[str]:
        """Find users with tracked addresses on multiple VMs."""
        # In production: query identity service for users with wallets on 2+ VMs
        return []

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def get_status(self) -> dict:
        """Get current monitor status."""
        return {
            "running": self.running,
            "enabled_vms": [v.value for v in self.config.enabled_vms],
            "tracked_addresses": {v.value: len(addrs) for v, addrs in self.tracked_addresses.items()},
            "active_tasks": len(self._tasks),
        }
