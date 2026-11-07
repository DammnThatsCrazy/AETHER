"""Kyber operator financial-health contract (CS3).

The backend fleet + tenant aggregates must match the typed, versioned contract
(:mod:`kyber_contract`) the Kyber frontend consumes — the shape drift that
previously rendered empty/misleading operator views. Validates the aggregates
parse back into their Pydantic models and expose the fields the console renders,
distinguishing real zeros from unknown (``None``).
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from connectors.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from connectors.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from connectors.integrations.providers.payment_rails.kyber_aggregate import (  # noqa: E402
    build_fleet_health,
    build_tenant_diagnostics,
)
from connectors.integrations.providers.payment_rails.kyber_contract import (  # noqa: E402
    CONTRACT_VERSION,
    FleetHealthResponse,
    TenantDiagnosticsResponse,
)
from connectors.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from connectors.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)
from connectors.providers.credentials.authority import credential_authority  # noqa: E402
from connectors.providers.credentials.operator_view import (  # noqa: E402
    collect_payment_rail_configured_tenants,
)

pytestmark = pytest.mark.asyncio


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


def _svc():
    return PaymentRailsService(PaymentRailsRepositories(), producer=_Producer())


def _patch_payment_rails(monkeypatch, **fields) -> None:
    monkeypatch.setattr(
        settings, "payment_rails", dataclasses.replace(settings.payment_rails, **fields)
    )


async def _activate(tenant: str, provider: str, env: str, slot: str, secret: str) -> None:
    await credential_authority.create_pending(
        tenant, provider, env, slot, secret, created_by="admin"
    )
    await credential_authority.activate(
        tenant, provider, env, slot, credential_version=1, actor="admin"
    )


async def _observe(svc, tenant, *, tx_id="mp-1", status="completed"):
    adapter = ADAPTERS["moonpay"]
    data = {"id": tx_id, "status": status, "externalCustomerId": "u1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    event = adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]
    await svc._process_event(tenant, adapter, event, environment="sandbox")


async def test_fleet_contract_shape_and_fields():
    reset_in_memory_stores()
    svc = _svc()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _observe(svc, tenant)

    response = await build_fleet_health(svc)
    # round-trips through the typed contract (JSON → model). Assertions are
    # presence/>= (not exact global counts): the fleet is a cross-tenant aggregate
    # over a shared store, so other tests' tenants may also be present.
    parsed = FleetHealthResponse.model_validate(response.model_dump(mode="json"))
    assert parsed.contract_version == CONTRACT_VERSION
    assert parsed.tenants_observed >= 1
    # Local credential authority is OFF by default: configured coverage is
    # unknown (None), never a fabricated zero.
    assert parsed.totals.configuration_inventory_available is False
    assert parsed.totals.configured_tenants is None
    assert parsed.totals.observed_tenants >= 1
    assert parsed.totals.sessions_observed_24h >= 1
    # per-provider rows carry the status + counters the fleet table renders
    moonpay = next(p for p in parsed.providers if p.provider == "moonpay")
    assert moonpay.status in ("healthy", "degraded", "error", "not_configured", "disabled", "unknown")
    assert moonpay.observation_status == "unknown"
    assert moonpay.configured_tenants is None
    assert moonpay.never_observed_tenants is None
    assert moonpay.observed_tenants >= 1
    # per-tenant fleet rows exist (the previously-missing array) and include ours
    tenant_row = next(t for t in parsed.tenants if t.tenant_id == tenant)
    assert tenant_row.observation_status == "unknown"
    assert tenant_row.providers_configured is None
    assert tenant_row.providers_never_observed is None
    assert tenant_row.providers_observed >= 1
    # unknown fleet-worker liveness is null, never a misleading 0
    assert parsed.totals.worker_heartbeat is None


async def test_tenant_contract_nested_adapter_and_health():
    reset_in_memory_stores()
    svc = _svc()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _observe(svc, tenant)

    response = await build_tenant_diagnostics(svc, tenant)
    parsed = TenantDiagnosticsResponse.model_validate(response.model_dump(mode="json"))
    assert parsed.tenant_id == tenant
    assert parsed.providers  # five adapters
    moonpay = next(p for p in parsed.providers if p.provider == "moonpay")
    # the drawer reads nested adapter + health — both present and typed
    assert moonpay.adapter.status in ("configured", "not_configured", "error", "disabled")
    assert moonpay.health.observation_status in ("observed", "never_observed", "not_configured")
    assert moonpay.health.sessions_observed_24h >= 1
    assert isinstance(moonpay.adapter.credential_slots, list)
    # delivery backlogs are present
    assert parsed.backlogs.receipt_backlog >= 0


async def test_fleet_configured_never_observed_is_not_fabricated(monkeypatch):
    reset_in_memory_stores()
    _patch_payment_rails(
        monkeypatch,
        enabled=True,
        moonpay_enabled=True,
        credential_authority_enabled=True,
    )
    svc = _svc()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    # Configure the full MoonPay slot set, but never send an observation.
    await _activate(tenant, "moonpay", "sandbox", "webhook_signing_secret", "whsec")
    await _activate(tenant, "moonpay", "sandbox", "server_api_key", "server_key")

    response = await build_fleet_health(svc)
    parsed = FleetHealthResponse.model_validate(response.model_dump(mode="json"))
    assert parsed.totals.configuration_inventory_available is True
    assert parsed.totals.configured_tenants >= 1

    moonpay = next(p for p in parsed.providers if p.provider == "moonpay")
    assert moonpay.observation_status == "never_observed"
    assert moonpay.status == "unknown"
    assert moonpay.configured_tenants >= 1
    assert moonpay.never_observed_tenants >= 1

    tenant_row = next(t for t in parsed.tenants if t.tenant_id == tenant)
    assert tenant_row.observation_status == "never_observed"
    assert tenant_row.status == "unknown"
    assert tenant_row.providers_configured == 1
    assert tenant_row.providers_observed == 0
    assert tenant_row.providers_never_observed == 1
    assert tenant_row.sessions_observed_24h == 0


async def test_fleet_inventory_unavailable_is_unknown_not_zero(monkeypatch):
    reset_in_memory_stores()
    _patch_payment_rails(monkeypatch, credential_authority_enabled=False)
    svc = _svc()
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _observe(svc, tenant)

    parsed = await build_fleet_health(svc)
    assert parsed.totals.configuration_inventory_available is False
    assert parsed.totals.configured_tenants is None
    assert parsed.totals.observed_tenants >= 1
    assert all(p.observation_status == "unknown" for p in parsed.providers)
    assert all(p.configured_tenants is None for p in parsed.providers)
    assert all(p.never_observed_tenants is None for p in parsed.providers)


async def test_disabled_provider_status_is_distinct():
    reset_in_memory_stores()
    svc = _svc()
    response = await build_fleet_health(svc)
    # with no sessions and providers not enabled, provider state is disabled —
    # NOT a fake "healthy" and NOT an empty string.
    for p in response.providers:
        assert p.status in ("disabled", "not_configured")


async def test_configured_inventory_requires_every_required_slot(monkeypatch):
    reset_in_memory_stores()
    _patch_payment_rails(monkeypatch, credential_authority_enabled=True)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _activate(tenant, "moonpay", "sandbox", "webhook_signing_secret", "whsec")

    configured = await collect_payment_rail_configured_tenants(ADAPTERS)
    assert tenant not in configured["moonpay"]

    await _activate(tenant, "moonpay", "sandbox", "server_api_key", "server_key")
    configured = await collect_payment_rail_configured_tenants(ADAPTERS)
    assert tenant in configured["moonpay"]


async def test_configured_inventory_requires_slots_in_one_environment(monkeypatch):
    reset_in_memory_stores()
    _patch_payment_rails(monkeypatch, credential_authority_enabled=True)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    # Every required slot is active, but split across sandbox and live. A tenant
    # is configured only when one environment has the complete required set.
    await _activate(tenant, "moonpay", "sandbox", "webhook_signing_secret", "whsec")
    await _activate(tenant, "moonpay", "live", "server_api_key", "server_key")

    configured = await collect_payment_rail_configured_tenants(ADAPTERS)
    assert tenant not in configured["moonpay"]


async def test_configured_inventory_ignores_pending_credentials(monkeypatch):
    reset_in_memory_stores()
    _patch_payment_rails(monkeypatch, credential_authority_enabled=True)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    for slot, secret in (
        ("webhook_signing_secret", "whsec"),
        ("server_api_key", "server_key"),
    ):
        await credential_authority.create_pending(
            tenant, "moonpay", "sandbox", slot, secret, created_by="admin"
        )

    configured = await collect_payment_rail_configured_tenants(ADAPTERS)
    assert tenant not in configured["moonpay"]


async def test_configured_inventory_paginates_without_truncation(monkeypatch):
    reset_in_memory_stores()
    _patch_payment_rails(monkeypatch, credential_authority_enabled=True)
    tenants = [f"t-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    for tenant in tenants:
        await _activate(tenant, "moonpay", "sandbox", "webhook_signing_secret", "whsec")
        await _activate(tenant, "moonpay", "sandbox", "server_api_key", "server_key")

    configured = await collect_payment_rail_configured_tenants(ADAPTERS, page_size=2)
    assert set(tenants) <= configured["moonpay"]
