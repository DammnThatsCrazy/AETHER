"""Real DeliveryWorker and signed OutcomeProcessor producers feed the 360 reader."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import pytest

from actions.agent.action_delivery_evidence import read_action_delivery_evidence
from actions.delivery.adapters.base import AdapterReceipt, ProviderAdapter, ProviderAdapterRegistry
from actions.delivery.models import DeliveryChannel, DeliveryIntent, DeliveryJob
from actions.delivery.outcome_processor import WebhookInboxProcessor
from actions.delivery.worker import DeliveryWorker
from repositories.delivery_repos import (
    DeliveryAttemptRepository, DeliveryIntentRepository, DeliveryJobRepository,
    ExternalOutcomeEventRepository, ExternalResourceLinkRepository, ProviderReceiptRepository,
    WebhookInboxRepository,
)
from repositories.repos import reset_in_memory_stores

SITE = "https://tracker.example.test"
SECRET = "callback-secret"


class Jira(ProviderAdapter):
    adapter_name = "jira"

    async def dispatch(self, payload, provider_config, *, credential=None, idempotency_key=None):
        return AdapterReceipt(external_id="OPS-360", raw_response={
            "key": "OPS-360", "self": f"{SITE}/rest/api/2/issue/123",
        }, http_status=201)


@pytest.fixture(autouse=True)
def clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_delivery_worker_and_verified_processor_are_visible_to_360_reader():
    tenant_id, dispatch_id = "tenant-a", "dispatch-360"
    dispatched_at = datetime.now(timezone.utc).isoformat()
    intent_repo, job_repo = DeliveryIntentRepository(), DeliveryJobRepository()
    intent = DeliveryIntent(id=f"action-{dispatch_id}", tenant_id=tenant_id,
                            source_type="action", source_id=dispatch_id, channels=["jira"])
    await intent_repo.insert(intent.id, intent.model_dump())
    job = DeliveryJob(intent_id=intent.id, tenant_id=tenant_id, channel=DeliveryChannel.JIRA,
                      provider_adapter="jira", provider_config={"base_url": SITE}, payload={})
    await job_repo.insert(job.id, job.model_dump())
    registry = ProviderAdapterRegistry()
    registry.register(Jira())
    worker = DeliveryWorker(job_repo=job_repo, intent_repo=intent_repo,
                            attempt_repo=DeliveryAttemptRepository(), receipt_repo=ProviderReceiptRepository(),
                            resource_link_repo=ExternalResourceLinkRepository(), adapter_registry=registry)
    await worker._process_job(await job_repo.find_by_id(job.id))

    dispatch = {"id": dispatch_id, "dispatch_id": dispatch_id, "tenant_id": tenant_id,
                "created_at": dispatched_at}
    evidence, complete = await read_action_delivery_evidence(tenant_id=tenant_id, dispatch=dispatch)
    assert complete and evidence["connectorReceiptRead"] == "complete"
    assert evidence["connectorReportedDeliveries"][0]["provider"] == "jira"
    assert evidence["connectorReportedDeliveries"][0]["externalId"] == "OPS-360"

    body = json.dumps({"webhookEvent": "jira:issue_updated",
                       "issue": {"key": "OPS-360", "self": f"{SITE}/rest/api/2/issue/123"}})
    signature = "sha256=" + hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    inbox = WebhookInboxRepository()
    await inbox.insert(str(uuid.uuid4()), {"provider": "jira", "raw_body": body,
        "headers": {"X-Hub-Signature-256": signature}, "webhook_secret": SECRET,
        "processed": False, "processing": False})
    outcomes = ExternalOutcomeEventRepository()
    processor = WebhookInboxProcessor(inbox_repo=inbox, outcome_repo=outcomes,
                                      link_repo=ExternalResourceLinkRepository())
    assert await processor.process_pending() == 1
    event_rows = await outcomes.find_many(filters={"tenant_id": tenant_id}, limit=10)
    assert len(event_rows) == 1
    assert event_rows[0]["producer_provenance"] == "verified_callback"
    assert event_rows[0]["signature_authority"] == "external_provider_signature"
    evidence, complete = await read_action_delivery_evidence(tenant_id=tenant_id, dispatch=dispatch)
    assert complete and len(evidence["verifiedCallbacks"]) == 1
    assert evidence["verifiedCallbacks"][0]["signatureAuthority"] == "external_provider_signature"
