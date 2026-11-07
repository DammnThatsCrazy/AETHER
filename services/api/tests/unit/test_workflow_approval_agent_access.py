"""Exact tenant, approval, execution, and grant joins for Workflow360."""
from __future__ import annotations

import pytest
from intelligence.workflow.approval_agent_access import read_approval_agent_access


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "foreign_tenant", "wrong_agent", "wrong_approval", "wrong_resource", "wrong_amount", "wrong_receipt", "mismatched_scope", "revoked", "approval_after", "legacy"])
async def test_approval_access_requires_exact_request_and_grant(case):
    scope = {"actions": ["pay"], "resources": ["order:1"], "max_amount": "10"}
    execution = {"tenant_id": "tenant-a", "workflow_run_id": "run-1", "execution_id": "exec-1",
                 "agent_id": "agent-1", "delegation_id": "grant-1", "status": "running",
                 "approval_id": "approval-1", "approval_decision_id": "decision-1",
                 "created_at": "2026-10-18T10:00:03Z",
                 "input_snapshot": {"action": "pay", "resource": "order:1", "amount": "5"},
                 "policy_log": {"delegation_check_tenant_id": "tenant-a", "delegation_check": {
                     "allowed": True, "delegation_id": "grant-1", "matched_scope": scope,
                     "evaluated_at": "2026-10-18T10:00:02Z"}}}
    approval = {"tenant_id": "tenant-a", "workflow_run_id": "run-1", "execution_id": "exec-1",
                "approval_id": "approval-1", "decision_id": "decision-1", "action": "approve",
                "requester_id": "agent-1", "requester_type": "agent", "execution_action": "pay", "resource_id": "order:1", "approved_amount_usd": 5,
                "decided_at": "2026-10-18T10:00:01Z", "decided_by": "operator-1",
                "permission_receipt": {"receipt_id": "receipt-1", "tenant_id": "tenant-a",
                    "approval_id": "approval-1", "execution_id": "exec-1", "principal_id": "operator-1",
                    "permission": "commerce:approve", "checked_at": "2026-10-18T10:00:00Z"}}
    grant = {"tenant_id": "tenant-a", "delegation_id": "grant-1", "grantee_entity_id": "agent-1", "grantor_entity_id": "owner-1",
             "scope": dict(scope), "created_at": "2026-10-18T09:00:00Z"}
    if case == "foreign_tenant": grant["tenant_id"] = "tenant-b"
    if case == "wrong_agent": grant["grantee_entity_id"] = "agent-2"
    if case == "wrong_approval": execution["approval_id"] = "approval-other"
    if case == "wrong_resource": approval["resource_id"] = "order:2"
    if case == "wrong_amount": approval["approved_amount_usd"] = 6
    if case == "wrong_receipt": approval["permission_receipt"]["tenant_id"] = "tenant-b"
    if case == "mismatched_scope": grant["scope"] = {"actions": ["refund"], "resources": ["order:1"]}
    if case == "revoked": grant["revoked_at"] = "2026-10-18T10:00:01Z"
    if case == "approval_after": approval["decided_at"] = "2026-10-18T10:00:04Z"
    if case == "legacy": execution["policy_log"].pop("delegation_check_tenant_id")

    class Grants:
        async def find_by_id(self, grant_id):
            assert grant_id == "grant-1"
            return grant

    result = await read_approval_agent_access(tenant_id="tenant-a", workflow_run_id="run-1",
                                              executions=[execution], approvals=[approval], repository=Grants())
    assert result.available
    if case == "valid":
        assert result.complete and result.rows[0]["delegation_id"] == "grant-1"
    else:
        assert not result.complete and result.rows == ()
