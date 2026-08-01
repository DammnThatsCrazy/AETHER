"""First value is DERIVED from the durable Bronze ``sdk_events`` store — honest.

No Bronze row -> ``waiting_for_event`` and ``ready=False`` with empty evidence.
A durable Bronze row (whatever its real ids) -> ``event_received`` then
``first_value_ready``, and the evidence dict echoes that row's actual
``provider_record_id`` / id — never a hard-coded success.
"""
from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from services.activation.models import ActivationState as S


async def _write_bronze_event(tenant_id: str, event_id: str, batch_id: str = "b-fv"):
    bronze = BronzeRepository("sdk_events")
    await bronze.ingest(
        source="sdk",
        source_tag=f"batch:{batch_id}",
        provider_record_id=event_id,
        payload={"event_id": event_id, "batch_id": batch_id, "event_type": "track"},
        schema_version="1.0.0",
        entity_id="anon-fv",
        entity_type="user",
        tenant_id=tenant_id,
    )


# ── waiting_for_event: nothing durable has arrived ───────────────────────────

@pytest.mark.asyncio
async def test_no_bronze_row_stays_waiting_not_ready(svc, onboard_with_keys):
    tenant = "tenant-fv-waiting"
    await onboard_with_keys(svc, tenant)

    ev = await svc.evaluate_first_value(tenant)
    assert ev["state"] == S.waiting_for_event.value
    assert ev["ready"] is False
    # Honest: no evidence is manufactured when nothing has landed.
    assert ev["evidence"] == {}

    status = await svc.get_status(tenant)
    assert status["waiting_reason"] == "no_events_received_yet"


# ── event_received / first_value_ready: a real Bronze row confirms it ─────────

@pytest.mark.asyncio
async def test_bronze_row_promotes_to_first_value_ready_with_real_evidence(
    svc, onboard_with_keys
):
    tenant = "tenant-fv-ready"
    await onboard_with_keys(svc, tenant)

    # Land a durable Bronze row directly in the in-memory store.
    await _write_bronze_event(tenant, "evt-fv-42", batch_id="batch-77")

    ev = await svc.evaluate_first_value(tenant)
    assert ev["state"] == S.first_value_ready.value
    assert ev["ready"] is True

    # Evidence is read back from the actual durable row, not fabricated.
    evidence = ev["evidence"]
    assert evidence["confirmed"] is True
    assert evidence["event_id"] == "evt-fv-42"
    assert evidence["batch_id"] == "batch-77"
    assert evidence["source"] == "bronze_sdk_events"
    assert evidence.get("bronze_id")


@pytest.mark.asyncio
async def test_first_value_transition_records_event_received_in_history(
    svc, onboard_with_keys
):
    tenant = "tenant-fv-history"
    await onboard_with_keys(svc, tenant)
    await _write_bronze_event(tenant, "evt-fv-hist")

    await svc.evaluate_first_value(tenant)
    status = await svc.get_status(tenant)
    reached = {h["to"] for h in status["history"]}
    # The record honestly passed through event_received on its way to ready.
    assert S.event_received.value in reached
    assert S.first_value_ready.value in reached
    assert status["waiting_reason"] is None


@pytest.mark.asyncio
async def test_evidence_reflects_a_different_event_id(svc, onboard_with_keys):
    """The evidence tracks whatever id is actually durable — proving the read
    is honest and not a constant."""
    tenant = "tenant-fv-distinct"
    await onboard_with_keys(svc, tenant)
    await _write_bronze_event(tenant, "totally-unique-99")

    ev = await svc.evaluate_first_value(tenant)
    assert ev["ready"] is True
    assert ev["evidence"]["event_id"] == "totally-unique-99"
