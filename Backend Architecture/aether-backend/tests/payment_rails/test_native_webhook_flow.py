"""PR2 seam: endpoint registry → server-resolved tenant → authority secret →
provider-native verification. Proves the header-selected tenant is gone and a
real Stripe compound signature verifies end-to-end through the wiring."""

from __future__ import annotations

import hashlib
import hmac
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)
from services.integrations.providers.payment_rails.signature_verify import (  # noqa: E402
    verify_signature,
)
from services.integrations.providers.payment_rails.webhook_endpoints import (  # noqa: E402
    WebhookEndpointRegistry,
)
from services.providers.credentials.authority import credential_authority  # noqa: E402

NOW = 1_700_000_000


async def _configure_secret(tenant: str, provider: str, env: str, secret: str) -> None:
    await credential_authority.create_pending(
        tenant, provider, env, "webhook_signing_secret", secret, created_by="admin"
    )
    await credential_authority.activate(
        tenant, provider, env, "webhook_signing_secret", credential_version=1, actor="admin"
    )


@pytest.mark.asyncio
async def test_endpoint_resolves_tenant_and_native_stripe_verifies():
    reset_in_memory_stores()
    reg = WebhookEndpointRegistry()
    svc = PaymentRailsService()
    adapter = ADAPTERS["stripe"]

    # tenant/env come from the endpoint id, never a header
    ep = await reg.create("tenantA", "stripe", "sandbox", created_by="admin")
    resolved = await reg.resolve(ep["endpoint_id"], "stripe")
    tenant, env = resolved["tenant_id"], resolved["environment"]
    assert tenant == "tenantA" and env == "sandbox"

    await _configure_secret(tenant, "stripe", env, "whsec_live")

    # the service resolves the signing secret from the credential authority
    secrets = await svc._webhook_secrets(tenant, "stripe", env, adapter)
    assert "whsec_live" in secrets

    # a genuine Stripe compound signature verifies under the native scheme
    assert adapter.native_signature_scheme() == "stripe_compound"
    payload = b'{"id":"evt_1","type":"checkout.session.completed"}'
    digest = hmac.new(b"whsec_live", f"{NOW}.".encode() + payload, hashlib.sha256).hexdigest()
    header = f"t={NOW},v1={digest}"
    assert verify_signature("stripe_compound", secrets, payload, header, now_epoch=NOW).ok

    # a one-byte body change fails
    assert not verify_signature(
        "stripe_compound", secrets, payload + b" ", header, now_epoch=NOW
    ).ok


@pytest.mark.asyncio
async def test_tenant_b_endpoint_cannot_load_tenant_a_secret():
    reset_in_memory_stores()
    reg = WebhookEndpointRegistry()
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]

    await _configure_secret("tenantA", "coinbase", "sandbox", "whsec_A")
    # tenantB has its own endpoint and no secret configured
    epB = await reg.create("tenantB", "coinbase", "sandbox", created_by="admin")
    resolved = await reg.resolve(epB["endpoint_id"], "coinbase")
    secretsB = await svc._webhook_secrets(resolved["tenant_id"], "coinbase", "sandbox", adapter)
    assert "whsec_A" not in secretsB


@pytest.mark.asyncio
async def test_rotation_overlap_secret_verifies():
    reset_in_memory_stores()
    svc = PaymentRailsService()
    adapter = ADAPTERS["bridge"]
    tenant, env = "tenantA", "live"
    await _configure_secret(tenant, "bridge", env, "whsec_v1")
    # rotate → v1 becomes the bounded 'previous' overlap secret, v2 active
    await credential_authority.rotate(
        tenant, "bridge", env, "webhook_signing_secret", "whsec_v2", actor="admin",
    )
    secrets = await svc._webhook_secrets(tenant, "bridge", env, adapter)
    assert set(secrets) == {"whsec_v2", "whsec_v1"}  # overlap window keeps both valid
