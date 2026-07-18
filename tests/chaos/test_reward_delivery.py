"""Reward-delivery timeout -> retry -> dead-letter -> operator recovery.

Drives the REAL durable reward-delivery outbox (``services.rewards.
delivery_outbox.RewardDeliveryOutbox``) with an injected scripted sender that
models a webhook timeout. NO live network: the sender is a stub, the webhook
url is loopback (allowed in local, never dialled).

Core invariant under chaos: a reward action is NEVER marked 'delivered' without
a persisted ProviderReceipt. A timeout schedules a backoff retry; exhausting the
attempt budget dead-letters the job and fails the action (never a false
success); an operator redeliver requeues it.
"""

from __future__ import annotations

from repositories.delivery_repos import ProviderReceiptRepository
from repositories.repos import reset_in_memory_stores
from services.rewards.delivery_outbox import (
    RewardDeliveryJobRepository,
    RewardDeliveryOutbox,
    SenderResult,
)
from services.rewards.repositories import RewardActionRepository

WEBHOOK = "http://127.0.0.1:9/reward-hook"  # loopback: allowed in local, never dialled


class _ScriptedSender:
    """Returns pre-scripted SenderResults; records the call count."""

    def __init__(self, *results: SenderResult) -> None:
        self._results = list(results)
        self.calls = 0

    async def send(self, job):
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return result


async def _make_action(action_repo: RewardActionRepository, tenant: str, idem: str = "idem-chaos"):
    return await action_repo.create(tenant, {
        "rail": "tenant_webhook",
        "status": "created",
        "reservation_id": None,
        "payload": {"event": "reward.action.ready", "idempotency_key": idem, "tenant_id": tenant},
    })


def _outbox(sender, jobs=None, actions=None):
    return RewardDeliveryOutbox(
        job_repo=jobs or RewardDeliveryJobRepository(),
        receipt_repo=ProviderReceiptRepository(),
        action_repo=actions or RewardActionRepository(),
        sender=sender,
    )


# ── timeout schedules a retry, never a false delivery ─────────────────────────
async def test_delivery_timeout_schedules_backoff_retry(tenant):
    reset_in_memory_stores()
    actions = RewardActionRepository()
    jobs = RewardDeliveryJobRepository()
    sender = _ScriptedSender(SenderResult("retryable", response_code=504, error="gateway timeout"))
    outbox = _outbox(sender, jobs=jobs, actions=actions)

    action = await _make_action(actions, tenant)
    job = await outbox.enqueue(action, {"webhook_url": WEBHOOK}, tenant)
    summary = await outbox.drain()

    job_after = await jobs.find_by_id(job["id"])
    updated = await actions.get(action["id"], tenant)
    assert summary["retried"] == 1
    assert job_after["state"] == "failed"                 # scheduled for retry
    assert job_after["attempt_count"] == 1
    assert job_after["next_attempt_at"] > job_after["created_at"]  # backoff into the future
    assert updated["status"] != "delivered"               # never a false success


# ── timeout exhausts the retry budget -> dead-letter + action failed ──────────
async def test_delivery_timeout_exhausts_budget_and_dead_letters(tenant):
    reset_in_memory_stores()
    actions = RewardActionRepository()
    jobs = RewardDeliveryJobRepository()
    sender = _ScriptedSender(SenderResult("retryable", response_code=504, error="gateway timeout"))
    outbox = _outbox(sender, jobs=jobs, actions=actions)

    action = await _make_action(actions, tenant)
    job = await outbox.enqueue(action, {"webhook_url": WEBHOOK}, tenant)
    await jobs.update(job["id"], {"max_attempts": 1})  # this is the last allowed attempt
    summary = await outbox.drain()

    job_after = await jobs.find_by_id(job["id"])
    updated = await actions.get(action["id"], tenant)
    assert summary["dead_lettered"] == 1
    assert job_after["state"] == "dead_letter"
    assert updated["status"] == "failed"  # explicitly failed, never delivered


# ── recovery after a transient timeout -> delivered with a receipt ────────────
async def test_delivery_recovers_after_transient_timeout(tenant):
    reset_in_memory_stores()
    actions = RewardActionRepository()
    jobs = RewardDeliveryJobRepository()
    receipts = ProviderReceiptRepository()

    # First attempt times out.
    fail_outbox = RewardDeliveryOutbox(
        job_repo=jobs, receipt_repo=receipts, action_repo=actions,
        sender=_ScriptedSender(SenderResult("retryable", response_code=504, error="timeout")),
    )
    action = await _make_action(actions, tenant)
    job = await fail_outbox.enqueue(action, {"webhook_url": WEBHOOK}, tenant)
    await fail_outbox.drain()
    assert (await jobs.find_by_id(job["id"]))["state"] == "failed"

    # The endpoint recovers; make the retry runnable and drain with a success sender.
    await jobs.update(job["id"], {"next_attempt_at": "2020-01-01T00:00:00+00:00"})
    ok_outbox = RewardDeliveryOutbox(
        job_repo=jobs, receipt_repo=receipts, action_repo=actions,
        sender=_ScriptedSender(SenderResult("success", external_id="ext-recovered", response_code=200)),
    )
    summary = await ok_outbox.drain()

    job_after = await jobs.find_by_id(job["id"])
    updated = await actions.get(action["id"], tenant)
    persisted = await receipts.find_for_intent(action["id"])
    assert summary["delivered"] == 1
    assert job_after["state"] == "delivered"
    assert updated["status"] == "delivered"
    assert len(persisted) == 1 and persisted[0]["external_id"] == "ext-recovered"
