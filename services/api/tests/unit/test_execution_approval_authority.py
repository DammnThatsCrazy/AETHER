"""Exact execution linkage for the canonical x402 approval authority."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent import user_agents  # noqa: E402
from shared.common.common import ConflictError, ForbiddenError  # noqa: E402
from repositories.repos import AgentExecutionRepository  # noqa: E402
from value.x402 import commerce_store as commerce_store_module  # noqa: E402
from value.x402.approvals import ApprovalService  # noqa: E402
from value.x402.commerce_models import (  # noqa: E402
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
)
from value.x402.commerce_store import CommerceStore  # noqa: E402


TENANT = "tenant-execution-approval-test"
AGENT = "agent-execution-approval-test"


class _NoopProducer:
    async def publish(self, event) -> None:
        return None


async def test_execution_bound_decision_is_persisted_with_exact_execution_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CommerceStore()
    monkeypatch.setattr("value.x402.approvals.get_commerce_store", lambda: store)
    service = ApprovalService(event_producer=_NoopProducer())

    approval = await service.request(
        tenant_id=TENANT,
        challenge_id="challenge-approval-1",
        resource_id="resource-1",
        requester_id=AGENT,
        requester_type="agent",
        amount_usd=12.5,
        asset_symbol="USDC",
        chain="eip155:8453",
        execution_action="pay",
    )
    assert approval.execution_id
    assert approval.execution_action == "pay"

    decided = await service.decide(
        TENANT,
        approval.approval_id,
        "approve",
        "human-approver-1",
        "approved for exact run",
    )
    stored_decision = await store.get_approval_decision(TENANT, decided.last_decision_id or "")
    assert stored_decision is not None
    assert stored_decision.execution_id == approval.execution_id
    assert stored_decision.approval_id == approval.approval_id
    assert stored_decision.action == "approve"

    revoked = await service.revoke(TENANT, approval.approval_id, "human-approver-1", "revoked")
    decisions = await store.list_approval_decisions_for_executions(
        TENANT, [approval.execution_id]
    )
    assert revoked.status == ApprovalStatus.REVOKED
    assert [decision.action for decision in decisions] == ["approve", "revoke"]
    assert all(decision.execution_id == approval.execution_id for decision in decisions)


async def test_agent_execution_requires_exact_current_approved_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CommerceStore()
    monkeypatch.setattr(commerce_store_module, "get_commerce_store", lambda: store)
    approval = ApprovalRequest(
        tenant_id=TENANT,
        challenge_id="challenge-approval-2",
        resource_id="resource-2",
        requester_id=AGENT,
        requester_type="agent",
        execution_id="exact-run-2",
        execution_action="pay",
        amount_usd=3.25,
        asset_symbol="USDC",
        chain="eip155:8453",
        status=ApprovalStatus.APPROVED,
        last_decision_id="decision-2",
    )
    decision = ApprovalDecision(
        decision_id="decision-2",
        approval_id=approval.approval_id,
        tenant_id=TENANT,
        execution_id="exact-run-2",
        action="approve",
        decided_by="human-approver-2",
        reason="approved",
    )
    await store.put_approval(approval)
    await store.put_approval_decision(decision)

    body = user_agents.AgentExecute(
        action="pay",
        resource="resource-2",
        amount="3.250",
        approval_id=approval.approval_id,
    )
    assert await user_agents._validate_execution_approval(
        tenant_id=TENANT,
        agent_id=AGENT,
        body=body,
    ) == ("exact-run-2", "decision-2")

    mismatched = body.model_copy(update={"resource": "resource-other"})
    with pytest.raises(ForbiddenError):
        await user_agents._validate_execution_approval(
            tenant_id=TENANT,
            agent_id=AGENT,
            body=mismatched,
        )
    with pytest.raises(ForbiddenError):
        await user_agents._validate_execution_approval(
            tenant_id="another-tenant",
            agent_id=AGENT,
            body=body,
        )

    approval.status = ApprovalStatus.REVOKED
    await store.put_approval(approval)
    with pytest.raises(ForbiddenError):
        await user_agents._validate_execution_approval(
            tenant_id=TENANT,
            agent_id=AGENT,
            body=body,
        )


async def test_approved_execution_id_is_claimed_once_under_concurrent_replay() -> None:
    repository = AgentExecutionRepository()
    execution_id = f"single-use-{uuid.uuid4()}"

    async def write_claim() -> dict:
        return await repository.record(
            execution_id=execution_id,
            agent_id=AGENT,
            tenant_id=TENANT,
            delegation_id="delegation-1",
            triggered_by_event_id=None,
            status="running",
            approval_id="approval-single-use",
            approval_decision_id="decision-single-use",
            create_only=True,
        )

    results = await asyncio.gather(write_claim(), write_claim(), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1


async def test_agent_execution_persists_exact_workflow_invocation_lineage() -> None:
    repository = AgentExecutionRepository()
    execution_id = f"workflow-linked-{uuid.uuid4()}"
    row = await repository.record(
        execution_id=execution_id,
        agent_id=AGENT,
        tenant_id=TENANT,
        delegation_id=None,
        triggered_by_event_id=None,
        status="running",
        workflow_run_id="workflow-run-authority",
        workflow_run_invocation_ids=["invocation-authority-a", "invocation-authority-b"],
    )

    assert row["workflow_run_id"] == "workflow-run-authority"
    assert row["workflow_run_invocation_ids"] == [
        "invocation-authority-a",
        "invocation-authority-b",
    ]


async def test_commerce_erasure_removes_subject_approval_decisions_without_cross_tenant_leak() -> None:
    store = CommerceStore()
    subject_approval = ApprovalRequest(
        tenant_id=TENANT,
        challenge_id="challenge-subject-erasure",
        resource_id="resource-1",
        requester_id="user-subject",
        requester_type="user",
        amount_usd=1,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    unrelated_approval = ApprovalRequest(
        tenant_id=TENANT,
        challenge_id="challenge-unrelated-erasure",
        resource_id="resource-2",
        requester_id="user-unrelated",
        requester_type="user",
        amount_usd=2,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    foreign_approval = ApprovalRequest(
        tenant_id="tenant-other-approval-erasure",
        challenge_id="challenge-foreign-erasure",
        resource_id="resource-3",
        requester_id="user-subject",
        requester_type="user",
        amount_usd=3,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    for approval in (subject_approval, unrelated_approval, foreign_approval):
        await store.put_approval(approval)

    linked_decision = ApprovalDecision(
        approval_id=subject_approval.approval_id,
        tenant_id=TENANT,
        action="approve",
        decided_by="user-operator",
        reason="subject approval record",
    )
    actor_decision = ApprovalDecision(
        approval_id=unrelated_approval.approval_id,
        tenant_id=TENANT,
        action="approve",
        decided_by="user-subject",
        reason="subject was the approver",
    )
    foreign_decision = ApprovalDecision(
        approval_id=foreign_approval.approval_id,
        tenant_id=foreign_approval.tenant_id,
        action="approve",
        decided_by="user-operator",
        reason="another tenant",
    )
    for decision in (linked_decision, actor_decision, foreign_decision):
        await store.put_approval_decision(decision)

    counts = await store.erase_subject_refs(TENANT, {"user-subject"})

    assert counts["approvals"] == 1
    assert counts["approval_decisions"] == 2
    assert await store.get_approval_decision(TENANT, linked_decision.decision_id) is None
    assert await store.get_approval_decision(TENANT, actor_decision.decision_id) is None
    assert await store.get_approval_decision(
        foreign_approval.tenant_id, foreign_decision.decision_id
    ) is not None
