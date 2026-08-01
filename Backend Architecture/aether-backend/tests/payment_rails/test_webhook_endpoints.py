"""Webhook endpoint registry: server-side resolution, isolation, revoke/rotate."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails.webhook_endpoints import (  # noqa: E402
    WebhookEndpointRegistry,
)


def _fresh() -> WebhookEndpointRegistry:
    reset_in_memory_stores()
    return WebhookEndpointRegistry()


@pytest.mark.asyncio
async def test_create_and_resolve():
    reg = _fresh()
    ep = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    eid = ep["endpoint_id"]
    assert eid.startswith("whe_") and len(eid) > 40  # high entropy
    resolved = await reg.resolve(eid, "stripe")
    assert resolved["tenant_id"] == "tenantA" and resolved["environment"] == "sandbox"


@pytest.mark.asyncio
async def test_provider_mismatch_and_unknown_are_uniform_none():
    reg = _fresh()
    ep = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    # provider in the route must match the endpoint's provider
    assert await reg.resolve(ep["endpoint_id"], "coinbase") is None
    # unknown / malformed ids resolve to None (no tenant existence leak)
    assert await reg.resolve("whe_deadbeef", "stripe") is None
    assert await reg.resolve("not-an-endpoint", "stripe") is None
    assert await reg.resolve("", "stripe") is None


@pytest.mark.asyncio
async def test_revoke_stops_resolution():
    reg = _fresh()
    ep = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    assert await reg.resolve(ep["endpoint_id"], "stripe") is not None
    assert await reg.revoke("tenantA", ep["endpoint_id"], actor="admin")
    assert await reg.resolve(ep["endpoint_id"], "stripe") is None
    # another tenant cannot revoke it
    ep2 = await reg.create("tenantA", "coinbase", "sandbox", created_by="admin")
    assert not await reg.revoke("tenantB", ep2["endpoint_id"], actor="attacker")
    assert await reg.resolve(ep2["endpoint_id"], "coinbase") is not None


@pytest.mark.asyncio
async def test_rotate_revokes_old_and_mints_new():
    reg = _fresh()
    old = await reg.create("tenantA", "moonpay", "live", created_by="admin")
    new = await reg.rotate("tenantA", "moonpay", "live", actor="admin")
    assert new["endpoint_id"] != old["endpoint_id"]
    assert await reg.resolve(old["endpoint_id"], "moonpay") is None
    assert await reg.resolve(new["endpoint_id"], "moonpay") is not None


@pytest.mark.asyncio
async def test_no_secret_in_public_view():
    reg = _fresh()
    ep = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    import json

    blob = json.dumps(ep)
    # tenant_id is not part of the safe public view; only endpoint metadata + path
    assert "tenant_id" not in ep
    assert ep["webhook_path"].endswith(ep["endpoint_id"])
    assert "secret" not in blob.lower()
