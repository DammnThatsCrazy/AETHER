"""Stored channel credentials resolve only for the tenant that owns them."""
from __future__ import annotations

import pytest

from repositories.repos import ProvidersRepository, reset_in_memory_stores
from journeys.notification_intelligence.delivery_router import DeliveryRouter
from journeys.notification_intelligence.routes import _resolve_channel_credentials

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _seed():
    reset_in_memory_stores()
    providers = ProvidersRepository()
    await providers.upsert("notif_channel:own", {"api_key": "own-token", "tenant_id": "own_tenant"})
    await providers.upsert("notif_channel:other", {"api_key": "other-token", "tenant_id": "other_tenant"})
    await providers.upsert("notif_channel:untagged", {"api_key": "untagged-token"})
    yield
    reset_in_memory_stores()


async def test_find_for_tenant_requires_matching_tenant():
    providers = ProvidersRepository()
    assert (await providers.find_for_tenant("own_tenant", "notif_channel:own"))["api_key"] == "own-token"
    assert await providers.find_for_tenant("own_tenant", "notif_channel:other") is None
    assert await providers.find_for_tenant("own_tenant", "notif_channel:untagged") is None
    assert await providers.find_for_tenant("own_tenant", "notif_channel:missing") is None
    assert await providers.find_for_tenant("", "notif_channel:own") is None
    assert await providers.find_for_tenant(None, "notif_channel:untagged") is None


async def test_delivery_router_rejects_other_tenant_credentials_ref():
    router = DeliveryRouter(channel_repo=None, providers_repo=ProvidersRepository())
    own = {"tenant_id": "own_tenant", "credentials_ref": "notif_channel:own"}
    assert await router._resolve_credentials(own) == "own-token"
    for ref in ("notif_channel:other", "notif_channel:untagged"):
        with pytest.raises(RuntimeError, match="not found"):
            await router._resolve_credentials({"tenant_id": "own_tenant", "credentials_ref": ref})


async def test_channel_test_credentials_never_fall_back_to_the_ref():
    assert await _resolve_channel_credentials(
        {"tenant_id": "own_tenant", "credentials_ref": "notif_channel:own"}
    ) == "own-token"
    for ref in ("notif_channel:other", "notif_channel:untagged", "notif_channel:missing"):
        assert await _resolve_channel_credentials({"tenant_id": "own_tenant", "credentials_ref": ref}) == ""
