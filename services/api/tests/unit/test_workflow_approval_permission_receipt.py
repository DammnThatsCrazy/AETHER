"""Execution approval permission checks retain exact decision evidence."""
import asyncio

import pytest

from graph.operational_intelligence.models import EvidenceRef
from intelligence.workflow.workflow360_provider import (
    WorkflowPrincipalIdentityRead,
    _approvals_section,
)
from shared.intelligence_projections.contracts import ProjectionSubject
from value.x402.commerce_models import ApprovalDecision
from value.x402.commerce_store import CommerceStore


class NoopProducer:
    async def publish(self, event):
        return None


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
        agent_access_rows=[],
    )
    check = section.content["approvals"][0]["approverPermissionCheck"]
    assert check["state"] == ("recorded" if changed is None else "unknown")
    assert section.content["workflowApprovalAuthorityState"] == "unknown"
    assert "principal-a" not in str(section.content)
