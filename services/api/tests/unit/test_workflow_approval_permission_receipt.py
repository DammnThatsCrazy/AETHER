"""Execution approval permission checks retain exact decision evidence."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from graph.operational_intelligence.models import EvidenceRef
from intelligence.workflow.workflow360_provider import (
    WorkflowPrincipalIdentityRead,
    _approvals_section,
)
from shared.auth.auth import Role, TenantContext
from shared.intelligence_projections.contracts import ProjectionSubject
from value.x402 import approvals as approvals_module
from value.x402 import commerce_routes
from value.x402.approvals import ApprovalService
from value.x402.commerce_models import ApprovalDecision, ApprovalRequest
from value.x402.commerce_store import CommerceStore


class NoopProducer:
    async def publish(self, event):
        return None


@pytest.mark.asyncio
async def test_execution_approval_permission_receipt_is_recorded_at_route(monkeypatch):
    store = CommerceStore()
    monkeypatch.setattr(approvals_module, "get_commerce_store", lambda: store)
    service = ApprovalService(event_producer=NoopProducer())
    approval = ApprovalRequest(
        tenant_id="tenant-a", approval_id="approval-a", challenge_id="challenge-a",
        resource_id="resource-a", requester_id="agent-a", requester_type="agent",
        execution_id="execution-a", execution_action="pay", amount_usd=1,
        asset_symbol="USDC", chain="eip155:8453",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    await store.put_approval(approval)

    class Plane:
        async def apply_decision(self, **kwargs):
            return await service.decide(**kwargs)

    monkeypatch.setattr(commerce_routes, "get_approval_service", lambda: service)
    monkeypatch.setattr(commerce_routes, "get_control_plane", lambda: Plane())
    request = SimpleNamespace(state=SimpleNamespace(tenant=TenantContext(
        tenant_id="tenant-a", user_id="principal-a", role=Role.VIEWER,
        permissions=["commerce:approve"],
    )))
    await commerce_routes.decide_approval(
        "approval-a", commerce_routes.ApprovalDecisionBody(
            action="approve", decided_by="untrusted-claim", reason="approved"
        ), request
    )
    saved = await store.get_approval_decision("tenant-a", approval.last_decision_id)
    assert saved.decided_by == "principal-a"
    assert saved.permission_receipt is not None
    assert saved.permission_receipt.tenant_id == "tenant-a"
    assert saved.permission_receipt.approval_id == "approval-a"
    assert saved.permission_receipt.execution_id == "execution-a"
    assert saved.permission_receipt.principal_id == "principal-a"
    assert saved.permission_receipt.permission == "commerce:approve"


@pytest.mark.asyncio
async def test_route_rejects_unverifiable_permissions():
    request = SimpleNamespace(state=SimpleNamespace(tenant=SimpleNamespace(tenant_id="tenant-a")))
    with pytest.raises(HTTPException) as exc:
        commerce_routes._require_perm(request, "commerce:approve")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_approval_decision_id_is_immutable_under_conflict_and_replay():
    store = CommerceStore()
    original = ApprovalDecision(
        decision_id="decision-immutable", tenant_id="tenant-a", approval_id="approval-a",
        action="approve", decided_by="principal-a", reason="original",
    )
    conflict = original.model_copy(update={"reason": "changed"})
    results = await asyncio.gather(
        store.put_approval_decision(original), store.put_approval_decision(conflict),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ApprovalDecision) for item in results) == 1
    assert sum(isinstance(item, ValueError) for item in results) == 1
    stored = await store.get_approval_decision("tenant-a", "decision-immutable")
    replay = await store.put_approval_decision(stored)
    assert replay == stored
    stored.reason = "local mutation"
    assert (await store.get_approval_decision("tenant-a", "decision-immutable")).reason != "local mutation"


@pytest.mark.asyncio
async def test_postgres_decision_insert_uses_atomic_do_nothing():
    from repositories.commerce_repos import ApprovalDecisionsRepository

    class Pool:
        async def fetchrow(self, query, record_id, payload, tenant_id):
            assert "ON CONFLICT (id) DO NOTHING RETURNING id" in query
            assert (record_id, tenant_id) == ("tenant-a:decision-a", "tenant-a")
            assert '"decision_id": "decision-a"' in payload
            return None

    repo = ApprovalDecisionsRepository()
    repo._pool = Pool()
    repo._table_ensured = True
    assert not await repo.insert_immutable(
        "tenant-a:decision-a", {"tenant_id": "tenant-a", "decision_id": "decision-a"}
    )


@pytest.mark.parametrize("changed", [None, "tenant_id", "execution_id", "principal_id", "checked_at"])
def test_workflow_permission_receipt_requires_exact_decision_binding(changed):
    receipt = {
        "receipt_id": "receipt-a", "tenant_id": "tenant-a", "approval_id": "approval-a",
        "execution_id": "execution-a", "principal_id": "principal-a", "permission": "commerce:approve",
        "checked_at": "2026-10-18T10:00:00Z",
    }
    if changed:
        receipt[changed] = "2026-10-18T10:00:02Z" if changed == "checked_at" else "foreign"
    row = {
        "tenant_id": "tenant-a", "workflow_run_id": "run-a", "execution_id": "execution-a",
        "approval_id": "approval-a", "decision_id": "decision-a", "action": "approve",
        "decided_by": "principal-a", "decided_at": "2026-10-18T10:00:01Z",
        "permission_receipt": receipt,
    }
    section, _ = _approvals_section(
        ProjectionSubject(kind="workflow_run", id="run-a"), tenant_id="tenant-a",
        approval_rows=[row], execution_refs=[EvidenceRef(id="execution-a", type="event", source="agent_executions")],
        available=True, complete=True, reason=None,
        principal_identity_read=WorkflowPrincipalIdentityRead((), True, True),
    )
    check = section.content["approvals"][0]["approverPermissionCheck"]
    assert check["state"] == ("recorded" if changed is None else "unknown")
    assert section.content["workflowApprovalAuthorityState"] == "unknown"
    assert "principal-a" not in str(section.content)
