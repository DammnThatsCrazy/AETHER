"""Read scoped delegation evidence for exact workflow execution approvals.

This joins a server-recorded request-time decision to the current canonical
Delegation row. Mutable grant state cannot establish a historical policy replay
or prove that an external action occurred.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.temporal.instant import parse_instant_strict


@dataclass(frozen=True)
class ApprovalAgentAccessRead:
    rows: tuple[dict[str, Any], ...]
    available: bool
    complete: bool


async def read_approval_agent_access(*, tenant_id: str, workflow_run_id: str,
                                     executions: list[dict[str, Any]], approvals: list[dict[str, Any]],
                                     repository: Any = None) -> ApprovalAgentAccessRead:
    from actions.agent.action_associations import _recorded_delegation_decision
    from actions.delegation.engine import DelegationEngine
    from repositories.repos import DelegationRepository

    repo = repository or DelegationRepository()
    by_execution = {row.get("execution_id"): row for row in executions}
    result: list[dict[str, Any]] = []
    complete = True
    for approval in approvals:
        execution = by_execution.get(approval.get("execution_id"))
        if not isinstance(execution, dict) or approval.get("action") != "approve":
            complete = False
            continue
        snapshot, policy = execution.get("input_snapshot"), execution.get("policy_log")
        receipt = approval.get("permission_receipt")
        try:
            created = parse_instant_strict(execution.get("created_at"))
            approval_time = parse_instant_strict(approval.get("decided_at"))
            receipt_time = parse_instant_strict(receipt.get("checked_at")) if isinstance(receipt, dict) else None
        except (TypeError, ValueError):
            complete = False
            continue
        decision = _recorded_delegation_decision(execution, created, created)
        if (execution.get("tenant_id") != tenant_id or execution.get("workflow_run_id") != workflow_run_id
                or approval.get("tenant_id") != tenant_id or approval.get("workflow_run_id") != workflow_run_id
                or approval.get("approval_id") != execution.get("approval_id")
                or approval.get("decision_id") != execution.get("approval_decision_id")
                or not isinstance(snapshot, dict) or not isinstance(policy, dict) or not decision
                or decision.get("decision") != "allow"
                or approval.get("requester_type") != "agent"
                or not isinstance(approval.get("decided_by"), str) or not approval["decided_by"].strip()
                or not isinstance(receipt, dict) or not isinstance(receipt.get("receipt_id"), str)
                or not receipt["receipt_id"].strip()
                or receipt.get("tenant_id") != tenant_id
                or receipt.get("approval_id") != approval.get("approval_id")
                or receipt.get("execution_id") != execution.get("execution_id")
                or receipt.get("principal_id") != approval.get("decided_by")
                or receipt.get("permission") != "commerce:approve"
                or receipt_time is None or receipt_time > approval_time
                or approval.get("requester_id") != execution.get("agent_id")
                or approval.get("execution_action") != snapshot.get("action")
                or approval.get("resource_id") != snapshot.get("resource")
                or not isinstance(snapshot.get("action"), str) or not snapshot["action"]
                or not isinstance(snapshot.get("resource"), str) or not snapshot["resource"]):
            complete = False
            continue
        try:
            requested_amount = Decimal(str(snapshot.get("amount")))
            approved_amount = Decimal(str(approval.get("approved_amount_usd")))
            if (not requested_amount.is_finite() or not approved_amount.is_finite()
                    or requested_amount != approved_amount):
                raise ValueError("approval amount mismatch")
        except (InvalidOperation, ValueError):
            complete = False
            continue
        evaluated = parse_instant_strict(decision["evaluatedAt"])
        if approval_time > evaluated:
            complete = False
            continue
        try:
            grant = await repo.find_by_id(decision["delegationId"])
        except Exception:  # noqa: BLE001 - dependency failure keeps authorization unknown
            return ApprovalAgentAccessRead((), False, False)
        recorded = policy.get("delegation_check")
        scope = grant.get("scope") if isinstance(grant, dict) else None
        if (not isinstance(grant, dict) or grant.get("tenant_id") != tenant_id
                or grant.get("delegation_id") != decision["delegationId"]
                or grant.get("grantee_entity_id") != execution.get("agent_id")
                or not isinstance(grant.get("grantor_entity_id"), str) or not grant["grantor_entity_id"].strip()
                or not grant.get("created_at")
                or not isinstance(scope, dict) or not isinstance(recorded, dict)
                or recorded.get("matched_scope") != scope):
            complete = False
            continue
        actions, resources = scope.get("actions"), scope.get("resources")
        if (not isinstance(actions, list) or not isinstance(resources, list)
                or not all(isinstance(v, str) for v in actions + resources)
                or (snapshot["action"] not in actions and "*" not in actions)
                or (resources and not any(DelegationEngine._resource_matches(v, snapshot["resource"]) for v in resources))
                or not DelegationEngine._amount_within(scope.get("max_amount"), snapshot.get("amount"))):
            complete = False
            continue
        try:
            for field in ("starts_at", "created_at"):
                if grant.get(field) and parse_instant_strict(grant[field]) > evaluated:
                    raise ValueError("grant not valid yet")
            for field in ("ends_at", "revoked_at"):
                if grant.get(field) and parse_instant_strict(grant[field]) <= evaluated:
                    raise ValueError("grant no longer valid")
        except (TypeError, ValueError):
            complete = False
            continue
        result.append({"tenant_id": tenant_id, "workflow_run_id": workflow_run_id,
                       "execution_id": execution["execution_id"], "approval_id": approval["approval_id"],
                       "decision_id": approval["decision_id"], "delegation_id": decision["delegationId"],
                       "evaluated_at": decision["evaluatedAt"], "requested_action": snapshot["action"],
                       "requested_resource": snapshot["resource"]})
    return ApprovalAgentAccessRead(tuple(result), True, complete)
