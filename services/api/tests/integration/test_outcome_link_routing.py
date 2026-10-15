"""A provider outcome updates the Aether object the delivery was made for.

Each test delivers a job through the real DeliveryWorker (stub Jira adapter),
then drains a signed Jira callback through the real WebhookInboxProcessor and
OutcomeRouter. The routed object comes only from the stored
ExternalResourceLink, scoped to the delivering tenant.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest

from actions.delivery.adapters.base import AdapterReceipt, ProviderAdapter, ProviderAdapterRegistry
from actions.delivery.models import (
    DeliveryChannel,
    DeliveryIntent,
    DeliveryJob,
    DeliveryJobPriority,
)
from actions.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor
from actions.delivery.worker import DeliveryWorker
from repositories.delivery_repos import (
    DeliveryAttemptRepository,
    DeliveryIntentRepository,
    DeliveryJobRepository,
    ExternalOutcomeEventRepository,
    ExternalResourceLinkRepository,
    ProviderReceiptRepository,
    WebhookInboxRepository,
)
from repositories.repos import NotificationIntelligenceRepository, reset_in_memory_stores

SITE = "https://tracker-a.example.test"
ISSUE_KEY = "OPS-101"
CALLBACK_SECRET = "jira-callback-secret"


class _StubJira(ProviderAdapter):
    adapter_name = "jira"

    async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
        return AdapterReceipt(
            external_id=ISSUE_KEY,
            raw_response={"key": ISSUE_KEY, "self": f"{SITE}/rest/api/2/issue/10001"},
            http_status=201,
        )


class _TenantSuggestions:
    """Suggestions keyed by (tenant, id) so two tenants can hold the same id."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    async def patch(self, record_id: str, tenant_id: str, data: dict) -> dict:
        row = self.rows.get((tenant_id, record_id))
        if row is None:
            raise KeyError(record_id)
        row.update(data)
        return row


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _deliver(tenant_id: str, source_type: str, source_id: str) -> None:
    intent_repo, job_repo = DeliveryIntentRepository(), DeliveryJobRepository()
    intent = DeliveryIntent(
        tenant_id=tenant_id, source_type=source_type, source_id=source_id, channels=["jira"],
    )
    await intent_repo.insert(intent.id, intent.model_dump())
    job = DeliveryJob(
        intent_id=intent.id,
        tenant_id=tenant_id,
        channel=DeliveryChannel.JIRA,
        provider_adapter="jira",
        provider_config={"base_url": SITE},
        priority=DeliveryJobPriority.P2,
        payload={"title": "Investigate"},
    )
    await job_repo.insert(job.id, job.model_dump())

    registry = ProviderAdapterRegistry()
    registry.register(_StubJira())
    worker = DeliveryWorker(
        job_repo=job_repo,
        intent_repo=intent_repo,
        attempt_repo=DeliveryAttemptRepository(),
        receipt_repo=ProviderReceiptRepository(),
        resource_link_repo=ExternalResourceLinkRepository(),
        adapter_registry=registry,
    )
    await worker._process_job(job.model_dump())


async def _drain_jira_update(*, suggestions=None, notifications=None) -> None:
    body = json.dumps({
        "webhookEvent": "jira:issue_updated",
        "issue": {"key": ISSUE_KEY, "self": f"{SITE}/rest/api/2/issue/10001"},
    })
    signature = "sha256=" + hmac.new(
        CALLBACK_SECRET.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    inbox = WebhookInboxRepository()
    record_id = str(uuid.uuid4())
    await inbox.insert(record_id, {
        "provider": "jira",
        "raw_body": body,
        "headers": {"X-Hub-Signature-256": signature},
        "webhook_secret": CALLBACK_SECRET,
        "processed": False,
        "processing": False,
    })
    outcomes, links = ExternalOutcomeEventRepository(), ExternalResourceLinkRepository()
    processor = WebhookInboxProcessor(
        inbox_repo=inbox,
        outcome_repo=outcomes,
        link_repo=links,
        router=OutcomeRouter(
            outcome_repo=outcomes,
            link_repo=links,
            suggestion_repo=suggestions,
            notification_repo=notifications,
        ),
    )
    assert await processor.process_pending() == 1
    assert (await inbox.find_by_id(record_id))["processed"] is True


@pytest.mark.asyncio
async def test_jira_outcome_updates_delivered_suggestion_only_in_its_tenant():
    suggestions = _TenantSuggestions()
    suggestions.rows[("tenant-a", "sugg-1")] = {"outcome_state": "pending"}
    suggestions.rows[("tenant-b", "sugg-1")] = {"outcome_state": "pending"}

    await _deliver("tenant-a", "suggestion", "sugg-1")
    links = await ExternalResourceLinkRepository().find_many(filters={"tenant_id": "tenant-a"})
    assert links[0]["aether_object_type"] == "suggestion"
    assert links[0]["aether_object_id"] == "sugg-1"

    await _drain_jira_update(suggestions=suggestions)

    assert suggestions.rows[("tenant-a", "sugg-1")]["outcome_state"] == "in_progress"
    assert suggestions.rows[("tenant-b", "sugg-1")] == {"outcome_state": "pending"}


@pytest.mark.asyncio
async def test_jira_outcome_updates_delivered_notification_only_in_its_tenant():
    notifications = NotificationIntelligenceRepository()
    await notifications.insert("notif-a", {"id": "notif-a", "tenant_id": "tenant-a"})
    await notifications.insert("notif-b", {"id": "notif-b", "tenant_id": "tenant-b"})

    await _deliver("tenant-a", "notification", "notif-a")
    await _drain_jira_update(suggestions=_TenantSuggestions(), notifications=notifications)

    assert (await notifications.find_by_id("notif-a"))["last_external_outcome"] == "status_changed"
    assert "last_external_outcome" not in await notifications.find_by_id("notif-b")
