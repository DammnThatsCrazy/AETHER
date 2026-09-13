"""Stage-boundary failures: payment receipt ingestion.

Pipeline: RECEIVED -> ENDPOINT_RESOLVED -> SIGNATURE_VERIFIED -> PARSED ->
NORMALIZED -> FUNDING_SESSION_PERSISTED -> CANONICAL_EVENT_WRITTEN ->
OUTBOX_ENQUEUED -> OUTBOX_PUBLISHED -> CONSUMED_OR_PROJECTED -> COMPLETED.

A fault is injected at EVERY stage boundary (a write fails right before the
transition lands). Recovery is deterministic:

  * the failed write never advances the stage machine (the receipt stays at
    the last durable stage),
  * a replay completes exactly once (forward-only; a provider retry maps to
    the SAME receipt_id, so there is no duplicate receipt),
  * the outbox publish boundary never loses the receipt row and never
    double-delivers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parents[1] / "adversarial"
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import (  # noqa: E402
    BROKER_UNAVAILABLE,
    DB_UNAVAILABLE,
    CopyStore,
    FaultyStore,
    FaultInjector,
    assert_no_duplicates,
    expect_fault,
    make_fault,
)
from repositories.repos import BaseRepository  # noqa: E402
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    ProviderReceiptRepository,
    ReceiptStage,
    STAGE_ORDER,
)
from shared.outbox import GenericOutboxWorker  # noqa: E402

# Every non-RECEIVED stage is a boundary whose write can fail.
_BOUNDARIES = list(STAGE_ORDER[1:])


async def _drive_to(repo, tenant_id: str, rid: str, target: str) -> None:
    """Advance the receipt through every stage strictly before ``target``."""
    for stage in _BOUNDARIES:
        if stage == target:
            break
        await repo.advance(tenant_id, rid, stage)


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_stage", _BOUNDARIES)
async def test_write_failure_at_every_stage_boundary_never_advances_and_replays_once(failing_stage):
    repo = ProviderReceiptRepository()
    record = await repo.open("t1", "moonpay", provider_event_id=f"evt-{failing_stage}", environment="production")
    rid = record["receipt_id"]
    idx = _BOUNDARIES.index(failing_stage)
    prior_stage = _BOUNDARIES[idx - 1] if idx > 0 else ReceiptStage.RECEIVED

    # Drive the pipeline up to the boundary (every prior write landed).
    await _drive_to(repo, "t1", rid, failing_stage)
    assert (await repo.get("t1", rid))["current_stage"] == prior_stage

    # DB unavailable at exactly the failing write. CopyStore makes reads cross
    # a serialization boundary (faithful to a real DB): the failed set leaves
    # durable state untouched, so the stage machine must NOT advance.
    repo._store = FaultyStore(
        CopyStore(repo._store),
        {"set": FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")},
    )

    exc = await expect_fault(repo.advance("t1", rid, failing_stage), DB_UNAVAILABLE)
    assert faultkit.classify(exc) == DB_UNAVAILABLE
    assert (await repo.get("t1", rid))["current_stage"] == prior_stage

    # Disarm: the replay completes the ENTIRE pipeline exactly once.
    await repo.advance("t1", rid, failing_stage)
    for stage in _BOUNDARIES[_BOUNDARIES.index(failing_stage) + 1:]:
        await repo.advance("t1", rid, stage)
    final = await repo.get("t1", rid)
    assert final["current_stage"] == ReceiptStage.COMPLETED
    assert final["completed_at"] is not None

    # A provider retry maps to the SAME deterministic receipt — no duplicate.
    reopened = await repo.open("t1", "moonpay", provider_event_id=f"evt-{failing_stage}", environment="production")
    assert reopened["receipt_id"] == rid
    assert reopened["current_stage"] == ReceiptStage.COMPLETED  # forward-only, no regression


@pytest.mark.asyncio
async def test_outbox_publish_boundary_never_loses_receipt_and_recovers():
    """Broker unavailable at the OUTBOX_ENQUEUED -> OUTBOX_PUBLISHED boundary:
    the receipt row is never lost, the outbox row is retried exactly once, and
    the publish completes exactly once."""
    repo = ProviderReceiptRepository()
    record = await repo.open("t1", "stripe_onramp", provider_event_id="evt-outbox", environment="production")
    rid = record["receipt_id"]
    await repo.advance("t1", rid, ReceiptStage.OUTBOX_ENQUEUED)
    assert (await repo.get("t1", rid))["current_stage"] == ReceiptStage.OUTBOX_ENQUEUED

    # The outbox row this receipt enqueued.
    outbox = BaseRepository("receipt_outbox")
    await outbox.insert("outbox-1", {
        "id": "outbox-1", "tenant_id": "t1", "status": "queued", "attempts": 0,
        "receipt_id": rid, "created_at": "2026-08-09T00:00:00Z",
    })

    attempts = {"n": 0}

    async def sink(row):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("broker publish rejected (transient outage)")

    worker = GenericOutboxWorker(
        outbox, sink, name="receipt-outbox", max_attempts=3, backoff_base_s=0.0,
    )
    first = await worker.drain_once(tenant_id="t1")
    assert first["failed"] == 1 and first["dead_lettered"] == 0
    # The receipt did not fabricate an advance on the failed publish.
    assert (await repo.get("t1", rid))["current_stage"] == ReceiptStage.OUTBOX_ENQUEUED

    second = await worker.drain_once(tenant_id="t1")
    assert second["succeeded"] == 1
    row = await outbox.find_by_id("outbox-1")
    assert row["status"] == "persisted" and row["attempts"] == 2  # exactly one retry

    # Publish landed once; the receipt completes once.
    await repo.advance("t1", rid, ReceiptStage.OUTBOX_PUBLISHED)
    await repo.advance("t1", rid, ReceiptStage.COMPLETED)
    final = await repo.get("t1", rid)
    assert final["current_stage"] == ReceiptStage.COMPLETED
    assert attempts["n"] == 2  # no duplicate delivery, no lost row


@pytest.mark.asyncio
async def test_terminal_mark_state_boundary_is_durable_and_no_duplicate_rows():
    """REJECTED / QUARANTINED writes also cross the durable boundary: a store
    failure during mark_state leaves the receipt at its prior stage, and the
    terminal write lands exactly once."""
    for state in ("rejected", "quarantined"):
        repo = ProviderReceiptRepository()
        record = await repo.open("t1", "kyber_routes", provider_event_id=f"evt-{state}", environment="production")
        rid = record["receipt_id"]

        repo._store = FaultyStore(
            CopyStore(repo._store),
            {"set": FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")},
        )
        await expect_fault(repo.mark_state("t1", rid, state, reason="bad signature"), DB_UNAVAILABLE)
        assert (await repo.get("t1", rid))["current_stage"] == ReceiptStage.RECEIVED

        terminal = await repo.mark_state("t1", rid, state, reason="bad signature")
        assert terminal["current_stage"] == state
        assert terminal["rejection_reason"] == "bad signature"

    rows = await ProviderReceiptRepository().list_for_tenant("t1")
    assert_no_duplicates(rows, "receipt_id", label="payment receipt")
    assert len(rows) == 2  # one terminal receipt per injected state
