"""HTTP transport seams for interop adapters — JSON-RPC (EVM) + CometBFT.

Implements the injectable ``RpcClient`` (EVM ``eth_*`` JSON-RPC) and
``IbcRpcClient`` (CometBFT JSON-RPC) protocol seams with real HTTP callers
built on httpx. Live endpoints are external and credential-gated: these
clients are constructed only at wiring time from configured endpoint URLs
(secret-ref) and are never touched in credentialless local runs — the
adapter ``scan`` guard still raises ``NotImplementedError`` while ``rpc`` is
``None``.

Rate limiting: an HTTP 429 raises :class:`RpcRateLimited` (``retry_after``
populated when the provider sends a ``Retry-After`` header). Every adapter's
protocol-native rate-limit exception subclasses :class:`RpcRateLimited`, so a
live HTTP scan participates in the same in-cycle resume contract the fixture
scans already exercise (checkpoint the last completed window, resume next
poll).
"""

from __future__ import annotations

from typing import Any, Optional

try:  # httpx is an optional transport dependency; missing only at construction.
    import httpx
except ImportError:  # pragma: no cover - guarded at construction time
    httpx = None  # type: ignore[assignment]


class RpcError(RuntimeError):
    """A non-rate-limit RPC failure (transport, JSON-RPC error, bad status)."""


class RpcRateLimited(RpcError):
    """Provider throttled the request (HTTP 429).

    Adapters resume from the last fully-scanned window next poll — the same
    contract their fixture clients already exercise.
    """

    def __init__(self, message: str, *, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class EvmJsonRpcClient:
    """EVM ``eth_*`` JSON-RPC client matching the interop ``RpcClient`` protocol.

    ``endpoints`` maps ``network_id`` -> RPC base URL. ``http_client`` may be
    injected (an ``httpx.AsyncClient`` — typically with a ``MockTransport`` in
    tests); when omitted, a short-lived client is created per request so no
    connection state leaks between providers.
    """

    def __init__(
        self,
        endpoints: dict[str, str],
        *,
        http_client: Optional[Any] = None,
        timeout: float = 20.0,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        if httpx is None:
            raise RpcError("httpx is required for live interop RPC transport")
        self._endpoints = dict(endpoints)
        self._client = http_client
        self._timeout = timeout
        self._headers = dict(headers or {})

    def _endpoint(self, network_id: str) -> str:
        url = self._endpoints.get(network_id)
        if not url:
            raise RpcError(f"{network_id}: no JSON-RPC endpoint configured")
        return url

    async def _rpc(self, network_id: str, method: str, params: list) -> Any:
        url = self._endpoint(network_id)
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        client = self._client
        owns = False
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout, headers=self._headers)
            owns = True
        try:
            response = await client.post(url, json=payload)
            if response.status_code == 429:
                retry_after = None
                raw = response.headers.get("Retry-After")
                if raw:
                    try:
                        retry_after = float(raw)
                    except ValueError:
                        retry_after = None
                raise RpcRateLimited(
                    f"{network_id}: JSON-RPC throttled ({response.status_code})",
                    retry_after=retry_after,
                )
            if response.status_code >= 400:
                raise RpcError(
                    f"{network_id}: JSON-RPC {method} HTTP {response.status_code}"
                )
            body = response.json()
            if body.get("error"):
                raise RpcError(f"{network_id}: JSON-RPC {method} error: {body['error']}")
            return body.get("result")
        finally:
            if owns:
                await client.aclose()

    async def get_head(self, network_id: str) -> dict[str, Any]:
        result = await self._rpc(network_id, "eth_blockNumber", [])
        return {"number": int(str(result), 16)}

    async def get_logs(
        self, network_id: str, from_block: int, to_block: int,
    ) -> list[dict[str, Any]]:
        result = await self._rpc(network_id, "eth_getLogs", [{
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }])
        return list(result) if result else []

    async def get_block_hash(self, network_id: str, block_number: int) -> str:
        result = await self._rpc(
            network_id, "eth_getBlockByNumber", [hex(block_number), False],
        )
        return (result or {}).get("hash", "")

    async def get_block(
        self, network_id: str, block_number: int,
    ) -> Optional[dict[str, Any]]:
        """Full block (used by parent-hash continuity checks)."""
        return await self._rpc(
            network_id, "eth_getBlockByNumber", [hex(block_number), True],
        )


class CometBftRpcClient:
    """CometBFT (Tendermint) JSON-RPC client matching the ``IbcRpcClient``
    protocol.

    ``endpoints`` maps ``chain_id`` -> RPC base URL. Block results are walked
    per height (the deterministic order-stable analogue of EVM ``get_logs``),
    exactly as the IBC adapter expects.
    """

    def __init__(
        self,
        endpoints: dict[str, str],
        *,
        http_client: Optional[Any] = None,
        timeout: float = 20.0,
    ) -> None:
        if httpx is None:
            raise RpcError("httpx is required for live interop RPC transport")
        self._endpoints = dict(endpoints)
        self._client = http_client
        self._timeout = timeout

    def _endpoint(self, chain_id: str) -> str:
        url = self._endpoints.get(chain_id)
        if not url:
            raise RpcError(f"{chain_id}: no CometBFT RPC endpoint configured")
        return url

    async def _rpc(self, chain_id: str, method: str, params: list) -> Any:
        url = self._endpoint(chain_id)
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        client = self._client
        owns = False
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            owns = True
        try:
            response = await client.post(url, json=payload)
            if response.status_code == 429:
                retry_after = None
                raw = response.headers.get("Retry-After")
                if raw:
                    try:
                        retry_after = float(raw)
                    except ValueError:
                        retry_after = None
                raise RpcRateLimited(
                    f"{chain_id}: CometBFT throttled ({response.status_code})",
                    retry_after=retry_after,
                )
            if response.status_code >= 400:
                raise RpcError(
                    f"{chain_id}: CometBFT {method} HTTP {response.status_code}"
                )
            body = response.json()
            if body.get("error"):
                raise RpcError(f"{chain_id}: CometBFT {method} error: {body['error']}")
            return body.get("result")
        finally:
            if owns:
                await client.aclose()

    async def get_status(self, chain_id: str) -> dict[str, Any]:
        result = await self._rpc(chain_id, "status", {})
        sync_info = (result or {}).get("sync_info", {}) or {}
        return {
            "latest_block_height": str(sync_info.get("latest_block_height", 0)),
        }

    async def get_block_results(
        self, chain_id: str, height: int,
    ) -> dict[str, Any]:
        result = await self._rpc(chain_id, "block_results", [str(height)])
        result = result or {}
        block_hash = ""
        try:
            block = await self._rpc(chain_id, "block", [str(height)])
            block_hash = (((block or {}).get("block_id") or {}).get("hash")) or ""
        except RpcError:  # noqa: BLE001 — hash lookup is best-effort
            block_hash = ""
        return {
            "height": str(height),
            "block_hash": block_hash,
            "txs_results": result.get("txs_results") or [],
            "begin_block_events": result.get("begin_block_events") or [],
            "end_block_events": result.get("end_block_events") or [],
        }

    async def get_block_hash(self, chain_id: str, height: int) -> str:
        result = await self._rpc(chain_id, "block", [str(height)])
        return ((result or {}).get("block_id") or {}).get("hash", "")
