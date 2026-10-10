"""Provider AetherEvents do not enter SDK-only projection or identity paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from shared.events.events import Event, Topic
from shared.integration_contracts.events import make_aether_event
from ingestion.ingestion import workers
from ingestion.ingestion.spine import is_provider_canonical_event, is_provider_delivery


def _provider_bus_event(*, legacy: bool = False, event_type: str = "order_completed") -> Event:
    canonical = make_aether_event(
        provider_identity="shopify.admin.orders_read",
        event_type=event_type,
        event_family="commerce",
        tenant_id="tenant-1",
        source_record_id="raw-1",
        subject_id="shopify-customer-local-id",
        data={"order_id": "order-1", "amount": "12.50"},
    )
    payload = canonical.model_dump()
    payload["event_id"] = "provider-event-1"
    if not legacy:
        payload["source_type"] = "provider"
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="tenant-1",
        source_service="provider_runtime.bridge" if legacy else "ingestion.outbox_relay",
        payload=payload,
    )


def test_provider_detection_requires_aether_event_lineage_not_marker_alone():
    assert is_provider_canonical_event(_provider_bus_event().payload)
    assert is_provider_canonical_event(_provider_bus_event(legacy=True).payload)
    assert is_provider_delivery(_provider_bus_event().payload, "ingestion.outbox_relay")
    assert is_provider_delivery(_provider_bus_event(legacy=True).payload, "provider_runtime.bridge")
    assert not is_provider_delivery(_provider_bus_event().payload, "ingestion.batch")
    assert not is_provider_delivery(_provider_bus_event(legacy=True).payload, "ingestion.outbox_relay")
    assert not is_provider_canonical_event({
        "source_type": "provider",
        "provider": "shopify",
        "provider_identity": "shopify.admin.orders_read",
        "source_record_id": "raw-1",
        "occurred_at": "2026-10-03T00:00:00Z",
        "data": {},
        "properties": {},  # normalized SDK payload keeps its SDK shape
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_sdk_only_workers_defer_provider_payload_and_emit_metric(monkeypatch, legacy):
    event = _provider_bus_event(legacy=legacy)
    calls = []

    class ForbiddenSilver:
        async def upsert_record(self, **kwargs):
            raise AssertionError("provider event reached SDK Silver normalizer")

    monkeypatch.setattr(workers, "_silver", ForbiddenSilver())
    monkeypatch.setattr(
        workers,
        "_analytics_repo",
        lambda: (_ for _ in ()).throw(AssertionError("provider event reached SDK analytics")),
    )
    with mock.patch("ingestion.silver.dispatcher.SilverDispatcher.project_with_outcome", side_effect=AssertionError("provider event reached SDK facts")):
        with mock.patch.object(workers.metrics, "increment", side_effect=lambda name, **kw: calls.append((name, kw))):
            await workers.silver_normalizer(event)
            await workers.silver_fact_projector(event)
            await workers.analytics_event_recorder(event)

    assert [kw["labels"]["consumer"] for name, kw in calls if name == "ingestion_provider_projection_deferred_total"] == [
        "silver_normalizer", "silver_fact_projector", "analytics_event_recorder"
    ]
    assert all(set(kw["labels"]) == {"consumer"} for name, kw in calls if name == "ingestion_provider_projection_deferred_total")


@pytest.mark.asyncio
async def test_provider_identity_signal_is_deferred():
    event = _provider_bus_event(event_type="identify")
    producer = SimpleNamespace(publish=mock.AsyncMock(side_effect=AssertionError("identity signal published")))

    await workers.identity_signal_emitter(event, producer)
    producer.publish.assert_not_called()


@pytest.mark.asyncio
async def test_flat_sdk_event_retains_normalizer_path(monkeypatch):
    captured = []

    class RecordingSilver:
        async def upsert_record(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(workers, "_silver", RecordingSilver())
    sdk = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="tenant-1",
        payload={
            "event_id": "sdk-1",
            "event_type": "page",
            "user_id": "user-1",
            "properties": {},
            "timestamp": "2026-10-03T00:00:00Z",
            "tenant_id": "tenant-1",
        },
    )
    assert not is_provider_canonical_event(sdk.payload)
    await workers.silver_normalizer(sdk)
    assert len(captured) == 1
    assert captured[0]["source"] == "sdk"
    assert captured[0]["entity_id"] == "user-1"
