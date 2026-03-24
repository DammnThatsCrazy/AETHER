"""
Aether Shared -- Provider Categories & Concrete Adapters

Defines four provider categories and their concrete implementations.
Each adapter makes real HTTP calls via httpx and normalises responses
into ProviderResult.

Requires: httpx >= 0.27 (included in backend extras)
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.providers.base import (
    Provider,
    ProviderConfig,
    ProviderResult,
    ProviderStatus,
)

logger = get_logger("aether.providers.categories")

# httpx is in the backend extras — fail loud if missing
try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


class ProviderCategory(str, Enum):
    """Categories of external providers requiring abstraction."""

    BLOCKCHAIN_RPC = "blockchain_rpc"
    BLOCK_EXPLORER = "block_explorer"
    SOCIAL_API = "social_api"
    ANALYTICS_DATA = "analytics_data"
    MARKET_DATA = "market_data"
    PREDICTION_MARKET = "prediction_market"
    WEB3_SOCIAL = "web3_social"
    IDENTITY_ENRICHMENT = "identity_enrichment"
    ONCHAIN_INTELLIGENCE = "onchain_intelligence"
    TRADFI_DATA = "tradfi_data"
    GOVERNANCE = "governance"


def _require_httpx() -> None:
    if httpx is None:
        raise RuntimeError("httpx is required for provider adapters: pip install httpx>=0.27")


# ======================================================================
# SHARED HTTP HELPER
# ======================================================================

async def _http_post_json(
    url: str,
    json_body: dict,
    headers: Optional[dict] = None,
    timeout: float = 30.0,
) -> dict:
    """POST JSON and return parsed response. Raises on HTTP errors."""
    _require_httpx()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=json_body, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


async def _http_get_json(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 30.0,
) -> dict:
    """GET with query params and return parsed response."""
    _require_httpx()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params or {}, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


# ======================================================================
# Category 1: Blockchain RPC Providers
# ======================================================================


class _BaseRPCProvider(Provider):
    """Shared logic for JSON-RPC providers (QuickNode, Alchemy, Infura, Generic)."""

    def _build_endpoint(self) -> str:
        """Build the RPC endpoint URL. Override in subclasses if needed."""
        return self.config.endpoint

    def _build_headers(self) -> dict:
        """Build request headers. Override for API-key-in-header patterns."""
        return {"Content-Type": "application/json"}

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        endpoint = self._build_endpoint()
        if not endpoint:
            return ProviderResult(
                success=False,
                error=f"{self.name}: endpoint not configured",
                provider_name=self.name,
                latency_ms=0.0,
            )

        rpc_method = params.get("method", method)
        rpc_params = params.get("params", [])
        self._request_count += 1

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_count,
            "method": rpc_method,
            "params": rpc_params,
        }

        try:
            result = await _http_post_json(
                endpoint, payload, headers=self._build_headers()
            )
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": rpc_method, "status": "success",
            })
            return ProviderResult(
                success=True, data=result, provider_name=self.name,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"{self.name} RPC error: {e}")
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": rpc_method, "status": "error",
            })
            return ProviderResult(
                success=False, error=str(e), provider_name=self.name,
                latency_ms=elapsed,
            )

    async def health_check(self) -> ProviderStatus:
        if not self._build_endpoint():
            return ProviderStatus.UNAVAILABLE
        try:
            result = await self.execute("net_version", {"method": "net_version", "params": []})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class QuickNodeProvider(_BaseRPCProvider):
    """QuickNode RPC adapter."""

    def _build_endpoint(self) -> str:
        if self.config.endpoint:
            return self.config.endpoint
        # QuickNode endpoints are custom per-account
        return ""

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return headers


class AlchemyProvider(_BaseRPCProvider):
    """Alchemy RPC adapter. API key is appended to endpoint URL."""

    def _build_endpoint(self) -> str:
        if self.config.endpoint:
            return self.config.endpoint
        if self.config.api_key:
            chain = self.config.extra.get("chain", "eth-mainnet")
            return f"https://{chain}.g.alchemy.com/v2/{self.config.api_key}"
        return ""


class InfuraProvider(_BaseRPCProvider):
    """Infura RPC adapter. API key is part of the endpoint path."""

    def _build_endpoint(self) -> str:
        if self.config.endpoint:
            return self.config.endpoint
        if self.config.api_key:
            network = self.config.extra.get("network", "mainnet")
            return f"https://{network}.infura.io/v3/{self.config.api_key}"
        return ""


class GenericRPCProvider(_BaseRPCProvider):
    """Custom RPC endpoint for BYOK with arbitrary endpoints."""

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


# ======================================================================
# Category 2: Block Explorer Providers
# ======================================================================


class EtherscanProvider(Provider):
    """Etherscan / PolygonScan / ArbScan block explorer adapter."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.etherscan.io/api"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(
                success=False, error="Etherscan API key not configured",
                provider_name=self.name, latency_ms=0.0,
            )

        query_params = {
            "module": params.get("module", "account"),
            "action": params.get("action", method),
            "apikey": self.config.api_key,
            **{k: v for k, v in params.items() if k not in ("module", "action")},
        }
        self._request_count += 1

        try:
            result = await _http_get_json(self._base_url(), params=query_params)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": method, "status": "success",
            })
            return ProviderResult(
                success=True, data=result, provider_name=self.name,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Etherscan error: {e}")
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": method, "status": "error",
            })
            return ProviderResult(
                success=False, error=str(e), provider_name=self.name,
                latency_ms=elapsed,
            )

    async def health_check(self) -> ProviderStatus:
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        try:
            result = await self.execute("ethprice", {"module": "stats", "action": "ethprice"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class MoralisProvider(Provider):
    """Moralis Web3 data API adapter."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://deep-index.moralis.io/api/v2.2"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(
                success=False, error="Moralis API key not configured",
                provider_name=self.name, latency_ms=0.0,
            )

        path = params.get("path", "")
        url = f"{self._base_url()}/{path}" if path else self._base_url()
        headers = {"X-API-Key": self.config.api_key, "Accept": "application/json"}
        self._request_count += 1

        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": method, "status": "success",
            })
            return ProviderResult(
                success=True, data=result, provider_name=self.name,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Moralis error: {e}")
            return ProviderResult(
                success=False, error=str(e), provider_name=self.name,
                latency_ms=elapsed,
            )

    async def health_check(self) -> ProviderStatus:
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.HEALTHY


# ======================================================================
# Category 3: Social API Providers
# ======================================================================


class TwitterProvider(Provider):
    """Twitter / X API v2 adapter using bearer token auth."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.twitter.com/2"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(
                success=False, error="Twitter bearer token not configured",
                provider_name=self.name, latency_ms=0.0,
            )

        path = params.get("path", "tweets/search/recent")
        url = f"{self._base_url()}/{path}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        query = params.get("query", {})
        self._request_count += 1

        try:
            result = await _http_get_json(url, params=query, headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": method, "status": "success",
            })
            return ProviderResult(
                success=True, data=result, provider_name=self.name,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Twitter API error: {e}")
            return ProviderResult(
                success=False, error=str(e), provider_name=self.name,
                latency_ms=elapsed,
            )

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


class RedditProvider(Provider):
    """Reddit API adapter using OAuth2 application-only auth."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://oauth.reddit.com"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(
                success=False, error="Reddit API credentials not configured",
                provider_name=self.name, latency_ms=0.0,
            )

        path = params.get("path", "r/all/new.json")
        url = f"{self._base_url()}/{path}"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": "aether-platform/1.0",
        }
        self._request_count += 1

        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": method, "status": "success",
            })
            return ProviderResult(
                success=True, data=result, provider_name=self.name,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Reddit API error: {e}")
            return ProviderResult(
                success=False, error=str(e), provider_name=self.name,
                latency_ms=elapsed,
            )

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 4: Analytics Data Providers
# ======================================================================


class DuneAnalyticsProvider(Provider):
    """Dune Analytics query execution and result retrieval."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.dune.com/api/v1"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(
                success=False, error="Dune API key not configured",
                provider_name=self.name, latency_ms=0.0,
            )

        query_id = params.get("query_id", "")
        action = params.get("action", "execute")
        headers = {"X-Dune-Api-Key": self.config.api_key}
        self._request_count += 1

        try:
            if action == "execute":
                url = f"{self._base_url()}/query/{query_id}/execute"
                result = await _http_post_json(url, json_body=params.get("parameters", {}), headers=headers)
            elif action == "results":
                execution_id = params.get("execution_id", "")
                url = f"{self._base_url()}/execution/{execution_id}/results"
                result = await _http_get_json(url, headers=headers)
            else:
                url = f"{self._base_url()}/query/{query_id}/results"
                result = await _http_get_json(url, headers=headers)

            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={
                "provider": self.name, "method": method, "status": "success",
            })
            return ProviderResult(
                success=True, data=result, provider_name=self.name,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Dune Analytics error: {e}")
            return ProviderResult(
                success=False, error=str(e), provider_name=self.name,
                latency_ms=elapsed,
            )

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 5: Market Data Providers
# ======================================================================


class DeFiLlamaProvider(Provider):
    """DeFiLlama — free, no auth required. TVL, yields, protocol data."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.llama.fi"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        path = params.get("path", "protocols")
        url = f"{self._base_url()}/{path}"
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}))
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"DeFiLlama error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("health", {"path": "protocols"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class CoinGeckoProvider(Provider):
    """CoinGecko — market data, prices, volumes. Free tier + Pro API."""

    def _base_url(self) -> str:
        if self.config.api_key:
            return self.config.endpoint or "https://pro-api.coingecko.com/api/v3"
        return "https://api.coingecko.com/api/v3"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        path = params.get("path", "ping")
        url = f"{self._base_url()}/{path}"
        headers = {}
        if self.config.api_key:
            headers["x-cg-pro-api-key"] = self.config.api_key
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("ping", {"path": "ping"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class BinanceProvider(Provider):
    """Binance — spot/futures market data, OHLCV, order book."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.binance.com/api/v3"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        path = params.get("path", "ticker/price")
        url = f"{self._base_url()}/{path}"
        headers = {}
        if self.config.api_key:
            headers["X-MBX-APIKEY"] = self.config.api_key
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        try:
            result = await self.execute("ping", {"path": "ping"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class CoinbaseProvider(Provider):
    """Coinbase — market data, exchange rates, product info."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.coinbase.com/v2"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        path = params.get("path", "exchange-rates")
        url = f"{self._base_url()}/{path}"
        headers = {"CB-VERSION": "2024-01-01"}
        if self.config.api_key:
            headers["CB-ACCESS-KEY"] = self.config.api_key
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("ping", {"path": "exchange-rates"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 6: Prediction Market Providers
# ======================================================================


class PolymarketProvider(Provider):
    """Polymarket — prediction market data, events, positions."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://gamma-api.polymarket.com"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        path = params.get("path", "markets")
        url = f"{self._base_url()}/{path}"
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("health", {"path": "markets", "query": {"limit": "1"}})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class KalshiProvider(Provider):
    """Kalshi — regulated prediction market, events and trades."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://trading-api.kalshi.com/trade-api/v2"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Kalshi API key not configured", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "events")
        url = f"{self._base_url()}/{path}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 7: Web3 Social Providers
# ======================================================================


class FarcasterProvider(Provider):
    """Farcaster — decentralized social protocol via Neynar API."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.neynar.com/v2/farcaster"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Farcaster/Neynar API key not configured", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "feed")
        url = f"{self._base_url()}/{path}"
        headers = {"accept": "application/json", "api_key": self.config.api_key}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 8: Identity Enrichment Providers
# ======================================================================


class LensProtocolProvider(Provider):
    """Lens Protocol — decentralized social graph via Lens API v2."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api-v2.lens.dev"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        query = params.get("query", "")
        variables = params.get("variables", {})
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["x-access-token"] = self.config.api_key
        self._request_count += 1
        try:
            result = await _http_post_json(
                self._base_url(),
                json_body={"query": query, "variables": variables},
                headers=headers,
            )
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Lens Protocol error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("health", {"query": "{ ping }"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class ENSProvider(Provider):
    """ENS — Ethereum Name Service lookup via The Graph subgraph."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.thegraph.com/subgraphs/name/ensdomains/ens"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        query = params.get("query", "")
        variables = params.get("variables", {})
        self._request_count += 1
        try:
            result = await _http_post_json(
                self._base_url(),
                json_body={"query": query, "variables": variables},
            )
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("health", {"query": '{ _meta { block { number } } }'})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


class GitHubProvider(Provider):
    """GitHub — repository, org, and user event ingestion via REST API v3."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.github.com"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="GitHub PAT not configured", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "user")
        url = f"{self._base_url()}/{path}"
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 9: Governance Providers
# ======================================================================


class SnapshotProvider(Provider):
    """Snapshot — governance proposals, votes, and spaces via GraphQL."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://hub.snapshot.org/graphql"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        query = params.get("query", "")
        variables = params.get("variables", {})
        self._request_count += 1
        try:
            result = await _http_post_json(
                self._base_url(),
                json_body={"query": query, "variables": variables},
            )
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        try:
            result = await self.execute("health", {"query": "{ spaces(first: 1) { id } }"})
            return ProviderStatus.HEALTHY if result.success else ProviderStatus.DEGRADED
        except Exception:
            return ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 10: On-Chain Intelligence Providers (contract-gated)
# ======================================================================


class ChainalysisProvider(Provider):
    """Chainalysis — on-chain risk and compliance data. Requires contract."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.chainalysis.com/api/risk/v2"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Chainalysis API key not configured (contract required)", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "entities")
        url = f"{self._base_url()}/{path}"
        headers = {"Token": self.config.api_key, "Accept": "application/json"}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


class NansenProvider(Provider):
    """Nansen — wallet labels, smart money flows. Requires contract."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.nansen.ai/v1"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Nansen API key not configured (contract required)", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "labels")
        url = f"{self._base_url()}/{path}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 11: TradFi Data Providers (contract-gated)
# ======================================================================


class MassiveProvider(Provider):
    """Massive — alternative data for financial markets. Requires contract."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.massive.com/v1"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Massive API key not configured (contract required)", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "datasets")
        url = f"{self._base_url()}/{path}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


class DatabentoProvider(Provider):
    """Databento — normalized market data across exchanges. Requires subscription."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://hist.databento.com/v0"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Databento API key not configured (subscription required)", provider_name=self.name, latency_ms=0.0)
        path = params.get("path", "metadata.list_datasets")
        url = f"{self._base_url()}/{path}"
        headers = {"Authorization": f"Basic {self.config.api_key}", "Accept": "application/json"}
        self._request_count += 1
        try:
            result = await _http_get_json(url, params=params.get("query", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# FACTORY: name -> Provider class mapping
# ======================================================================

PROVIDER_FACTORY: dict[str, type[Provider]] = {
    # Blockchain RPC
    "quicknode": QuickNodeProvider,
    "alchemy": AlchemyProvider,
    "infura": InfuraProvider,
    "custom_rpc": GenericRPCProvider,
    # Block Explorer
    "etherscan": EtherscanProvider,
    "moralis": MoralisProvider,
    # Social
    "twitter": TwitterProvider,
    "reddit": RedditProvider,
    # Analytics
    "dune": DuneAnalyticsProvider,
    # Market Data
    "defillama": DeFiLlamaProvider,
    "coingecko": CoinGeckoProvider,
    "binance": BinanceProvider,
    "coinbase": CoinbaseProvider,
    # Prediction Markets
    "polymarket": PolymarketProvider,
    "kalshi": KalshiProvider,
    # Web3 Social
    "farcaster": FarcasterProvider,
    "lens": LensProtocolProvider,
    # Identity Enrichment
    "ens": ENSProvider,
    "github": GitHubProvider,
    # Governance
    "snapshot": SnapshotProvider,
    # On-Chain Intelligence (contract-gated)
    "chainalysis": ChainalysisProvider,
    "nansen": NansenProvider,
    # TradFi Data (contract-gated)
    "massive": MassiveProvider,
    "databento": DatabentoProvider,
}

CATEGORY_PROVIDERS: dict[ProviderCategory, list[str]] = {
    ProviderCategory.BLOCKCHAIN_RPC: ["quicknode", "alchemy", "infura", "custom_rpc"],
    ProviderCategory.BLOCK_EXPLORER: ["etherscan", "moralis"],
    ProviderCategory.SOCIAL_API: ["twitter", "reddit"],
    ProviderCategory.ANALYTICS_DATA: ["dune"],
    ProviderCategory.MARKET_DATA: ["defillama", "coingecko", "binance", "coinbase"],
    ProviderCategory.PREDICTION_MARKET: ["polymarket", "kalshi"],
    ProviderCategory.WEB3_SOCIAL: ["farcaster", "lens"],
    ProviderCategory.IDENTITY_ENRICHMENT: ["ens", "github"],
    ProviderCategory.GOVERNANCE: ["snapshot"],
    ProviderCategory.ONCHAIN_INTELLIGENCE: ["chainalysis", "nansen"],
    ProviderCategory.TRADFI_DATA: ["massive", "databento"],
}
