"""
Unit tests for reward claim reconciliation (A6).

Covers the durable-proof ↔ delivery-receipt binding:
    - nonce/replay guard (guard_and_persist_proof refuses replayed nonces)
    - reconcile_receipt marks a proof used + transitions the action to
      delivered, idempotently
    - the embedded-proof path (proof inside the action payload, no separate
      proof row) backfills a proof row and marks it used
    - reconcile_tenant / claim_reconciliation_status summaries
    - non-confirmed / non-onchain-claim receipts are safe no-ops

All tests run against the in-memory repo backend (AETHER_ENV=local); the
per-table stores are reset before each test.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.rewards.reconcile import (
    NonceReplayError,
    RewardClaimReconciler,
    get_reward_claim_reconciler,
    reset_reward_claim_reconciler,
)
from services.rewards.repositories import (
    RewardActionRepository,
    RewardProofRepository,
    RewardReceiptRepository,
)

TENANT = "tenant_reconcile_a"


def _run(coro):
    # These sync tests may run in the same process as pytest-asyncio async tests
    # (auto mode), which tears down its event loop between tests — so the
    # main-thread loop may not exist here. Create one rather than raising.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_in_memory_stores()
    reset_reward_claim_reconciler()
    yield
    reset_in_memory_stores()
    reset_reward_claim_reconciler()


def _make_reconciler() -> RewardClaimReconciler:
    return RewardClaimReconciler(
        proof_repo=RewardProofRepository(),
        action_repo=RewardActionRepository(),
        receipt_repo=RewardReceiptRepository(),
    )


def _make_proof(tenant_id: str = TENANT, nonce: str | None = None) -> dict:
    reconciler = _make_reconciler()
    nonce = nonce or uuid.uuid4().hex
    return _run(reconciler.guard_and_persist_proof(
        tenant_id,
        {
            "decision_id": "dec_1",
            "user": "0x1234567890abcdef1234567890abcdef12345678",
            "chain_id": 8453,
            "vm_type": "evm",
            "proof_format": "eip191",
        },
        nonce=nonce,
    ))


# ── Nonce / replay guard ────────────────────────────────────────────────────

def test_guard_and_persist_proof_records_nonce():
    reconciler = _make_reconciler()
    nonce = uuid.uuid4().hex
    record = _run(reconciler.guard_and_persist_proof(TENANT, {"user": "0xabc"}, nonce=nonce))
    assert record.get("nonce") == nonce
    assert record.get("tenant_id") == TENANT
    assert _run(reconciler.is_nonce_available(nonce)) is False


def test_guard_refuses_replayed_nonce():
    reconciler = _make_reconciler()
    nonce = uuid.uuid4().hex
    _run(reconciler.guard_and_persist_proof(TENANT, {"user": "0xabc"}, nonce=nonce))
    with pytest.raises(NonceReplayError):
        _run(reconciler.guard_and_persist_proof(TENANT, {"user": "0xdef"}, nonce=nonce))


def test_is_nonce_available_empty():
    reconciler = _make_reconciler()
    assert _run(reconciler.is_nonce_available("")) is False


# ── reconcile_receipt: proof row path ───────────────────────────────────────

def test_reconcile_receipt_marks_proof_used_and_delivers_action():
    reconciler = _make_reconciler()
    proof = _make_proof()
    action = _run(reconciler._actions.create(TENANT, {
        "decision_id": "dec_1",
        "rail": "onchain_claim",
        "payload": {"proof": {"nonce": proof["nonce"]}},
        "status": "created",
    }))
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
        "action_payload_id": action["id"],
    }))

    result = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert result["changed"] is True

    stored = _run(reconciler._proofs.find_by_id(proof["id"]))
    assert stored["status"] == "used"
    assert stored.get("used_at")

    action_after = _run(reconciler._actions.get(action["id"], TENANT))
    assert action_after["status"] == "delivered"


def test_reconcile_receipt_is_idempotent():
    reconciler = _make_reconciler()
    proof = _make_proof()
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "delivered",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
    }))

    first = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert first["changed"] is True

    second = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert second["changed"] is False
    assert second["reason"] == "proof_already_used"


def test_reconcile_receipt_unconfirmed_status_is_noop():
    reconciler = _make_reconciler()
    proof = _make_proof()
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "pending",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
    }))
    result = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert result["changed"] is False
    assert result["reason"] == "not_confirmed"
    stored = _run(reconciler._proofs.find_by_id(proof["id"]))
    assert stored["status"] == "created"


def test_reconcile_receipt_non_onchain_rail_is_noop():
    reconciler = _make_reconciler()
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "tenant_webhook",
    }))
    result = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert result["changed"] is False
    assert result["reason"] == "not_onchain_claim"


# ── reconcile_receipt: embedded-proof path ──────────────────────────────────

def test_reconcile_receipt_backfills_embedded_proof_and_marks_used():
    reconciler = _make_reconciler()
    embedded_nonce = uuid.uuid4().hex
    action = _run(reconciler._actions.create(TENANT, {
        "decision_id": "dec_2",
        "rail": "onchain_claim",
        "payload": {
            "proof": {
                "nonce": embedded_nonce,
                "user": "0x1234567890abcdef1234567890abcdef12345678",
            },
        },
        "status": "created",
    }))
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "onchain_claim",
        "action_payload_id": action["id"],
    }))

    result = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert result["changed"] is True

    # The embedded proof was backfilled and marked used (replay-protected).
    assert _run(reconciler.is_nonce_available(embedded_nonce)) is False
    action_after = _run(reconciler._actions.get(action["id"], TENANT))
    assert action_after["status"] == "delivered"


def test_reconcile_receipt_wrong_tenant_proof_not_marked():
    """A proof owned by another tenant is never touched (fail-closed)."""
    reconciler = _make_reconciler()
    proof = _make_proof(tenant_id="tenant_reconcile_other")
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
    }))
    result = _run(reconciler.reconcile_receipt(TENANT, receipt))
    # The mismatched proof is skipped (changed stays False via no-op path).
    assert result["changed"] is False
    stored = _run(reconciler._proofs.find_by_id(proof["id"]))
    assert stored["status"] == "created"


def test_reconcile_retries_action_transition_after_proof_used(monkeypatch):
    """Proof-used/action-undelivered is resumable: after a transient transition
    failure on the first pass, the next reconcile retries the delivery transition
    (never re-marking the proof) so the action converges to ``delivered``."""
    reconciler = _make_reconciler()
    proof = _make_proof()
    action = _run(reconciler._actions.create(TENANT, {
        "decision_id": "dec_1",
        "rail": "onchain_claim",
        "payload": {"proof": {"nonce": proof["nonce"]}},
        "status": "created",
    }))
    receipt = _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
        "action_payload_id": action["id"],
    }))

    real_transition = reconciler._actions.transition
    transition_calls = {"count": 0}

    async def flaky_transition(action_id, tenant_id, new_status, **kwargs):
        transition_calls["count"] += 1
        if transition_calls["count"] == 1:
            raise RuntimeError("transient store failure")
        return await real_transition(action_id, tenant_id, new_status, **kwargs)

    monkeypatch.setattr(reconciler._actions, "transition", flaky_transition)

    # First pass: the proof is marked used; the action transition fails silently.
    first = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert first["changed"] is True
    proof_before = _run(reconciler._proofs.find_by_id(proof["id"]))
    assert proof_before["status"] == "used"
    assert _run(reconciler._actions.get(action["id"], TENANT))["status"] != "delivered"

    # Second pass: proof_already_used is resumable — retry the transition.
    second = _run(reconciler.reconcile_receipt(TENANT, receipt))
    assert second["changed"] is True
    assert second["reason"] == "proof_already_used_action_delivered"
    assert _run(reconciler._actions.get(action["id"], TENANT))["status"] == "delivered"
    # The proof was NOT re-marked (single-use preserved, used_at unchanged).
    proof_after = _run(reconciler._proofs.find_by_id(proof["id"]))
    assert proof_after["status"] == "used"
    assert proof_after.get("used_at") == proof_before.get("used_at")


# ── reconcile_tenant / status ───────────────────────────────────────────────

def test_reconcile_tenant_summary_counts():
    reconciler = _make_reconciler()
    proof = _make_proof()
    receipt_ok = _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
    }))
    _run(reconciler._receipts.create(TENANT, {
        "status": "pending",
        "rail": "onchain_claim",
    }))
    _run(reconciler._receipts.create(TENANT, {
        "status": "success",
        "rail": "tenant_webhook",
    }))

    summary = _run(reconciler.reconcile_tenant(TENANT, limit=200))
    assert summary["tenant_id"] == TENANT
    assert summary["receipts_scanned"] == 3
    assert summary["reconciled"] == 1  # only the confirmed onchain_claim receipt
    assert summary["skipped"] == 2
    assert receipt_ok["id"] in [d.get("receipt_id") for d in summary["details"]]


def test_claim_reconciliation_status_snapshot():
    reconciler = _make_reconciler()
    proof = _make_proof()
    _run(reconciler._receipts.create(TENANT, {
        "status": "executed",
        "rail": "onchain_claim",
        "proof_id": proof["id"],
    }))
    _run(reconciler._receipts.create(TENANT, {
        "status": "pending",
        "rail": "onchain_claim",
    }))

    status = _run(reconciler.claim_reconciliation_status(TENANT))
    assert status["tenant_id"] == TENANT
    assert status["proofs_total"] == 1
    assert status["receipts_total"] == 2
    assert status["reconcile_ready"] == 1
    assert status["proofs_by_status"].get("created") == 1


def test_singleton_reset_cycle():
    get_reward_claim_reconciler()
    reset_reward_claim_reconciler()
    assert get_reward_claim_reconciler() is not None
