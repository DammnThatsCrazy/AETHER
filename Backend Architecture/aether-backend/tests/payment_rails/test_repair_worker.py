"""Supervised canonical-backlog repair for payment rails (PR3).

``repair_canonical_backlog`` recovers funding sessions whose implied ``payment_*``
canonical events were never delivered — a crash between the session upsert and
emission, or an outbox relay outage while the durable path is enabled. It scans
sessions, finds those whose expected canonical types are not all recorded in
``emitted_canonical``, and re-drives emission. Recovery is idempotent on BOTH
delivery paths (direct publish dedupes on ``emitted_canonical``; the outbox path
dedupes on the accepted Bronze row), so repeated runs never double-emit.
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


async def _wipe_checkpoint(svc, tenant):
    record = (await svc.repos.sessions.list_for_tenant(tenant))[0]
    record.setdefault("metadata", {})["emitted_canonical"] = []
    await svc.repos.sessions.save(tenant, record)


# ── direct-publish path (default) ─────────────────────────────────────────────

async def test_repair_recovers_a_missed_delivery(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, False)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    first_count = len(svc.producer.events)
    assert first_count >= 1  # initiated + completed

    await _wipe_checkpoint(svc, tenant)  # simulate a lost delivery
    svc.producer.events.clear()

    stats = await svc.repair_canonical_backlog(tenant)
    assert stats == {"scanned": 1, "repaired": 1, "events_reemitted": first_count}
    assert len(svc.producer.events) == first_count  # backlog recovered


async def test_repair_is_noop_when_nothing_is_missing(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, False)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    svc.producer.events.clear()

    stats = await svc.repair_canonical_backlog(tenant)
    assert stats["scanned"] == 1 and stats["repaired"] == 0
    assert svc.producer.events == []  # no double-emit


async def test_second_repair_after_recovery_is_a_noop(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, False)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    await _wipe_checkpoint(svc, tenant)
    await svc.repair_canonical_backlog(tenant)  # recovers
    svc.producer.events.clear()

    stats = await svc.repair_canonical_backlog(tenant)  # gap closed
    assert stats["repaired"] == 0
    assert svc.producer.events == []


# ── durable outbox path: repair re-enqueues idempotently ──────────────────────

async def test_repair_reenqueues_to_outbox_without_duplicates(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, True)
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    outbox_after_first = set(_outbox().keys())
    assert outbox_after_first

    await _wipe_checkpoint(svc, tenant)  # lost checkpoint, outbox rows still present

    stats = await svc.repair_canonical_backlog(tenant)
    assert stats["repaired"] == 1
    # deterministic id → ingest_many dedupes on the accepted Bronze row; no new rows
    assert set(_outbox().keys()) == outbox_after_first
