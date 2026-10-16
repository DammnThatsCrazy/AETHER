"""A Shopify shop is selected only with live identity and by one tenant at a time."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from repositories.repos import reset_in_memory_stores
from shared.credentials.types import ApiKeyCredential, MultiCredential
from shared.integration_contracts.acquisition import ProviderAccount
from shared.integration_contracts.lifecycle import ConnectionState

import connectors.providers.shopify.account as account_mod
from connectors.provider_runtime.acquisition import (
    AcquisitionCoordinator,
    ProviderAccountRepository,
)
from connectors.provider_runtime.connection import (
    ProviderConnection,
    ProviderConnectionRepository,
)
from connectors.provider_runtime.errors import ProviderConfigurationInvalid
from connectors.providers.shopify.account import ShopifyAccountAdapter

SHOP = "a-shop.myshopify.com"
ACCOUNT = f"shop:{SHOP}"
CREDENTIAL = MultiCredential(credentials={
    "shop_access_token": ApiKeyCredential(api_key=SecretStr("synthetic-token")),
})


@pytest.fixture
def env(monkeypatch):
    reset_in_memory_stores()

    async def _live_shop(context, shop_domain, cred):
        return ProviderAccount(
            account_id=f"shop:{shop_domain}", display_name="Shop", external_id="1001",
            metadata={"shop_domain": shop_domain, "shop_id": 1001},
        )

    monkeypatch.setattr(account_mod, "_fetch_shop_account", _live_shop)
    connections = ProviderConnectionRepository()
    return SimpleNamespace(
        coordinator=AcquisitionCoordinator(
            accounts=ProviderAccountRepository(), connections=connections,
        ),
        connections=connections,
        plugin=SimpleNamespace(account=lambda: ShopifyAccountAdapter(), manifest=lambda: None),
    )


def _connection(tenant: str, orders_api: str = "rest") -> ProviderConnection:
    return ProviderConnection(
        connection_id=f"conn-{tenant}", tenant_id=tenant,
        provider_identity="shopify.admin.orders_read",
        state=ConnectionState.ACCOUNT_SELECTION_REQUIRED,
        config={"shop_domain": SHOP, "orders_api": orders_api},
    )


async def _claim(env, tenant: str, *, credential=CREDENTIAL, orders_api: str = "rest") -> ProviderConnection:
    conn = _connection(tenant, orders_api)
    found = await env.coordinator.discover_accounts(conn, plugin=env.plugin, credential=credential)
    assert found.success
    conn = await env.coordinator.select_account(conn, account_id=ACCOUNT, plugin=env.plugin)
    await env.connections.upsert(conn)
    return conn


@pytest.mark.asyncio
@pytest.mark.parametrize("orders_api", ["rest", "rest_webhook"])
async def test_domain_only_discovery_cannot_be_selected(env, orders_api):
    with pytest.raises(ProviderConfigurationInvalid):
        await _claim(env, "tenant-A", credential=None, orders_api=orders_api)


@pytest.mark.asyncio
async def test_live_shop_identity_can_be_selected(env):
    conn = await _claim(env, "tenant-A")
    assert conn.selected_accounts == [ACCOUNT]


@pytest.mark.asyncio
async def test_shop_held_by_another_tenant_is_rejected(env):
    await _claim(env, "tenant-A")
    with pytest.raises(ProviderConfigurationInvalid, match="another"):
        await _claim(env, "tenant-B")


@pytest.mark.asyncio
async def test_released_shop_can_be_claimed_by_another_tenant(env):
    held = await _claim(env, "tenant-A")
    held.state = ConnectionState.REVOKED
    await env.connections.upsert(held)

    conn = await _claim(env, "tenant-B")
    assert conn.selected_accounts == [ACCOUNT]
