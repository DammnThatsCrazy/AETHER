"""Canonical delivery evidence joins fail closed on ambiguity and spoofing."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from actions.agent.action_delivery_evidence import read_action_delivery_evidence


class Repo:
    def __init__(self, rows=(), by_id=None):
        self.rows = list(rows)
        self.by_id = by_id or {}
        self.fail = False

    async def find_by_id(self, key):
        if self.fail:
            raise RuntimeError("incomplete")
        return self.by_id.get(key)

    async def find_many(self, *, filters, limit):
        if self.fail:
            raise RuntimeError("incomplete")
        return [row for row in self.rows if all(row.get(k) == v for k, v in filters.items())][:limit]


@pytest.fixture
def chain():
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(seconds=5)
    dispatch = {"id": "d-1", "dispatch_id": "d-1", "tenant_id": "t-1", "created_at": earlier.isoformat()}
    intent = {"id": "action-d-1", "tenant_id": "t-1", "source_type": "action", "source_id": "d-1",
              "created_at": (earlier + timedelta(seconds=1)).isoformat()}
    job = {"id": "j-1", "tenant_id": "t-1", "intent_id": "action-d-1", "provider_adapter": "jira",
           "created_at": (earlier + timedelta(seconds=2)).isoformat()}
    receipt = {"id": "r-1", "tenant_id": "t-1", "intent_id": "action-d-1", "job_id": "j-1",
               "provider_adapter": "jira", "external_id": "OPS-1", "created_at": (earlier + timedelta(seconds=3)).isoformat(),
               "delivered_at": (earlier + timedelta(seconds=3)).isoformat()}
    link = {"id": "l-1", "tenant_id": "t-1", "intent_id": "action-d-1", "receipt_id": "r-1",
            "provider": "jira", "external_id": "OPS-1", "aether_object_type": "action", "aether_object_id": "d-1",
            "created_at": (earlier + timedelta(seconds=3)).isoformat()}
    event = {"id": "o-1", "tenant_id": "t-1", "intent_id": "action-d-1", "receipt_id": "r-1",
             "provider": "jira", "external_id": "OPS-1", "producer_provenance": "verified_callback",
             "signature_authority": "external_provider_signature", "outcome_type": "status_changed",
             "occurred_at": (earlier + timedelta(seconds=4)).isoformat(),
             "ingested_at": (earlier + timedelta(seconds=4)).isoformat()}
    repos = dict(intents=Repo(by_id={intent["id"]: intent}), jobs=Repo([job]), receipts=Repo([receipt]),
                 links=Repo([link]), outcomes=Repo([event]))
    return dispatch, repos


@pytest.mark.asyncio
async def test_exact_chain_exposes_delivery_and_verified_callback_without_claiming_effect(chain):
    dispatch, repos = chain
    evidence, complete = await read_action_delivery_evidence(tenant_id="t-1", dispatch=dispatch, **repos)
    assert complete and evidence["connectorReceiptRead"] == "complete"
    assert evidence["connectorReportedDeliveries"][0]["externalId"] == "OPS-1"
    assert evidence["verifiedCallbacks"][0]["signatureAuthority"] == "external_provider_signature"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "foreign_tenant", "wrong_dispatch", "wrong_receipt", "receipt_job_mismatch", "caller_asserted", "malformed",
    "malformed_callback", "duplicate_receipt", "duplicate_link", "missing_receipt", "incomplete_read",
])
async def test_mismatch_spoof_and_incomplete_delivery_evidence_fail_closed(chain, mutation):
    dispatch, repos = chain
    repos = deepcopy(repos)
    if mutation == "foreign_tenant":
        repos["jobs"].rows[0]["tenant_id"] = "t-2"
    elif mutation == "wrong_dispatch":
        repos["intents"].by_id["action-d-1"]["source_id"] = "d-other"
    elif mutation == "wrong_receipt":
        repos["outcomes"].rows[0]["receipt_id"] = "r-other"
    elif mutation == "receipt_job_mismatch":
        repos["receipts"].rows[0]["job_id"] = "j-other"
    elif mutation == "caller_asserted":
        repos["outcomes"].rows[0]["producer_provenance"] = "caller_asserted"
    elif mutation == "malformed":
        repos["receipts"].rows[0]["delivered_at"] = "not-a-time"
    elif mutation == "malformed_callback":
        repos["outcomes"].rows[0]["occurred_at"] = "not-a-time"
    elif mutation == "duplicate_receipt":
        repos["receipts"].rows.append(dict(repos["receipts"].rows[0]))
    elif mutation == "duplicate_link":
        repos["links"].rows.append(dict(repos["links"].rows[0]))
    elif mutation == "missing_receipt":
        repos["receipts"].rows.clear()
    elif mutation == "incomplete_read":
        repos["jobs"].fail = True
    evidence, complete = await read_action_delivery_evidence(tenant_id="t-1", dispatch=dispatch, **repos)
    if mutation in {"missing_receipt", "foreign_tenant", "receipt_job_mismatch"}:
        assert complete and evidence["connectorReportedDeliveries"] == []
        assert evidence["verifiedCallbacks"] == []
    elif mutation == "caller_asserted":
        assert complete and evidence["connectorReportedDeliveries"]
        assert evidence["verifiedCallbacks"] == []
    elif mutation == "wrong_receipt":
        assert complete and evidence["connectorReportedDeliveries"]
        assert evidence["verifiedCallbacks"] == []
    else:
        assert not complete and evidence["connectorReportedDeliveries"] == []


@pytest.mark.asyncio
async def test_tenant_owned_webhook_callback_is_labeled_weakly(chain):
    dispatch, repos = chain
    repos["jobs"].rows[0]["provider_adapter"] = "webhook"
    repos["receipts"].rows[0]["provider_adapter"] = "webhook"
    repos["links"].rows[0]["provider"] = "webhook"
    repos["outcomes"].rows[0]["provider"] = "webhook"
    repos["outcomes"].rows[0]["signature_authority"] = "tenant_owned_webhook_signature"
    evidence, complete = await read_action_delivery_evidence(tenant_id="t-1", dispatch=dispatch, **repos)
    assert complete
    assert evidence["verifiedCallbacks"][0]["signatureAuthority"] == "tenant_owned_webhook_signature"


@pytest.mark.asyncio
async def test_tenant_outcome_write_forces_caller_asserted_provenance(monkeypatch):
    from actions.delivery import routes

    class Tenant:
        tenant_id = "t-1"

        def require_permission(self, permission):
            assert permission == "write"

    class Request:
        state = type("State", (), {"tenant": Tenant()})()

        async def json(self):
            return {"provider": "jira", "external_id": "OPS-1", "intent_id": "action-d-1",
                    "receipt_id": "r-1", "producer_provenance": "verified_callback",
                    "signature_authority": "external_provider_signature"}

    class Outcomes:
        async def insert(self, key, value):
            return value

    monkeypatch.setattr(routes, "_outcome_repo", Outcomes())
    response = await routes.ingest_outcome(Request(), tenantId="t-1")
    assert response.status_code == 201
    assert b'"producer_provenance":"caller_asserted"' in response.body
    assert b'"signature_authority":null' in response.body
