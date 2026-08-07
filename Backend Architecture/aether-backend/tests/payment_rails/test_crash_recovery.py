"""D3 — crash-after-each-stage recovery through the supervised repair worker.

WHAT THIS COVERS / WHY IT WAS NEEDED
------------------------------------
Deterministic canonical delivery can be interrupted by a crash at ANY point in
the receipt lifecycle (received → … → funding_session_persisted →
canonical_event_written → outbox_enqueued → … → completed). ``test_receipt_
lifecycle.py`` proves the repair worker completes a receipt stuck at ONE stage
(funding_session_persisted). This module systematically simulates an
interruption after EACH stage and asserts the supervised repair worker
(``run_repair_cycle``) re-drives every recoverable delivery to completion
IDEMPOTENTLY, while never fabricating state it cannot reconstruct.

Two regimes, split along the only boundary that matters — whether the receipt
had linked its FundingSession before the crash:

  1. Recoverable crashes (at/after ``funding_session_persisted``): the receipt
     knows its funding session, so repair re-drives to a completion stage. We
     assert the delivery-integrity invariants hold across the repair:
       * exactly ONE receipt and ONE FundingSession for the observation;
       * exactly ONE canonical event per observation + type (two deterministic
         ids: payment_initiated + payment_completed) even when the crash lost the
         canonical delivery and repair must re-emit it;
       * NO duplicate usage metering (billing safety) — metering is keyed by the
         deterministic canonical id and dedupes on re-emit;
       * a final completion stage is visible; and
       * the repair OUTCOME is recorded/audited on the receipt (repair_attempts
         incremented + a bounded repair_history entry).

  2. Pre-session crashes (before ``funding_session_persisted``): the receipt has
     no funding session to re-drive and the ledger stores no raw payload, so
     repair must NOT fabricate a session. We assert it records a bounded
     ``no_funding_session`` repair attempt and, after ``MAX_REPAIR_ATTEMPTS``,
     dead-letters the delivery (a durable, inspectable terminal record) rather
     than looping forever — a pre-session crash is instead recovered by the
     provider's own redelivery, which maps to the SAME deterministic receipt.

DELIVERY-INTEGRITY GUARANTEE PROTECTED
--------------------------------------
One receipt / one FundingSession / one canonical event per observation / no
duplicate usage — preserved across a crash at any lifecycle stage, with an
honest, bounded terminal for deliveries that cannot be reconstructed.
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
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    COMPLETE_STAGES,
    ReceiptStage,
    ReceiptState,
)
from services.integrations.providers.payment_rails.repair_worker import (  # noqa: E402
    run_repair_cycle,
)
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


def _enable_metering(monkeypatch):
    monkeypatch.setattr(
        settings, "payment_rails",
        dataclasses.replace(settings.payment_rails, usage_metering_enabled=True),
    )


def _moonpay_event(adapter, tenant, *, tx_id="mp-1", status="completed"):
    data = {"id": tx_id, "status": status, "externalCustomerId": "user-1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    return adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]


async def _meters(tenant):
    return await UsageMeteringEventRepository().find_many(filters={"tenant_id": tenant})


async def _rewind_receipt(svc, tenant, rid, stage):
    """Force a receipt back to ``stage`` as a mid-flight crash would leave it.

    ``advance`` is forward-only by design, so a crash (which reverts nothing but
    simply never progressed past ``stage``) is simulated by writing the stored
    stage back directly — exactly as ``test_receipt_lifecycle`` does.
    """
    receipt = await svc.repos.receipts.get(tenant, rid)
    receipt["current_stage"] = stage
    await svc.repos.receipts._store.set(f"{tenant}:{rid}", receipt)
    return receipt


# ── 1. recoverable crashes: at/after funding_session_persisted ────────────────

# (crash_stage, canonical_delivered_before_crash)
_RECOVERABLE = [
    (ReceiptStage.FUNDING_SESSION_PERSISTED, False),  # crashed before canonical write
    (ReceiptStage.CANONICAL_EVENT_WRITTEN, True),     # canonical written, delivery not closed
    (ReceiptStage.OUTBOX_ENQUEUED, True),             # enqueued, receipt not completed
]


@pytest.mark.parametrize("crash_stage, canonical_delivered", _RECOVERABLE)
async def test_repair_redrives_each_stage_to_completion_idempotently(
    monkeypatch, crash_stage, canonical_delivered
):
    reset_in_memory_stores()
    _enable_metering(monkeypatch)
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]

    # A complete, correct delivery first (session + 2 canonical events + 2 meters).
    result = await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    rid, fsid = result["receipt_id"], result["funding_session_id"]
    assert len(await _meters(tenant)) == 2

    expected_ids = {
        canonical_event_id(tenant, e.payload["session_id"], e.payload["event_type"])
        for e in svc.producer.events
    }
    assert len(expected_ids) == 2

    # Simulate the crash: rewind the receipt stage, and if the crash preceded the
    # canonical write, ALSO drop the canonical delivery (emitted_canonical /
    # receipt linkage) so repair must re-emit it to close the gap.
    await _rewind_receipt(svc, tenant, rid, crash_stage)
    if not canonical_delivered:
        record = await svc.repos.sessions.get_record(tenant, fsid)
        record["metadata"]["emitted_canonical"] = []
        await svc.repos.sessions.save(tenant, record)
        receipt = await svc.repos.receipts.get(tenant, rid)
        receipt["canonical_event_ids"] = []
        await svc.repos.receipts._store.set(f"{tenant}:{rid}", receipt)

    # The supervised repair worker re-drives the interrupted delivery.
    stats = await run_repair_cycle(service=svc)
    assert stats["receipts_repaired"] >= 1

    # Still exactly ONE receipt and ONE funding session.
    receipts = await svc.repos.receipts.list_for_tenant(tenant)
    assert len(receipts) == 1
    assert len(await svc.repos.sessions.list_for_tenant(tenant)) == 1

    healed = receipts[0]
    # A final completion stage is visible + the repair outcome is recorded.
    assert healed["current_stage"] in COMPLETE_STAGES
    assert healed["completed_at"] is not None
    assert healed["repair_attempts"] >= 1
    assert healed["repair_history"]
    assert healed["repair_history"][-1]["outcome"] in ("reemitted", "advanced")

    # One canonical event per observation + type — two DETERMINISTIC ids, whether
    # or not repair had to re-emit them; and usage metered exactly once each.
    got_ids = {
        canonical_event_id(tenant, e.payload["session_id"], e.payload["event_type"])
        for e in svc.producer.events
    }
    assert got_ids == expected_ids
    session = (await svc.repos.sessions.list_for_tenant(tenant))[0]
    assert sorted(session["metadata"]["emitted_canonical"]) == [
        "payment_completed", "payment_initiated",
    ]
    assert len(await _meters(tenant)) == 2  # NO duplicate usage metering

    # Idempotent: a second sweep changes nothing (no re-emit, no re-bill).
    meters_before = len(await _meters(tenant))
    producer_ids_before = {
        canonical_event_id(tenant, e.payload["session_id"], e.payload["event_type"])
        for e in svc.producer.events
    }
    await run_repair_cycle(service=svc)
    assert len(await _meters(tenant)) == meters_before
    assert {
        canonical_event_id(tenant, e.payload["session_id"], e.payload["event_type"])
        for e in svc.producer.events
    } == producer_ids_before
    assert len(await svc.repos.sessions.list_for_tenant(tenant)) == 1


# ── 2. pre-session crashes: honest, bounded, never fabricated ─────────────────

_PRE_SESSION = [
    ReceiptStage.RECEIVED,
    ReceiptStage.SIGNATURE_VERIFIED,
    ReceiptStage.PARSED,
    ReceiptStage.NORMALIZED,
]


@pytest.mark.parametrize("crash_stage", _PRE_SESSION)
async def test_pre_session_crash_is_not_fabricated_and_is_bounded(monkeypatch, crash_stage):
    reset_in_memory_stores()
    _enable_metering(monkeypatch)
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]

    result = await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    rid = result["receipt_id"]

    # Model a crash before the funding session was linked: rewind the stage AND
    # unlink the funding session (the ledger stores no raw payload, so a receipt
    # with no funding_session_id cannot be re-driven from the ledger alone).
    receipt = await svc.repos.receipts.get(tenant, rid)
    receipt["current_stage"] = crash_stage
    receipt["funding_session_id"] = None
    await svc.repos.receipts._store.set(f"{tenant}:{rid}", receipt)

    # One repair pass records a bounded ``no_funding_session`` attempt; it does
    # NOT complete the receipt and does NOT fabricate a second funding session.
    stats = await svc.run_canonical_repair(tenant)
    assert stats["receipts_repaired"] == 0
    healed = await svc.repos.receipts.get(tenant, rid)
    assert healed["current_stage"] == crash_stage  # not advanced/fabricated
    assert healed["repair_attempts"] >= 1
    assert healed["repair_history"][-1]["outcome"] == "no_funding_session"
    # the original observation's session is untouched — never duplicated
    assert len(await svc.repos.sessions.list_for_tenant(tenant)) == 1


async def test_pre_session_crash_dead_letters_after_max_attempts(monkeypatch):
    """A pre-session delivery that can never be reconstructed is dead-lettered
    after ``MAX_REPAIR_ATTEMPTS`` — a durable terminal record, never an infinite
    repair loop."""
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]

    result = await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    rid = result["receipt_id"]

    receipt = await svc.repos.receipts.get(tenant, rid)
    receipt["current_stage"] = ReceiptStage.NORMALIZED
    receipt["funding_session_id"] = None
    receipt["repair_attempts"] = svc.MAX_REPAIR_ATTEMPTS  # at the bound
    await svc.repos.receipts._store.set(f"{tenant}:{rid}", receipt)

    stats = await svc.run_canonical_repair(tenant)
    assert stats["receipts_dead_lettered"] == 1
    dead = await svc.repos.receipts.get(tenant, rid)
    assert dead["current_stage"] == ReceiptState.DEAD_LETTERED
    assert dead["rejection_reason"] == "no_funding_session_after_max_repair"
