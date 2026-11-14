"""A notification for a tenant with an active channel queues delivery jobs.

The consumer, the emit route and the replay route each write one delivery
intent and one job per active channel, all under the notification's tenant.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from repositories.repos import reset_in_memory_stores  # noqa: E402

TENANT = "tenant-delivery"


def _run(coro):
    return asyncio.run(coro)


class _Consumer:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def subscribe(self, topic, handler):
        self.handlers[topic] = handler


class _Tenant:
    tenant_id = TENANT
    user_id = "user-1"

    def require_permission(self, permission: str) -> None:
        return None


@pytest.fixture(autouse=True)
def channel():
    from repositories.repos import UserNotificationChannelRepository

    reset_in_memory_stores()
    _run(UserNotificationChannelRepository().create({
        "id": "ch-1", "tenant_id": TENANT, "user_id": "u", "channel_type": "notification",
        "active": True, "created_at": "2026-10-01T00:00:00+00:00",
    }))
    yield
    reset_in_memory_stores()


def _queued() -> tuple[list[dict], list[dict]]:
    from repositories.delivery_repos import DeliveryIntentRepository, DeliveryJobRepository

    return (
        _run(DeliveryIntentRepository().find_many(limit=50)),
        _run(DeliveryJobRepository().find_many(limit=50)),
    )


def _assert_one_job_per_intent(intents: list[dict], jobs: list[dict]) -> None:
    assert intents and len(jobs) == len(intents)
    assert {row["tenant_id"] for row in intents + jobs} == {TENANT}
    assert {job["intent_id"] for job in jobs} == {intent["id"] for intent in intents}
    # The redacted push projection travels with the job payload.
    assert all(job["payload"].get("push_title") for job in jobs)


def _client() -> TestClient:
    from journeys.notification_intelligence.routes import router

    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _tenant(request: Request, call_next):
        request.state.tenant = _Tenant()
        return await call_next(request)

    return TestClient(app)


def test_consumed_event_queues_delivery_jobs():
    from journeys.notification_intelligence.consumer import attach_notification_consumers
    from shared.events.events import Event, Topic

    consumer = _Consumer()
    attach_notification_consumers(consumer)
    _run(consumer.handlers[Topic.ANOMALY_DETECTED](Event(
        topic=Topic.ANOMALY_DETECTED, payload={"title": "Spike"}, tenant_id=TENANT,
    )))

    _assert_one_job_per_intent(*_queued())


def test_emitted_and_replayed_notifications_queue_delivery_jobs():
    client = _client()
    emitted = client.post("/v1/notifications/intelligence", json={
        "tenant_id": TENANT, "source_topic": "aether.anomaly.detected",
        "severity": "P1", "notification_class": "alert", "title": "Spike",
        "body": "body", "what": "what", "why": "why", "impact": "impact",
    })
    assert emitted.status_code in (200, 201), emitted.text
    intents, jobs = _queued()
    assert len(intents) == 1
    _assert_one_job_per_intent(intents, jobs)

    notification_id = intents[0]["source_id"]
    replayed = client.post(
        f"/v1/notifications/intelligence/{notification_id}/replay", params={"tenantId": TENANT},
    )
    assert replayed.status_code == 202, replayed.text
    assert replayed.json()["data"]["jobs_queued"] == 1
    intents, jobs = _queued()
    assert len(intents) == 2
    _assert_one_job_per_intent(intents, jobs)
