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
    """
    Categories of external providers requiring abstraction.

    Entity-agnostic: categories cover Web2 and Web3 data sources equally.
    A social_api provider might be Twitter (Web2) or Farcaster (Web3).
    """

    # ── Data source categories ─────────────────────────────────────────────
    BLOCKCHAIN_RPC = "blockchain_rpc"
    BLOCK_EXPLORER = "block_explorer"
    ANALYTICS_DATA = "analytics_data"
    MARKET_DATA = "market_data"
    PREDICTION_MARKET = "prediction_market"
    IDENTITY_ENRICHMENT = "identity_enrichment"
    ONCHAIN_INTELLIGENCE = "onchain_intelligence"
    TRADFI_DATA = "tradfi_data"
    GOVERNANCE = "governance"

    # ── Social / content platforms (Web2 + Web3) ──────────────────────────
    SOCIAL_API = "social_api"            # Twitter/X, Instagram, LinkedIn, Reddit, Discord, GitHub
    WEB3_SOCIAL = "web3_social"          # Farcaster, Lens Protocol
    STREAMING_MEDIA = "streaming_media"  # YouTube, Spotify, TikTok, Twitch
    CONTENT_PLATFORM = "content_platform"  # Telegram channels, newsletters, podcasts

    # ── Financial data sources ────────────────────────────────────────────
    AD_PLATFORM = "ad_platform"          # Twitter Ads, Google Ads, Meta, LinkedIn, TikTok Ads
    OPEN_BANKING = "open_banking"        # Plaid, open banking connectors
    CREDIT_BUREAU = "credit_bureau"      # Experian, Equifax, TransUnion
    BROKERAGE = "brokerage"              # Fidelity, Schwab, Robinhood, Alpaca, IBKR, SoFi, etc.


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
# Category 12: Discord Social Provider
# ======================================================================


class DiscordProvider(Provider):
    """Discord — guild memberships and user metadata via Bot token."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://discord.com/api/v10"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error="Discord Bot token not configured", provider_name=self.name, latency_ms=0.0)
        headers = {"Authorization": f"Bot {self.config.api_key}", "Content-Type": "application/json"}
        self._request_count += 1
        try:
            if method == "user_guilds":
                url = f"{self._base_url()}/users/{params['user_id']}/guilds"
                result = await _http_get_json(url, headers=headers)
            elif method == "user":
                url = f"{self._base_url()}/users/{params['user_id']}"
                result = await _http_get_json(url, headers=headers)
            else:
                url = f"{self._base_url()}/{method}"
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
# Category 13: Ad Platform Providers
# ======================================================================


class _BaseAdPlatformProvider(Provider):
    """Shared base for ad platform providers."""

    def _base_url(self) -> str:
        return self.config.endpoint or ""

    def _auth_headers(self) -> dict:
        if self.config.api_key:
            return {"Authorization": f"Bearer {self.config.api_key}"}
        return {}

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error=f"{self.name}: API credentials not configured", provider_name=self.name, latency_ms=0.0)
        self._request_count += 1
        try:
            url = f"{self._base_url()}/{params.get('path', method)}"
            if params.get("body"):
                result = await _http_post_json(url, params["body"], headers=self._auth_headers())
            else:
                result = await _http_get_json(url, params=params.get("query", {}), headers=self._auth_headers())
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


class TwitterAdsProvider(_BaseAdPlatformProvider):
    """Twitter Ads API v2 — campaign spend + impressions + custom audiences."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://ads-api.twitter.com/12"


class GoogleAdsProvider(_BaseAdPlatformProvider):
    """Google Ads API v15 — CustomerService + CampaignService + UserLists."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://googleads.googleapis.com/v15"


class MetaAdsProvider(_BaseAdPlatformProvider):
    """Meta Marketing API v19.0 — Insights + Custom Audiences."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://graph.facebook.com/v19.0"


class LinkedInAdsProvider(_BaseAdPlatformProvider):
    """LinkedIn Campaign Manager API v3 — spend data + audience segments."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://api.linkedin.com/v2"


class TikTokAdsProvider(_BaseAdPlatformProvider):
    """TikTok for Business API v1.3 — campaign analytics + custom audiences."""

    def _base_url(self) -> str:
        return self.config.endpoint or "https://business-api.tiktok.com/open_api/v1.3"


# ======================================================================
# Category 14: Open Banking — Plaid
# ======================================================================


class PlaidProvider(Provider):
    """Plaid — bank accounts, transactions, investments, liabilities."""

    def _base_url(self) -> str:
        if self.config.extra.get("sandbox"):
            return "https://sandbox.plaid.com"
        return self.config.endpoint or "https://production.plaid.com"

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        client_id = self.config.extra.get("client_id") or self.config.api_key
        client_secret = self.config.extra.get("client_secret", "")
        if not client_id:
            return ProviderResult(success=False, error="Plaid client_id not configured", provider_name=self.name, latency_ms=0.0)
        self._request_count += 1

        # Inject Plaid credentials into every request body
        body = {**params.get("body", {}), "client_id": client_id, "secret": client_secret}
        endpoint_map = {
            "accounts_balance_get": "/accounts/balance/get",
            "transactions_get": "/transactions/get",
            "investments_holdings_get": "/investments/holdings/get",
            "liabilities_get": "/liabilities/get",
            "link_token_create": "/link/token/create",
            "item_public_token_exchange": "/item/public_token/exchange",
        }
        path = endpoint_map.get(method, f"/{method.replace('_', '/')}")
        url = f"{self._base_url()}{path}"

        try:
            result = await _http_post_json(url, body)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if (self.config.api_key or self.config.extra.get("client_id")) else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 15: Credit Bureau Provider
# ======================================================================


class CreditBureauProvider(Provider):
    """
    Tri-bureau credit bureau adapter (Experian / Equifax / TransUnion).
    The bureau is selected via config.extra['bureau']: 'experian' | 'equifax' | 'transunion'.
    Requires 'credit' consent purpose before any query is issued.
    SSN is NEVER stored — it is passed at query time only as a hashed value.
    """

    _ENDPOINTS = {
        "experian": "https://us-api.experian.com/consumerservices/credit-profile/v2",
        "equifax": "https://api.equifax.com/business/instant-decision",
        "transunion": "https://api.transunion.com/v1",
    }

    def _base_url(self) -> str:
        bureau = self.config.extra.get("bureau", "experian")
        return self.config.endpoint or self._ENDPOINTS.get(bureau, self._ENDPOINTS["experian"])

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error=f"Credit bureau API key not configured (consent + contract required)", provider_name=self.name, latency_ms=0.0)
        self._request_count += 1
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        try:
            url = f"{self._base_url()}/{method}"
            result = await _http_post_json(url, params.get("body", {}), headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


# ======================================================================
# Category 16: Brokerage Providers
# ======================================================================


class _BaseBrokerageProvider(Provider):
    """Shared base for brokerage/TradFi portfolio providers."""

    def _auth_headers(self) -> dict:
        if self.config.api_key:
            return {"Authorization": f"Bearer {self.config.api_key}"}
        return {}

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        start = time.perf_counter()
        if not self.config.api_key:
            return ProviderResult(success=False, error=f"{self.name}: credentials not configured", provider_name=self.name, latency_ms=0.0)
        self._request_count += 1
        try:
            base = self.config.endpoint or ""
            url = f"{base}/{params.get('path', method)}"
            if params.get("body"):
                result = await _http_post_json(url, params["body"], headers=self._auth_headers())
            else:
                result = await _http_get_json(url, params=params.get("query", {}), headers=self._auth_headers())
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=result, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.HEALTHY if self.config.api_key else ProviderStatus.UNAVAILABLE


class AlpacaProvider(_BaseBrokerageProvider):
    """Alpaca Markets API — equities, ETFs, crypto positions + orders."""

    def _auth_headers(self) -> dict:
        key_id = self.config.extra.get("key_id", self.config.api_key or "")
        secret = self.config.extra.get("secret_key", "")
        return {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}


class IBKRProvider(_BaseBrokerageProvider):
    """Interactive Brokers Client Portal API — portfolio + account management."""


class SchwabProvider(_BaseBrokerageProvider):
    """Charles Schwab Developer API (TD Ameritrade successor) — portfolio data."""


class FidelityProvider(_BaseBrokerageProvider):
    """Fidelity FidelityConnect API — portfolio positions + transaction history."""


class RobinhoodProvider(_BaseBrokerageProvider):
    """Robinhood API — retail brokerage portfolio + options positions."""


class SoFiProvider(_BaseBrokerageProvider):
    """SoFi Invest API — managed + active investment accounts."""


class BettermentProvider(_BaseBrokerageProvider):
    """Betterment API — robo-advisor portfolio + savings goals."""


class VanguardProvider(_BaseBrokerageProvider):
    """Vanguard API — index fund + retirement account positions."""


class ETradeProvider(_BaseBrokerageProvider):
    """E*TRADE / Morgan Stanley API — brokerage + options + retirement."""


class TDAmeritradeProvider(_BaseBrokerageProvider):
    """TD Ameritrade / Schwab API — brokerage + thinkorswim data."""


class WebullProvider(_BaseBrokerageProvider):
    """Webull API — commission-free brokerage account positions."""


# ======================================================================
# STREAMING MEDIA PROVIDERS (YouTube, Spotify, TikTok)
# ======================================================================

class _BaseStreamingProvider(Provider):
    """
    Shared base for streaming/content platform providers.
    BYOK pattern: tenants supply their own API credentials.
    Normalises creator and consumer signals into ProviderResult.
    """

    async def health_check(self) -> ProviderStatus:
        _require_httpx()
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.HEALTHY

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError(f"{self.__class__.__name__}.execute({method}) not implemented")


class YouTubeProvider(_BaseStreamingProvider):
    """YouTube Data API v3 — channel stats, video counts, subscriber count."""

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        _require_httpx()
        start = time.perf_counter()
        self._request_count += 1
        try:
            if method == "channel_stats":
                channel_id = params.get("channel_id", "")
                url = "https://www.googleapis.com/youtube/v3/channels"
                query = {
                    "part": "statistics,snippet,brandingSettings",
                    "id": channel_id,
                    "key": self.config.api_key,
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url, params=query)
                    resp.raise_for_status()
                    items = resp.json().get("items", [])
                    data = items[0] if items else {}
            else:
                data = {}
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=data, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"YouTube error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)


class SpotifyProvider(_BaseStreamingProvider):
    """Spotify Web API — artist profile, monthly listeners, user library."""

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        _require_httpx()
        start = time.perf_counter()
        self._request_count += 1
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        try:
            if method == "artist_profile":
                artist_id = params.get("artist_id", "")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://api.spotify.com/v1/artists/{artist_id}",
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
            elif method == "user_profile":
                user_id = params.get("user_id", "")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://api.spotify.com/v1/users/{user_id}",
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
            else:
                data = {}
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=data, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Spotify error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)


class TikTokProvider(_BaseStreamingProvider):
    """TikTok Display API — creator profile, follower count, video stats."""

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        _require_httpx()
        start = time.perf_counter()
        self._request_count += 1
        try:
            if method == "user_info":
                username = params.get("username", "")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://open.tiktokapis.com/v2/user/info/",
                        params={"fields": "open_id,union_id,display_name,username,avatar_url,follower_count,following_count,likes_count,video_count"},
                        headers={"Authorization": f"Bearer {self.config.api_key}"},
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data", {})
            else:
                data = {}
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=data, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"TikTok error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)


# ======================================================================
# CONTENT PLATFORM PROVIDERS (Telegram, newsletters)
# ======================================================================

class _BaseContentPlatformProvider(Provider):
    """Base for content distribution platform providers (Telegram, etc.)."""

    async def health_check(self) -> ProviderStatus:
        _require_httpx()
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.HEALTHY

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        raise NotImplementedError(f"{self.__class__.__name__}.execute({method}) not implemented")


class TelegramProvider(_BaseContentPlatformProvider):
    """Telegram Bot API — public channel stats (subscriber count, post reach)."""

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        _require_httpx()
        start = time.perf_counter()
        self._request_count += 1
        try:
            if method == "channel_stats":
                channel_id = params.get("channel_id", "")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://api.telegram.org/bot{self.config.api_key}/getChat",
                        params={"chat_id": channel_id},
                    )
                    resp.raise_for_status()
                    result = resp.json().get("result", {})
                    # Get member count separately
                    count_resp = await client.get(
                        f"https://api.telegram.org/bot{self.config.api_key}/getChatMemberCount",
                        params={"chat_id": channel_id},
                    )
                    member_count = count_resp.json().get("result", 0) if count_resp.is_success else 0
                    result["members_count"] = member_count
                    data = result
            else:
                data = {}
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=data, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Telegram error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)


# ======================================================================
# EXTENDED SOCIAL API PROVIDERS
# ======================================================================

class InstagramProvider(Provider):
    """
    Instagram Graph API — business/creator profile stats.
    Requires Facebook Business API access.
    Returns followers, following, media count, engagement rate.
    """

    async def health_check(self) -> ProviderStatus:
        _require_httpx()
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.HEALTHY

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        _require_httpx()
        start = time.perf_counter()
        self._request_count += 1
        try:
            if method == "user_profile":
                ig_user_id = params.get("ig_user_id") or params.get("username", "")
                fields = "id,name,followers_count,follows_count,media_count,is_verified"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://graph.facebook.com/v19.0/{ig_user_id}",
                        params={"fields": fields, "access_token": self.config.api_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
            else:
                data = {}
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=data, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"Instagram error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)


class LinkedInProvider(Provider):
    """
    LinkedIn API — profile stats, connection count, company page followers.
    Uses OAuth 2.0 member / company token.
    """

    async def health_check(self) -> ProviderStatus:
        _require_httpx()
        if not self.config.api_key:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.HEALTHY

    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        _require_httpx()
        start = time.perf_counter()
        self._request_count += 1
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        try:
            if method == "profile_stats":
                linkedin_id = params.get("linkedin_id", "")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://api.linkedin.com/v2/people/{linkedin_id}",
                        headers=headers,
                        params={"projection": "(id,localizedFirstName,localizedLastName,vanityName,followersCount)"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
            else:
                data = {}
            elapsed = (time.perf_counter() - start) * 1000
            metrics.increment("provider_request", labels={"provider": self.name, "method": method, "status": "success"})
            return ProviderResult(success=True, data=data, provider_name=self.name, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"LinkedIn error: {e}")
            return ProviderResult(success=False, error=str(e), provider_name=self.name, latency_ms=elapsed)


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
    # Social (Web2 primary)
    "twitter": TwitterProvider,
    "instagram": InstagramProvider,
    "linkedin": LinkedInProvider,
    "reddit": RedditProvider,
    "discord": DiscordProvider,
    # Streaming / content platforms
    "youtube": YouTubeProvider,
    "spotify": SpotifyProvider,
    "tiktok": TikTokProvider,
    "telegram": TelegramProvider,
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
    # Ad Platforms
    "twitter_ads": TwitterAdsProvider,
    "google_ads": GoogleAdsProvider,
    "meta_ads": MetaAdsProvider,
    "linkedin_ads": LinkedInAdsProvider,
    "tiktok_ads": TikTokAdsProvider,
    # Open Banking
    "plaid": PlaidProvider,
    # Credit Bureau
    "experian": CreditBureauProvider,
    "equifax": CreditBureauProvider,
    "transunion": CreditBureauProvider,
    # Brokerage (traditional + retail)
    "alpaca": AlpacaProvider,
    "ibkr": IBKRProvider,
    "schwab": SchwabProvider,
    "fidelity": FidelityProvider,
    "robinhood": RobinhoodProvider,
    "sofi": SoFiProvider,
    "betterment": BettermentProvider,
    "vanguard": VanguardProvider,
    "etrade": ETradeProvider,
    "tdameritrade": TDAmeritradeProvider,
    "webull": WebullProvider,
}

CATEGORY_PROVIDERS: dict[ProviderCategory, list[str]] = {
    ProviderCategory.BLOCKCHAIN_RPC: ["quicknode", "alchemy", "infura", "custom_rpc"],
    ProviderCategory.BLOCK_EXPLORER: ["etherscan", "moralis"],
    # Social API — Web2 primary + secondary
    ProviderCategory.SOCIAL_API: ["twitter", "instagram", "linkedin", "reddit", "discord", "github"],
    ProviderCategory.STREAMING_MEDIA: ["youtube", "spotify", "tiktok"],
    ProviderCategory.CONTENT_PLATFORM: ["telegram"],
    ProviderCategory.ANALYTICS_DATA: ["dune"],
    ProviderCategory.MARKET_DATA: ["defillama", "coingecko", "binance", "coinbase"],
    ProviderCategory.PREDICTION_MARKET: ["polymarket", "kalshi"],
    ProviderCategory.WEB3_SOCIAL: ["farcaster", "lens"],
    ProviderCategory.IDENTITY_ENRICHMENT: ["ens", "github"],
    ProviderCategory.GOVERNANCE: ["snapshot"],
    ProviderCategory.ONCHAIN_INTELLIGENCE: ["chainalysis", "nansen"],
    ProviderCategory.TRADFI_DATA: ["massive", "databento"],
    ProviderCategory.AD_PLATFORM: ["twitter_ads", "google_ads", "meta_ads", "linkedin_ads", "tiktok_ads"],
    ProviderCategory.OPEN_BANKING: ["plaid"],
    ProviderCategory.CREDIT_BUREAU: ["experian", "equifax", "transunion"],
    ProviderCategory.BROKERAGE: [
        "alpaca", "ibkr", "schwab", "fidelity",
        "robinhood", "sofi", "betterment", "vanguard", "etrade", "tdameritrade", "webull",
    ],
}
