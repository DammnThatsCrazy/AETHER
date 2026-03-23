from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in ("config", "services", "shared"):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in ("config", "services", "shared"):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.mark.asyncio
async def test_rpc_gateway_fails_closed_without_transport(monkeypatch):
    monkeypatch.setenv("QUICKNODE_ENDPOINT", "")
    monkeypatch.setenv("PROVIDER_GATEWAY_ENABLED", "0")

    with backend_module_path():
        rpc_module = importlib.import_module("services.onchain.rpc_gateway")
        importlib.reload(rpc_module)

        gateway = rpc_module.RPCGateway()
        with pytest.raises(RuntimeError, match="endpoint not configured"):
            await gateway.execute("1", "eth_getBalance", ["0xabc", "latest"])


@pytest.mark.asyncio
async def test_rpc_gateway_executes_over_http_and_caches(monkeypatch):
    monkeypatch.setenv("QUICKNODE_ENDPOINT", "https://rpc.example.test")
    monkeypatch.setenv("QUICKNODE_API_KEY", "secret")
    monkeypatch.setenv("PROVIDER_GATEWAY_ENABLED", "0")

    class MockResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            calls.append((url, json, headers))
            return MockResponse({"jsonrpc": "2.0", "id": json["id"], "result": "0x1"})

    with backend_module_path():
        rpc_module = importlib.import_module("services.onchain.rpc_gateway")
        importlib.reload(rpc_module)
        monkeypatch.setattr(rpc_module.httpx, "AsyncClient", MockClient)

        gateway = rpc_module.RPCGateway()
        first = await gateway.execute("1", "eth_getBalance", ["0xabc", "latest"])
        second = await gateway.execute("1", "eth_getBalance", ["0xabc", "latest"])

        assert first["result"] == "0x1"
        assert second == first
        assert len(calls) == 1
        assert calls[0][0] == "https://rpc.example.test"
        assert calls[0][2]["x-api-key"] == "secret"
