"""Billing-outage-safe usage metering on the payment observation path (PR3).

Default OFF: nothing is metered. When AETHER_PAYMENT_USAGE_METERING_ENABLED is
set, each emitted payment_* canonical event records a RevOps usage-metering event
(accept-then-meter), keyed by the deterministic canonical event id so a
redelivery / repair re-emit dedupes. Metering is fail-open: a metering-store
failure never rejects or drops the observation.
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.billing.revops import UsageMeteringEventRepository  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import PaymentRailsService  # noqa: E402

pytestmark = pytest.mark.asyncio


class _RecordingProducer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


def _svc():
    return PaymentRailsService(
        repositories=PaymentRailsRepositories(), producer=_RecordingProducer()
    )


def _tenant():
    return f"t-{uuid.uuid4().hex[:8]}"


def _patch_meter(monkeypatch, enabled: bool):
    monkeypatch.setattr(
        settings, "payment_rails",
        dataclasses.replace(settings.payment_rails, usage_metering_enabled=enabled),
    )


def _moonpay_event(adapter, tenant, *, status="completed"):
    data = {"id": "mp-1", "status": status, "externalCustomerId": "user-1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    return adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]


async def _meters(tenant):
    return await UsageMeteringEventRepository().find_many(filters={"tenant_id": tenant})


async def test_flag_off_records_no_meter(monkeypatch):
    reset_in_memory_stores()
    _patch_meter(monkeypatch, False)  # default
    svc = _svc()
    tenant = _tenant()
    await svc._process_event(tenant, ADAPTERS["moonpay"], _moonpay_event(ADAPTERS["moonpay"], tenant))
    assert svc.producer.events        # observation emitted
    assert await _meters(tenant) == []  # nothing metered


async def test_flag_on_meters_each_emitted_event_idempotently(monkeypatch):
    reset_in_memory_stores()
    _patch_meter(monkeypatch, True)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    meters = await _meters(tenant)
    assert len(meters) == 2  # payment_initiated + payment_completed
    assert all(m["event_type"] == "payment_rail_observation_ingested" for m in meters)
    assert all(m["source_type"] == "payment_rail_canonical_event" for m in meters)

    # a repair re-emit (checkpoint wiped) re-meters the SAME deterministic ids → deduped
    record = (await svc.repos.sessions.list_for_tenant(tenant))[0]
    record["metadata"]["emitted_canonical"] = []
    await svc.repos.sessions.save(tenant, record)
    await svc._emit_canonical_events(tenant, adapter, record)
    assert len(await _meters(tenant)) == 2  # no double-count


async def test_metering_failure_is_fail_open(monkeypatch):
    reset_in_memory_stores()
    _patch_meter(monkeypatch, True)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    async def _boom(self, event):
        raise RuntimeError("meter store down")

    monkeypatch.setattr("services.billing.revops.MeteringService.record_event", _boom)

    result = await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    # the observation is still accepted + persisted despite the metering failure
    assert result.get("funding_session_id")
    assert len(await svc.repos.sessions.list_for_tenant(tenant)) == 1
