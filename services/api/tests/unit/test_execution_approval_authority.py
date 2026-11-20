"""Historical agent execution and x402 approval records stay exact and erasable.

Aether no longer admits agent executions or decides x402 approvals (ADR-012).
These tests pin what remains: execution rows written before that change keep
their single-use identity and workflow lineage, and commerce erasure still
removes a subject's historical approval decisions without cross-tenant leaks.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.common.common import ConflictError  # noqa: E402
from repositories.repos import AgentExecutionRepository  # noqa: E402
from value.x402.commerce_models import (  # noqa: E402
    ApprovalDecision,
    ApprovalRequest,
)
from value.x402.commerce_store import CommerceStore  # noqa: E402


TENANT = "tenant-execution-approval-test"
AGENT = "agent-execution-approval-test"


class _NoopProducer:
    async def publish(self, event) -> None:
        return None


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
