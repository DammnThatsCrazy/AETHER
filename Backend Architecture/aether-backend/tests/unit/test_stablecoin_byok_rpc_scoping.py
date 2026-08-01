"""Per-tenant BYOK-RPC endpoint/credential scoping for stablecoin observation.

Default OFF: a tenant-scoped RPCGateway resolves to the global QuickNode endpoint
(identity behavior). When AETHER_ONCHAIN_TENANT_BYOK_RPC_ENABLED is set, the
tenant's OWN read-only RPC (endpoint, api_key) is resolved as an ATOMIC pair from
the BYOK vault — a tenant endpoint is NEVER paired with the platform's global
key. Observe-only: reads the vault, never writes; execute() still gates on the
read-only method allowlist.
"""

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import settings
from services.onchain.rpc_gateway import RPCGateway

pytestmark = pytest.mark.asyncio

_CHAIN = "8453"


class _FakeVault:
    """Minimal BYOK vault stub: (endpoint, key) the tenant provisioned."""

    def __init__(self, endpoint=None, key=None):
        self._endpoint, self._key = endpoint, key

    async def get_endpoint(self, tenant_id, provider_name):
        return self._endpoint

    async def get_key(self, tenant_id, provider_name):
        return self._key


def _patch(monkeypatch, *, enabled, endpoint="https://global.example", api_key="GLOBAL-KEY"):
    monkeypatch.setattr(
        settings, "quicknode",
        dataclasses.replace(
            settings.quicknode,
            tenant_byok_enabled=enabled, endpoint=endpoint, api_key=api_key,
        ),
    )


async def test_flag_off_resolves_to_global(monkeypatch):
    _patch(monkeypatch, enabled=False)
    ep, key = await RPCGateway.resolve_tenant_rpc_endpoint(
        "t1", _CHAIN, vault=_FakeVault("https://tenant.example", "tenant-key")
    )
    assert (ep, key) == (None, None)  # global — vault not consulted for scoping
    gw = await RPCGateway.for_tenant("t1", _CHAIN, vault=_FakeVault("https://tenant.example", "tenant-key"))
    assert gw._endpoint == "https://global.example" and gw._api_key == "GLOBAL-KEY"


async def test_flag_on_uses_tenant_pair(monkeypatch):
    _patch(monkeypatch, enabled=True)
    ep, key = await RPCGateway.resolve_tenant_rpc_endpoint(
        "t1", _CHAIN, vault=_FakeVault("https://tenant-rpc.example", "tenant-key")
    )
    assert ep == "https://tenant-rpc.example" and key == "tenant-key"
    gw = await RPCGateway.for_tenant("t1", _CHAIN, vault=_FakeVault("https://tenant-rpc.example", "tenant-key"))
    assert gw._endpoint == "https://tenant-rpc.example" and gw._api_key == "tenant-key"


async def test_flag_on_tenant_endpoint_without_key_never_uses_global_key(monkeypatch):
    # THE SECURITY INVARIANT: a tenant endpoint with no tenant key resolves to
    # (tenant_endpoint, None) — NEVER the platform's global key.
    _patch(monkeypatch, enabled=True, api_key="GLOBAL-KEY")
    ep, key = await RPCGateway.resolve_tenant_rpc_endpoint(
        "t1", _CHAIN, vault=_FakeVault("https://tenant-rpc.example", None)
    )
    assert ep == "https://tenant-rpc.example"
    assert key is None and key != "GLOBAL-KEY"
    gw = await RPCGateway.for_tenant("t1", _CHAIN, vault=_FakeVault("https://tenant-rpc.example", None))
    assert gw._endpoint == "https://tenant-rpc.example"
    assert gw._api_key is None  # atomic pairing — no global-key leak to a tenant endpoint


async def test_flag_on_no_tenant_endpoint_falls_back_to_global(monkeypatch):
    _patch(monkeypatch, enabled=True)
    ep, key = await RPCGateway.resolve_tenant_rpc_endpoint("t1", _CHAIN, vault=_FakeVault(None, None))
    assert (ep, key) == (None, None)  # → global pair (atomic)
    gw = await RPCGateway.for_tenant("t1", _CHAIN, vault=_FakeVault(None, None))
    assert gw._endpoint == "https://global.example" and gw._api_key == "GLOBAL-KEY"


async def test_vault_error_fails_open_to_global(monkeypatch):
    _patch(monkeypatch, enabled=True)

    class _BoomVault:
        async def get_endpoint(self, *a):
            raise RuntimeError("vault down")

        async def get_key(self, *a):
            raise RuntimeError("vault down")

    ep, key = await RPCGateway.resolve_tenant_rpc_endpoint("t1", _CHAIN, vault=_BoomVault())
    assert (ep, key) == (None, None)  # fail open to global, never crash the observer
