"""Historical agent invocation receipts stay readable after the producer was retired.

Aether no longer invokes MCP tools or reads MCP resources for an agent (ADR-012),
so no new receipts are written. These tests pin that existing receipts still
validate and reach Agent 360 and workflow readers exactly as before.
"""

from __future__ import annotations

import sys
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from actions.agent.invocation_receipts import (  # noqa: E402
    InvocationReceiptRepository,
    validated_agent_receipt,
)
from actions.agent_access_intelligence.authority import CapabilityAuthorizationRepository  # noqa: E402
from actions.agent_access_intelligence.models import capability_id_for  # noqa: E402
from actions.agent_access_intelligence.models import resource_id_for  # noqa: E402
from actions.agent_access_intelligence.repositories import CapabilityCatalogRepository  # noqa: E402
from actions.delegation.engine import DelegationEngine  # noqa: E402
from repositories.repos import DelegationRepository, reset_in_memory_stores  # noqa: E402
from intelligence.workflow.action_authorities import invocation_receipt  # noqa: E402


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

def _historical_receipt(tenant: str, agent: str, execution: str, cap: str) -> dict:
    """A tool receipt exactly as the retired producer wrote it (fixed past times)."""
    scope = {"actions": ["invoke"], "resources": [f"capability:{cap}"]}
    result = {"content": [{"text": "real"}]}
    receipt_id = "d2cb913e-04c4-55f5-8115-1b2a3348865c"
    return {
        "receipt_id": receipt_id,
        "id": receipt_id,
        "tenant_id": tenant,
        "agent_id": agent,
        "execution_id": execution,
        "workflow_run_id": "run-a",
        "workflow_definition_link": {"workflow_id": "wf-a", "revision": 2},
        "tool_name": "lookup",
        "capability_id": cap,
        "resource": f"capability:{cap}",
        "policy_resource": f"capability:{cap}",
        "provider": "provider",
        "provider_url": "https://tools.example/mcp",
        "server_key": "srv.example",
        "initiating_principal_user_id": "owner",
        "policy_decision": {
            "allowed": True,
            "delegation_id": "grant-a",
            "reason": "",
            "matched_scope": scope,
            "evaluated_at": "2026-11-01T10:00:02+00:00",
        },
        "grant_scope": scope,
        "grant_id": "grant-a",
        "grant_starts_at": "2026-11-01T10:00:00+00:00",
        "grant_ends_at": None,
        "invoked_at": "2026-11-01T10:00:02+00:00",
        "completed_at": "2026-11-01T10:00:03+00:00",
        "result_status": "succeeded",
        "tool_call_attempted": True,
        "provider_result": result,
        "provider_result_digest": hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest(),
        "provider_result_complete": True,
        "provider_error": None,
        "arguments_digest": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "evidence_version": 1,
        "agent_policy_version": 3,
        "action": "invoke",
    }


async def _completed_invocation(monkeypatch):
    """Seed one historical receipt and its execution window; no producer runs."""
    tenant, agent, execution, _tool, cap, *_rest, run = await _fixture()
    row = _historical_receipt(tenant, agent, execution, cap)
    await InvocationReceiptRepository().insert(row["id"], row)
    run["started_at"] = "2026-11-01T10:00:01+00:00"
    run["ended_at"] = row["completed_at"]
    assert await validated_agent_receipt(tenant_id=tenant, agent_id=agent, execution=run)
    return row, run



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

    async def validated_resource_read(**_kwargs):
        return {
            "state": "provider_resource_read_succeeded", "receiptId": "read-receipt-a",
            "resourceId": "resource-a", "resourceUri": "https://data.example/item/a",
            "resourceOperation": "read", "action": "read_resource", "grantId": "read-grant-a",
            "initiatingPrincipalUserId": "operator-a",
            "policyDecision": {"allowed": True, "delegation_id": "read-grant-a",
                               "matched_scope": {"actions": ["read_resource"], "resources": ["mcp-resource:resource-a"]},
                               "evaluated_at": "2026-10-18T10:00:00Z"},
            "invokedAt": "2026-10-18T10:00:01Z", "completedAt": "2026-10-18T10:00:02Z",
            "resultStatus": "succeeded", "providerResultDigest": "a" * 64,
            "providerResultComplete": True, "providerResult": {"contents": [{"uri": "https://data.example/item/a", "text": "value"}]},
            "externalEffect": "unknown",
        }

    monkeypatch.setattr("actions.agent.invocation_receipts.validated_agent_receipt", validated_resource_read)
    read_result = await Agent360Provider(ReceiptSource()).project(_request(), _context())
    read_profile = next(item for item in _sections(read_result)["state"].content["dimensions"]
                        if item["id"] == "authority_and_delegation")["content"]["capabilityAccessProfile"]
    read_authority = read_profile["actionResourceAuthority"]
    assert read_authority["resources"]["state"] == "observed"
    assert read_authority["resources"]["supportedOperations"] == ["read"]
    assert read_authority["resources"]["receipts"][0]["principalUserId"] == "operator-a"
    assert read_authority["actions"]["state"] == "unknown"
    assert read_authority["effectiveToolAuthorization"] == "unknown"
    assert "agent360_resource_operation_authority_source_unbound" not in read_profile["missingInputs"]
    assert any(claim.kind == "agent_provider_resource_read_result" for claim in read_result.claims)


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
    assert section.content["resourceReadAuthority"]["state"] == "unknown"
    assert (
        any(claim.kind == "workflow_linked_provider_tool_result" for claim in claims) is authorized
    )
    if authorized:
        assert section.state == "available"
        assert "actions" in section.canonicalAuthorityRefs


@pytest.mark.asyncio
async def test_workflow_actions_slot_projects_only_bound_resource_read_receipts(monkeypatch):
    from intelligence.workflow.workflow360_provider import _workflow_actions_section, WorkflowActionRead
    from intelligence.workflow.action_authorities import ApprovedResourceRead
    from shared.intelligence_projections.contracts import ProjectionSubject, EvidenceRef

    _row, run = await _completed_invocation(monkeypatch)
    async def validated_resource_read(**_kwargs):
        return {
            "state": "provider_resource_read_succeeded", "receiptId": "read-receipt-a",
            "resourceId": "resource-a", "resourceUri": "https://data.example/item/a",
            "resourceOperation": "read", "action": "read_resource", "grantId": "read-grant-a",
            "initiatingPrincipalUserId": "operator-a",
            "policyDecision": {"allowed": True, "delegation_id": "read-grant-a",
                               "matched_scope": {"actions": ["read_resource"], "resources": ["mcp-resource:resource-a"]},
                               "evaluated_at": "2026-10-18T10:00:00Z"},
            "invokedAt": "2026-10-18T10:00:01Z", "completedAt": "2026-10-18T10:00:02Z",
            "resultStatus": "succeeded", "providerResultDigest": "a" * 64,
            "providerResultComplete": True, "providerResult": {"contents": [{"uri": "https://data.example/item/a", "text": "value"}]},
            "externalEffect": "unknown",
        }
    monkeypatch.setattr("actions.agent.invocation_receipts.validated_agent_receipt", validated_resource_read)
    section, claims = await _workflow_actions_section(
        ProjectionSubject(kind="workflow_run", id="run-a"), tenant_id="tenant-a",
        read=WorkflowActionRead((), True, True), execution_rows=[run],
        execution_refs=[EvidenceRef(id="exec-a", type="event", source="agent_executions")],
        execution_inventory_complete=True, time_range=None, requested=True, historical=False,
        execution_results_authorized=True, resource_read=ApprovedResourceRead((), True, True),
    )
    authority = section.content["resourceReadAuthority"]
    assert authority == {"state": "observed", "supportedOperations": ["read"],
                        "receiptIds": ["read-receipt-a"], "coverage": "bounded_observed_receipts_only",
                        "mutation": "unknown", "externalEffect": "unknown"}
    assert any(claim.kind == "workflow_linked_provider_resource_read" for claim in claims)

    denied, denied_claims = await _workflow_actions_section(
        ProjectionSubject(kind="workflow_run", id="run-a"), tenant_id="tenant-a",
        read=WorkflowActionRead((), True, True), execution_rows=[run],
        execution_refs=[EvidenceRef(id="exec-a", type="event", source="agent_executions")],
        execution_inventory_complete=True, time_range=None, requested=True, historical=False,
        execution_results_authorized=False, resource_read=ApprovedResourceRead((), True, True),
    )
    assert denied.content["resourceReadAuthority"]["state"] == "unknown"
    assert not any(claim.kind == "workflow_linked_provider_resource_read" for claim in denied_claims)


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
