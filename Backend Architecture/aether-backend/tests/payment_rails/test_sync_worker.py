"""Supervised sync-worker cycle — per-provider failure isolation (C1).

`run_sync_cycle` must never let one provider's pull failure abort the sweep: the
other providers (and the staleness re-evaluation) for that tenant still run.
All in-memory (AETHER_ENV=local).
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.repository import PaymentRailsRepositories  # noqa: E402
from services.integrations.providers.payment_rails.service import PaymentRailsService  # noqa: E402
from services.integrations.providers.payment_rails.sync_worker import run_sync_cycle  # noqa: E402

pytestmark = pytest.mark.asyncio


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


async def _seed_open(svc, tenant, provider):
    """Persist one open (pending) funding session for a provider."""
    if provider == "moonpay":
        adapter = ADAPTERS["moonpay"]
        data = {"id": f"mp-{uuid.uuid4().hex[:6]}", "status": "pending",
                "externalCustomerId": "u1", "baseCurrencyAmount": 100,
                "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
        payload = {"type": "transaction_updated", "data": data}
    else:  # coinbase
        adapter = ADAPTERS["coinbase"]
        tx = {"transaction_id": f"cb-{uuid.uuid4().hex[:6]}", "status": "pending",
              "partner_user_ref": "u1", "purchase_currency": "USDC", "purchase_network": "base"}
        payload = {"event_type": "onramp.transaction.updated", "transaction": tx}
    event = adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]
    await svc._process_event(tenant, adapter, event, environment="sandbox")


async def test_cycle_continues_after_one_provider_pull_fails(monkeypatch):
    reset_in_memory_stores()
    svc = PaymentRailsService(PaymentRailsRepositories(), producer=_Producer())
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _seed_open(svc, tenant, "moonpay")
    await _seed_open(svc, tenant, "coinbase")

    pulled: list[str] = []
    orig = svc.status_sync

    async def _flaky_status_sync(tid, provider, **kwargs):
        if provider == "moonpay":
            raise RuntimeError("moonpay provider outage")
        pulled.append(provider)
        return await orig(tid, provider, **kwargs)

    monkeypatch.setattr(svc, "status_sync", _flaky_status_sync)

    # Must NOT raise despite moonpay failing, and coinbase must still be pulled.
    stats = await run_sync_cycle(service=svc)
    assert stats["tenants"] == 1
    assert "coinbase" in pulled  # the sweep continued past the moonpay failure
