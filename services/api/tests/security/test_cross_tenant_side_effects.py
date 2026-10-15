"""Background writes and fan-out stay inside one tenant.

Delivery receipts, outcome webhooks, notification fan-out, Profile 360 drill
and CIS provenance reads each act on an id; ``own_tenant`` must never change or
see ``other_tenant``'s row through them, and an event with no tenant fans out to
nobody.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from repositories.repos import reset_in_memory_stores  # noqa: E402

OWN = "own_tenant"
OTHER = "other_tenant"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── delivery worker: suggestion advanced on receipt ──────────────────────────


def test_delivery_receipt_advances_only_the_jobs_tenants_suggestion():
    from actions.delivery.adapters.base import AdapterReceipt, ProviderAdapter, ProviderAdapterRegistry
    from actions.delivery.models import DeliveryChannel, DeliveryIntent, DeliveryJob, DeliveryJobPriority
    from actions.delivery.worker import DeliveryWorker
    from intelligence.suggestions.repository import SuggestionRepository
    from repositories.delivery_repos import (
        DeliveryAttemptRepository, DeliveryIntentRepository, DeliveryJobRepository,
        ExternalResourceLinkRepository, ProviderReceiptRepository,
    )

    class _Ok(ProviderAdapter):
        adapter_name = "ok"

        async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
            return AdapterReceipt(external_id="ext-1", raw_response={}, http_status=200)

    suggestions = SuggestionRepository()
    for sid, tenant in (("sugg-own", OWN), ("sugg-other", OTHER)):
        _run(suggestions.insert(sid, {"id": sid, "tenant_id": tenant, "status": "approved"}))
    intents, jobs = DeliveryIntentRepository(), DeliveryJobRepository()
    registry = ProviderAdapterRegistry()
    registry.register(_Ok())
    worker = DeliveryWorker(
        job_repo=jobs, intent_repo=intents, attempt_repo=DeliveryAttemptRepository(),
        receipt_repo=ProviderReceiptRepository(), resource_link_repo=ExternalResourceLinkRepository(),
        adapter_registry=registry,
    )

    for source_id in ("sugg-other", "sugg-own"):
        intent = DeliveryIntent(tenant_id=OWN, source_type="suggestion", source_id=source_id, channels=["ok"])
        _run(intents.insert(intent.id, intent.model_dump()))
        job = DeliveryJob(
            intent_id=intent.id, tenant_id=OWN, channel=DeliveryChannel.NOTIFICATION,
            provider_adapter="ok", priority=DeliveryJobPriority.P2, payload={"title": "t"},
        )
        _run(jobs.insert(job.id, job.model_dump()))
        _run(worker._process_job(job.model_dump()))

    assert _run(suggestions.find_by_id("sugg-other"))["status"] == "approved"
    assert _run(suggestions.find_by_id("sugg-own"))["status"] == "delivered"


# ── outcome router: notification advanced from a webhook ─────────────────────


def test_outcome_updates_only_the_webhook_tenants_notification():
    from actions.delivery.models import ExternalOutcomeEvent, ExternalOutcomeType
    from actions.delivery.outcome_processor import OutcomeRouter
    from repositories.delivery_repos import ExternalOutcomeEventRepository, ExternalResourceLinkRepository
    from repositories.repos import NotificationIntelligenceRepository

    notifications = NotificationIntelligenceRepository()
    for nid, tenant in (("n-own", OWN), ("n-other", OTHER)):
        _run(notifications.create({"id": nid, "tenant_id": tenant, "lifecycle_state": "queued"}))
    router = OutcomeRouter(
        outcome_repo=ExternalOutcomeEventRepository(), link_repo=ExternalResourceLinkRepository(),
        notification_repo=notifications,
    )
    outcome = ExternalOutcomeEvent(
        tenant_id=OWN, provider="webhook", external_id="x", outcome_type=ExternalOutcomeType.DELIVERED,
        raw_payload={"event_type": "delivered"},
    )

    _run(router._route_to_notification(outcome, link={"notification_id": "n-other"}))
    _run(router._route_to_notification(outcome, link={"notification_id": "n-own"}))

    assert "last_external_outcome" not in _run(notifications.find_by_id("n-other"))
    assert _run(notifications.find_by_id("n-own"))["last_external_outcome"] == "delivered"


# ── notification consumer: tenant-less events ────────────────────────────────


class _CapturingConsumer:
    def __init__(self) -> None:
        self.handlers = {}

    def subscribe(self, topic, handler):
        self.handlers[topic] = handler


def test_notification_consumer_drops_events_without_a_tenant():
    from journeys.notification_intelligence.consumer import attach_notification_consumers
    from repositories.delivery_repos import DeliveryIntentRepository, DeliveryJobRepository
    from repositories.repos import NotificationIntelligenceRepository, UserNotificationChannelRepository
    from shared.events.events import Event, Topic

    channels = UserNotificationChannelRepository()
    for cid, tenant in (("ch-unowned", ""), ("ch-own", OWN)):
        _run(channels.create({
            "id": cid, "tenant_id": tenant, "user_id": "u", "channel_type": "notification",
            "active": True, "created_at": "2026-10-01T00:00:00+00:00",
        }))
    notifications, intents = NotificationIntelligenceRepository(), DeliveryIntentRepository()
    consumer = _CapturingConsumer()
    attach_notification_consumers(
        consumer, repo=notifications, intent_repo=intents, job_repo=DeliveryJobRepository(),
    )
    handle = consumer.handlers[Topic.ANOMALY_DETECTED]

    _run(handle(Event(topic=Topic.ANOMALY_DETECTED, payload={"title": "unowned"}, tenant_id="")))
    assert _run(notifications.find_many(limit=10)) == []
    assert _run(intents.find_many(limit=10)) == []

    _run(handle(Event(topic=Topic.ANOMALY_DETECTED, payload={"title": "own"}, tenant_id=OWN)))
    assert [n["tenant_id"] for n in _run(notifications.find_many(limit=10))] == [OWN]
    assert [i["tenant_id"] for i in _run(intents.find_many(limit=10))] == [OWN]


# ── Profile 360 drill: legacy rows without a tenant ──────────────────────────


def test_profile_drill_rejects_rows_without_a_tenant():
    from identity.profile.aggregator import Profile360Aggregator
    from repositories.repos import WalletRepository

    wallets = WalletRepository()
    _run(wallets.insert("w-unowned", {
        "wallet_id": "w-unowned", "owner_entity_id": "entity-1", "chain": "eth", "address": "0xa",
    }))
    _run(wallets.link_wallet("w-own", "entity-1", OWN, "eth", "0xb"))
    agg = Profile360Aggregator()

    assert _run(agg.drill("entity-1", OWN, "wallet", "w-unowned"))["found"] is False
    assert _run(agg.drill("entity-1", OWN, "wallet", "w-own"))["found"] is True


# ── CIS provenance: no database pool outside local ───────────────────────────


def test_provenance_fallback_checks_the_tenant_outside_local(monkeypatch):
    from shared.cis.provenance import ProvenanceRecord, ProvenanceTracker

    tracker = ProvenanceTracker()
    _run(tracker.record(ProvenanceRecord(
        entity_id="e-1", entity_type="claim", tenant_id=OWN, lineage_hash="h",
    )))
    monkeypatch.setenv("AETHER_ENV", "staging")

    async def _no_pool():
        return None

    monkeypatch.setattr(tracker, "_get_pool", _no_pool)

    assert _run(tracker.get("e-1", OTHER)) is None
    assert _run(tracker.get("e-1", OWN)).tenant_id == OWN
