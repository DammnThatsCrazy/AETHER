"""Activation is tenant-scoped end to end.

Tenant isolation is inherent to the store (every read filters on ``tenant_id``)
and to the first-value derivation (Bronze rows are read tenant-scoped). Tenant B
never observes, advances, or inherits tenant A's activation record, key ids, or
durable events, and vice versa.
"""
from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from repositories.repos import APIKeyRepository
from services.activation.models import ActivationState as S


async def _land_bronze(tenant_id: str, event_id: str):
    await BronzeRepository("sdk_events").ingest(
        source="sdk",
        source_tag="batch:iso",
        provider_record_id=event_id,
        payload={"event_id": event_id, "event_type": "track"},
        schema_version="1.0.0",
        entity_id="anon",
        entity_type="user",
        tenant_id=tenant_id,
    )


# ── B cannot read A's activation ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_b_cannot_read_tenant_a_activation(svc, onboard_with_keys):
    await onboard_with_keys(svc, "tenant-A", count=2, plan_tier="P3")

    a_status = await svc.get_status("tenant-A")
    assert a_status["state"] == S.waiting_for_event.value
    assert a_status["selected_plan_tier"] == "P3"
    assert len(a_status["created_key_ids"]) == 2

    # B has never onboarded: reading status mints B's OWN fresh record only.
    b_status = await svc.get_status("tenant-B")
    assert b_status["state"] == S.account_verified.value
    assert b_status["selected_plan_tier"] is None
    assert b_status["created_key_ids"] == []
    assert b_status["first_value_evidence"] == {}


# ── B cannot advance / inherit A's activation ────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_b_actions_do_not_mutate_tenant_a(svc, onboard_with_keys):
    await onboard_with_keys(svc, "tenant-A", count=1, plan_tier="P2")
    a_before = await svc.get_status("tenant-A")

    # A full independent flow on B, including its own evaluation.
    await onboard_with_keys(svc, "tenant-B", count=1, plan_tier="P1")
    await svc.evaluate_first_value("tenant-B")
    await svc.select_plan("tenant-B", "P4")

    # A is entirely unchanged by anything B did.
    a_after = await svc.get_status("tenant-A")
    assert a_after["state"] == a_before["state"] == S.waiting_for_event.value
    assert a_after["selected_plan_tier"] == "P2"
    assert a_after["created_key_ids"] == a_before["created_key_ids"]


@pytest.mark.asyncio
async def test_bronze_first_value_is_tenant_scoped(svc, onboard_with_keys):
    # Only tenant-A has a durable event.
    await onboard_with_keys(svc, "tenant-A", count=1)
    await onboard_with_keys(svc, "tenant-B", count=1)
    await _land_bronze("tenant-A", "evt-A-only")

    # A reaches first value from its own row.
    a_ev = await svc.evaluate_first_value("tenant-A")
    assert a_ev["ready"] is True
    assert a_ev["evidence"]["event_id"] == "evt-A-only"

    # B, with no durable row of its own, cannot claim first value from A's row.
    b_ev = await svc.evaluate_first_value("tenant-B")
    assert b_ev["ready"] is False
    assert b_ev["state"] == S.waiting_for_event.value
    assert b_ev["evidence"] == {}


# ── Key ids never leak across tenants ────────────────────────────────────────

@pytest.mark.asyncio
async def test_key_ids_never_leak_across_tenants(svc, onboard_with_keys):
    a_keys = await onboard_with_keys(svc, "tenant-A", count=2)
    b_keys = await onboard_with_keys(svc, "tenant-B", count=3)

    a_ids = {k["id"] for k in a_keys["keys"]}
    b_ids = {k["id"] for k in b_keys["keys"]}
    assert len(a_ids) == 2
    assert len(b_ids) == 3
    # Disjoint id sets — no shared key identifier.
    assert a_ids.isdisjoint(b_ids)

    # get_status only ever surfaces the caller's own key ids.
    a_status = await svc.get_status("tenant-A")
    b_status = await svc.get_status("tenant-B")
    assert set(a_status["created_key_ids"]) == a_ids
    assert set(b_status["created_key_ids"]) == b_ids
    assert set(a_status["created_key_ids"]).isdisjoint(b_status["created_key_ids"])

    # The persisted api_keys rows are stamped with the owning tenant.
    key_repo = APIKeyRepository()
    for key_id in a_ids:
        row = await key_repo.find_by_id(key_id)
        assert row is not None and row["tenant_id"] == "tenant-A"
    for key_id in b_ids:
        row = await key_repo.find_by_id(key_id)
        assert row is not None and row["tenant_id"] == "tenant-B"
