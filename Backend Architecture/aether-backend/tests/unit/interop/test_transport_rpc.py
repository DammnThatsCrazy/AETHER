"""Interop RPC transport seam tests (BUILD: HTTP JSON-RPC + CometBFT clients).

Proves the injectable ``RpcClient``/``IbcRpcClient`` protocol implementations
(``EvmJsonRpcClient`` / ``CometBftRpcClient``) against a mocked httpx
``MockTransport`` — NO live network. Covers:
  * EVM: head, logs, block-hash calls, hex -> int decoding.
  * CometBFT: status (sync height) + block_results (per-height walk).
  * HTTP 429 -> RpcRateLimited with retry_after (from Retry-After header).
  * HTTP >= 400 and JSON-RPC error bodies -> RpcError.
  * unconfigured network/chain -> RpcError.
"""
from __future__ import annotations

import sys
from pathlib import Path

import json

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.interop.providers.transport import (
    CometBftRpcClient,
    EvmJsonRpcClient,
    RpcError,
    RpcRateLimited,
)

ETH = "ethereum-mainnet"
ARB = "arbitrum-mainnet"
CHAIN_A = "cosmoshub-4"


def _jsonrpc_result(payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": payload}


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── EVM JSON-RPC client ────────────────────────────────────────────────

def test_evm_get_head_decodes_hex_block_number():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == f"https://rpc.example/{ETH}"
        assert json.loads(request.content)["method"] == "eth_blockNumber"
        return httpx.Response(200, json=_jsonrpc_result("0x64"))  # 100

    client = EvmJsonRpcClient(
        {ETH: f"https://rpc.example/{ETH}", ARB: f"https://rpc.example/{ARB}"},
        http_client=_transport(handler),
    )

    async def _run():
        return await client.get_head(ETH)

    head = _asyncio_run(_run())
    assert head == {"number": 100}


def test_evm_get_logs_and_block_hash():
    log = {"address": "0xabc", "topics": ["0x1"], "data": "0x2", "blockNumber": "0x32"}
    calls: list[tuple[str, list]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        calls.append((method, json.loads(request.content)["params"]))
        if method == "eth_getLogs":
            return httpx.Response(200, json=_jsonrpc_result([log]))
        if method == "eth_getBlockByNumber":
            return httpx.Response(200, json=_jsonrpc_result({"hash": "0xh-50"}))
        return httpx.Response(500, json={"error": "unexpected"})

    client = EvmJsonRpcClient(
        {ETH: f"https://rpc.example/{ETH}"}, http_client=_transport(handler),
    )

    async def _run():
        logs = await client.get_logs(ETH, 50, 55)
        block_hash = await client.get_block_hash(ETH, 50)
        return logs, block_hash

    logs, block_hash = _asyncio_run(_run())
    assert logs == [log]
    assert block_hash == "0xh-50"
    methods = [m for m, _ in calls]
    assert methods == ["eth_getLogs", "eth_getBlockByNumber"]
    from_block, to_block = calls[0][1][0]["fromBlock"], calls[0][1][0]["toBlock"]
    assert from_block == hex(50) and to_block == hex(55)


def test_evm_429_raises_rpc_rate_limited_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "12"}, text="throttled")

    client = EvmJsonRpcClient(
        {ETH: f"https://rpc.example/{ETH}"}, http_client=_transport(handler),
    )

    with pytest.raises(RpcRateLimited) as exc_info:
        _asyncio_run(client.get_head(ETH))
    assert exc_info.value.retry_after == 12.0


def test_evm_429_without_retry_after_raises_rpc_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="throttled")

    client = EvmJsonRpcClient(
        {ETH: f"https://rpc.example/{ETH}"}, http_client=_transport(handler),
    )

    with pytest.raises(RpcRateLimited) as exc_info:
        _asyncio_run(client.get_head(ETH))
    assert exc_info.value.retry_after is None


def test_evm_http_error_and_jsonrpc_error_raise_rpc_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("500"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "revert"}})

    client = EvmJsonRpcClient(
        {"bad": "https://rpc.example/500", "revert": "https://rpc.example/revert"},
        http_client=_transport(handler),
    )

    with pytest.raises(RpcError):
        _asyncio_run(client.get_head("bad"))
    with pytest.raises(RpcError):
        _asyncio_run(client.get_head("revert"))


def test_evm_unconfigured_network_raises_rpc_error():
    client = EvmJsonRpcClient({ETH: f"https://rpc.example/{ETH}"})
    with pytest.raises(RpcError):
        _asyncio_run(client.get_head("moon-network"))


# ── CometBFT JSON-RPC client ───────────────────────────────────────────

def test_cometbft_get_status_reads_sync_height():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["method"] == "status"
        return httpx.Response(200, json=_jsonrpc_result({
            "sync_info": {"latest_block_height": "123456"},
        }))

    client = CometBftRpcClient(
        {CHAIN_A: f"https://rpc.example/{CHAIN_A}"}, http_client=_transport(handler),
    )

    status = _asyncio_run(client.get_status(CHAIN_A))
    assert status == {"latest_block_height": "123456"}


def test_cometbft_get_block_results_walks_block_and_hash():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "block_results":
            return httpx.Response(200, json=_jsonrpc_result({
                "txs_results": [{"code": 0, "hash": "0xtx"}],
                "begin_block_events": [],
                "end_block_events": [],
            }))
        if method == "block":
            return httpx.Response(200, json=_jsonrpc_result({
                "block_id": {"hash": "0xblockhash"},
            }))
        return httpx.Response(500, json={"error": "unexpected"})

    client = CometBftRpcClient(
        {CHAIN_A: f"https://rpc.example/{CHAIN_A}"}, http_client=_transport(handler),
    )

    result = _asyncio_run(client.get_block_results(CHAIN_A, 42))
    assert result["height"] == "42"
    assert result["block_hash"] == "0xblockhash"
    assert result["txs_results"] == [{"code": 0, "hash": "0xtx"}]
    assert result["begin_block_events"] == []


def test_cometbft_429_raises_rpc_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "5"}, text="throttled")

    client = CometBftRpcClient(
        {CHAIN_A: f"https://rpc.example/{CHAIN_A}"}, http_client=_transport(handler),
    )

    with pytest.raises(RpcRateLimited) as exc_info:
        _asyncio_run(client.get_status(CHAIN_A))
    assert exc_info.value.retry_after == 5.0


def test_cometbft_unconfigured_chain_raises_rpc_error():
    client = CometBftRpcClient({CHAIN_A: f"https://rpc.example/{CHAIN_A}"})
    with pytest.raises(RpcError):
        _asyncio_run(client.get_status("other-chain"))


# ── tiny asyncio runner ────────────────────────────────────────────────

def _asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
