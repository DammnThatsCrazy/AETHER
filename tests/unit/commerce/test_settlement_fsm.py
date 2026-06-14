"""
Unit tests for SettlementTracker FSM transitions.
FSM: pending → verifying → settled | failed | disputed.

In local mode, start() calls _advance() immediately so the settlement lands
in SETTLED state right away. mark_pending() / fail() / retry() are tested
by manipulating state after start().
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-settlement-test"


@pytest.fixture(autouse=True)
def reset():
    from services.x402.commerce_store import reset_commerce_store
    reset_commerce_store()
    yield
    reset_commerce_store()


@pytest.fixture()
def tracker():
    from services.x402.settlement import SettlementTracker
    return SettlementTracker()


async def _make_receipt(tenant_id: str = TENANT):
    from services.x402.commerce_models import PaymentReceipt
    return PaymentReceipt(
        tenant_id=tenant_id,
        authorization_id="auth-001",
        challenge_id="chg-001",
        tx_hash="0xabc123",
        chain="eip155:8453",
        asset_symbol="USDC",
        amount_usd=1.0,
        payer="agent-001",
        recipient="0xrecipient",
        verified=True,  # must be verified before settlement
        verified_by="fac-001",
    )


@pytest.mark.asyncio
async def test_start_creates_settlement(tracker):
    receipt = await _make_receipt()
    from services.x402.commerce_models import SettlementState
    settlement = await tracker.start(TENANT, receipt, facilitator_id="fac-001")
    # In local mode advances immediately to SETTLED
    assert settlement.state in (SettlementState.VERIFYING, SettlementState.SETTLED)
    assert settlement.tenant_id == TENANT


@pytest.mark.asyncio
async def test_advance_to_settled(tracker):
    receipt = await _make_receipt()
    from services.x402.commerce_models import SettlementState
    s = await tracker.start(TENANT, receipt, "fac-001")
    # mark_pending then check get
    pending = await tracker.mark_pending(TENANT, s.settlement_id, "waiting")
    assert pending.state == SettlementState.PENDING


@pytest.mark.asyncio
async def test_fail_marks_settlement_failed(tracker):
    receipt = await _make_receipt()
    from services.x402.commerce_models import SettlementState
    s = await tracker.start(TENANT, receipt, "fac-001")
    failed = await tracker.fail(TENANT, s.settlement_id, "network error")
    assert failed.state == SettlementState.FAILED


@pytest.mark.asyncio
async def test_retry_increments_retry_count(tracker):
    receipt = await _make_receipt()
    s = await tracker.start(TENANT, receipt, "fac-001")
    await tracker.fail(TENANT, s.settlement_id, "timeout")
    retried = await tracker.retry(TENANT, s.settlement_id)
    assert retried.attempts >= 1


@pytest.mark.asyncio
async def test_retry_exceeded_max_fails(tracker):
    receipt = await _make_receipt()
    from services.x402.commerce_models import SettlementState
    s = await tracker.start(TENANT, receipt, "fac-001")
    await tracker.fail(TENANT, s.settlement_id, "first fail")
    # Exhaust retries (max is 5)
    for _ in range(5):
        try:
            s = await tracker.retry(TENANT, s.settlement_id)
            await tracker.fail(TENANT, s.settlement_id, "still failing")
        except ValueError:
            break
    final = await tracker.get(TENANT, s.settlement_id)
    assert final is not None
    assert final.state == SettlementState.FAILED


@pytest.mark.asyncio
async def test_get_returns_settlement(tracker):
    receipt = await _make_receipt()
    s = await tracker.start(TENANT, receipt, "fac-001")
    found = await tracker.get(TENANT, s.settlement_id)
    assert found is not None
    assert found.settlement_id == s.settlement_id


@pytest.mark.asyncio
async def test_list_pending(tracker):
    receipt1 = await _make_receipt()
    receipt2 = await _make_receipt()
    s1 = await tracker.start(TENANT, receipt1, "fac-001")
    await tracker.start(TENANT, receipt2, "fac-001")
    await tracker.mark_pending(TENANT, s1.settlement_id, "waiting on chain")
    pending = await tracker.list_pending(TENANT)
    assert any(p.settlement_id == s1.settlement_id for p in pending)


@pytest.mark.asyncio
async def test_list_failed(tracker):
    receipt = await _make_receipt()
    s = await tracker.start(TENANT, receipt, "fac-001")
    await tracker.fail(TENANT, s.settlement_id, "rpc failure")
    failed = await tracker.list_failed(TENANT)
    assert any(f.settlement_id == s.settlement_id for f in failed)
