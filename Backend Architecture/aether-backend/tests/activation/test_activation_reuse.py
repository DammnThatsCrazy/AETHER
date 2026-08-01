"""The activation flow REUSES existing primitives — it does not reimplement them.

* ``run_test_event`` sends the event IN-PROCESS through the canonical
  :func:`services.ingestion.batch.ingest_batch`, producing a real durable Bronze
  ``sdk_events`` write and an ``accepted`` disposition.
* Re-firing the exact same event through that same path returns ``duplicate``
  via the ``sha256(tenant_id:event_id:schema_version)`` idempotency claim, with
  no double Bronze row and no double count.
* Billing state is DERIVED read-only from the Stripe billing account. The
  activation service performs no billing writes.
"""
from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from shared.billing import stripe_repository
from services.activation.models import ActivationState as S, TestEventRequest
from services.ingestion.batch import BaseEvent, BatchRequest, ingest_batch
from dependencies.providers import get_producer


# ── Test event routes through the real ingestion path ────────────────────────

@pytest.mark.asyncio
async def test_test_event_writes_bronze_and_is_accepted(svc, make_request, onboard_with_keys):
    tenant = "tenant-reuse-1"
    await onboard_with_keys(svc, tenant)

    request = make_request(tenant)
    result = await svc.run_test_event(
        request, tenant, TestEventRequest(event_type="track", properties={"plan": "P1"})
    )

    # The disposition comes straight from ingest_batch's per-event result.
    assert result["results"], "expected at least one per-event result"
    assert result["results"][0]["status"] == "accepted"
    # First value is proven from the durable Bronze row, not hard-coded.
    assert result["state"] == S.first_value_ready.value

    # A real Bronze sdk_events row exists, tenant-scoped, source=sdk.
    bronze = BronzeRepository("sdk_events")
    rows = await bronze.find_many(
        filters={"tenant_id": tenant, "source": "sdk"}, limit=50
    )
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == tenant
    assert rows[0]["source"] == "sdk"


@pytest.mark.asyncio
async def test_refired_identical_event_is_duplicate_no_double_count(
    svc, make_request, onboard_with_keys
):
    tenant = "tenant-reuse-2"
    await onboard_with_keys(svc, tenant)
    request = make_request(tenant)

    # 1) First event goes through the activation service (accepted, 1 row).
    first = await svc.run_test_event(
        request, tenant, TestEventRequest(event_type="track")
    )
    assert first["results"][0]["status"] == "accepted"

    bronze = BronzeRepository("sdk_events")
    rows = await bronze.find_many(
        filters={"tenant_id": tenant, "source": "sdk"}, limit=50
    )
    assert len(rows) == 1
    event_id = rows[0]["provider_record_id"]

    # 2) Re-fire the IDENTICAL event id straight through the canonical path the
    #    service reuses. The idempotency claim must mark it duplicate.
    replay = BatchRequest(
        batch=[
            BaseEvent(
                id=event_id,
                type="track",
                timestamp="2026-07-30T00:00:00Z",
                sessionId="sess-replay",
                anonymousId="anon-replay",
                properties={},
            )
        ],
        sentAt="2026-07-30T00:00:00Z",
    )
    response = await ingest_batch(request, replay, get_producer())
    assert response["accepted"] == 0
    assert response["duplicates"] == 1
    assert response["events"][0]["status"] == "duplicate"

    # No double count: still exactly one durable Bronze row.
    rows_after = await bronze.find_many(
        filters={"tenant_id": tenant, "source": "sdk"}, limit=50
    )
    assert len(rows_after) == 1


# ── Billing state is derived read-only, with no billing write ────────────────

@pytest.mark.asyncio
async def test_billing_state_derived_active_from_seeded_stripe(svc):
    tenant = "tenant-billing-active"
    # Seed an in-memory Stripe account directly (simulating the billing service).
    stripe_repository._mem_accounts[tenant] = {
        "tenant_id": tenant,
        "subscription_status": "active",
        "plan_tier": "P2",
    }
    assert await svc.derive_billing_state(tenant) == S.billing_active


@pytest.mark.asyncio
async def test_billing_state_pending_for_inactive_or_missing_account(svc):
    inactive = "tenant-billing-pastdue"
    stripe_repository._mem_accounts[inactive] = {
        "tenant_id": inactive,
        "subscription_status": "past_due",
    }
    assert await svc.derive_billing_state(inactive) == S.billing_pending
    # No account at all also derives to pending — never asserted active.
    assert await svc.derive_billing_state("tenant-no-account") == S.billing_pending


@pytest.mark.asyncio
async def test_select_plan_performs_no_billing_write(svc):
    # Unseeded tenant: after selecting a plan, activation must NOT have created
    # a billing account (billing is read-only here).
    unseeded = "tenant-no-billing-write"
    status = await svc.select_plan(unseeded, "P3")
    assert status["selected_plan_tier"] == "P3"
    assert status["billing_state"] == S.billing_pending.value
    assert unseeded not in stripe_repository._mem_accounts

    # Seeded active tenant: the seeded row is read but never mutated.
    seeded = "tenant-seeded-active"
    stripe_repository._mem_accounts[seeded] = {
        "tenant_id": seeded,
        "subscription_status": "active",
        "plan_tier": "P1",
    }
    snapshot = dict(stripe_repository._mem_accounts[seeded])
    status2 = await svc.select_plan(seeded, "P4")
    assert status2["billing_state"] == S.billing_active.value
    # The activation service left the billing account exactly as it found it.
    assert stripe_repository._mem_accounts[seeded] == snapshot
