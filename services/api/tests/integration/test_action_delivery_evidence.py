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
from actions.delivery.adapters.jira import JiraAdapter
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


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "valid_journey", "valid_risk", "missing_credential", "wrong_project", "wrong_title",
    "wrong_key", "readback_failed", "foreign_tenant", "wrong_subject", "wrong_subject_kind",
    "wrong_dispatch", "wrong_policy", "wrong_receipt", "wrong_association", "future",
    "ambiguous", "revoked_decision", "rebound_payload", "rebound_site",
])
async def test_credential_bound_readback_worker_to_reader(case, monkeypatch):
    from actions.delivery.adapters import jira as jira_module
    from actions.delivery.adapters.jira import JiraAdapter
    from governance.security.repositories import PolicyDecisionRepository
    from intelligence.intelligence.repositories import (
        ActionDispatchRepository, ActionFeedbackRepository, DecisionRepository, RecommendationRepository,
    )
    from repositories.delivery_repos import ProviderExecutionVerificationRepository

    association_key = "risk_action_association" if case == "valid_risk" else "journey_action_association"
    association = {
        "record_id": "association-1", "subject_id": "subject-1", "subject_kind": "entity",
        "kind": "risk_intervention" if case == "valid_risk" else "journey_action_intent",
        "link_state": "caller_associated", "action_key": "create_issue", "action_type": "create",
        "recommendation_id": "recommendation-1", "version_id": "version-1", "intervention_id": "intervention-1",
    }
    dispatch = {
        "id": "dispatch-readback", "dispatch_id": "dispatch-readback", "tenant_id": "tenant-a",
        "action_id": "action-1", "dispatch_policy_decision_id": "policy-1",
        "decision_id": "decision-1", "recommendation_id": "recommendation-1", "status": "queued",
        "dispatch_actor_id": "user-1", "dispatch_action_key": "create_issue",
        "dispatch_action_type": "create", "dispatch_requires_elevation": False,
        "dispatch_approval_id": None, "target_type": "jira", association_key: association,
        "payload": {"title": "Approved action"},
        f"{association_key}_record_id": "association-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    associated_at = datetime.fromisoformat(dispatch["created_at"])
    policies = PolicyDecisionRepository()
    await policies.insert("policy-1", {
        "decision_id": "policy-1", "tenant_id": "tenant-a", "policy_key": "action.dispatch",
        "actor_type": "tenant_user", "actor_id": "user-1", "action": "dispatch",
        "resource_type": "action", "resource_id": "action-1", "allowed": True,
        "evaluated_at": dispatch["created_at"], "context": {
            "dispatch_id": dispatch["dispatch_id"], "target_type": "jira",
            "selected_action_key": "create_issue", "selected_action_type": "create",
            "is_elevated": False, "approval_id": None, "association_record_id": "association-1",
        },
    })
    await ActionDispatchRepository().insert(dispatch["id"], dispatch)
    intents, jobs = DeliveryIntentRepository(), DeliveryJobRepository()
    intent = DeliveryIntent(id=f"action-{dispatch['id']}", tenant_id="tenant-a",
                            source_type="action", source_id=dispatch["id"], channels=["jira"])
    await intents.insert(intent.id, intent.model_dump())
    job = DeliveryJob(intent_id=intent.id, tenant_id="tenant-a", channel=DeliveryChannel.JIRA,
                      provider_adapter="jira", provider_config={"base_url": SITE, "project_key": "OPS"},
                      payload=dispatch["payload"], idempotency_key=dispatch["id"])
    await jobs.insert(job.id, job.model_dump())
    requests = []

    class Response:
        headers = {}

        def __init__(self, method):
            self.status_code = 201 if method == "POST" else 503 if case == "readback_failed" else 200

        def json(self):
            return {"id": "360", "key": "OTHER-1" if case == "wrong_key" else "OPS-360", "fields": {
                "project": {"key": "OTHER" if case == "wrong_project" else "OPS"},
                "summary": "Different" if case == "wrong_title" else "Approved action",
            }}

    async def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        response = Response(method)
        if method == "POST":
            response.json = lambda: {"id": "360", "key": "OPS-360"}
        return response

    credential_reads = []

    async def credential(job):
        credential_reads.append(job["id"])
        return None if case == "missing_credential" and len(credential_reads) > 1 else "Bearer scoped-token"

    monkeypatch.setattr(jira_module, "send_public_request", request)
    registry = ProviderAdapterRegistry()
    registry.register(JiraAdapter())
    worker = DeliveryWorker(job_repo=jobs, intent_repo=intents, adapter_registry=registry,
                            attempt_repo=DeliveryAttemptRepository(), receipt_repo=ProviderReceiptRepository(),
                            resource_link_repo=ExternalResourceLinkRepository())
    monkeypatch.setattr(worker, "_resolve_credential", credential)
    await worker._process_job(await jobs.find_by_id(job.id))
    verifications = ProviderExecutionVerificationRepository()
    records = await verifications.find_many(filters={"tenant_id": "tenant-a"}, limit=10)
    if case in {"missing_credential", "wrong_project", "wrong_title", "wrong_key", "readback_failed"}:
        assert records == []
        evidence, complete = await read_action_delivery_evidence(tenant_id="tenant-a", dispatch=dispatch)
        assert complete and evidence["independentExecutionVerifications"] == []
        assert evidence["connectorReportedDeliveries"][0]["executionVerificationStatus"] == "not_verified"
        return
    assert len(records) == 1
    verification = records[0]
    mutations = {
        "wrong_subject": {"subject_id": "other"},
        "wrong_subject_kind": {"subject_kind": "other"}, "wrong_dispatch": {"dispatch_id": "other"},
        "wrong_policy": {"policy_decision_id": "other"}, "wrong_receipt": {"receipt_id": "other"},
        "wrong_association": {"association_record_id": "other"}, "future": {"observed_at": "2999-01-01T00:00:00Z"},
    }
    if case in mutations:
        await verifications.update(verification["id"], mutations[case])
    if case == "foreign_tenant":
        async def foreign_rows(self, tenant_id, receipt_id):
            return [{**verification, "tenant_id": "tenant-b"}]

        monkeypatch.setattr(ProviderExecutionVerificationRepository, "find_for_receipt", foreign_rows)
    if case == "ambiguous":
        await verifications.insert("duplicate", {**verification, "id": "duplicate"})
    if case == "revoked_decision":
        await policies.update("policy-1", {"allowed": False})
    if case == "rebound_payload":
        await jobs.update(job.id, {"payload": {"title": "Unapproved action"}})
    if case == "rebound_site":
        await jobs.update(job.id, {"provider_config": {"base_url": "https://other.example.test", "project_key": "OPS"}})
    evidence, complete = await read_action_delivery_evidence(tenant_id="tenant-a", dispatch=dispatch)
    if case in {"valid_journey", "valid_risk"}:
        assert complete
        assert len(evidence["independentExecutionVerifications"]) == 1
        assert evidence["independentExecutionVerifications"][0]["subjectId"] == "subject-1"
        assert requests[-1][0] == "GET"
        assert requests[-1][2]["headers"]["Authorization"] == "Bearer scoped-token"
        await ActionFeedbackRepository().insert("action-1", {
            "tenant_id": "tenant-a", "action_id": "action-1", "decision_id": "decision-1",
            "recommendation_id": "recommendation-1", "action_type": "create",
        })
        await DecisionRepository().insert("decision-1", {
            "tenant_id": "tenant-a", "decision_id": "decision-1", "recommendation_id": "recommendation-1",
            "decision_status": "approved", "selected_action": {"action_key": "create_issue", "action_type": "create"},
        })
        await RecommendationRepository().insert("recommendation-1", {
            "tenant_id": "tenant-a", "recommendation_id": "recommendation-1", "entity_id": "subject-1",
        })
        if case == "valid_journey":
            from actions.agent.journey_dispatch_association import read_journey_dispatches

            rows, complete = await read_journey_dispatches(
                tenant_id="tenant-a", journey_id="subject-1", version_id="version-1", record_id="association-1",
                action_key="create_issue", action_type="create", recommendation_id="recommendation-1",
                recorded_at=associated_at, occurred_at=associated_at,
            )
        else:
            from types import SimpleNamespace
            from actions.agent.risk_dispatch_association import read_risk_dispatches

            record = SimpleNamespace(
                tenant_id="tenant-a", record_id="association-1", subject_id="subject-1", subject_kind="entity",
                intervention_id="intervention-1", intervention_type="create_issue", record_kind="decision",
                decision_state="approved", recorded_at=associated_at, observed_at=associated_at, effective_at=associated_at,
            )
            rows, complete = await read_risk_dispatches(tenant_id="tenant-a", record=record)
        assert complete and len(rows) == 1
        assert rows[0]["externalEffect"] == "provider_resource_readback_verified"
        from graph.operational_intelligence.models import EvidenceRef

        assert any(EvidenceRef.model_validate(reference).source == "provider_execution_verifications"
                   for reference in rows[0]["evidenceRefs"])
    elif case == "wrong_receipt":
        assert complete and evidence["independentExecutionVerifications"] == []
    else:
        assert not complete and evidence["independentExecutionVerifications"] == []


@pytest.mark.asyncio
async def test_jira_readback_requires_credential_and_exact_canonical_resource(monkeypatch):
    from types import SimpleNamespace
    import actions.delivery.adapters.jira as jira_module
    calls = []
    async def request(method, url, *, headers, timeout):
        calls.append((method, url, headers))
        return SimpleNamespace(status_code=200, json=lambda: {
            "key": "OPS-360", "fields": {"summary": "Approved action", "project": {"key": "OPS"}}
        })
    monkeypatch.setattr(jira_module, "send_public_request", request)
    adapter = JiraAdapter()
    config = {"base_url": SITE, "project_key": "OPS"}
    payload = {"title": "Approved action"}
    assert await adapter.verify_readback("OPS-360", payload, config, "Bearer scoped-token")
    assert calls[0][0] == "GET" and calls[0][1].endswith("/issue/OPS-360")
    assert calls[0][2]["Authorization"] == "Bearer scoped-token"
    assert not await adapter.verify_readback("OPS-360", payload, config, None)
    assert not await adapter.verify_readback("OPS-360", {"title": "different"}, config, "Bearer scoped-token")
