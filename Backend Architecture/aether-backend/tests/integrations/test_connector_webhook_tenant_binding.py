"""Connector public webhook tenant binding — fail-closed adversarial tests.

Pins the closure of the header-tenant-selection defect: the public connector
webhook route used to accept ``X-Aether-Tenant-ID`` from any caller in every
environment. Now:

- the authoritative route resolves the tenant SERVER-SIDE from a durable,
  high-entropy ``endpoint_id`` (``cwe_…``);
- the legacy header route is fenced to local development behind an explicit
  opt-in flag and returns a uniform 404 everywhere else;
- endpoint misses are uniform (no existence oracle).
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import dataclasses

import pytest

from services.integrations.connectors.webhook_endpoints import (
    connector_webhook_endpoint_registry,
)

TENANT = "tenant-webhook-binding"


# ── Endpoint registry semantics ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_resolves_server_side_tenant():
    ep = await connector_webhook_endpoint_registry.create(
        TENANT, "shopify", "live", created_by="test"
    )
    assert ep["endpoint_id"].startswith("cwe_")
    assert ep["webhook_path"] == (
        f"/v1/integrations/webhooks/connectors/shopify/{ep['endpoint_id']}"
    )
    resolved = await connector_webhook_endpoint_registry.resolve(
        ep["endpoint_id"], "shopify"
    )
    assert resolved == {
        "tenant_id": TENANT,
        "provider": "shopify",
        "environment": "live",
        "endpoint_id": ep["endpoint_id"],
    }


@pytest.mark.asyncio
async def test_endpoint_misses_are_uniform():
    ep = await connector_webhook_endpoint_registry.create(
        TENANT, "shopify", "live", created_by="test"
    )
    # wrong provider for a real endpoint → None (no cross-connector reuse)
    assert await connector_webhook_endpoint_registry.resolve(
        ep["endpoint_id"], "stripe"
    ) is None
    # unknown id, wrong prefix, empty → None
    assert await connector_webhook_endpoint_registry.resolve("cwe_" + "0" * 64, "shopify") is None
    assert await connector_webhook_endpoint_registry.resolve("whe_" + "0" * 64, "shopify") is None
    assert await connector_webhook_endpoint_registry.resolve("", "shopify") is None


@pytest.mark.asyncio
async def test_revoked_endpoint_stops_resolving():
    ep = await connector_webhook_endpoint_registry.create(
        TENANT, "shopify", "live", created_by="test"
    )
    ok = await connector_webhook_endpoint_registry.revoke(
        TENANT, ep["endpoint_id"], actor="test"
    )
    assert ok is True
    assert await connector_webhook_endpoint_registry.resolve(
        ep["endpoint_id"], "shopify"
    ) is None


@pytest.mark.asyncio
async def test_cross_tenant_revocation_is_refused():
    ep = await connector_webhook_endpoint_registry.create(
        TENANT, "shopify", "live", created_by="test"
    )
    assert await connector_webhook_endpoint_registry.revoke(
        "some-other-tenant", ep["endpoint_id"], actor="attacker"
    ) is False
    # still resolvable — the foreign revocation attempt changed nothing
    assert await connector_webhook_endpoint_registry.resolve(
        ep["endpoint_id"], "shopify"
    ) is not None


@pytest.mark.asyncio
async def test_rotation_revokes_prior_endpoint():
    first = await connector_webhook_endpoint_registry.create(
        TENANT, "hubspot", "live", created_by="test"
    )
    second = await connector_webhook_endpoint_registry.rotate(
        TENANT, "hubspot", "live", actor="test"
    )
    assert second["endpoint_id"] != first["endpoint_id"]
    assert await connector_webhook_endpoint_registry.resolve(
        first["endpoint_id"], "hubspot"
    ) is None
    assert await connector_webhook_endpoint_registry.resolve(
        second["endpoint_id"], "hubspot"
    ) is not None


# ── Legacy header route fencing ───────────────────────────────────────────


def _set_legacy_flag(monkeypatch, enabled: bool) -> None:
    from config.settings import settings

    monkeypatch.setattr(
        settings,
        "connectors",
        dataclasses.replace(settings.connectors, legacy_webhook_route_enabled=enabled),
    )


def test_legacy_route_404_by_default_even_in_local():
    from shared.common.common import NotFoundError
    from services.integrations.connectors.routes import (
        _require_legacy_connector_webhook_route,
    )

    with pytest.raises(NotFoundError):
        _require_legacy_connector_webhook_route()


def test_legacy_route_404_outside_local_even_with_flag(monkeypatch):
    from shared.common.common import NotFoundError
    from services.integrations.connectors.routes import (
        _require_legacy_connector_webhook_route,
    )

    _set_legacy_flag(monkeypatch, True)
    for env in ("staging", "production", "integration", "dev"):
        monkeypatch.setenv("AETHER_ENV", env)
        with pytest.raises(NotFoundError):
            _require_legacy_connector_webhook_route()


def test_legacy_route_allowed_only_local_plus_flag(monkeypatch):
    from services.integrations.connectors.routes import (
        _require_legacy_connector_webhook_route,
    )

    _set_legacy_flag(monkeypatch, True)
    monkeypatch.setenv("AETHER_ENV", "local")
    _require_legacy_connector_webhook_route()  # does not raise


@pytest.mark.asyncio
async def test_public_endpoint_route_rejects_unknown_endpoint_uniformly():
    from shared.common.common import NotFoundError
    from services.integrations.connectors.routes import public_webhook_ingest_endpoint

    with pytest.raises(NotFoundError):
        # resolution happens before the request object is ever touched
        await public_webhook_ingest_endpoint("shopify", "cwe_" + "0" * 64, None)
