"""Reward rail matrix + sender dispatch — P5 invariants.

Pins the classification matrix, the sender indirection (outbox can dispatch
every deliverable rail, not just tenant_webhook), the bidirectional validator,
and internal_credit double-entry idempotency.
"""

from __future__ import annotations

import os
import sys
import uuid
from decimal import Decimal

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def test_matrix_generator_is_deterministic():
    from services.rewards.rail_matrix import build_rail_matrix

    assert build_rail_matrix() == build_rail_matrix()
    m = build_rail_matrix()
    assert m["summary"]["total"] == 10
    assert m["summary"]["by_tier"]["intentionally_unsupported"] == 2


def test_bidirectional_validator_passes():
    import subprocess

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    # locate repo root that holds scripts/
    here = os.path.dirname(__file__)
    repo = here
    for _ in range(6):
        repo = os.path.dirname(repo)
        if os.path.exists(os.path.join(repo, "scripts", "release", "check_reward_rail_matrix.py")):
            break
    proc = subprocess.run(
        [sys.executable, os.path.join(repo, "scripts", "release", "check_reward_rail_matrix.py")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_configurable_deliverable_rail_has_a_sender():
    from services.rewards.rail_matrix import CONFIGURABLE_TIERS, RAIL_MATRIX
    from services.rewards.senders import has_sender

    for name, c in RAIL_MATRIX.items():
        if c.tier in CONFIGURABLE_TIERS and c.delivery_mode in ("sync_api", "internal_ledger"):
            assert has_sender(name), f"{name} deliverable but has no sender"


def test_intentionally_unsupported_have_no_sender():
    from services.rewards.senders import has_sender

    assert not has_sender("loyalty_points")
    assert not has_sender("coupon")


@pytest.mark.asyncio
async def test_internal_credit_sender_double_entry_and_idempotent():
    from services.rewards.credit_ledger import get_internal_credit_ledger
    from services.rewards.senders import InternalCreditSender

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    job = {
        "tenant_id": tenant, "action_id": "a1",
        "payload": {
            "recipient_id": "r1", "campaign_id": "c1",
            "amount": "7.25", "currency": "USD", "idempotency_key": "idem-x",
        },
    }
    r1 = await InternalCreditSender().send(job)
    assert r1.outcome == "success"
    r2 = await InternalCreditSender().send(job)  # replay
    assert r2.outcome == "success"
    bal = await get_internal_credit_ledger().get_balance(tenant, "r1", "USD")
    assert bal == Decimal("7.25")  # not doubled


@pytest.mark.asyncio
async def test_stripe_credit_sender_fail_closed_without_credential(monkeypatch):
    from services.rewards.senders import StripeCreditSender

    monkeypatch.setenv("AETHER_ENV", "staging")
    job = {
        "tenant_id": f"t-{uuid.uuid4().hex[:8]}",
        "payload": {
            "customer_ref": "cus_x", "amount": "5.00",
            "currency": "usd", "idempotency_key": "s-idem",
        },
        "provider_config": {},
    }
    result = await StripeCreditSender().send(job)
    assert result.outcome == "fatal"
    assert "credential" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_outbox_enqueue_refuses_rail_without_sender():
    from services.rewards.delivery_outbox import RewardDeliveryOutbox

    outbox = RewardDeliveryOutbox()
    with pytest.raises(ValueError, match="no registered outbox sender"):
        await outbox.enqueue({"rail": "loyalty_points", "payload": {}}, {}, "t1")


@pytest.mark.asyncio
async def test_outbox_dispatches_internal_credit_end_to_end():
    from services.rewards.credit_ledger import get_internal_credit_ledger
    from services.rewards.delivery_outbox import RewardDeliveryOutbox

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    outbox = RewardDeliveryOutbox()
    action = {
        "id": "act-1", "rail": "internal_credit",
        "payload": {
            "recipient_id": "r9", "campaign_id": "c9", "amount": "3.00",
            "currency": "USD", "idempotency_key": f"e2e-{uuid.uuid4().hex[:8]}",
        },
    }
    await outbox.enqueue(action, {}, tenant)
    summary = await outbox.drain()
    assert summary["delivered"] >= 1
    bal = await get_internal_credit_ledger().get_balance(tenant, "r9", "USD")
    assert bal == Decimal("3.00")
