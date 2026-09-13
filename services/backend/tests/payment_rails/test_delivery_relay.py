"""D1 — relay-publish stage on the durable canonical-outbox path.

WHAT THIS COVERS / WHY IT WAS NEEDED
------------------------------------
When ``canonical_outbox_enabled`` is set, ``_process_event`` does NOT publish the
canonical ``payment_*`` events synchronously; it atomically enqueues them to the
durable Bronze + ``event_outbox`` spine and leaves the delivery receipt parked at
stage ``OUTBOX_ENQUEUED`` with ``outbox_publication_state="enqueued"``. The
supervised outbox relay drains (publishes) those rows asynchronously, and the
supervised canonical-repair sweep then confirms the delivery closed.

Previously the repair sweep advanced such a receipt straight from
``OUTBOX_ENQUEUED`` to ``COMPLETED`` — so a completed durable-path receipt kept a
stale ``outbox_publication_state="enqueued"`` and never recorded the
``OUTBOX_PUBLISHED`` transition, misrepresenting its own delivery state. The
accompanying product fix (``service.run_canonical_repair``) makes the sweep
advance the receipt THROUGH ``OUTBOX_PUBLISHED`` (flipping the publication state
to ``"published"``) before ``COMPLETED``.

This module asserts that relay-publish transition end to end:
  enqueue → (relay publishes) → receipt stage / outbox-pub-state advance,
and that it is idempotent (a re-run neither re-enqueues an outbox row nor
re-emits a canonical event).

DELIVERY-INTEGRITY GUARANTEE PROTECTED
--------------------------------------
A durable-path receipt's ledger truthfully records that its one canonical event
per observation was published — never a completed receipt that still claims its
canonical delivery is merely "enqueued". Idempotency keeps it one outbox row /
one canonical event on replay.
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
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    COMPLETE_STAGES,
    STAGE_ORDER,
    ReceiptStage,
)
from services.integrations.providers.payment_rails.repair_worker import (  # noqa: E402
    run_repair_cycle,
)
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)

pytestmark = pytest.mark.asyncio

_RANK = {stage: i for i, stage in enumerate(STAGE_ORDER)}


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
        settings, "payment_rails",
        dataclasses.replace(settings.payment_rails, canonical_outbox_enabled=enabled),
    )


def _moonpay_event(adapter, tenant, *, tx_id="mp-1", status="completed"):
    data = {"id": tx_id, "status": status, "externalCustomerId": "user-1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    return adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]


async def test_durable_receipt_reaches_outbox_published_after_relay(monkeypatch):
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, True)
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]

    result = await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    rid = result["receipt_id"]

    # Live pipeline parked the receipt at OUTBOX_ENQUEUED (durable path, no direct
    # publish), and the canonical events are durable outbox rows awaiting a relay.
    enqueued = await svc.repos.receipts.get(tenant, rid)
    assert enqueued["current_stage"] == ReceiptStage.OUTBOX_ENQUEUED
    assert enqueued["outbox_publication_state"] == "enqueued"
    assert enqueued["completed_at"] is None
    assert svc.producer.events == []  # durable path never uses the direct producer
    outbox_rows = set(_outbox().keys())
    assert len(outbox_rows) == 2  # payment_initiated + payment_completed

    # Supervised sweep = the relay having drained (published) the outbox rows:
    # the receipt advances THROUGH OUTBOX_PUBLISHED (pub-state -> "published").
    await svc.run_canonical_repair(tenant)

    published = await svc.repos.receipts.get(tenant, rid)
    assert published["outbox_publication_state"] == "published"
    assert published["current_stage"] in COMPLETE_STAGES
    # the receipt actually recorded reaching (or passing) the OUTBOX_PUBLISHED rank
    assert _RANK[published["current_stage"]] >= _RANK[ReceiptStage.OUTBOX_PUBLISHED]
    assert published["completed_at"] is not None

    # Idempotent: a second sweep neither re-enqueues an outbox row nor re-emits,
    # and the receipt stays published/complete.
    await svc.run_canonical_repair(tenant)
    again = await svc.repos.receipts.get(tenant, rid)
    assert again["outbox_publication_state"] == "published"
    assert set(_outbox().keys()) == outbox_rows  # no new rows
    assert svc.producer.events == []


async def test_repair_worker_cycle_publishes_durable_receipt(monkeypatch):
    """The same relay-publish advance is driven by the actual supervised repair
    worker (``run_repair_cycle``), not just the per-tenant entrypoint."""
    reset_in_memory_stores()
    _patch_outbox(monkeypatch, True)
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]

    result = await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    rid = result["receipt_id"]
    outbox_rows = set(_outbox().keys())

    stats = await run_repair_cycle(service=svc)
    assert stats["receipts_repaired"] >= 1

    receipt = await svc.repos.receipts.get(tenant, rid)
    assert receipt["outbox_publication_state"] == "published"
    assert receipt["current_stage"] in COMPLETE_STAGES
    assert set(_outbox().keys()) == outbox_rows  # relay confirm re-enqueues nothing
