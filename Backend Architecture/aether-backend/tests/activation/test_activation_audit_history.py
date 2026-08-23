"""Audit-history contract for :class:`ActivationService`.

``advance`` records a tamper-evident-ish audit entry for every real state
move: ``{from, to, at, reason}``. This suite pins the audit *content* (not
just the count): entry shape, reason propagation, the full forward chain's
history sequence, and that a rejected (illegal) move writes nothing.

The activation record is tenant-scoped, so the history is read back through
``get_status`` (the same tenant the flow was driven with) and never leaks
cross-tenant.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repositories.lake import BronzeRepository
from services.activation.models import ActivationState as S


def _parse_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _states(record: dict) -> list[str]:
    return [entry["to"] for entry in record.get("history", [])]


@pytest.mark.asyncio
async def test_history_entry_shape_and_reason_propagation(svc):
    record = {"state": S.not_started.value, "tenant_id": "t-audit", "history": []}
    svc.advance(record, S.account_verified, reason="tenant_authenticated")
    entry = record["history"][0]
    assert set(entry) >= {"from", "to", "at", "reason"}
    assert entry["from"] == S.not_started.value
    assert entry["to"] == S.account_verified.value
    assert entry["reason"] == "tenant_authenticated"
    # timestamps parse as aware UTC and are monotonically increasing
    ts = _parse_at(entry["at"])
    assert ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


@pytest.mark.asyncio
async def test_full_forward_chain_audit(svc):
    record = {"state": S.not_started.value, "tenant_id": "t-audit", "history": []}
    chain = [
        (S.account_verified, "tenant_authenticated"),
        (S.plan_selected, "plan_tier=P2"),
        (S.billing_pending, "billing_state_derived"),
        (S.sdk_selected, "platforms=['web','ios']"),
        (S.keys_created, "count=1"),
        (S.waiting_for_event, "keys_provisioned"),
    ]
    for target, reason in chain:
        svc.advance(record, target, reason=reason)
    assert _states(record) == [target.value for target, _ in chain]
    reasons = [e["reason"] for e in record["history"]]
    assert reasons == [reason for _, reason in chain]


@pytest.mark.asyncio
async def test_get_status_returns_full_history_for_tenant(svc):
    await svc.select_plan("t-audit", "P2")
    await svc.select_sdks("t-audit", ["web"])
    status = await svc.get_status("t-audit")
    # the driven tenant's history includes its own moves
    assert S.account_verified.value in _states(status)
    assert S.plan_selected.value in _states(status)
    assert S.sdk_selected.value in _states(status)
    # a different tenant never sees this history
    other = await svc.get_status("t-other")
    assert S.sdk_selected.value not in _states(other)


@pytest.mark.asyncio
async def test_illegal_transition_writes_no_audit_entry(svc):
    record = {"state": S.not_started.value, "tenant_id": "t-audit", "history": []}
    from shared.common.common import ConflictError

    with pytest.raises(ConflictError):
        svc.advance(record, S.complete, reason="sneaky")
    assert record["history"] == []
    assert record["state"] == S.not_started.value


@pytest.mark.asyncio
async def test_complete_flow_audit_ends_at_complete(svc, onboard_with_keys):
    tenant = "t-audit-complete"
    await onboard_with_keys(svc, tenant)

    bronze = BronzeRepository("sdk_events")
    await bronze.ingest(
        source="sdk",
        source_tag="batch:b-audit-1",
        provider_record_id="evt-audit-1",
        payload={"event_id": "evt-audit-1", "event_type": "track"},
        schema_version="1.0.0",
        entity_id="anon-audit",
        entity_type="user",
        tenant_id=tenant,
    )
    await svc.evaluate_first_value(tenant)
    status = await svc.complete(tenant)
    history = _states(status)
    assert history[-1] == S.complete.value
    # the forward path is a strictly increasing audit chain ending at complete
    assert S.complete.value in history
    assert history == sorted(history, key=lambda s: list(S).index(S(s)))


@pytest.mark.asyncio
async def test_honest_halt_records_reason(svc):
    record = {"state": S.keys_created.value, "tenant_id": "t-audit", "history": []}
    svc.advance(record, S.externally_blocked, reason="provider_blackout")
    entry = record["history"][-1]
    assert entry["to"] == S.externally_blocked.value
    assert entry["reason"] == "provider_blackout"
