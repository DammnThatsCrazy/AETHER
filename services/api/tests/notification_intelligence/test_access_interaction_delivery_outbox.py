from __future__ import annotations

import pytest

import journeys.notification_intelligence.customer_webhook_delivery as customer_delivery
import journeys.notification_intelligence.delivery_outbox as outbox
import repositories.repos as repos


@pytest.mark.asyncio
async def test_subscribed_access_events_queue_and_dispatch_through_hardened_delivery(monkeypatch):
    records = {}
    hooks = [
        {"id": "wh-active", "tenant_id": "tenant-a", "active": True,
         "events": ["access.interaction.completed"], "secret_ref": "ref-active",
         "url": "https://hooks.example.test/aether"},
        {"id": "wh-other-event", "tenant_id": "tenant-a", "active": True,
         "events": ["access.interaction.failed"]},
        {"id": "wh-inactive", "tenant_id": "tenant-a", "active": False,
         "events": ["access.interaction.completed"]},
        {"id": "wh-other-tenant", "tenant_id": "tenant-b", "active": True,
         "events": ["access.interaction.completed"]},
    ]

    class WebhookRepository:
        async def find_many(self, filters=None, **_kwargs):
            return [hook for hook in hooks if all(hook.get(k) == v for k, v in (filters or {}).items())]

        async def find_by_id(self, webhook_id):
            return next((hook for hook in hooks if hook["id"] == webhook_id), None)

    class OutboxRepository:
        async def insert_once(self, row_id, row):
            if row_id in records:
                return records[row_id], False
            row["id"] = row_id
            row["status"] = "queued"
            records[row_id] = row
            return row, True

    class ProviderRepository:
        pass

    class SecretStore:
        def __init__(self, _repo):
            pass

        async def resolve(self, tenant_id, secret_ref):
            assert (tenant_id, secret_ref) == ("tenant-a", "ref-active")
            return "private-signing-secret"

    delivered = []

    class DeliveryService:
        async def deliver(self, **kwargs):
            delivered.append(kwargs)
            return customer_delivery.WebhookDeliveryOutcome(
                status="delivered", success=True, webhook_id="wh-active", tenant_id="tenant-a",
                idempotency_key="delivery-key", attempts=1, status_code=204,
                latency_ms=10.0, attempt_id="attempt-1",
            )

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(repos, "WebhookRepository", WebhookRepository)
    monkeypatch.setattr(repos, "ProvidersRepository", ProviderRepository)
    monkeypatch.setattr(outbox, "get_delivery_outbox_repository", lambda: OutboxRepository())
    monkeypatch.setattr(outbox, "publish_notification_event", publish)
    monkeypatch.setattr(customer_delivery, "CustomerWebhookSecretStore", SecretStore)
    monkeypatch.setattr(customer_delivery, "CustomerWebhookDeliveryService", DeliveryService)

    event = {
        "schema_version": "1.0", "id": "request-1",
        "type": "access.interaction.completed", "surface": "cli",
        "capability_id": "entities.list", "outcome": "allowed",
        "audit_event_id": "audit-1", "usage_event_id": "meter-1",
    }
    rows = await outbox.queue_access_interaction_event("tenant-a", event)
    assert len(rows) == 1
    assert rows[0]["channel"] == "customer_webhook:wh-active"
    assert rows[0]["notification"] == event

    await outbox.deliver_outbox_row(rows[0])
    assert delivered[0]["tenant_id"] == "tenant-a"
    assert delivered[0]["webhook_id"] == "wh-active"
    assert delivered[0]["event_id"] == "request-1"
    assert delivered[0]["payload"]["audit_event_id"] == "audit-1"
    assert rows[0]["delivery"]["status"] == "delivered"
    assert "private-signing-secret" not in str(rows[0])

    records[rows[0]["id"]]["status"] = "delivered"
    duplicate = await outbox.queue_access_interaction_event("tenant-a", event)
    assert duplicate == []
    assert records[rows[0]["id"]]["status"] == "delivered"


@pytest.mark.asyncio
async def test_customer_webhook_sink_fails_closed_for_cross_tenant_config(monkeypatch):
    class WebhookRepository:
        async def find_by_id(self, _webhook_id):
            return {"id": "wh-1", "tenant_id": "another-tenant", "active": True}

    monkeypatch.setattr(repos, "WebhookRepository", WebhookRepository)
    row = {
        "id": "outbox-1", "tenant_id": "tenant-a", "channel": "customer_webhook:wh-1",
        "notification": {"id": "request-1", "type": "access.interaction.completed"},
    }
    with pytest.raises(RuntimeError, match="no active customer webhook"):
        await outbox._deliver_customer_webhook_row(
            row, "tenant-a", "customer_webhook:wh-1", row["notification"],
        )


@pytest.mark.asyncio
async def test_queue_rejects_event_types_outside_the_access_interaction_contract():
    with pytest.raises(ValueError, match="unsupported"):
        await outbox.queue_access_interaction_event(
            "tenant-a", {"id": "x", "type": "entity.created"},
        )
