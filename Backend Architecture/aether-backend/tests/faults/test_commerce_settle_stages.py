"""Stage-boundary failures: x402 commerce settlement.

Pipeline: receive (verified payment receipt) -> start (VERIFYING) -> settle
(SETTLED) -> emit events -> retry (bounded attempts, retried_from chain).

Boundary recovery asserted:

  * receive: an unverified receipt raises BEFORE anything is persisted — no
    settlement row, no event (distinguishable from healthy-empty).
  * persist: a store write failure raises loudly and the retry persists
    exactly one settlement — no duplicate, no fabricated success.
  * emit: a producer/broker publish failure is non-fatal — the settlement still
    settles (the store is authoritative, events are best-effort).
  * settle: a settled settlement is never re-settled by the sweeper
    (list_pending is empty).
  * retry: a failed settlement retries with an incremented attempt count and a
    ``retried_from`` chain; at max attempts it fails with a visible reason
    rather than looping forever.
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
    DB_UNAVAILABLE,
    BROKER_UNAVAILABLE,
    arm,
    expect_fault,
    make_fault,
)
from services.x402.commerce_models import (  # noqa: E402
    PaymentReceipt,
    Settlement,
    SettlementState,
)
from services.x402.commerce_store import (  # noqa: E402
    get_commerce_store,
    reset_commerce_store,
)
from services.x402.settlement import SettlementTracker  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_commerce():
    reset_commerce_store()
    yield
    reset_commerce_store()


def _receipt(*, verified: bool = True, receipt_id: str = "rcpt-1") -> PaymentReceipt:
    return PaymentReceipt(
        receipt_id=receipt_id,
        tenant_id="t1",
        authorization_id="auth-1",
        challenge_id="ch-1",
        tx_hash="0xsettle",
        chain="base",
        asset_symbol="USDC",
        amount_usd=100.0,
        payer="0x" + "a" * 40,
        recipient="0x" + "b" * 40,
        verified=verified,
    )


# ── receive boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_receive_boundary_unverified_receipt_raises_and_persists_nothing():
    tracker = SettlementTracker()
    exc = await expect_fault(
        tracker.start("t1", _receipt(verified=False), facilitator_id="fac-1"),
        None,
    )
    assert isinstance(exc, ValueError)
    assert "unverified receipt" in str(exc)
    assert await get_commerce_store().list_settlements("t1") == []


# ── persist boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_boundary_store_unavailable_raises_then_settles_once():
    tracker = SettlementTracker()
    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")
    restore = arm(tracker._store, "put_settlement", injector)

    exc = await expect_fault(
        tracker.start("t1", _receipt(), facilitator_id="fac-1"), DB_UNAVAILABLE,
    )
    assert faultkit.classify(exc) == DB_UNAVAILABLE
    assert await get_commerce_store().list_settlements("t1") == []

    restore()
    settlement = await tracker.start("t1", _receipt(), facilitator_id="fac-1")
    assert settlement.state == SettlementState.SETTLED
    assert len(await get_commerce_store().list_settlements("t1")) == 1


# ── emit boundary ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_boundary_broker_failure_is_non_fatal_settlement_still_lands():
    """The store is authoritative; event publish is best-effort. A broker
    failure at the emit boundary must not abort the settlement."""
    tracker = SettlementTracker()
    injector = faultkit.FaultInjector(make_fault(BROKER_UNAVAILABLE), mode="always")
    arm(tracker._producer, "publish", injector)

    settlement = await tracker.start("t1", _receipt(), facilitator_id="fac-1")
    assert settlement.state == SettlementState.SETTLED
    persisted = await get_commerce_store().get_settlement("t1", settlement.settlement_id)
    assert persisted is not None and persisted.state == SettlementState.SETTLED


# ── settle boundary ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_settle_boundary_settled_never_resettled_by_sweeper():
    tracker = SettlementTracker()
    await tracker.start("t1", _receipt(), facilitator_id="fac-1")
    # The sweeper only re-drives PENDING settlements; a SETTLED one is terminal.
    assert await tracker.list_pending("t1") == []
    assert len(await tracker.list_failed("t1")) == 0


# ── retry boundary ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_boundary_attempts_chain_and_max_attempts_fails_visibly():
    tracker = SettlementTracker()
    first = await tracker.start("t1", _receipt(), facilitator_id="fac-1")
    assert first.attempts == 1

    # A failed settlement is retried: attempt increments and retried_from links.
    await tracker.fail("t1", first.settlement_id, "insufficient liquidity")
    retried = await tracker.retry("t1", first.settlement_id)
    assert retried.attempts == 2
    assert retried.retried_from == first.settlement_id
    assert retried.state == SettlementState.SETTLED

    # At max attempts the retry fails with a visible reason, not a loop.
    exhausted = Settlement(
        tenant_id="t1", receipt_id="rcpt-ex", challenge_id="ch-ex",
        state=SettlementState.FAILED, tx_hash="0xex", chain="base",
        amount_usd=1.0, facilitator_id="fac-1", attempts=5, max_attempts=5,
    )
    await get_commerce_store().put_settlement(exhausted)
    terminal = await tracker.retry("t1", exhausted.settlement_id)
    assert terminal.state == SettlementState.FAILED
    assert terminal.failure_reason == "max attempts exceeded"
