from __future__ import annotations

import sys
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from actions.agent.invocation_runtime import (  # noqa: E402
    InvocationReceiptRepository,
    invoke_observed_mcp_tool,
    validated_agent_receipt,
)
from actions.agent_access_intelligence.authority import CapabilityAuthorizationRepository  # noqa: E402
from actions.agent_access_intelligence.models import capability_id_for  # noqa: E402
from actions.agent_access_intelligence.models import resource_id_for  # noqa: E402
from actions.agent_access_intelligence.repositories import CapabilityCatalogRepository  # noqa: E402
from actions.delegation.engine import DelegationEngine  # noqa: E402
from repositories.repos import DelegationRepository, reset_in_memory_stores  # noqa: E402
from intelligence.workflow.action_authorities import invocation_receipt  # noqa: E402
from shared.common.common import ConflictError, ForbiddenError  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    reset_in_memory_stores()


async def _fixture():
    tenant, agent, execution, tool, server = (
        "tenant-a",
        "agent-a",
        "exec-a",
        "lookup",
        "srv.example",
    )
    cap = capability_id_for(tenant, "provider", server, tool)
    catalog = CapabilityCatalogRepository()
    await catalog.insert(
        cap,
        {
            "capability_id": cap,
            "tenant_id": tenant,
            "provider": "provider",
            "server_name": server,
            "server_url": "https://tools.example/mcp",
            "tool_name": tool,
            "capability_kind": "mcp_tool",
        },
    )
    grants = CapabilityAuthorizationRepository()
    grant = await grants.grant_capability(
        authorization_id="grant-a",
        tenant_id=tenant,
        granted_by_entity_id="owner",
        agent_id=agent,
        capability_id=cap,
        scope={"actions": ["invoke"], "resources": [f"capability:{cap}"]},
    )
    engine = DelegationEngine(DelegationRepository())
    config = {"tools": [tool], "policy_version": 3}
    execution_record = {
        "tenant_id": tenant,
        "agent_id": agent,
        "execution_id": execution,
        "workflow_run_id": "run-a",
        "workflow_definition_link": {"workflow_id": "wf-a", "revision": 2},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
    }
    return (
        tenant,
        agent,
        execution,
        tool,
        cap,
        catalog,
        grants,
        engine,
        config,
        grant,
        execution_record,
    )


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

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    @classmethod
    async def post(cls, method, url, *, json, headers, max_redirects):
        assert method == "POST" and max_redirects == 0
        cls.calls += 1
        assert url == "https://tools.example/mcp"
        if json["method"] == "initialize":
            return _Response(
                {"jsonrpc": "2.0", "id": json["id"], "result": {"protocolVersion": "2025-03-26"}}
            )
        if json["method"] == "notifications/initialized":
            return _Response({})
        assert json["method"] == "tools/call" and json["params"]["name"] == "lookup"
        return _Response(cls.payload)


@pytest.mark.asyncio
async def test_real_provider_completion_receipt_joins_workflow_reader(monkeypatch):
    (
        tenant,
        agent,
        execution,
        tool,
        cap,
        catalog,
        grants,
        engine,
        config,
        _grant,
        run,
    ) = await _fixture()
    _Client.payload = {"jsonrpc": "2.0", "id": execution, "result": {"content": [{"text": "real"}]}}
    _Client.calls = 0
    monkeypatch.setattr("actions.agent.invocation_runtime.send_public_request", _Client.post)

    async def safe_url(_url):
        return False, "safe"

    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe_url)
    row = await invoke_observed_mcp_tool(
        tenant_id=tenant,
        agent_id=agent,
        execution_id=execution,
        initiating_principal_user_id="owner",
        tool_name=tool,
        arguments={"query": "x"},
        config=config,
        engine=engine,
        workflow_run_id="run-a",
        workflow_definition_link=run["workflow_definition_link"],
        grants=grants,
        catalog=catalog,
    )
    assert row["result_status"] == "succeeded", row["provider_error"]
    run["ended_at"] = row["completed_at"]
    evidence = await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run)
    assert evidence["state"] == "provider_invocation_succeeded"
    assert evidence["receiptId"] == row["receipt_id"]
    assert evidence["capabilityId"] == cap and evidence["resourceOperation"] == "unknown"
    assert row["grant_id"] == "grant-a" and row["policy_decision"]["allowed"] is True
    with pytest.raises(ConflictError):
        await invoke_observed_mcp_tool(
            tenant_id=tenant,
            agent_id=agent,
            execution_id=execution,
            initiating_principal_user_id="owner",
            tool_name=tool,
            arguments={"query": "x"},
            config=config,
            engine=engine,
            workflow_run_id="run-a",
            grants=grants,
            catalog=catalog,
        )
    assert _Client.calls == 3  # initialize, initialized notification, one actual tool call


@pytest.mark.asyncio
async def test_provider_failure_is_receipted_and_does_not_claim_success(monkeypatch):
    fixture = await _fixture()
    tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, run = fixture
    _Client.payload = {"jsonrpc": "2.0", "id": execution, "error": {"code": -1, "message": "no"}}
    monkeypatch.setattr("actions.agent.invocation_runtime.send_public_request", _Client.post)

    async def safe_url(_url):
        return False, "safe"

    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe_url)
    row = await invoke_observed_mcp_tool(
        tenant_id=tenant,
        agent_id=agent,
        execution_id=execution,
        initiating_principal_user_id="owner",
        tool_name=tool,
        arguments={},
        config=config,
        engine=engine,
        workflow_run_id="run-a",
        workflow_definition_link=run["workflow_definition_link"],
        grants=grants,
        catalog=catalog,
    )
    run["ended_at"] = row["completed_at"]
    assert row["result_status"] == "failed" and row["provider_result"] is None
    assert (await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run))[
        "state"
    ] == "provider_invocation_failed"


@pytest.mark.asyncio
async def test_cross_tenant_or_missing_grant_cannot_invoke(monkeypatch):
    fixture = await _fixture()
    tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, run = fixture
    await grants.revoke("grant-a", "owner")
    called = False

    async def no_call(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("actions.agent.invocation_runtime.send_public_request", no_call)
    with pytest.raises(ForbiddenError):
        await invoke_observed_mcp_tool(
            tenant_id="tenant-other",
            agent_id=agent,
            execution_id=execution,
            initiating_principal_user_id="owner",
            tool_name=tool,
            arguments={},
            config=config,
            engine=engine,
            grants=grants,
            catalog=catalog,
        )
    with pytest.raises(ForbiddenError):
        await invoke_observed_mcp_tool(
            tenant_id=tenant,
            agent_id=agent,
            execution_id=execution,
            initiating_principal_user_id="owner",
            tool_name=tool,
            arguments={},
            config=config,
            engine=engine,
            grants=grants,
            catalog=catalog,
        )
    assert called is False
    assert await InvocationReceiptRepository().for_execution(tenant, agent, execution) == []


@pytest.mark.asyncio
async def test_reader_rejects_replayed_cross_subject_and_truncated_receipts(monkeypatch):
    fixture = await _fixture()
    tenant, agent, execution, tool, cap, catalog, grants, engine, config, grant, run = fixture
    repo = InvocationReceiptRepository()
    base = {
        "receipt_id": "receipt-1",
        "tenant_id": tenant,
        "agent_id": agent,
        "execution_id": execution,
        "workflow_run_id": "run-a",
        "tool_name": tool,
        "capability_id": cap,
        "action": "invoke",
        "policy_decision": {"allowed": True},
        "grant_id": "grant-a",
        "result_status": "succeeded",
        "invoked_at": "2026-10-30T12:00:10Z",
        "completed_at": "2026-10-30T12:00:20Z",
        "evidence_version": 1,
    }
    await repo.record_once(base)
    run["ended_at"] = "2026-10-30T12:00:30Z"
    assert (
        await invocation_receipt(tenant_id=tenant, workflow_run_id="other-run", execution=run)
        is None
    )
    assert (
        await invocation_receipt(tenant_id="other-tenant", workflow_run_id="run-a", execution=run)
        is None
    )
    with pytest.raises(ConflictError):
        await repo.record_once(base)
    run["workflow_run_id"] = "run-a"
    run["started_at"] = "2026-10-30T12:00:15Z"
    assert (
        await invocation_receipt(tenant_id=tenant, workflow_run_id="run-a", execution=run) is None
    )
    for receipt_index in range(100):
        await repo.record_once(dict(base, receipt_id=f"extra-receipt-{receipt_index}"))
    assert await repo.for_execution(tenant, agent, execution) == []


async def _completed_invocation(monkeypatch):
    (
        tenant,
        agent,
        execution,
        tool,
        cap,
        catalog,
        grants,
        engine,
        config,
        grant,
        run,
    ) = await _fixture()
    _Client.payload = {"jsonrpc": "2.0", "id": execution, "result": {"content": [{"text": "real"}]}}
    monkeypatch.setattr("actions.agent.invocation_runtime.send_public_request", _Client.post)

    async def safe_url(_url):
        return False, "safe"

    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe_url)
    row = await invoke_observed_mcp_tool(
        tenant_id=tenant,
        agent_id=agent,
        execution_id=execution,
        tool_name=tool,
        arguments={},
        config=config,
        engine=engine,
        grants=grants,
        catalog=catalog,
        initiating_principal_user_id="owner",
        workflow_run_id="run-a",
        workflow_definition_link=run["workflow_definition_link"],
    )
    run["ended_at"] = row["completed_at"]
    assert await validated_agent_receipt(tenant_id=tenant, agent_id=agent, execution=run)
    return row, run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "other-tenant"),
        ("agent_id", "other-agent"),
        ("execution_id", "other-execution"),
        ("workflow_run_id", "other-run"),
        ("workflow_definition_link", {"workflow_id": "other", "revision": 2}),
        ("id", "other-receipt"),
        ("tool_call_attempted", False),
        ("initiating_principal_user_id", " owner "),
        ("provider_url", "http://tools.example/mcp"),
        ("capability_id", "other-capability"),
        ("policy_resource", "arbitrary-resource"),
        ("completed_at", "2999-01-01T00:00:00Z"),
        ("grant_starts_at", "2999-01-01T00:00:00Z"),
        ("grant_ends_at", "2000-01-01T00:00:00Z"),
        ("policy_decision", {"allowed": True, "evaluated_at": "bad"}),
        ("grant_scope", {"actions": ["invoke"], "resources": [["malformed"]]}),
    ],
)
async def test_reader_rejects_mutated_otherwise_valid_receipt(monkeypatch, field, value):
    row, run = await _completed_invocation(monkeypatch)
    mutated = deepcopy(row)
    mutated[field] = value

    async def receipts(*args):
        return [mutated]

    monkeypatch.setattr(InvocationReceiptRepository, "for_execution", receipts)
    assert (
        await invocation_receipt(tenant_id="tenant-a", workflow_run_id="run-a", execution=run)
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [False, True])
async def test_handshake_failure_or_revocation_never_becomes_invocation_evidence(
    monkeypatch, revoke
):
    (
        tenant,
        agent,
        execution,
        tool,
        cap,
        catalog,
        grants,
        engine,
        config,
        grant,
        run,
    ) = await _fixture()
    methods = []

    async def transport(method, url, **kwargs):
        methods.append(kwargs["json"]["method"])
        if not revoke:
            raise RuntimeError("initialization failed")
        if kwargs["json"]["method"] == "initialize":
            await grants.revoke("grant-a", "owner")
        return await _Client.post(method, url, **kwargs)

    monkeypatch.setattr("actions.agent.invocation_runtime.send_public_request", transport)

    async def safe_url(_url):
        return False, "safe"

    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe_url)
    row = await invoke_observed_mcp_tool(
        tenant_id=tenant,
        agent_id=agent,
        execution_id=execution,
        tool_name=tool,
        arguments={},
        config=config,
        engine=engine,
        grants=grants,
        catalog=catalog,
        initiating_principal_user_id="owner",
        workflow_run_id="run-a",
        workflow_definition_link=run["workflow_definition_link"],
    )
    run["ended_at"] = row["completed_at"]
    assert row["tool_call_attempted"] is False
    assert "tools/call" not in methods
    assert await validated_agent_receipt(tenant_id=tenant, agent_id=agent, execution=run) is None


@pytest.mark.asyncio
async def test_workflow_reads_receipt_once_and_requires_exact_run(monkeypatch):
    row, run = await _completed_invocation(monkeypatch)
    calls = []

    async def receipts(*args):
        calls.append(args)
        return [row]

    monkeypatch.setattr(InvocationReceiptRepository, "for_execution", receipts)
    assert await invocation_receipt(tenant_id="tenant-a", workflow_run_id="run-a", execution=run)
    assert len(calls) == 1
    assert (
        await invocation_receipt(tenant_id="tenant-a", workflow_run_id="other-run", execution=run)
        is None
    )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_provider_receipt_reaches_agent_capabilities(monkeypatch):
    from tests.unit.test_agent360_provider import FakeSource, _request, _context, _sections
    from actions.agent.agent360_provider import Agent360Provider

    row, run = await _completed_invocation(monkeypatch)

    class ReceiptSource(FakeSource):
        async def executions(self, tenant_id, agent_id, limit):
            return [run]

    result = await Agent360Provider(ReceiptSource()).project(_request(), _context())
    dimensions = _sections(result)["state"].content["dimensions"]
    profile = next(item for item in dimensions if item["id"] == "authority_and_delegation")[
        "content"
    ]["capabilityAccessProfile"]
    assert profile["providerInvocationReceipts"][0]["receiptId"] == row["receipt_id"]
    assert profile["providerInvocationReceipts"][0]["resourceOperation"] == "unknown"
    assert any(
        claim.kind == "agent_provider_tool_invocation_result"
        and "capabilities" in claim.domainSlotIds
        for claim in result.claims
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_workflow_receipt_without_graph_edge_requires_authorization(monkeypatch, authorized):
    from intelligence.workflow.action_authorities import ApprovedResourceRead
    from intelligence.workflow.workflow360_provider import (
        _workflow_actions_section,
        WorkflowActionRead,
    )
    from shared.intelligence_projections.contracts import ProjectionSubject
    from shared.intelligence_projections.contracts import EvidenceRef

    row, run = await _completed_invocation(monkeypatch)
    section, claims = await _workflow_actions_section(
        ProjectionSubject(kind="workflow_run", id="run-a"),
        tenant_id="tenant-a",
        read=WorkflowActionRead((), True, True),
        execution_rows=[run],
        execution_refs=[EvidenceRef(id="exec-a", type="event", source="agent_executions")],
        execution_inventory_complete=True,
        time_range=None,
        requested=True,
        historical=False,
        execution_results_authorized=authorized,
        resource_read=ApprovedResourceRead((), True, True),
    )
    assert bool(section.content["providerInvocationReceipts"]) is authorized
    assert (
        any(claim.kind == "workflow_linked_provider_tool_result" for claim in claims) is authorized
    )
    if authorized:
        assert section.state == "available"
        assert "actions" in section.canonicalAuthorityRefs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("permissions", "principal"),
    [
        (["write"], "owner"),
        (["dispatch"], "owner"),
        (["write", "dispatch"], None),
    ],
)
async def test_invocation_ingress_requires_dispatch_write_and_principal(permissions, principal):
    from actions.agent.user_agents import invoke_agent_tool, AgentToolInvocation
    from shared.auth.auth import TenantContext

    request = SimpleNamespace(
        state=SimpleNamespace(
            tenant=TenantContext(
                tenant_id="tenant-a",
                user_id=principal,
                permissions=permissions,
            )
        )
    )
    with pytest.raises(ForbiddenError):
        await invoke_agent_tool(
            "agent-a", "exec-a", "lookup", AgentToolInvocation(arguments={}), request, engine=None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("response_shape", ["valid", "foreign_uri", "empty_contents"])
async def test_resource_read_requires_distinct_grant_and_creates_reader_bound_receipt(monkeypatch, response_shape):
    from actions.agent.invocation_runtime import read_observed_mcp_resource
    from actions.agent_access_intelligence.authority import RESOURCE_READ_ACTION, MCP_RESOURCE_PREFIX
    from actions.agent_access_intelligence.models import CapabilityKind

    tenant, agent, execution = "tenant-a", "agent-a", "exec-resource"
    uri, server, provider, url = "https://data.example/items/42", "srv.example", "provider", "https://tools.example/mcp"
    rid = resource_id_for(tenant, provider, server, uri)
    catalog = CapabilityCatalogRepository()
    await catalog.insert(rid, {"capability_id": rid, "tenant_id": tenant, "provider": provider,
        "server_name": server, "server_url": url, "capability_kind": CapabilityKind.RESOURCE.value,
        "resource_uri": uri})
    grants = CapabilityAuthorizationRepository()
    await grants.grant_capability(authorization_id="invoke-only", tenant_id=tenant,
        granted_by_entity_id="owner", agent_id=agent, capability_id="cap_fake",
        scope={"actions": ["invoke"], "resources": ["capability:cap_fake"]})
    engine = DelegationEngine(DelegationRepository())
    with pytest.raises(ForbiddenError, match="resource-read grant"):
        await read_observed_mcp_resource(tenant_id=tenant, agent_id=agent, execution_id=execution,
            resource_uri=uri, config={"resource_uris": [uri]}, engine=engine,
            initiating_principal_user_id="owner", grants=grants, catalog=catalog)
    other_id = resource_id_for(tenant, provider, server, "https://data.example/items/other")
    await grants.grant_capability(authorization_id="wrong-resource", tenant_id=tenant,
        granted_by_entity_id="owner", agent_id=agent, capability_id=other_id,
        scope={"actions": [RESOURCE_READ_ACTION], "resources": [f"{MCP_RESOURCE_PREFIX}{other_id}"]})
    with pytest.raises(ForbiddenError, match="resource-read grant"):
        await read_observed_mcp_resource(tenant_id=tenant, agent_id=agent, execution_id=execution,
            resource_uri=uri, config={"resource_uris": [uri]}, engine=engine,
            initiating_principal_user_id="owner", grants=grants, catalog=catalog)

    grant = await grants.grant_capability(authorization_id="read-only", tenant_id=tenant,
        granted_by_entity_id="owner", agent_id=agent, capability_id=rid,
        scope={"actions": [RESOURCE_READ_ACTION], "resources": [f"{MCP_RESOURCE_PREFIX}{rid}"]})
    # Keep the grant's scope exact and make the runtime DNS safety policy deterministic.
    async def safe(_url): return False, "public"
    monkeypatch.setattr("governance.security.policy_engine.evaluate_destination_safety", safe)
    calls = []
    class Response:
        status_code = 200
        content = b"{}"
        headers = {}
        def __init__(self, body): self.body = body
        def json(self): return self.body
    async def request(method, request_url, *, json, headers, max_redirects):
        calls.append(json)
        assert method == "POST" and request_url == url and max_redirects == 0
        if json["method"] == "initialize":
            return Response({"jsonrpc":"2.0", "id":json["id"], "result":{"protocolVersion":"2025-03-26"}})
        if json["method"] == "notifications/initialized": return Response({})
        if json["method"] == "resources/list":
            return Response({"jsonrpc":"2.0", "id":json["id"], "result":{"resources":[{"uri":uri,"name":"item"}]}})
        assert json["method"] == "resources/read" and json["params"] == {"uri":uri}
        contents = [{"uri": uri if response_shape == "valid" else "other-resource", "text": "value"}]
        if response_shape == "empty_contents":
            contents = []
        return Response({"jsonrpc":"2.0", "id":execution, "result":{"contents": contents}})
    monkeypatch.setattr("actions.agent.invocation_runtime.send_public_request", request)
    execution_record = {"tenant_id":tenant, "agent_id":agent, "execution_id":execution,
        "workflow_run_id":"run-resource", "started_at":(datetime.now(timezone.utc) - __import__("datetime").timedelta(seconds=2)).isoformat(),
        "ended_at":(datetime.now(timezone.utc)).isoformat()}
    receipt = await read_observed_mcp_resource(tenant_id=tenant, agent_id=agent, execution_id=execution,
        resource_uri=uri, config={"resource_uris":[uri]}, engine=engine, initiating_principal_user_id="owner",
        workflow_run_id="run-resource", grants=grants, catalog=catalog)
    assert receipt["action"] == RESOURCE_READ_ACTION and receipt["resource_operation"] == "read"
    validated = await validated_agent_receipt(tenant_id=tenant, agent_id=agent,
        execution={**execution_record, "ended_at":(datetime.now(timezone.utc) + __import__("datetime").timedelta(seconds=1)).isoformat()},
        expected_workflow_run_id="run-resource")
    assert validated["resourceOperation"] == "read"
    assert len(calls) == 4
    if response_shape == "valid":
        assert validated["state"] == "provider_resource_read_succeeded"
        assert validated["providerResultDigest"]
    else:
        assert validated["state"] == "provider_resource_read_failed"
        assert validated["providerResult"] is None
    assert grant["scope"]["actions"] == [RESOURCE_READ_ACTION]

    async def not_attempted(*_args):
        return [{**receipt, "resource_read_attempted": False}]

    monkeypatch.setattr(InvocationReceiptRepository, "for_execution", not_attempted)
    assert await validated_agent_receipt(tenant_id=tenant, agent_id=agent,
        execution={**execution_record, "ended_at": datetime.now(timezone.utc).isoformat()}) is None

    async def ambiguous(*_args):
        return [receipt, {**receipt, "action": "invoke"}]

    monkeypatch.setattr(InvocationReceiptRepository, "for_execution", ambiguous)
    assert await validated_agent_receipt(tenant_id=tenant, agent_id=agent,
        execution={**execution_record, "ended_at": datetime.now(timezone.utc).isoformat()}) is None


@pytest.mark.asyncio
async def test_resource_allowlist_is_persisted_and_updates_policy_version(monkeypatch):
    from actions.agent import user_agents
    from repositories.repos import AgentConfigRepository

    body = user_agents.AgentRegister(
        agent_id="agent-a", owner_entity_id="owner", model="model-a",
        resource_uris=["resource://exact-item"],
    )
    repository = AgentConfigRepository()
    await repository.register(**body.model_dump(), tenant_id="tenant-a")
    assert (await repository.find_by_id("agent-a"))["resource_uris"] == body.resource_uris
    monkeypatch.setattr(user_agents, "_configs", repository)
    tenant = SimpleNamespace(tenant_id="tenant-a", require_permission=lambda _permission: None)
    await user_agents.update("agent-a", user_agents.AgentUpdate(resource_uris=[]),
        SimpleNamespace(state=SimpleNamespace(tenant=tenant)))
    saved = await repository.find_by_id("agent-a")
    assert saved["resource_uris"] == []
    assert saved["policy_version"] == 2


@pytest.mark.asyncio
async def test_catalog_materializes_exact_observed_mcp_resource_uri():
    from actions.agent_access_intelligence.catalog_service import CapabilityCatalogService

    uri, server, tenant = "https://data.example/items/9", "catalog-server", "tenant-a"
    service = CapabilityCatalogService()
    result = await service.record_from_fact({"tenant_id": tenant, "source_event_id": "resource-observation-1",
        "event_name": "agent_mcp_resource_observed", "occurred_at": datetime.now(timezone.utc).isoformat(),
        "provider": "provider", "server_name": server, "server_url": "https://mcp.example/mcp",
        "resource_uri": uri, "agent_id": "agent-a"})
    row = await service.get_capability(tenant, result["capability_id"])
    assert row["capability_kind"] == "resource"
    assert row["resource_uri"] == uri
    assert row["capability_id"] == resource_id_for(tenant, "provider", server, uri)
