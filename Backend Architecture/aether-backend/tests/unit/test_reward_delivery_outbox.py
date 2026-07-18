"""
Unit tests for the durable reward-delivery outbox (A6, deliverable 2).

Proves: durable enqueue, leased dispatch, ProviderReceipt on success,
retry/backoff, dead-letter, PR-1 SSRF rejection BEFORE enqueue, and the core
invariant — a reward action is NEVER marked 'delivered' without a persisted
ProviderReceipt (else it stays pending / goes failed).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from repositories.delivery_repos import ProviderReceiptRepository
from services.rewards.delivery_outbox import (
    RewardDeliveryJobRepository,
    RewardDeliveryOutbox,
    SenderResult,
)
from services.rewards.repositories import RewardActionRepository


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


TENANT = "tenant_outbox_001"
WEBHOOK = "http://127.0.0.1:9/reward-hook"   # loopback: allowed in local, no network used


class _ScriptedSender:
    """Returns pre-scripted SenderResults; records call count."""

    def __init__(self, *results: SenderResult) -> None:
        self._results = list(results)
        self.calls = 0

    async def send(self, job):
        r = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return r


async def _make_action(action_repo, *, idem="idem-1"):
    return await action_repo.create(TENANT, {
        "rail": "tenant_webhook",
        "status": "created",
        "reservation_id": None,
        "payload": {
            "event": "reward.action.ready",
            "idempotency_key": idem,
            "tenant_id": TENANT,
        },
    })


def _outbox(sender):
    return RewardDeliveryOutbox(
        job_repo=RewardDeliveryJobRepository(),
        receipt_repo=ProviderReceiptRepository(),
        action_repo=RewardActionRepository(),
        sender=sender,
    )


# ═══════════════════════════════════════════════════════════════════════════
# happy path: enqueue → drain → receipt → action delivered
# ═══════════════════════════════════════════════════════════════════════════

def test_enqueue_and_deliver_records_receipt_and_marks_action_delivered():
    sender = _ScriptedSender(SenderResult("success", external_id="ext-abc-123", response_code=200))

    async def run():
        actions = RewardActionRepository()
        receipts = ProviderReceiptRepository()
        outbox = RewardDeliveryOutbox(
            job_repo=RewardDeliveryJobRepository(), receipt_repo=receipts,
            action_repo=actions, sender=sender,
        )
        action = await _make_action(actions)
        job = await outbox.enqueue(action, {"webhook_url": WEBHOOK, "signing_secret": "s"}, TENANT)
        assert job["state"] == "queued"

        summary = await outbox.drain()
        updated_action = await actions.get(action["id"], TENANT)
        job_after = await RewardDeliveryJobRepository().find_by_id(job["id"])
        all_receipts = await receipts.find_for_intent(action["id"])
        return summary, updated_action, job_after, all_receipts

    summary, action, job, receipts = _run(run())
    assert summary["delivered"] == 1
    assert job["state"] == "delivered"
    assert action["status"] == "delivered"
    assert action["delivery_receipt_id"]
    # A real ProviderReceipt was persisted with the provider external id.
    assert len(receipts) == 1
    assert receipts[0]["external_id"] == "ext-abc-123"


# ═══════════════════════════════════════════════════════════════════════════
# never 'delivered' without a valid receipt
# ═══════════════════════════════════════════════════════════════════════════

def test_success_with_empty_external_id_never_marks_delivered():
    # Provider "succeeded" but returned no external id → receipt validation
    # fails → the delivery is NOT acked; action stays pending, job retries.
    sender = _ScriptedSender(SenderResult("success", external_id="", response_code=200))

    async def run():
        actions = RewardActionRepository()
        receipts = ProviderReceiptRepository()
        outbox = RewardDeliveryOutbox(
            job_repo=RewardDeliveryJobRepository(), receipt_repo=receipts,
            action_repo=actions, sender=sender,
        )
        action = await _make_action(actions)
        await outbox.enqueue(action, {"webhook_url": WEBHOOK}, TENANT)
        await actions.transition(action["id"], TENANT, "pending")
        summary = await outbox.drain()
        updated = await actions.get(action["id"], TENANT)
        all_receipts = await receipts.find_for_intent(action["id"])
        return summary, updated, all_receipts

    summary, action, receipts = _run(run())
    assert summary["delivered"] == 0
    assert action["status"] != "delivered"    # never acked without a receipt
    assert receipts == []                       # nothing persisted


# ═══════════════════════════════════════════════════════════════════════════
# retry then dead-letter → action failed
# ═══════════════════════════════════════════════════════════════════════════

def test_retryable_failure_schedules_retry_and_keeps_pending():
    sender = _ScriptedSender(SenderResult("retryable", response_code=503, error="HTTP 503"))

    async def run():
        actions = RewardActionRepository()
        jobs = RewardDeliveryJobRepository()
        outbox = RewardDeliveryOutbox(job_repo=jobs, action_repo=actions,
                                      receipt_repo=ProviderReceiptRepository(), sender=sender)
        action = await _make_action(actions)
        job = await outbox.enqueue(action, {"webhook_url": WEBHOOK}, TENANT)
        summary = await outbox.drain()
        job_after = await jobs.find_by_id(job["id"])
        updated = await actions.get(action["id"], TENANT)
        return summary, job_after, updated

    summary, job, action = _run(run())
    assert summary["retried"] == 1
    assert job["state"] == "failed"           # scheduled for retry
    assert job["attempt_count"] == 1
    assert job["next_attempt_at"] > job["created_at"]  # backoff into the future
    assert action["status"] != "delivered"


def test_dead_letter_after_max_attempts_marks_action_failed():
    sender = _ScriptedSender(SenderResult("retryable", response_code=500, error="HTTP 500"))

    async def run():
        actions = RewardActionRepository()
        jobs = RewardDeliveryJobRepository()
        outbox = RewardDeliveryOutbox(job_repo=jobs, action_repo=actions,
                                      receipt_repo=ProviderReceiptRepository(), sender=sender)
        action = await _make_action(actions)
        job = await outbox.enqueue(action, {"webhook_url": WEBHOOK}, TENANT)
        # Force this to be the last allowed attempt so a retryable failure DLQs.
        await jobs.update(job["id"], {"max_attempts": 1})
        summary = await outbox.drain()
        job_after = await jobs.find_by_id(job["id"])
        updated = await actions.get(action["id"], TENANT)
        return summary, job_after, updated

    summary, job, action = _run(run())
    assert summary["dead_lettered"] == 1
    assert job["state"] == "dead_letter"
    assert action["status"] == "failed"       # never delivered; explicitly failed


def test_fatal_client_error_dead_letters_immediately():
    sender = _ScriptedSender(SenderResult("fatal", response_code=400, error="HTTP 400 bad request"))

    async def run():
        actions = RewardActionRepository()
        jobs = RewardDeliveryJobRepository()
        outbox = RewardDeliveryOutbox(job_repo=jobs, action_repo=actions,
                                      receipt_repo=ProviderReceiptRepository(), sender=sender)
        action = await _make_action(actions)
        job = await outbox.enqueue(action, {"webhook_url": WEBHOOK}, TENANT)
        summary = await outbox.drain()
        job_after = await jobs.find_by_id(job["id"])
        return summary, job_after

    summary, job = _run(run())
    assert summary["dead_lettered"] == 1
    assert job["state"] == "dead_letter"
    assert job["attempt_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# PR-1 SSRF hardening preserved: block BEFORE a durable job is written
# ═══════════════════════════════════════════════════════════════════════════

def test_ssrf_destination_rejected_before_enqueue(monkeypatch):
    # Non-local so the SSRF blocklist is active. The block occurs BEFORE any
    # durable write, so a plain-dict action is enough (no repo/DB access).
    monkeypatch.setenv("AETHER_ENV", "production")
    sender = _ScriptedSender(SenderResult("success", external_id="x"))

    async def run():
        jobs = RewardDeliveryJobRepository()
        outbox = RewardDeliveryOutbox(job_repo=jobs, action_repo=RewardActionRepository(),
                                      receipt_repo=ProviderReceiptRepository(), sender=sender)
        action = {"id": "act-ssrf", "payload": {"idempotency_key": "k", "tenant_id": TENANT}}
        raised = None
        try:
            await outbox.enqueue(action, {"webhook_url": "https://169.254.169.254/hook"}, TENANT)
        except ValueError as exc:
            raised = exc
        return raised, dict(jobs._store)

    raised, store = _run(run())
    assert raised is not None and "rejected" in str(raised)
    assert store == {}   # no durable job written


def test_plain_http_rejected_before_enqueue_outside_local(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    sender = _ScriptedSender(SenderResult("success", external_id="x"))

    async def run():
        jobs = RewardDeliveryJobRepository()
        outbox = RewardDeliveryOutbox(job_repo=jobs, action_repo=RewardActionRepository(),
                                      receipt_repo=ProviderReceiptRepository(), sender=sender)
        action = {"id": "act-http", "payload": {"idempotency_key": "k", "tenant_id": TENANT}}
        raised = None
        try:
            await outbox.enqueue(action, {"webhook_url": "http://example.com/hook"}, TENANT)
        except ValueError as exc:
            raised = exc
        return raised, dict(jobs._store)

    raised, store = _run(run())
    assert raised is not None
    assert store == {}


# ═══════════════════════════════════════════════════════════════════════════
# status + operator replay
# ═══════════════════════════════════════════════════════════════════════════

def test_status_counts_and_redeliver():
    sender = _ScriptedSender(SenderResult("fatal", response_code=400, error="bad"))

    async def run():
        actions = RewardActionRepository()
        jobs = RewardDeliveryJobRepository()
        outbox = RewardDeliveryOutbox(job_repo=jobs, action_repo=actions,
                                      receipt_repo=ProviderReceiptRepository(), sender=sender)
        action = await _make_action(actions)
        job = await outbox.enqueue(action, {"webhook_url": WEBHOOK}, TENANT)
        await outbox.drain()
        status_before = await outbox.status(TENANT)
        # Operator replay requeues the dead-lettered job.
        replayed = await outbox.redeliver(job["id"], TENANT)
        status_after = await outbox.status(TENANT)
        return status_before, replayed, status_after

    before, replayed, after = _run(run())
    assert before.get("dead_letter") == 1
    assert replayed["state"] == "queued"
    assert after.get("queued") == 1
