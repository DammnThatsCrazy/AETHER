"""Durable receipt lifecycle, canonical repair, and exact-decimal fees (CS2).

Covers the metadata-only provider-receipt ledger (one deterministic receipt per
delivery, forward-only stage machine), the scheduled canonical-repair worker
(idempotent crash recovery with no duplicate usage), and MoonPay's exact-decimal
fee handling. All in-memory (AETHER_ENV=local); no live network.
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
from services.integrations.providers.payment_rails.moonpay import _sum_fee  # noqa: E402
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    COMPLETE_STAGES,
    ReceiptStage,
    ReceiptState,
    receipt_id,
)
from services.integrations.providers.payment_rails.repair_worker import run_repair_cycle  # noqa: E402
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


def _mp_event(adapter, tenant, *, tx_id="mp-1", status="completed"):
    data = {"id": tx_id, "status": status, "externalCustomerId": "user-1",
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    return adapter.parse_webhook(tenant, payload, payload_hash(payload))[0]


# ── receipt lifecycle ─────────────────────────────────────────────────────────

async def test_accepted_webhook_receipt_reaches_completed():
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]
    event = _mp_event(adapter, tenant)
    result = await svc._process_event(
        tenant, adapter, event, environment="sandbox", endpoint_id="whe_abc"
    )
    rid = result["receipt_id"]
    receipt = await svc.repos.receipts.get(tenant, rid)
    assert receipt["current_stage"] == ReceiptStage.COMPLETED
    assert receipt["environment"] == "sandbox"
    assert receipt["endpoint_id"] == "whe_abc"
    assert receipt["funding_session_id"] == result["funding_session_id"]
    assert receipt["canonical_event_ids"]  # linked to the emitted canonical events
    assert receipt["completed_at"] is not None
    # metadata-only: never a plaintext secret or raw sensitive payload
    assert "secret" not in receipt and "payload" not in receipt


async def test_receipt_id_deterministic_across_retries():
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]
    event = _mp_event(adapter, tenant)
    r1 = await svc._process_event(tenant, adapter, event, environment="sandbox")
    r2 = await svc._process_event(tenant, adapter, event, environment="sandbox")
    assert r1["receipt_id"] == r2["receipt_id"]  # one receipt for a retry
    receipt = await svc.repos.receipts.get(tenant, r1["receipt_id"])
    assert receipt["processing_attempts"] == 2  # retry incremented the counter
    # the retry deduped — exactly the canonical events of ONE observation emitted
    assert r2["disposition"] == "ignored_duplicate"


async def test_reused_event_id_mutated_payload_quarantines_receipt():
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]
    ev1 = _mp_event(adapter, tenant, tx_id="mpX", status="completed")
    await svc._process_event(tenant, adapter, ev1, environment="sandbox")
    # same provider_event_id, different body hash → mutated-payload conflict
    ev2 = dataclasses_replace_event(ev1, raw_hash="deadbeef")
    r2 = await svc._process_event(tenant, adapter, ev2, environment="sandbox")
    assert r2["disposition"] == "rejected"
    receipt = await svc.repos.receipts.get(tenant, r2["receipt_id"])
    assert receipt["current_stage"] == ReceiptState.QUARANTINED


def dataclasses_replace_event(event, **changes):
    return event.model_copy(update=changes)


# ── canonical repair (crash recovery, idempotent) ─────────────────────────────

async def test_repair_recovers_emission_gap_without_duplicate_usage(monkeypatch):
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]
    event = _mp_event(adapter, tenant)
    result = await svc._process_event(tenant, adapter, event, environment="sandbox")
    first_emitted = len(svc.producer.events)
    assert first_emitted >= 1  # payment_initiated + payment_completed

    # Simulate a crash that lost the canonical delivery AFTER the session persisted.
    record = await svc.repos.sessions.get_record(tenant, result["funding_session_id"])
    record["metadata"]["emitted_canonical"] = []
    await svc.repos.sessions.save(tenant, record)

    stats = await svc.run_canonical_repair(tenant)
    assert stats["sessions_repaired"] == 1
    assert stats["events_reemitted"] == first_emitted
    # Re-driving twice more never re-emits (deterministic id dedupes → no rebill).
    again = await svc.run_canonical_repair(tenant)
    assert again["events_reemitted"] == 0


async def test_repair_worker_cycle_completes_stuck_receipt():
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]
    event = _mp_event(adapter, tenant)
    result = await svc._process_event(tenant, adapter, event, environment="sandbox")
    rid = result["receipt_id"]
    # Force the receipt back to an incomplete stage (as a mid-flight crash would).
    await svc.repos.receipts.advance(tenant, rid, ReceiptStage.FUNDING_SESSION_PERSISTED)
    receipt = await svc.repos.receipts.get(tenant, rid)
    receipt["current_stage"] = ReceiptStage.FUNDING_SESSION_PERSISTED
    await svc.repos.receipts._store.set(f"{tenant}:{rid}", receipt)

    stats = await run_repair_cycle(service=svc)
    assert stats["receipts_repaired"] >= 1
    healed = await svc.repos.receipts.get(tenant, rid)
    assert healed["current_stage"] in COMPLETE_STAGES
    assert healed["repair_attempts"] >= 1


async def test_receipt_id_helper_is_stable():
    a = receipt_id("t1", "moonpay", "whe_1", "evt_1", "hash_1")
    b = receipt_id("t1", "moonpay", "whe_1", "evt_1", "hash_2")  # event id wins
    c = receipt_id("t1", "moonpay", "whe_1", None, "hash_1")     # falls back to hash
    assert a == b  # provider_event_id is the discriminator when present
    assert a != c


# ── exact-decimal fees ────────────────────────────────────────────────────────

def test_sum_fee_exact_decimal_multiple_components():
    assert _sum_fee({"feeAmount": "0.1", "extraFeeAmount": "0.2"}) == "0.3"  # not 0.30000000004
    assert _sum_fee({"feeAmount": "1.005", "networkFeeAmount": "2.5"}) == "3.505"


def test_sum_fee_large_and_fractional_precision():
    assert _sum_fee({"feeAmount": "1000000.123456789"}) == "1000000.123456789"


def test_sum_fee_null_and_malformed():
    assert _sum_fee({}) is None                                   # nothing present → None
    assert _sum_fee({"feeAmount": None, "extraFeeAmount": ""}) is None
    # a present-but-malformed component → None (never a wrong partial / zero-coerce)
    assert _sum_fee({"feeAmount": "1.0", "extraFeeAmount": "abc"}) is None
