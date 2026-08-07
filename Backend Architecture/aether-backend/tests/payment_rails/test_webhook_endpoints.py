"""Webhook endpoint registry: server-side resolution, isolation, revoke/rotate."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails.webhook_endpoints import (  # noqa: E402
    DOMAIN_COMMS,
    DOMAIN_PAYMENT,
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


# ── Domain discriminator (payment / comms share one registry) ─────────────────


@pytest.mark.asyncio
async def test_comms_domain_create_resolve_and_path():
    reg = _fresh()
    ep = await reg.create("tenantA", "klaviyo", "sandbox",
                          created_by="admin", domain=DOMAIN_COMMS)
    assert ep["domain"] == DOMAIN_COMMS
    # comms endpoints publish under the /comms/ URL family
    assert ep["webhook_path"] == (
        f"/v1/integrations/webhooks/comms/klaviyo/{ep['endpoint_id']}"
    )
    resolved = await reg.resolve(ep["endpoint_id"], "klaviyo", domain=DOMAIN_COMMS)
    assert resolved["tenant_id"] == "tenantA"
    assert resolved["domain"] == DOMAIN_COMMS


@pytest.mark.asyncio
async def test_payment_default_domain_backward_compatible():
    reg = _fresh()
    ep = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    assert ep["domain"] == DOMAIN_PAYMENT
    assert ep["webhook_path"] == (
        f"/v1/integrations/webhooks/payment-rails/stripe/{ep['endpoint_id']}"
    )
    # legacy resolve() with no domain still resolves payment endpoints
    assert await reg.resolve(ep["endpoint_id"], "stripe") is not None
    assert await reg.resolve(ep["endpoint_id"], "stripe", domain=DOMAIN_PAYMENT) is not None


@pytest.mark.asyncio
async def test_cross_domain_isolation_uniform_none():
    reg = _fresh()
    pay = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    comms = await reg.create("tenantA", "klaviyo", "sandbox",
                             created_by="admin", domain=DOMAIN_COMMS)
    # a payment endpoint must never resolve through the comms domain (and vice versa)
    assert await reg.resolve(pay["endpoint_id"], "stripe", domain=DOMAIN_COMMS) is None
    assert await reg.resolve(comms["endpoint_id"], "klaviyo", domain=DOMAIN_PAYMENT) is None
    # same provider name on both domains is still isolated by domain
    pay2 = await reg.create("tenantB", "hubspot", "sandbox", created_by="admin")
    comms2 = await reg.create("tenantB", "hubspot", "sandbox",
                              created_by="admin", domain=DOMAIN_COMMS)
    assert await reg.resolve(pay2["endpoint_id"], "hubspot", domain=DOMAIN_COMMS) is None
    assert await reg.resolve(comms2["endpoint_id"], "hubspot", domain=DOMAIN_PAYMENT) is None


@pytest.mark.asyncio
async def test_list_and_rotate_are_domain_scoped():
    reg = _fresh()
    await reg.create("tenantA", "klaviyo", "sandbox", created_by="admin", domain=DOMAIN_COMMS)
    await reg.create("tenantA", "klaviyo", "sandbox", created_by="admin", domain=DOMAIN_COMMS)
    await reg.create("tenantA", "klaviyo", "sandbox", created_by="admin")
    assert len(await reg.list_for("tenantA", "klaviyo", domain=DOMAIN_COMMS)) == 2
    assert len(await reg.list_for("tenantA", "klaviyo")) == 3
    old = await reg.create("tenantA", "klaviyo", "live", created_by="admin", domain=DOMAIN_COMMS)
    fresh = await reg.rotate("tenantA", "klaviyo", "live",
                             actor="admin", domain=DOMAIN_COMMS)
    assert fresh["endpoint_id"] != old["endpoint_id"]
    # rotating the comms slot leaves the payment-domain klaviyo endpoints alone
    assert await reg.resolve(old["endpoint_id"], "klaviyo", domain=DOMAIN_COMMS) is None
    assert await reg.resolve(fresh["endpoint_id"], "klaviyo", domain=DOMAIN_COMMS) is not None
