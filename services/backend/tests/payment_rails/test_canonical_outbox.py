"""Atomic Bronze + event_outbox delivery for canonical payment events (PR3).

Default OFF: canonical payment_* events publish directly to the validated-events
bus via the injected producer (unchanged). When
``AETHER_PAYMENT_CANONICAL_OUTBOX_ENABLED`` is set, ``_emit_canonical_events``
instead writes each event atomically to the durable Bronze + event_outbox spine
(``ingest_many``); the supervised outbox relay publishes it later. The
deterministic canonical event id is the Bronze/outbox key, so a retry writes no
second outbox row — proving no-duplicate-on-replay end to end.
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
    canonical_event_id,
)

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


def _bronze():
    return _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})


def _outbox():
    return _IN_MEMORY_STORES.setdefault("event_outbox", {})


def _patch_outbox(monkeypatch, enabled: bool):
    monkeypatch.setattr(
        settings,
        "payment_rails",
        dataclasses.replace(settings.payment_rails, canonical_outbox_enabled=enabled),
    )


def _moonpay_event(adapter, tenant, *, tx_id="mp-1", status="completed", user_ref="user-1"):
    data = {"id": tx_id, "status": status, "externalCustomerId": user_ref,
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    events = adapter.parse_webhook(tenant, payload, payload_hash(payload))
    assert events
    return events[0]


# ── default OFF is unchanged (direct publish) ─────────────────────────────────

async def test_flag_off_publishes_directly_no_outbox(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, False)  # default
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    assert svc.producer.events  # published directly, as before
    assert _outbox() == {}      # nothing routed to the durable spine
    assert _bronze() == {}


# ── enabled: atomic Bronze + outbox, no direct publish ────────────────────────

async def test_flag_on_writes_bronze_and_outbox_not_producer(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, True)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    # a completed session implies payment_initiated + payment_completed
    assert svc.producer.events == []            # no direct publish on this path
    assert len(_bronze()) == 2 and len(_outbox()) == 2

    # every outbox row carries the deterministic canonical id as its event_id
    outbox_ids = {row["event_id"] for row in _outbox().values()}
    expected = {
        canonical_event_id(tenant, row["payload"]["session_id"], row["payload"]["event_type"])
        for row in _outbox().values()
    }
    assert outbox_ids == expected
    assert all(row["topic"] == "aether.sdk.events.validated" for row in _outbox().values())
    assert all(row["status"] == "pending" for row in _outbox().values())


async def test_flag_on_retry_after_lost_checkpoint_writes_no_second_outbox_row(monkeypatch):
    # A retry (checkpoint lost mid-crash) re-enters emission, but ingest_many
    # enqueues an outbox row only for a NEWLY-accepted Bronze row — the
    # deterministic id dedupes, so the outbox count never doubles.
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, True)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    first_outbox_ids = set(_outbox().keys())
    first_bronze_ids = set(_bronze().keys())
    assert first_outbox_ids and first_bronze_ids

    record = (await svc.repos.sessions.list_for_tenant(tenant))[0]
    record.setdefault("metadata", {})["emitted_canonical"] = []  # lost checkpoint
    await svc.repos.sessions.save(tenant, record)

    await svc._emit_canonical_events(tenant, adapter, record)

    assert set(_outbox().keys()) == first_outbox_ids  # no re-queue
    assert set(_bronze().keys()) == first_bronze_ids  # no duplicate Bronze row
