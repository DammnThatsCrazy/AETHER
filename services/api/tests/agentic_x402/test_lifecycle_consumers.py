"""Wiring and authority tests for the lifecycle consumers.

The x402 and agent lifecycle mappers are only useful if a registered consumer
calls them, and only safe if each consumer honours its source-authority rules.
These tests pin both: the consumer specs subscribe the handlers to the right
topics, public-SDK terminal claims are not projected, untrusted sources are
deferred, and trusted events reach the mapper.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from actions.agent import lifecycle_consumer
from ingestion.ingestion import lifecycle_worker
from repositories.repos import (
    PaymentIntentRepository,
    SettlementEventRepository,
    reset_in_memory_stores,
)
from shared.events.events import Event, Topic
from value.x402.provenance import AUTHORITATIVE_X402_SOURCES
from workers.runtime import consumer_specs

TENANT = "tenant-a"


@pytest.fixture(autouse=True)
def isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _spec(name: str):
    return next(spec for spec in consumer_specs.CONSUMER_SPECS if spec.name == name)


def _subscriptions(handler_factory):
    """Run a spec's attach function against a recording registry."""
    seen: list[tuple[Topic, object]] = []
    registry = SimpleNamespace(
        consumer=SimpleNamespace(subscribe=lambda topic, fn: seen.append((topic, fn))),
        graph=object(),
    )
    handler_factory(registry)
    return seen


def test_x402_authoritative_consumer_is_registered_for_every_commerce_topic():
    spec = _spec("x402-lifecycle-projection")
    assert spec.role == "graph-writer"
    subs = _subscriptions(spec.handler_factory)
    assert {topic.value for topic, _ in subs} == set(AUTHORITATIVE_X402_SOURCES)
    assert all(fn is lifecycle_worker.project_authoritative_x402_lifecycle for _, fn in subs)


def test_sdk_observation_projection_is_subscribed_to_validated_sdk_events():
    spec = next(
        s for s in consumer_specs.CONSUMER_SPECS if Topic.SDK_EVENTS_VALIDATED in s.topics
        and s.handler_factory is consumer_specs._attach_stream_ingestion
    )
    subs = _subscriptions(spec.handler_factory)
    assert (
        Topic.SDK_EVENTS_VALIDATED,
        lifecycle_worker.project_sdk_lifecycle_observation,
    ) in subs


def test_agent_execution_consumer_is_wired_through_the_graph_spec(monkeypatch):
    monkeypatch.setattr(
        "workers.profile360_workers.attach_profile360_workers", lambda *a, **k: None
    )
    spec = _spec("graph-profile-projection")
    subs = dict(_subscriptions(spec.handler_factory))
    for topic in (
        Topic.AGENT_EXECUTION_STARTED,
        Topic.AGENT_EXECUTION_COMPLETED,
        Topic.AGENT_EXECUTION_FAILED,
    ):
        assert subs[topic] is lifecycle_consumer.project_agent_execution_lifecycle


@pytest.mark.asyncio
async def test_sdk_intent_observation_is_projected_with_observed_provenance():
    event = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_type": "x402_payment_intent_created",
            "event_id": "evt-1",
            "properties": {
                "payment_intent_id": "pi-1",
                "agent_id": "agent-1",
                "amount": "5.00",
                "currency": "USDC",
                "provider": "x402",
                "protocol": "x402",
            },
        },
    )
    await lifecycle_worker.project_sdk_lifecycle_observation(event)
    rows = await PaymentIntentRepository().list_for_agent("agent-1", TENANT)
    assert any(r["intent_id"] == "pi-1" for r in rows)


@pytest.mark.asyncio
async def test_sdk_settlement_claim_is_never_projected():
    event = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_type": "x402_payment_settled",
            "event_id": "evt-2",
            "properties": {"payment_intent_id": "pi-2", "agent_id": "agent-2"},
        },
    )
    await lifecycle_worker.project_sdk_lifecycle_observation(event)
    assert await SettlementEventRepository().list_for_intent("pi-2", TENANT) == []
    assert await PaymentIntentRepository().list_for_agent("agent-2", TENANT) == []


@pytest.mark.asyncio
async def test_authoritative_x402_event_from_the_wrong_service_is_deferred(monkeypatch):
    called = []

    class Boom:
        async def handle_event(self, *a, **k):
            called.append(a)
            return {}

    monkeypatch.setattr("value.x402.lifecycle_mapper.X402LifecycleMapper", Boom)
    topic = next(t for t in Topic if t.value == "aether.commerce.settlement.completed")
    event = Event(
        topic=topic,
        tenant_id=TENANT,
        source_service="some.client",
        payload={"settlement_id": "s-1"},
    )
    await lifecycle_worker.project_authoritative_x402_lifecycle(event)
    assert called == []


@pytest.mark.asyncio
async def test_agent_execution_event_from_untrusted_source_is_deferred(monkeypatch):
    called = []

    class Boom:
        async def handle_event(self, *a, **k):
            called.append(a)
            return {}

    monkeypatch.setattr("actions.agent.lifecycle_mapper.AgentLifecycleMapper", Boom)
    event = Event(
        topic=Topic.AGENT_EXECUTION_STARTED,
        tenant_id=TENANT,
        source_service="public-sdk",
        payload={"agent_id": "a-1", "execution_id": "x-1"},
    )
    await lifecycle_consumer.project_agent_execution_lifecycle(event)
    assert called == []


@pytest.mark.asyncio
async def test_agent_execution_event_from_the_agent_service_reaches_the_mapper(monkeypatch):
    captured = []

    class Capture:
        async def handle_event(self, event_type, mapped, tenant_id):
            captured.append((event_type, mapped, tenant_id))
            return {"status": "ok"}

    monkeypatch.setattr("actions.agent.lifecycle_mapper.AgentLifecycleMapper", Capture)
    event = Event(
        topic=Topic.AGENT_EXECUTION_COMPLETED,
        tenant_id=TENANT,
        source_service="agents",
        payload={"agent_id": "a-1", "execution_id": "x-1"},
    )
    await lifecycle_consumer.project_agent_execution_lifecycle(event)
    assert len(captured) == 1
    event_type, mapped, tenant = captured[0]
    assert event_type == "agent_task_completed" and tenant == TENANT
    assert mapped["agent_id"] == "a-1" and mapped["execution_id"] == "x-1"
    assert mapped["evidence_status"] == "server_observed"
