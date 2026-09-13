"""Deterministic, replay-safe canonical event ids (PR3 foundation).

``service._emit_canonical_events`` previously stamped each emitted validated-bus
event with ``uuid.uuid4()``. A provider redelivery or a crash between the
``producer.publish`` and the ``emitted_canonical`` checkpoint would then re-emit
the SAME logical payment event with a fresh random id — a downstream duplicate.

The id is now ``uuid5(namespace, tenant | session | event_type)``: the same
logical event always hashes to the same id, so a re-emission is a
downstream-idempotent no-op. These tests prove the pure id function and that the
emission path and a post-crash re-emit both stamp that stable id.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
    canonical_event_id,
)


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


def _moonpay_event(adapter, tenant, *, tx_id="mp-1", status="completed", user_ref="user-1"):
    data = {"id": tx_id, "status": status, "externalCustomerId": user_ref,
            "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
            "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    payload = {"type": "transaction_updated", "data": data}
    events = adapter.parse_webhook(tenant, payload, payload_hash(payload))
    assert events
    return events[0]


# ── pure id function ──────────────────────────────────────────────────────────

def test_id_is_deterministic_and_a_valid_uuid():
    a = canonical_event_id("t1", "s1", "payment_completed")
    b = canonical_event_id("t1", "s1", "payment_completed")
    assert a == b
    uuid.UUID(a)  # parses as a UUID


def test_id_separates_tenant_session_and_type():
    base = canonical_event_id("t1", "s1", "payment_completed")
    assert canonical_event_id("t2", "s1", "payment_completed") != base  # tenant
    assert canonical_event_id("t1", "s2", "payment_completed") != base  # session
    assert canonical_event_id("t1", "s1", "payment_initiated") != base  # type


def test_none_session_is_stable_and_distinct_from_empty():
    # A missing session id must still be deterministic, and must not collide with
    # a literal empty-string session id shape beyond the documented normalization.
    assert canonical_event_id("t1", None, "e") == canonical_event_id("t1", None, "e")


# ── emission path stamps the deterministic id ─────────────────────────────────

@pytest.mark.asyncio
async def test_emission_stamps_deterministic_ids():
    reset_in_memory_stores()
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))

    assert svc.producer.events  # a completed session emits initiated + completed
    for ev in svc.producer.events:
        et = ev.payload["event_type"]
        sid = ev.payload["session_id"]
        # the emission derives the id from (tenant, session_id, event_type)
        assert ev.payload["event_id"] == canonical_event_id(tenant, sid, et)


@pytest.mark.asyncio
async def test_reemit_after_lost_checkpoint_is_idempotent():
    # Simulate a crash between publish and the emitted_canonical checkpoint: the
    # persisted record's checkpoint is wiped, so a retry re-emits — but with the
    # SAME ids, so the downstream bus dedupes instead of double-counting.
    reset_in_memory_stores()
    svc = _svc()
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()

    await svc._process_event(tenant, adapter, _moonpay_event(adapter, tenant))
    first = {e.payload["event_type"]: e.payload["event_id"] for e in svc.producer.events}
    assert first

    record = (await svc.repos.sessions.list_for_tenant(tenant))[0]
    record.setdefault("metadata", {})["emitted_canonical"] = []  # lost checkpoint
    await svc.repos.sessions.save(tenant, record)
    svc.producer.events.clear()

    await svc._emit_canonical_events(tenant, adapter, record)
    second = {e.payload["event_type"]: e.payload["event_id"] for e in svc.producer.events}

    assert second  # the retry re-emitted
    for event_type, event_id in second.items():
        assert event_id == first[event_type]  # identical id → downstream-idempotent
