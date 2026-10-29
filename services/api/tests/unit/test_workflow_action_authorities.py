"""Exact workflow result and protected-resource source joins."""
from __future__ import annotations

import uuid
import pytest
from intelligence.workflow.action_authorities import approved_resources, execution_result


@pytest.mark.parametrize("case", ["valid", "foreign", "unpublished", "wrong_id", "wrong_time", "no_timestamp"])
def test_executor_result_is_not_tool_completion(case):
    tenant, execution_id = "tenant-a", "exec-1"
    event = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:agent-execution:{tenant}:{execution_id}:completed"))
    row = {"tenant_id": tenant, "workflow_run_id": "run-1", "execution_id": execution_id,
           "id": execution_id,
           "status": "completed", "created_at": "2026-10-18T10:00:00Z", "ended_at": "2026-10-18T10:00:03Z",
           "outcome_event_id": event, "outcome_event_published": True}
    called = "2026-10-18T10:00:01Z"
    if case == "foreign": row["tenant_id"] = "foreign"
    if case == "unpublished": row["outcome_event_published"] = False
    if case == "wrong_id": row["outcome_event_id"] = "foreign-event"
    if case == "wrong_time": called = "2026-10-18T10:00:04Z"
    if case == "no_timestamp": row["ended_at"] = None
    result = execution_result(tenant_id=tenant, workflow_run_id="run-1", execution=row, called_at=called)
    if case == "valid":
        assert result["state"] == "recorded_executor_completion"
        assert result["toolResult"] == "unknown" and result["externalEffect"] == "unknown"
    else:
        assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "foreign", "wrong_id", "inactive", "registered_after", "missing"])
async def test_approved_resource_requires_current_exact_tenant_record(case):
    row = {"tenant_id": "tenant-a", "workflow_run_id": "run-1", "execution_id": "exec-1",
           "id": "exec-1",
           "requested_resource": "resource-1", "approval_id": "approval-1", "decision_id": "decision-1",
           "delegation_id": "grant-1", "evaluated_at": "2026-10-18T10:00:02Z"}
    resource = {"tenant_id": "tenant-a", "resource_id": "resource-1", "active": True,
                "registered_at": "2026-10-18T09:00:00Z"}
    if case == "foreign": resource["tenant_id"] = "tenant-b"
    if case == "wrong_id": resource["resource_id"] = "resource-other"
    if case == "inactive": resource["active"] = False
    if case == "registered_after": resource["registered_at"] = "2026-10-18T10:00:03Z"
    class Store:
        async def get_resource(self, tenant_id, resource_id):
            assert (tenant_id, resource_id) == ("tenant-a", "resource-1")
            return None if case == "missing" else resource
    rows = await approved_resources(tenant_id="tenant-a", workflow_run_id="run-1", access_rows=[row], store=Store())
    assert len(rows) == (1 if case == "valid" else 0)


@pytest.mark.asyncio
async def test_executor_callback_record_flows_to_workflow_result(monkeypatch):
    from types import SimpleNamespace
    from actions.agent import user_agents, runtime_repository

    row = {"tenant_id": "tenant-a", "workflow_run_id": "run-1", "execution_id": "exec-1",
           "id": "exec-1", "agent_id": "agent-1", "status": "running", "created_at": "2026-10-18T10:00:00Z",
           "input_snapshot": {"action": "pay", "resource": "resource-1"}}
    class Executions:
        async def find_by_id(self, key): return dict(row)
        async def update(self, key, fields):
            row.update(fields)
            return dict(row)
    class Configs:
        async def find_by_id(self, key): return {}
    class Producer:
        events = []
        async def publish(self, event): self.events.append(event)
    producer = Producer()
    monkeypatch.setattr(user_agents, "_executions", Executions())
    monkeypatch.setattr(user_agents, "_configs", Configs())
    monkeypatch.setattr(runtime_repository, "utc_now", lambda: "2026-10-18T10:00:03Z")
    tenant = SimpleNamespace(tenant_id="tenant-a", require_permission=lambda permission: None)
    await user_agents.update_execution_status("agent-1", "exec-1", user_agents.AgentExecutionOutcome(status="completed"),
                                              SimpleNamespace(state=SimpleNamespace(tenant=tenant)), producer=producer)
    assert len(producer.events) == 1
    result = execution_result(tenant_id="tenant-a", workflow_run_id="run-1", execution=row,
                              called_at="2026-10-18T10:00:01Z")
    assert result["state"] == "recorded_executor_completion"
    assert result["recordedEventId"] == row["outcome_event_id"]
