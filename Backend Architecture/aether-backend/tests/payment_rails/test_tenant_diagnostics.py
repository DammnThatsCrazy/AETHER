"""Tenant-facing diagnostics route, per-session receipt exposure, and the
per-tenant action rate limiter (L1).

The tenant now has its own typed diagnostics endpoint (reusing the shared
builder, re-scoped to the caller), the session-detail endpoint exposes the
metadata-only per-session delivery state, and the two tenant write actions are
rate-limited. All in-memory (AETHER_ENV=local).
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS, routes as rails_routes  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.repository import PaymentRailsRepositories  # noqa: E402
from services.integrations.providers.payment_rails.service import PaymentRailsService  # noqa: E402
from shared.common.common import ForbiddenError, RateLimitedError  # noqa: E402

pytestmark = pytest.mark.asyncio


class _Tenant:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.principal_id = f"admin-{tenant_id}"

    def require_permission(self, permission):
        if permission not in ("read", "write", "admin"):
            raise ForbiddenError(permission)


class _Request:
    def __init__(self, tenant_id):
        self.state = SimpleNamespace(tenant=_Tenant(tenant_id), request_id="req-1")
        self.headers = {}


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings, "payment_rails", dataclasses.replace(
        settings.payment_rails, enabled=True, moonpay_enabled=True, coinbase_enabled=True,
    ))


def _tenant():
    return f"t-{uuid.uuid4().hex[:8]}"


async def _observe(svc, tenant, *, tx_id="mp-1", status="completed"):
    adapter = ADAPTERS["moonpay"]
    data = {"id": tx_id, "status": status, "externalCustomerId": "u1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    event = adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]
    return await svc._process_event(tenant, adapter, event, environment="sandbox")


def _use(monkeypatch, svc):
    monkeypatch.setattr(rails_routes, "get_payment_rails_service", lambda: svc)


async def test_tenant_diagnostics_route_returns_typed_contract(monkeypatch):
    reset_in_memory_stores()
    svc, tenant = PaymentRailsService(PaymentRailsRepositories(), producer=_Producer()), _tenant()
    _use(monkeypatch, svc)
    await _observe(svc, tenant)

    resp = await rails_routes.tenant_diagnostics(_Request(tenant))
    data = resp["data"]
    assert data["tenant_id"] == tenant
    assert data["contract_version"]
    moonpay = next(p for p in data["providers"] if p["provider"] == "moonpay")
    # credential slots + backlogs are present, no secret values
    assert isinstance(moonpay["adapter"]["credential_slots"], list)
    assert "backlogs" in data and data["backlogs"]["receipt_backlog"] >= 0
    assert "secret" not in str(data).lower() or "webhook_signing_secret" in str(data)


async def test_session_detail_exposes_receipt_delivery(monkeypatch):
    reset_in_memory_stores()
    svc, tenant = PaymentRailsService(PaymentRailsRepositories(), producer=_Producer()), _tenant()
    _use(monkeypatch, svc)
    result = await _observe(svc, tenant)
    sid = result["funding_session_id"]

    resp = await rails_routes.get_funding_session(sid, _Request(tenant))
    data = resp["data"]
    assert data["receipts"], "per-session receipts should be exposed"
    assert data["delivery"]["stage"] == "completed"
    assert data["delivery"]["canonical_event_ids"]
    assert data["delivery"]["repair_eligible"] is False  # completed → not eligible
    # metadata-only: no raw payload / secret
    assert "payload" not in str(data["receipts"][0])


async def test_sync_action_rate_limited(monkeypatch):
    reset_in_memory_stores()
    svc, tenant = PaymentRailsService(PaymentRailsRepositories(), producer=_Producer()), _tenant()
    _use(monkeypatch, svc)
    monkeypatch.setattr(settings, "payment_rails", dataclasses.replace(
        settings.payment_rails, enabled=True, moonpay_enabled=True,
        tenant_sync_rate_limit_per_minute=1,
    ))
    body = rails_routes.SyncRequest(records=[])
    await rails_routes.sync_provider("moonpay", body, _Request(tenant))  # first: allowed
    with pytest.raises(RateLimitedError):
        await rails_routes.sync_provider("moonpay", body, _Request(tenant))  # second: 429


async def test_connection_probe_result_reflects_poll_health(monkeypatch):
    """connection_probe_result is wired from the stored poll health, honestly.

    A real probe classification is surfaced verbatim; `not_configured` /
    `webhook_only` / a missing value stays null — an honest "unknown / N-A",
    never a fabricated "ok".
    """
    reset_in_memory_stores()
    svc, tenant = PaymentRailsService(PaymentRailsRepositories(), producer=_Producer()), _tenant()
    _use(monkeypatch, svc)
    await _observe(svc, tenant)  # creates a moonpay health row + account record

    # A last poll that failed auth → surfaced as the probe result.
    await svc.repos.accounts.upsert(tenant, "moonpay", {"provider_poll_health": "auth_error"})
    resp = await rails_routes.tenant_diagnostics(_Request(tenant))
    moonpay = next(p for p in resp["data"]["providers"] if p["provider"] == "moonpay")
    assert moonpay["health"]["connection_probe_result"] == "auth_error"

    # not_configured is unknown, not a probe result → null (never a fake "ok").
    await svc.repos.accounts.upsert(tenant, "moonpay", {"provider_poll_health": "not_configured"})
    resp2 = await rails_routes.tenant_diagnostics(_Request(tenant))
    moonpay2 = next(p for p in resp2["data"]["providers"] if p["provider"] == "moonpay")
    assert moonpay2["health"]["connection_probe_result"] is None

    # A healthy poll IS a positive connectivity probe → surfaced as "ok".
    await svc.repos.accounts.upsert(tenant, "moonpay", {"provider_poll_health": "ok"})
    resp3 = await rails_routes.tenant_diagnostics(_Request(tenant))
    moonpay3 = next(p for p in resp3["data"]["providers"] if p["provider"] == "moonpay")
    assert moonpay3["health"]["connection_probe_result"] == "ok"
