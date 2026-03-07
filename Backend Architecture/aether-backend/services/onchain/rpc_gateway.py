"""
Aether Service — RPC Gateway (L6 Infrastructure Backbone)
Single shared RPC client for all chain access. DRY — no layer imports its own RPC.
Wraps QuickNode endpoints with rate limiting, caching, and x402 pay-per-request.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Optional

from config.settings import settings
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.onchain.rpc")

ALLOWED_RPC_METHODS = {
    # EVM read methods
    "eth_getBalance", "eth_getTransactionCount", "eth_getCode", "eth_getStorageAt",
    "eth_call", "eth_estimateGas", "eth_getBlockByNumber", "eth_getBlockByHash",
    "eth_getTransactionByHash", "eth_getTransactionReceipt", "eth_getLogs",
    "eth_blockNumber", "eth_chainId", "eth_gasPrice", "eth_feeHistory",
    "eth_getBlockTransactionCountByNumber", "eth_getBlockTransactionCountByHash",
    # Solana read methods
    "sol_getBalance", "sol_getAccountInfo", "sol_getTransaction",
    "sol_getBlock", "sol_getLatestBlockhash", "sol_getSlot",
}


class RPCGateway:
    """
    Single shared RPC client for all blockchain interactions.
    In production, connects to QuickNode multi-chain endpoints.
    Stub implementation returns mock responses.
    """

    def __init__(self) -> None:
        self._config = settings.quicknode
        self._request_count = 0
        self._request_times: list[float] = []
        self._cache: dict[str, Any] = {}
        self._connected = False
        self._rate_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Initialize RPC connections."""
        self._connected = True
        logger.info(
            f"RPC Gateway connected | x402={self._config.x402_enabled} "
            f"| max_rps={self._config.max_rps}"
        )

    async def close(self) -> None:
        """Close all RPC connections."""
        self._connected = False
        self._cache.clear()
        logger.info("RPC Gateway closed")

    async def execute(
        self,
        chain_id: str,
        method: str,
        params: Optional[list[Any]] = None,
        vm_type: str = "evm",
    ) -> dict:
        """
        Execute an RPC call with rate limiting and caching.
        Returns the RPC response.
        """
        if method not in ALLOWED_RPC_METHODS:
            raise ValueError(f"RPC method not allowed: {method}")

        params = params or []

        # Rate limiting: enforce max_rps
        await self._rate_limit()

        # Cache check for read-only methods
        cache_key = f"{chain_id}:{method}:{hashlib.sha256(str(params).encode()).hexdigest()[:16]}"
        if method.startswith("eth_get") or method.startswith("sol_get"):
            cached = self._cache.get(cache_key)
            if cached is not None:
                metrics.increment("rpc_cache_hit", labels={"chain_id": chain_id})
                return cached

        # Execute RPC call (stub)
        self._request_count += 1
        self._request_times.append(time.time())

        result = {
            "jsonrpc": "2.0",
            "id": self._request_count,
            "result": None,
            "chain_id": chain_id,
            "vm_type": vm_type,
            "method": method,
        }

        # Cache read-only results for 12 seconds
        if method.startswith("eth_get") or method.startswith("sol_get"):
            self._cache[cache_key] = result

        metrics.increment("rpc_requests", labels={"chain_id": chain_id, "method": method})
        logger.debug(f"RPC {method} on {chain_id} ({vm_type})")
        return result

    async def _rate_limit(self) -> None:
        """Simple sliding-window rate limiter."""
        async with self._rate_lock:
            now = time.time()
            # Remove timestamps older than 1 second
            self._request_times = [t for t in self._request_times if now - t < 1.0]
            if len(self._request_times) >= self._config.max_rps:
                wait = 1.0 - (now - self._request_times[0])
                if wait > 0:
                    await asyncio.sleep(wait)

    async def health_check(self) -> dict:
        """RPC gateway health status."""
        return {
            "connected": self._connected,
            "total_requests": self._request_count,
            "cache_size": len(self._cache),
            "x402_enabled": self._config.x402_enabled,
        }
