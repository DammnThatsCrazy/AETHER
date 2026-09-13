"""Tests for the event bridge (Bronze-before-publish; publish never fails ingest)."""

from __future__ import annotations

from unittest import mock

import pytest

from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from shared.integration_contracts.events import make_aether_event
from shared.events.events import Topic

from services.provider_runtime import bridge as bridge_module
from services.provider_runtime.bridge import EventBridge

# make_aether_event does not accept an event_id; model_copy keeps the helper's
# event ids deterministic so tests can assert on them.
def _event(event_id: str = "evt_1", *, tenant_id: str = "tenant-1", **overrides):
    base = make_aether_event(
        provider_identity="shopify.orders.catalog",
        event_type="commerce.order.created",
        event_family="commerce",
        tenant_id=tenant_id,
        source_record_id="raw_1",
        data={"order_id": event_id},
        context={"acquisition_mode": "poll"},
        **overrides,
    )
    return base.model_copy(update={"event_id": event_id})


@pytest.fixture
def bronze() -> BronzeRepository:
    reset_in_memory_stores()
    return BronzeRepository("test_connector_events")


@pytest.fixture
def event_bridge(bronze: BronzeRepository) -> EventBridge:
    return EventBridge(bronze=bronze)


@pytest.mark.asyncio
async def test_ingest_events_returns_count(event_bridge: EventBridge):
    count = await event_bridge.ingest_events("tenant-1", [_event(), _event("evt_2")])
    assert count == 2


@pytest.mark.asyncio
async def test_ingest_writes_bronze_rows(event_bridge: EventBridge, bronze: BronzeRepository):
    await event_bridge.ingest_events("tenant-1", [_event("evt_1")])
    rows = await bronze.find_many(filters={"tenant_id": "tenant-1"})
    assert len(rows) == 1
    assert rows[0]["source"] == "shopify"
    assert rows[0]["source_tag"] == "provider:shopify:tenant-1"
    assert rows[0]["provider_record_id"] == "evt_1"
    assert rows[0]["payload"]["event_type"] == "commerce.order.created"


@pytest.mark.asyncio
async def test_publish_uses_sdk_events_validated(event_bridge: EventBridge):
    captured: list[dict] = []

    async def _fake_publish(tenant_id: str, event) -> None:
        captured.append({"tenant_id": tenant_id, "event_id": event.event_id})

    with mock.patch.object(bridge_module, "_publish_event", side_effect=_fake_publish):
        await event_bridge.ingest_events("tenant-1", [_event("evt_1"), _event("evt_2")])
    assert [c["event_id"] for c in captured] == ["evt_1", "evt_2"]
    assert all(c["tenant_id"] == "tenant-1" for c in captured)


@pytest.mark.asyncio
async def test_publish_failure_does_not_fail_ingestion(event_bridge: EventBridge, bronze: BronzeRepository):
    with mock.patch.object(
        bridge_module, "_publish_event", side_effect=RuntimeError("bus down")
    ):
        count = await event_bridge.ingest_events("tenant-1", [_event("evt_1"), _event("evt_2")])
    # Ingestion still succeeds and Bronze is durable.
    assert count == 2
    rows = await bronze.find_many(filters={"tenant_id": "tenant-1"})
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_default_bronze_is_connector_events():
    bridge = EventBridge()
    assert bridge.bronze.table_name == "bronze_connector_events"
    # The canonical topic used by the publish helper matches the seam.
    assert Topic.SDK_EVENTS_VALIDATED == "aether.sdk.events.validated"
