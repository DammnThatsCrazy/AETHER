"""Every connector and SDK is optional: first value comes from ANY ingestion path.

A tenant may skip SDK keys entirely (connector-only, import-only, or browser
publishable site keys). Activation still proves first value — but only from a
durable Bronze row the tenant's own ingestion wrote, never from a step having
been taken, and never by force-moving an honest-halt state.
"""
from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from tenancy.activation.models import ActivationState as S


async def _land(store: str, tenant_id: str, *, source: str, record_id: str, tag: str = "t"):
    await BronzeRepository(store).ingest(
        source=source,
        source_tag=tag,
        provider_record_id=record_id,
        payload={"event_id": record_id},
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store", "source"),
    [
        ("provider_records", "shopify"),
        ("connector_events", "hubspot"),
        ("tenant_import", "tenant_import"),
        ("sdk_events", "sdk"),
    ],
)
async def test_first_value_without_sdk_keys_from_any_ingestion_store(svc, store, source):
    tenant = f"tenant-optional-{store}"
    status = await svc.get_status(tenant)
    assert status["state"] == S.account_verified.value  # no plan, no SDKs, no keys

    await _land(store, tenant, source=source, record_id=f"rec-{store}")

    ev = await svc.evaluate_first_value(tenant)
    assert ev["state"] == S.first_value_ready.value
    assert ev["ready"] is True
    assert ev["evidence"]["source"] == f"bronze_{store}"
    assert ev["evidence"]["event_id"] == f"rec-{store}"
    assert ev["evidence"]["confirmed"] is True

    done = await svc.complete(tenant)
    assert done["state"] == S.complete.value


@pytest.mark.asyncio
async def test_connector_evidence_reaches_first_value_from_plan_and_sdk_states(svc):
    tenant = "tenant-optional-plan"
    await svc.select_plan(tenant, "alpha")
    await svc.select_sdks(tenant, ["web"])
    await _land("provider_records", tenant, source="stripe", record_id="ch_1")

    ev = await svc.evaluate_first_value(tenant)
    assert ev["state"] == S.first_value_ready.value
    assert ev["evidence"]["source"] == "bronze_provider_records"


@pytest.mark.asyncio
async def test_no_evidence_leaves_an_early_record_untouched(svc):
    tenant = "tenant-optional-empty"
    await svc.select_plan(tenant, "alpha")
    before = await svc.get_status(tenant)

    ev = await svc.evaluate_first_value(tenant)
    assert ev["ready"] is False
    assert ev["evidence"] == {}
    after = await svc.get_status(tenant)
    assert after["state"] == before["state"]
    # Nothing was asked of the tenant yet, so nothing is reported as awaited.
    assert after["waiting_reason"] is None


@pytest.mark.asyncio
async def test_other_tenants_rows_are_never_evidence(svc):
    await _land("provider_records", "tenant-optional-other", source="shopify", record_id="foreign")
    ev = await svc.evaluate_first_value("tenant-optional-mine")
    assert ev["ready"] is False


@pytest.mark.asyncio
async def test_non_sdk_rows_in_sdk_events_are_not_evidence(svc):
    tenant = "tenant-optional-nonsdk"
    await _land("sdk_events", tenant, source="replay", record_id="not-an-sdk-event")
    ev = await svc.evaluate_first_value(tenant)
    assert ev["ready"] is False


@pytest.mark.asyncio
async def test_honest_halt_states_are_not_force_transitioned(svc):
    tenant = "tenant-optional-blocked"
    record = await svc._load_or_create(tenant)
    svc.advance(record, S.blocked, reason="test_blocker")
    await svc.repo.save_or_update(record)
    await _land("provider_records", tenant, source="shopify", record_id="r1")

    ev = await svc.evaluate_first_value(tenant)
    assert ev["state"] == S.blocked.value
    assert ev["ready"] is False
