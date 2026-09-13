"""State-machine contract for :class:`ActivationService`.

Covers ``advance``'s explicit ``ALLOWED_FROM`` map: legal transitions mutate
state and append history, illegal transitions raise :class:`ConflictError`, a
self-transition is a no-op that stamps ``updated_at`` without a new history
row, the honest-halt states are reachable from anywhere, and ``complete`` is
gated on ``first_value_ready`` (proved from a durable Bronze row, never faked).
"""
from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from services.activation.models import ActivationState as S
from shared.common.common import ConflictError


def _record(state: S = S.not_started) -> dict:
    """A minimal activation record dict — ``advance`` operates on dicts."""
    return {"state": state.value, "tenant_id": "t-fsm", "history": []}


# ── Legal transitions ────────────────────────────────────────────────────────

# The canonical forward path (billing derives to *_pending with no Stripe acct).
FORWARD_CHAIN = [
    S.account_verified,
    S.plan_selected,
    S.billing_pending,
    S.sdk_selected,
    S.keys_created,
    S.waiting_for_event,
    S.event_received,
    S.first_value_ready,
    S.complete,
]


def test_legal_forward_transitions_succeed(svc):
    record = _record(S.not_started)
    prev_history = 0
    for target in FORWARD_CHAIN:
        svc.advance(record, target, reason=f"to_{target.value}")
        assert record["state"] == target.value
        # Each real move appends exactly one history entry.
        assert len(record["history"]) == prev_history + 1
        last = record["history"][-1]
        assert last["to"] == target.value
        assert "at" in last and "from" in last
        prev_history += 1


def test_self_transition_is_noop_without_history(svc):
    record = _record(S.plan_selected)
    record["updated_at"] = "1970-01-01T00:00:00+00:00"
    svc.advance(record, S.plan_selected)
    # No new history row, but updated_at is refreshed.
    assert record["history"] == []
    assert record["state"] == S.plan_selected.value
    assert record["updated_at"] != "1970-01-01T00:00:00+00:00"


# ── Illegal transitions ──────────────────────────────────────────────────────

ILLEGAL = [
    # Skipping straight past the required predecessors.
    (S.not_started, S.keys_created),
    (S.not_started, S.first_value_ready),
    (S.account_verified, S.complete),
    (S.account_verified, S.sdk_selected),
    (S.plan_selected, S.keys_created),
    (S.sdk_selected, S.first_value_ready),
    (S.keys_created, S.complete),
    # complete may only be entered from first_value_ready.
    (S.event_received, S.complete),
    (S.waiting_for_event, S.complete),
]


@pytest.mark.parametrize("current,target", ILLEGAL)
def test_illegal_transition_raises_conflict(svc, current, target):
    record = _record(current)
    with pytest.raises(ConflictError):
        svc.advance(record, target)
    # State is untouched and no history was written on the rejected move.
    assert record["state"] == current.value
    assert record["history"] == []


# ── Honest-halt states ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "halt", [S.manual_pending, S.blocked, S.externally_blocked]
)
@pytest.mark.parametrize(
    "start", [S.not_started, S.plan_selected, S.keys_created, S.event_received]
)
def test_honest_halt_states_reachable_from_anywhere(svc, start, halt):
    record = _record(start)
    svc.advance(record, halt, reason="precondition_unmet")
    assert record["state"] == halt.value


# ── complete gate (async) ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_blocked_for_fresh_tenant(svc):
    # A freshly authenticated tenant is at account_verified — nowhere near ready.
    with pytest.raises(ConflictError):
        await svc.complete("tenant-fresh")


@pytest.mark.asyncio
async def test_complete_blocked_when_waiting_without_bronze(svc, onboard_with_keys):
    # Parked at waiting_for_event with no durable event: completion is refused.
    await onboard_with_keys(svc, "tenant-waiting")
    status = await svc.get_status("tenant-waiting")
    assert status["state"] == S.waiting_for_event.value
    with pytest.raises(ConflictError):
        await svc.complete("tenant-waiting")
    # The failed completion did not fake a forward state.
    assert (await svc.get_status("tenant-waiting"))["state"] == S.waiting_for_event.value


@pytest.mark.asyncio
async def test_complete_succeeds_only_after_first_value_ready(svc, onboard_with_keys):
    tenant = "tenant-complete"
    await onboard_with_keys(svc, tenant)

    # A durable Bronze sdk_events row IS the first-value proof.
    bronze = BronzeRepository("sdk_events")
    await bronze.ingest(
        source="sdk",
        source_tag="batch:b-1",
        provider_record_id="evt-complete-1",
        payload={"event_id": "evt-complete-1", "event_type": "track"},
        schema_version="1.0.0",
        entity_id="anon-1",
        entity_type="user",
        tenant_id=tenant,
    )

    ev = await svc.evaluate_first_value(tenant)
    assert ev["ready"] is True
    assert ev["state"] == S.first_value_ready.value

    done = await svc.complete(tenant)
    assert done["state"] == S.complete.value
    # Idempotent re-complete returns the completed view without re-raising.
    assert (await svc.complete(tenant))["state"] == S.complete.value
