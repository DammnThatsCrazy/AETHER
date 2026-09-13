"""
Aether Agent Layer — Chain Monitor Discovery Worker
Monitors on-chain activity for tracked wallet addresses and contracts.

Capabilities:
  - Watch wallet addresses for inbound/outbound transfers
  - Monitor smart-contract events (ERC-20 Transfer, ERC-721, etc.)
  - Detect large / unusual transactions (whale alerts)
  - Track token balances and DeFi positions
  - Multi-chain support (Ethereum, Polygon, Arbitrum, Base)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.chain_monitor")

# Supported chains and their block explorer API sources
_CHAIN_SOURCES: dict[str, str] = {
    "ethereum": "etherscan",
    "polygon": "polygonscan",
    "arbitrum": "arbiscan",
    "base": "basescan",
}

# Block explorer API base URLs
_EXPLORER_APIS: dict[str, str] = {
    "etherscan": "https://api.etherscan.io/api",
    "polygonscan": "https://api.polygonscan.com/api",
    "arbiscan": "https://api.arbiscan.io/api",
    "basescan": "https://api.basescan.org/api",
}

# Public JSON-RPC endpoints (fallbacks, rate-limited)
_PUBLIC_RPC: dict[str, str] = {
    "ethereum": "https://eth.llamarpc.com",
    "polygon": "https://polygon-rpc.com",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "base": "https://mainnet.base.org",
}

# Environment variable names for explorer API keys
_API_KEY_ENV: dict[str, str] = {
    "etherscan": "ETHERSCAN_API_KEY",
    "polygonscan": "POLYGONSCAN_API_KEY",
    "arbiscan": "ARBISCAN_API_KEY",
    "basescan": "BASESCAN_API_KEY",
}

# HTTP timeout
_HTTP_TIMEOUT = 30

# Approximate ETH price for whale alert thresholds (production: use a price feed)
_ETH_PRICE_USD_FALLBACK = 3000.0


class ChainMonitorWorker(BaseWorker):
    """
    Discovery worker for on-chain activity monitoring.

    Payload contract:
        entity_id       : str        -- graph entity being tracked
        addresses       : list[str]  -- wallet / contract addresses to watch
        chains          : list[str]  -- e.g. ["ethereum", "polygon"]
        event_types     : list[str]  -- filter: ["transfer", "swap", "mint", "all"]
        min_value_usd   : float      -- ignore txns below this threshold
        since_block     : int | None -- start block (None = last 1000 blocks)
    """

    worker_type = WorkerType.CHAIN_MONITOR
    data_source = "etherscan"

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        addresses = task.payload.get("addresses", [])
        chains = task.payload.get("chains", ["ethereum"])
        event_types = task.payload.get("event_types", ["all"])
        min_value = task.payload.get("min_value_usd", 0.0)
        since_block = task.payload.get("since_block")

        if not addresses:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error="No addresses provided in payload",
                confidence=0.0,
            )

        logger.info(
            f"Monitoring {len(addresses)} address(es) on {chains} "
            f"(entity={entity_id}, min_value=${min_value})"
        )

        transactions: list[dict[str, Any]] = []
        token_balances: list[dict[str, Any]] = []
        chain_errors: dict[str, str] = {}
        chains_succeeded = 0

        for chain in chains:
            source = _CHAIN_SOURCES.get(chain, chain)
            explorer_url = _EXPLORER_APIS.get(source)
            rpc_url = _PUBLIC_RPC.get(chain)
            api_key = os.environ.get(_API_KEY_ENV.get(source, ""), "")

            if not explorer_url and not rpc_url:
                chain_errors[chain] = f"No API endpoint configured for chain: {chain}"
                continue

            chain_had_success = False

            for addr in addresses:
                # --- Fetch transactions via block explorer API ----------------
                if explorer_url:
                    txns = self._fetch_transactions_explorer(
                        explorer_url, api_key, addr, chain, source,
                        since_block, min_value, event_types,
                    )
                    if txns is not None:
                        transactions.extend(txns)
                        chain_had_success = True

                # --- Fetch native balance via JSON-RPC -----------------------
                if rpc_url:
                    balance_info = self._fetch_balance_rpc(
                        rpc_url, addr, chain
                    )
                    if balance_info is not None:
                        token_balances.append(balance_info)
                        chain_had_success = True

                # --- Fetch ERC-20 token transfers via explorer ---------------
                if explorer_url and ("transfer" in event_types or "all" in event_types):
                    token_txns = self._fetch_token_transfers(
                        explorer_url, api_key, addr, chain, source, min_value,
                    )
                    if token_txns is not None:
                        transactions.extend(token_txns)

            if chain_had_success:
                chains_succeeded += 1

        # Filter transactions by min_value_usd
        if min_value > 0:
            transactions = [
                tx for tx in transactions
                if tx.get("value_usd", 0.0) >= min_value
            ]

        # Detect whale alerts (transactions >= $100k)
        whale_alerts = [
            tx for tx in transactions if tx.get("value_usd", 0.0) >= 100_000
        ]

        data: dict[str, Any] = {
            "entity_id": entity_id,
            "transactions": transactions,
            "transaction_count": len(transactions),
            "token_balances": token_balances,
            "whale_alerts": whale_alerts,
            "whale_alert_count": len(whale_alerts),
            "chains_scanned": chains,
            "chains_succeeded": chains_succeeded,
            "addresses_monitored": len(addresses),
            "chain_errors": chain_errors if chain_errors else None,
        }

        # On-chain data is inherently reliable when we get it
        if chains_succeeded == 0:
            confidence = 0.1
        else:
            base = chains_succeeded / len(chains)
            # On-chain data is highly reliable
            confidence = base * 0.5 + 0.45
            if transactions:
                confidence += 0.05
            confidence = max(0.0, min(1.0, round(confidence, 4)))

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=chains_succeeded > 0,
            data=data,
            confidence=confidence,
            source_attribution=", ".join(
                _CHAIN_SOURCES.get(c, c) for c in chains
            ),
            error=(
                f"Chain errors: {chain_errors}"
                if chain_errors and chains_succeeded == 0
                else None
            ),
        )

    # ------------------------------------------------------------------
    # Block explorer API helpers
    # ------------------------------------------------------------------

    def _fetch_transactions_explorer(
        self,
        explorer_url: str,
        api_key: str,
        address: str,
        chain: str,
        source: str,
        since_block: int | None,
        min_value: float,
        event_types: list[str],
    ) -> list[dict[str, Any]] | None:
        """
        Fetch normal transactions for an address using Etherscan-compatible API.
        """
        params: dict[str, Any] = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": since_block if since_block else 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 50,  # last 50 transactions
            "sort": "desc",
        }
        if api_key:
            params["apikey"] = api_key

        try:
            resp = httpx.get(
                explorer_url,
                params=params,
                timeout=_HTTP_TIMEOUT,
            )

            if resp.status_code != 200:
                logger.warning(
                    f"{source} returned {resp.status_code} for {address}"
                )
                return None

            body = resp.json()
            status = body.get("status", "0")
            result = body.get("result", [])

            if status != "1" or not isinstance(result, list):
                message = body.get("message", "Unknown error")
                logger.debug(
                    f"{source} query status={status} for {address}: {message}"
                )
                # status "0" with "No transactions found" is not an error
                if "No transactions found" in str(message):
                    return []
                return None

            transactions: list[dict[str, Any]] = []
            for tx in result:
                # Convert value from Wei to ETH
                value_wei = int(tx.get("value", "0"))
                value_eth = value_wei / 1e18
                value_usd = value_eth * _ETH_PRICE_USD_FALLBACK

                # Determine event type
                tx_input = tx.get("input", "0x")
                if tx_input == "0x" or tx_input == "":
                    event_type = "transfer"
                elif tx_input[:10] == "0xa9059cbb":
                    event_type = "transfer"  # ERC-20 transfer
                elif tx_input[:10] == "0x095ea7b3":
                    event_type = "approval"
                else:
                    event_type = "contract_call"

                # Filter by event type if specified
                if "all" not in event_types and event_type not in event_types:
                    continue

                timestamp_unix = int(tx.get("timeStamp", "0"))
                timestamp = datetime.fromtimestamp(
                    timestamp_unix, tz=timezone.utc
                ).isoformat() if timestamp_unix else ""

                transactions.append({
                    "chain": chain,
                    "address": address,
                    "tx_hash": tx.get("hash", ""),
                    "block_number": int(tx.get("blockNumber", 0)),
                    "from": tx.get("from", ""),
                    "to": tx.get("to", ""),
                    "value_eth": str(round(value_eth, 8)),
                    "value_usd": round(value_usd, 2),
                    "gas_used": int(tx.get("gasUsed", 0)),
                    "gas_price_gwei": round(
                        int(tx.get("gasPrice", 0)) / 1e9, 4
                    ),
                    "event_type": event_type,
                    "timestamp": timestamp,
                    "source": source,
                    "is_error": tx.get("isError", "0") == "1",
                })

            return transactions

        except httpx.TimeoutException:
            logger.warning(f"{source} request timed out for {address}")
            return None
        except httpx.RequestError as exc:
            logger.warning(f"{source} request failed for {address}: {exc}")
            return None
        except (ValueError, KeyError) as exc:
            logger.warning(f"Error parsing {source} response: {exc}")
            return None

    def _fetch_balance_rpc(
        self,
        rpc_url: str,
        address: str,
        chain: str,
    ) -> dict[str, Any] | None:
        """
        Fetch native token balance using JSON-RPC eth_getBalance.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [address, "latest"],
            "id": 1,
        }

        try:
            resp = httpx.post(
                rpc_url,
                json=payload,
                timeout=_HTTP_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code != 200:
                logger.warning(
                    f"RPC {chain} returned {resp.status_code} for balance query"
                )
                return None

            body = resp.json()
            result_hex = body.get("result", "0x0")

            if result_hex is None or body.get("error"):
                error_msg = body.get("error", {}).get("message", "Unknown RPC error")
                logger.warning(f"RPC error for {address} on {chain}: {error_msg}")
                return None

            # Convert hex Wei to ETH
            balance_wei = int(result_hex, 16)
            balance_eth = balance_wei / 1e18

            # Also fetch latest block number for context
            block_number = self._fetch_block_number_rpc(rpc_url, chain)

            return {
                "chain": chain,
                "address": address,
                "native_balance_wei": str(balance_wei),
                "native_balance_eth": str(round(balance_eth, 8)),
                "native_balance_usd": round(
                    balance_eth * _ETH_PRICE_USD_FALLBACK, 2
                ),
                "latest_block": block_number,
                "queried_at": datetime.now(timezone.utc).isoformat(),
            }

        except httpx.TimeoutException:
            logger.warning(f"RPC {chain} balance request timed out for {address}")
            return None
        except httpx.RequestError as exc:
            logger.warning(f"RPC {chain} balance request failed: {exc}")
            return None
        except (ValueError, KeyError) as exc:
            logger.warning(f"Error parsing RPC balance response: {exc}")
            return None

    def _fetch_block_number_rpc(
        self, rpc_url: str, chain: str
    ) -> int | None:
        """Fetch the latest block number via JSON-RPC."""
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 2,
        }

        try:
            resp = httpx.post(
                rpc_url,
                json=payload,
                timeout=_HTTP_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                body = resp.json()
                result_hex = body.get("result", "0x0")
                if result_hex and not body.get("error"):
                    return int(result_hex, 16)
        except (httpx.TimeoutException, httpx.RequestError, ValueError):
            pass

        return None

    def _fetch_token_transfers(
        self,
        explorer_url: str,
        api_key: str,
        address: str,
        chain: str,
        source: str,
        min_value: float,
    ) -> list[dict[str, Any]] | None:
        """
        Fetch ERC-20 token transfers for an address via Etherscan-compatible API.
        """
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "page": 1,
            "offset": 50,
            "sort": "desc",
        }
        if api_key:
            params["apikey"] = api_key

        try:
            resp = httpx.get(
                explorer_url,
                params=params,
                timeout=_HTTP_TIMEOUT,
            )

            if resp.status_code != 200:
                return None

            body = resp.json()
            status = body.get("status", "0")
            result = body.get("result", [])

            if status != "1" or not isinstance(result, list):
                return []

            token_txns: list[dict[str, Any]] = []
            for tx in result:
                token_decimal = int(tx.get("tokenDecimal", "18") or "18")
                value_raw = int(tx.get("value", "0"))
                value_token = value_raw / (10 ** token_decimal)

                timestamp_unix = int(tx.get("timeStamp", "0"))
                timestamp = datetime.fromtimestamp(
                    timestamp_unix, tz=timezone.utc
                ).isoformat() if timestamp_unix else ""

                token_txns.append({
                    "chain": chain,
                    "address": address,
                    "tx_hash": tx.get("hash", ""),
                    "block_number": int(tx.get("blockNumber", 0)),
                    "from": tx.get("from", ""),
                    "to": tx.get("to", ""),
                    "token_name": tx.get("tokenName", ""),
                    "token_symbol": tx.get("tokenSymbol", ""),
                    "token_amount": str(round(value_token, 6)),
                    "value_usd": 0.0,  # would need a price oracle
                    "event_type": "token_transfer",
                    "timestamp": timestamp,
                    "source": source,
                })

            return token_txns

        except httpx.TimeoutException:
            logger.warning(f"{source} token transfer request timed out for {address}")
            return None
        except httpx.RequestError as exc:
            logger.warning(f"{source} token transfer request failed: {exc}")
            return None
        except (ValueError, KeyError) as exc:
            logger.warning(f"Error parsing token transfer response: {exc}")
            return None
