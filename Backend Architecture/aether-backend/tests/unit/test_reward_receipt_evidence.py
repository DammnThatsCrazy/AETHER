"""
Unit tests for durable reward receipt-evidence recording (A6 / program sec18).

Every delivery receipt (from the durable reward outbox) and every settlement
receipt (tenant-submitted execution receipt) must leave an immutable, append-only
trace on the reward audit trail, with bounded retry + dead-letter routing when
the append cannot be persisted.

Covers:
    - record() appends a durable audit entry (delivery + settlement kinds)
    - confirmed settlements are flagged settlement_confirmed=true
    - idempotency: re-recording the same (type, tenant, external_id) is a no-op
    - a transient audit failure routes the evidence to the durable evidence
      outbox and drain() recovers it
    - exhausted retries dead-letter the evidence (never silently dropped)
    - build_evidence_loop returns a supervised async loop
    - evidence_id is deterministic per (type, tenant, external_id)

All tests run against the in-memory repo backend (AETHER_ENV=local); the shared
per-table stores are reset before each test.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.rewards.receipt_evidence import (
    RewardEvidenceOutboxRepository,
    RewardReceiptEvidenceService,
    evidence_id,
    get_receipt_evidence_service,
    reset_receipt_evidence_service,
)
from services.rewards.repositories import RewardAuditRepository


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    reset_receipt_evidence_service()
    yield
    reset_in_memory_stores()
    reset_receipt_evidence_service()


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


TENANT = "tenant_evidence_001"


def _audit_entries(target_id: str) -> list[dict]:
    return _run(RewardAuditRepository().find_many(
        filters={"tenant_id": TENANT, "target_id": target_id}, limit=20
    ))


# ═══════════════════════════════════════════════════════════════════════════
# happy path
# ═══════════════════════════════════════════════════════════════════════════

def test_record_settlement_receipt_appends_durable_audit_entry():
    svc = RewardReceiptEvidenceService()
    record = _run(svc.record(
        "settlement", tenant_id=TENANT, receipt_id="rec_1", rail="tenant_webhook",
        external_id="ext-abc-1", status="success", action_id="act_1",
        tx_hash="0xtx", chain_id=8453,
    ))
    assert record["action"] == "receipt.settlement.recorded"
    assert record["target_type"] == "reward_settlement_receipt"
    assert record["after_state"]["settlement_confirmed"] is True
    assert record["after_state"]["external_id"] == "ext-abc-1"
    assert record["after_state"]["tx_hash"] == "0xtx"

    # The audit trail has exactly one immutable entry for the evidence.
    entries = _audit_entries(evidence_id("settlement", TENANT, "ext-abc-1"))
    assert len(entries) == 1


def test_record_delivery_receipt_appends_durable_audit_entry():
    svc = RewardReceiptEvidenceService()
    record = _run(svc.record(
        "delivery", tenant_id=TENANT, receipt_id="prec_9", rail="tenant_webhook",
        external_id="whk-1", status="delivered", action_id="act_9",
    ))
    assert record["action"] == "receipt.delivery.recorded"
    assert record["target_type"] == "reward_delivery_receipt"
    assert record["after_state"]["settlement_confirmed"] is True

    entries = _audit_entries(evidence_id("delivery", TENANT, "whk-1"))
    assert len(entries) == 1


def test_confirmed_settlement_flag():
    svc = RewardReceiptEvidenceService()
    pending = _run(svc.record(
        "settlement", tenant_id=TENANT, receipt_id="rec_p", rail="onchain_claim",
        external_id="ext-p", status="pending", proof_id="pf_1",
    ))
    assert pending["after_state"]["settlement_confirmed"] is False
    # Confirmed statuses → flag true.
    for status in ("success", "delivered", "confirmed", "executed"):
        r = _run(svc.record(
            "settlement", tenant_id=TENANT, receipt_id=f"rec_{status}",
            rail="onchain_claim", external_id=f"ext-{status}", status=status,
        ))
        assert r["after_state"]["settlement_confirmed"] is True


def test_record_is_idempotent_per_receipt():
    svc = RewardReceiptEvidenceService()
    external_id = "ext-dup"
    _run(svc.record(
        "settlement", tenant_id=TENANT, receipt_id="rec_a", rail="manual_export",
        external_id=external_id, status="success",
    ))
    # Re-record the same receipt (e.g. a retry of the POST /receipts request).
    _run(svc.record(
        "settlement", tenant_id=TENANT, receipt_id="rec_a", rail="manual_export",
        external_id=external_id, status="success",
    ))
    assert len(_audit_entries(evidence_id("settlement", TENANT, external_id))) == 1


def test_record_rejects_bad_kind_and_empty_external_id():
    svc = RewardReceiptEvidenceService()
    with pytest.raises(ValueError):
        _run(svc.record("bad_kind", tenant_id=TENANT, rail="x", external_id="e"))
    with pytest.raises(ValueError):
        _run(svc.record("settlement", tenant_id=TENANT, rail="x", external_id=""))


def test_evidence_id_is_deterministic():
    a = evidence_id("settlement", TENANT, "ext-z")
    b = evidence_id("settlement", TENANT, "ext-z")
    c = evidence_id("delivery", TENANT, "ext-z")
    assert a == b
    assert a != c
    assert a.startswith("ev_")


# ═══════════════════════════════════════════════════════════════════════════
# bounded retry + DLQ routing
# ═══════════════════════════════════════════════════════════════════════════

class _FailingAudit:
    """Audit backend that always fails → evidence must route to the outbox."""

    async def append(self, *args, **kwargs):
        raise RuntimeError("audit db down")


def test_transient_failure_routes_evidence_to_outbox_then_drain_recovers(monkeypatch):
    monkeypatch.setenv("REWARD_EVIDENCE_MAX_ATTEMPTS", "3")
    svc = RewardReceiptEvidenceService(audit_repo=_FailingAudit())

    result = _run(svc.record(
        "settlement", tenant_id=TENANT, receipt_id="rec_fail", rail="onchain_claim",
        external_id="ext-fail", status="success",
    ))
    assert result.get("outboxed") is True

    # Durable outbox holds exactly one pending job keyed by evidence id.
    ev_id = evidence_id("settlement", TENANT, "ext-fail")
    job = _run(RewardEvidenceOutboxRepository().find_by_id(ev_id))
    assert job is not None
    assert job["state"] in ("queued", "failed")
    assert job["payload"]["external_id"] == "ext-fail"

    # Once the audit backend recovers, drain() records the evidence.
    healthy = RewardReceiptEvidenceService()
    summary = _run(healthy.drain(batch_size=10))
    assert summary["scanned"] == 1
    assert summary["recorded"] == 1
    assert len(_audit_entries(ev_id)) == 1
    assert _run(RewardEvidenceOutboxRepository().find_by_id(ev_id))["state"] == "done"


def test_failed_append_is_retried_with_backoff(monkeypatch):
    monkeypatch.setenv("REWARD_EVIDENCE_MAX_ATTEMPTS", "3")
    svc = RewardReceiptEvidenceService(audit_repo=_FailingAudit())

    _run(svc.record(
        "delivery", tenant_id=TENANT, receipt_id="rec_retry", rail="tenant_webhook",
        external_id="ext-retry", status="delivered",
    ))
    ev_id = evidence_id("delivery", TENANT, "ext-retry")

    summary = _run(svc.drain(batch_size=10))
    assert summary["recorded"] == 0
    job = _run(RewardEvidenceOutboxRepository().find_by_id(ev_id))
    assert job["state"] == "failed"
    assert job["attempt_count"] == 1
    # Backoff pushes the next attempt into the future (bounded retry, not spam).
    from datetime import datetime
    from shared.common.common import utc_now
    assert datetime.fromisoformat(job["next_attempt_at"]) > utc_now()
    # The not-yet-due retry is not re-scanned immediately.
    assert _run(svc.drain(batch_size=10))["scanned"] == 0


def test_exhausted_retries_dead_letter_evidence(monkeypatch):
    monkeypatch.setenv("REWARD_EVIDENCE_MAX_ATTEMPTS", "1")
    svc = RewardReceiptEvidenceService(audit_repo=_FailingAudit())

    _run(svc.record(
        "delivery", tenant_id=TENANT, receipt_id="rec_dlq", rail="tenant_webhook",
        external_id="ext-dlq", status="delivered",
    ))
    ev_id = evidence_id("delivery", TENANT, "ext-dlq")

    summary = _run(svc.drain(batch_size=10))
    assert summary["dead_lettered"] == 1
    job = _run(RewardEvidenceOutboxRepository().find_by_id(ev_id))
    assert job["state"] == "dead_letter"
    assert "audit db down" in job.get("last_error", "")
    # The evidence was NOT silently dropped — it is visible in the DLQ.
    counts = _run(svc.status())
    assert counts.get("dead_letter") == 1


def test_drain_idempotent_when_no_pending_evidence():
    summary = _run(RewardReceiptEvidenceService().drain(batch_size=10))
    assert summary == {"scanned": 0, "recorded": 0, "dead_lettered": 0, "retried": 0}


# ═══════════════════════════════════════════════════════════════════════════
# supervised loop builder
# ═══════════════════════════════════════════════════════════════════════════

def test_build_evidence_loop_returns_supervised_async_loop():
    loop = RewardReceiptEvidenceService().build_evidence_loop(interval_s=3600)
    assert callable(loop)
    assert asyncio.iscoroutinefunction(loop)


def test_singleton_reset_cycle():
    get_receipt_evidence_service()
    reset_receipt_evidence_service()
    assert get_receipt_evidence_service() is not None
