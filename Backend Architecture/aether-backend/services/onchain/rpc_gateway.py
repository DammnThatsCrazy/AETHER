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

import httpx

from config.settings import settings
from shared.logger.logger import get_logger, metrics
from shared.providers.categories import ProviderCategory

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
    In production, connects to QuickNode or provider-gateway-backed endpoints.
    Fails closed when no live RPC transport is configured.
    """

    def __init__(self, provider_gateway=None, *, endpoint: Optional[str] = None,
                 api_key: Optional[str] = None) -> None:
        self._config = settings.quicknode
        # (endpoint, api_key) is an ATOMIC pair. An explicit endpoint (tenant
        # scoping) uses ITS paired key verbatim — even None, meaning "no key" —
        # so a tenant endpoint is NEVER sent with the global key. No endpoint
        # (the default) uses the global config pair (identity behavior).
        # ``_explicit_endpoint`` distinguishes a tenant-scoped gateway (an
        # explicit (endpoint, key) pair) from the DEFAULT gateway that uses the
        # global config pair. The default gateway reports scope/fingerprint
        # ``global`` even when the config endpoint resolves to an empty string.
        self._explicit_endpoint = endpoint is not None
        if endpoint is not None:
            self._endpoint = endpoint
            self._api_key = api_key
        else:
            self._endpoint = self._config.endpoint
            self._api_key = self._config.api_key
        self._provider_gateway = provider_gateway
        self._request_count = 0
        self._request_times: list[float] = []
        self._cache: dict[str, Any] = {}
        self._connected = False
        self._rate_lock = asyncio.Lock()
        self._credential_fingerprint = self._compute_fingerprint(
            self._endpoint if self._explicit_endpoint else None,
            self._api_key if self._explicit_endpoint else None,
        )

    @staticmethod
    async def resolve_tenant_rpc_endpoint(
        tenant_id: str, chain_id: str, *, vault=None
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve a tenant's read-only RPC ``(endpoint, api_key)`` as an ATOMIC
        pair. Default OFF, or no tenant BYOK on file → ``(None, None)`` so the
        gateway uses the global QuickNode pair (identity behavior). When a tenant
        has provisioned a BYOK RPC endpoint, returns THAT endpoint together with
        the tenant's key (which may be None) — NEVER the tenant endpoint paired
        with the global key. Read-only: reads the BYOK vault only, never writes.
        """
        if not getattr(settings.quicknode, "tenant_byok_enabled", False):
            return None, None
        if vault is None:
            from shared.providers.key_vault import BYOKKeyVault

            vault = BYOKKeyVault()
        provider_name = f"onchain_rpc:{chain_id}"
        try:
            endpoint = await vault.get_endpoint(tenant_id, provider_name)
        except Exception:  # noqa: BLE001 — vault unavailable → global fallback (atomic)
            return None, None
        if not endpoint:
            return None, None
        try:
            api_key = await vault.get_key(tenant_id, provider_name)
        except Exception:  # noqa: BLE001 — key unreadable → tenant endpoint, no key (never global key)
            api_key = None
        return endpoint, api_key

    @classmethod
    async def for_tenant(
        cls, tenant_id: str, chain_id: str, *, provider_gateway=None, vault=None
    ) -> "RPCGateway":
        """A read-only RPCGateway scoped to the tenant's BYOK RPC endpoint+key
        (atomic pair) when tenant BYOK is enabled; otherwise the global endpoint
        (identity behavior)."""
        endpoint, api_key = await cls.resolve_tenant_rpc_endpoint(
            tenant_id, chain_id, vault=vault
        )
        return cls(provider_gateway=provider_gateway, endpoint=endpoint, api_key=api_key)

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

    # ── credential rotation seam (tenant BYOK) ──────────────────────────────

    @staticmethod
    def _compute_fingerprint(endpoint: Optional[str], api_key: Optional[str]) -> str:
        """Deterministic, secret-free id of the active (endpoint, key) pair.

        A credential rotation changes this fingerprint; callers compare it over
        time to detect that an in-flight gateway is holding a stale credential.
        """
        if endpoint is None:
            return "global"
        material = f"{endpoint}::{api_key or ''}"
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    @property
    def credential_fingerprint(self) -> str:
        """The id of the credential pair currently in force (``global`` when the
        gateway is not tenant-scoped). Changes on every credential rotation."""
        return self._credential_fingerprint

    @property
    def credential_scope(self) -> str:
        """``tenant`` when the gateway holds an explicit (endpoint, key) pair,
        ``global`` when it uses the global config pair (identity behavior)."""
        return "tenant" if self._explicit_endpoint else "global"

    async def refresh_credentials(
        self, endpoint: Optional[str], api_key: Optional[str]
    ) -> str:
        """Rotate the gateway's credential pair and return the new fingerprint.

        Atomic: the (endpoint, key) pair is always replaced together — a tenant
        endpoint is NEVER paired with a different key. When the pair actually
        changes, the read cache is cleared so no stale response is served from
        an earlier credential; unchanged credentials are a no-op. Passing
        ``(None, None)`` reverts to the global config pair (scope ``global``).
        """
        new_fingerprint = self._compute_fingerprint(endpoint, api_key)
        changed = new_fingerprint != self._credential_fingerprint
        self._endpoint = endpoint
        self._api_key = api_key
        self._explicit_endpoint = endpoint is not None
        self._credential_fingerprint = new_fingerprint
        if changed:
            self._cache.clear()
            self._request_times = []
            logger.info(
                f"RPC Gateway credentials rotated | scope={self.credential_scope} "
                f"fingerprint={new_fingerprint}"
            )
        return new_fingerprint

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

        # Delegate to Provider Gateway when enabled
        if self._provider_gateway and settings.provider_gateway.enabled:
            result = await self._provider_gateway.route(
                category=ProviderCategory.BLOCKCHAIN_RPC,
                method=method,
                params={"chain_id": chain_id, "method": method, "params": params, "vm_type": vm_type},
            )
            if result.success:
                return result.data
            logger.warning(f"Provider Gateway failed, falling back to direct RPC: {result.error}")

        # Rate limiting: enforce max_rps
        await self._rate_limit()

        # Cache check for read-only methods
        cache_key = f"{chain_id}:{method}:{hashlib.sha256(str(params).encode()).hexdigest()[:16]}"
        if method.startswith("eth_get") or method.startswith("sol_get"):
            cached = self._cache.get(cache_key)
            if cached is not None:
                metrics.increment("rpc_cache_hit", labels={"chain_id": chain_id})
                return cached

        if not self._endpoint:
            raise RuntimeError("RPC gateway endpoint not configured and provider gateway unavailable")

        result = await self._execute_via_http(chain_id, method, params, vm_type)

        # Cache read-only results for 12 seconds
        if method.startswith("eth_get") or method.startswith("sol_get"):
            self._cache[cache_key] = result

        metrics.increment("rpc_requests", labels={"chain_id": chain_id, "method": method})
        logger.debug(f"RPC {method} on {chain_id} ({vm_type})")
        return result


    async def _execute_via_http(
        self,
        chain_id: str,
        method: str,
        params: list[Any],
        vm_type: str,
    ) -> dict[str, Any]:
        self._request_count += 1
        self._request_times.append(time.time())

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_count,
            "method": method,
            "params": params,
        }
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(self._endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict) or "error" in data:
            raise RuntimeError(f"RPC call failed: {data.get('error') if isinstance(data, dict) else data}")

        data.setdefault("chain_id", chain_id)
        data.setdefault("vm_type", vm_type)
        data.setdefault("method", method)
        return data

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
            "configured": bool(self._provider_gateway and settings.provider_gateway.enabled) or bool(self._endpoint),
            "total_requests": self._request_count,
            "cache_size": len(self._cache),
            "x402_enabled": self._config.x402_enabled,
            "credential_scope": self.credential_scope,
            "credential_fingerprint": self._credential_fingerprint,
        }
