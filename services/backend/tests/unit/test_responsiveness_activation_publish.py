"""Regressions for the responsiveness spine's activation path.

The staging API logged, on the ingestion ACK path:

* ``responsiveness first_event_ack failed: ActivationMilestone.__init__()
  missing 1 required positional argument: 'tenant_id'`` — the repository's
  ``_get`` strips ``tenant_id`` from the stored payload, and
  ``_load_milestone`` rebuilt the dataclass from that payload, so every event
  after a tenant's first one failed;
* ``responsiveness activation publish failed: 'tenant.activation.updated' is
  not a valid Topic`` — the publisher built ``Topic("tenant.activation.updated")``
  (and three sibling strings) that no ``Topic`` member declared.
"""

from __future__ import annotations

import pytest

import dependencies.providers as providers
import services.responsiveness.service as service_mod
from repositories.repos import reset_in_memory_stores
from services.responsiveness.service import ResponsivenessService
from shared.events.events import Topic


class _Producer:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)


@pytest.fixture
def spine(monkeypatch):
    reset_in_memory_stores()
    producer = _Producer()
    monkeypatch.setattr(providers, "get_producer", lambda: producer)
    warnings: list[str] = []
    monkeypatch.setattr(
        service_mod.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg) % a if a else str(msg))
    )
    yield ResponsivenessService(), producer, warnings
    reset_in_memory_stores()


async def _ack(service, tenant_id: str, n: int):
    return await service.record_first_event_ack(
        tenant_id=tenant_id,
        event_id=f"evt-{n}",
        batch_id=f"batch-{n}",
        received_at="2026-09-24T17:37:19.604646+00:00",
        ack_latency_ms=12.5,
    )


@pytest.mark.asyncio
async def test_milestone_reload_keeps_its_tenant(spine):
    service, _producer, _warnings = spine

    first = await _ack(service, "tenant-a", 1)
    second = await _ack(service, "tenant-a", 2)  # reloads the persisted row
    third = await service.mark_first_value("tenant-a", "graph_node")

    assert first.tenant_id == second.tenant_id == third.tenant_id == "tenant-a"
    assert second.first_event_acked_at == first.first_event_acked_at
    assert third.first_graph_node_at is not None


@pytest.mark.asyncio
async def test_activation_update_publishes_on_the_declared_topic(spine):
    service, producer, warnings = spine

    await _ack(service, "tenant-b", 1)
    await service.mark_first_value("tenant-b", "graph_node")

    assert warnings == []
    assert producer.events
    assert {e.topic for e in producer.events} == {Topic.TENANT_ACTIVATION_UPDATED}
    assert all(e.tenant_id == "tenant-b" for e in producer.events)


@pytest.mark.asyncio
async def test_sibling_spine_updates_publish_declared_topics(spine):
    service, producer, warnings = spine

    await service._publish_provider_update("tenant-c", "shopify")
    await service._publish_lens_update("tenant-c", "lens-1", "gv-1", "scope")
    await service._publish_job_update("tenant-c", "job-1")

    assert warnings == []
    assert [e.topic for e in producer.events] == [
        Topic.TENANT_SURFACE_READINESS_UPDATED,
        Topic.LENS_PROJECTION_UPDATED,
        Topic.BACKGROUND_JOB_UPDATED,
    ]


@pytest.mark.asyncio
async def test_persisted_surface_readiness_reloads_with_its_tenant(spine):
    service, _producer, _warnings = spine

    derived = await service.get_surface_readiness("tenant-d", "graph")
    reloaded = await service.get_surface_readiness("tenant-d", "graph")

    assert derived.tenant_id == reloaded.tenant_id == "tenant-d"
    assert reloaded.surface == derived.surface
