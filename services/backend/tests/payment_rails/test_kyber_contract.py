"""Kyber operator financial-health contract (CS3).

The backend fleet + tenant aggregates must match the typed, versioned contract
(:mod:`kyber_contract`) the Kyber frontend consumes — the shape drift that
previously rendered empty/misleading operator views. Validates the aggregates
parse back into their Pydantic models and expose the fields the console renders,
distinguishing real zeros from unknown (``None``).
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.kyber_aggregate import (  # noqa: E402
    build_fleet_health,
    build_tenant_diagnostics,
)
from services.integrations.providers.payment_rails.kyber_contract import (  # noqa: E402
    CONTRACT_VERSION,
    FleetHealthResponse,
    TenantDiagnosticsResponse,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
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
    # fleet totals expose the fields the operator metric tiles render
    assert parsed.totals.configured_tenants >= 1
    assert parsed.totals.sessions_observed_24h >= 1
    # per-provider rows carry the status + counters the fleet table renders
    moonpay = next(p for p in parsed.providers if p.provider == "moonpay")
    assert moonpay.status in ("healthy", "degraded", "error", "not_configured", "disabled", "unknown")
    assert moonpay.configured_tenants >= 1
    # per-tenant fleet rows exist (the previously-missing array) and include ours
    assert any(t.tenant_id == tenant for t in parsed.tenants)
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
    assert moonpay.health.sessions_observed_24h >= 1
    assert isinstance(moonpay.adapter.credential_slots, list)
    # delivery backlogs are present
    assert parsed.backlogs.receipt_backlog >= 0


async def test_disabled_provider_status_is_distinct():
    reset_in_memory_stores()
    svc = _svc()
    response = await build_fleet_health(svc)
    # with no sessions and providers not enabled, provider state is disabled —
    # NOT a fake "healthy" and NOT an empty string.
    for p in response.providers:
        assert p.status in ("disabled", "not_configured")
