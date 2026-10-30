from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from actions.agent.invocation_runtime import (  # noqa: E402
    InvocationReceiptRepository, invoke_observed_mcp_tool,
)
from actions.agent_access_intelligence.authority import CapabilityAuthorizationRepository  # noqa: E402
from actions.agent_access_intelligence.models import capability_id_for  # noqa: E402
from actions.agent_access_intelligence.repositories import CapabilityCatalogRepository  # noqa: E402
from actions.delegation.engine import DelegationEngine  # noqa: E402
from repositories.repos import DelegationRepository, reset_in_memory_stores  # noqa: E402
from intelligence.workflow.action_authorities import invocation_receipt  # noqa: E402
from shared.common.common import ConflictError, ForbiddenError  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    reset_in_memory_stores()


async def _fixture():
    tenant, agent, execution, tool, server = "tenant-a", "agent-a", "exec-a", "lookup", "srv.example"
    cap = capability_id_for(tenant, "provider", server, tool)
    catalog = CapabilityCatalogRepository()
    await catalog.insert(cap, {"capability_id": cap, "tenant_id": tenant, "provider": "provider",
        "server_name": server, "server_url": "https://tools.example/mcp", "tool_name": tool,
        "capability_kind": "mcp_tool"})
    grants = CapabilityAuthorizationRepository()
    grant = await grants.grant_capability(authorization_id="grant-a", tenant_id=tenant,
        granted_by_entity_id="owner", agent_id=agent, capability_id=cap,
        scope={"actions": ["invoke"], "resources": [f"capability:{cap}"]})
    engine = DelegationEngine(DelegationRepository())
    config = {"tools": [tool], "policy_version": 3}
    execution_record = {"tenant_id": tenant, "agent_id": agent, "execution_id": execution,
        "workflow_run_id": "run-a", "workflow_definition_link": {"workflow_id": "wf-a", "revision": 2},
        "started_at": "2026-10-30T12:00:00+00:00", "ended_at": "2026-10-30T12:01:00+00:00"}
    return tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, execution_record


class _Response:
    status_code = 200
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}
        self.content = b"{}"

    def json(self):
        return self.payload


class _Client:
    payload = None
    calls = 0
    def __init__(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return None
    async def post(self, url, *, json, headers):
        type(self).calls += 1
        assert url == "https://tools.example/mcp"
        if json["method"] == "initialize":
            return _Response({"jsonrpc": "2.0", "id": json["id"], "result": {"protocolVersion": "2025-03-26"}})
        if json["method"] == "notifications/initialized":
            return _Response({})
        assert json["method"] == "tools/call" and json["params"]["name"] == "lookup"
        return _Response(self.payload)


@pytest.mark.asyncio
async def test_real_provider_completion_receipt_joins_workflow_reader(monkeypatch):
    (tenant, agent, execution, tool, cap, catalog, grants, engine,
     config, _grant, run) = await _fixture()
    _Client.payload = {"jsonrpc": "2.0", "id": execution, "result": {"content": [{"text": "real"}]}}
    _Client.calls = 0
    monkeypatch.setattr("actions.agent.invocation_runtime.httpx.AsyncClient", _Client)
    async def safe_url(_url): return False, "safe"
    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe_url)
    row = await invoke_observed_mcp_tool(tenant_id=tenant, agent_id=agent, execution_id=execution,
        tool_name=tool, arguments={"query": "x"}, config=config, engine=engine,
        workflow_run_id="run-a", workflow_definition_link=run["workflow_definition_link"],
        grants=grants, catalog=catalog)
    assert row["result_status"] == "succeeded", row["provider_error"]
    run["ended_at"] = row["completed_at"]
    evidence = await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run)
    assert evidence["state"] == "provider_invocation_succeeded"
    assert evidence["receiptId"] == row["receipt_id"]
    assert evidence["capabilityId"] == cap and evidence["resourceOperation"] == "unknown"
    assert row["grant_id"] == "grant-a" and row["policy_decision"]["allowed"] is True
    with pytest.raises(ConflictError):
        await invoke_observed_mcp_tool(tenant_id=tenant, agent_id=agent, execution_id=execution,
            tool_name=tool, arguments={"query": "x"}, config=config, engine=engine,
            workflow_run_id="run-a", grants=grants, catalog=catalog)
    assert _Client.calls == 3  # initialize, initialized notification, one actual tool call


@pytest.mark.asyncio
async def test_provider_failure_is_receipted_and_does_not_claim_success(monkeypatch):
    fixture = await _fixture()
    tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, run = fixture
    _Client.payload = {"jsonrpc": "2.0", "id": execution, "error": {"code": -1, "message": "no"}}
    monkeypatch.setattr("actions.agent.invocation_runtime.httpx.AsyncClient", _Client)
    async def safe_url(_url): return False, "safe"
    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe_url)
    row = await invoke_observed_mcp_tool(tenant_id=tenant, agent_id=agent, execution_id=execution,
        tool_name=tool, arguments={}, config=config, engine=engine, workflow_run_id="run-a",
        grants=grants, catalog=catalog)
    run["ended_at"] = row["completed_at"]
    assert row["result_status"] == "failed" and row["provider_result"] is None
    assert (await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run))["state"] == "provider_invocation_failed"


@pytest.mark.asyncio
async def test_cross_tenant_or_missing_grant_cannot_invoke(monkeypatch):
    fixture = await _fixture()
    tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, run = fixture
    await grants.revoke("grant-a", "owner")
    called = False
    async def no_call(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr("actions.agent.invocation_runtime.httpx.AsyncClient", no_call)
    with pytest.raises(ForbiddenError):
        await invoke_observed_mcp_tool(tenant_id="tenant-other", agent_id=agent, execution_id=execution,
            tool_name=tool, arguments={}, config=config, engine=engine, grants=grants, catalog=catalog)
    with pytest.raises(ForbiddenError):
        await invoke_observed_mcp_tool(tenant_id=tenant, agent_id=agent, execution_id=execution,
            tool_name=tool, arguments={}, config=config, engine=engine, grants=grants, catalog=catalog)
    assert called is False
    assert await InvocationReceiptRepository().for_execution(tenant, agent, execution) == []


@pytest.mark.asyncio
async def test_reader_rejects_replayed_cross_subject_and_truncated_receipts(monkeypatch):
    fixture = await _fixture()
    tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, run = fixture
    repo = InvocationReceiptRepository()
    base = {"receipt_id": "receipt-1", "tenant_id": tenant, "agent_id": agent, "execution_id": execution,
        "workflow_run_id": "run-a", "tool_name": tool, "capability_id": cap, "action": "invoke",
        "policy_decision": {"allowed": True}, "grant_id": "grant-a", "result_status": "succeeded",
        "invoked_at": "2026-10-30T12:00:10Z", "completed_at": "2026-10-30T12:00:20Z", "evidence_version": 1}
    await repo.record_once(base)
    run["ended_at"] = "2026-10-30T12:00:30Z"
    assert await invocation_receipt(tenant_id=tenant, workflow_run_id="other-run", execution=run) is None
    assert await invocation_receipt(tenant_id="other-tenant", workflow_run_id="run-a", execution=run) is None
    with pytest.raises(ConflictError):
        await repo.record_once(base)
    run["workflow_run_id"] = "run-a"
    run["started_at"] = "2026-10-30T12:00:15Z"
    assert await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run) is None
    # More than the read bound suppresses the entire claim.
    for n in range(100):
        item = dict(base, receipt_id=f"r{n}")
        await repo.record_once(item)
    assert await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run) is None
