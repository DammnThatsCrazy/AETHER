"""Graph projection shape and the MCP protocol surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from actions.agent_correlation.mcp_server import TOOLS, handle_jsonrpc
from actions.agent_correlation.projection import GraphProjector, build_link_mutations
from shared.graph.graph import Edge, Vertex
from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type
from shared.graph.write_validator import GraphWriteValidator
from shared.integration_contracts.correlation import CorrelationObservation, CorrelationVerdict

T0 = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _obs(oid: str, role: str, at: datetime) -> CorrelationObservation:
    return CorrelationObservation(tenant_id="t1", observation_id=oid, source_role=role, provider_family="p", occurred_at=at)


def _verdict(status: str, evidence: str, proves: bool) -> CorrelationVerdict:
    return CorrelationVerdict(status=status, evidence_class=evidence, key_kind="shared_object_ref",
                              supporting_keys=("shared_object_ref",), proves_link=proves, reason="matched")


def test_linked_verdict_projects_one_valid_edge_from_earlier_to_later() -> None:
    early, late = _obs("a", "tool_bridge", T0), _obs("b", "system_of_record", T0 + timedelta(seconds=5))
    mutations = build_link_mutations(late, early, _verdict("linked", "DETERMINISTIC_BINDING", True), "acv_1")
    vertices = [m for m in mutations if isinstance(m, Vertex)]
    (edge,) = [m for m in mutations if isinstance(m, Edge)]
    assert len(vertices) == 2
    assert edge.from_vertex_id == vertices[0].vertex_id and edge.to_vertex_id == vertices[1].vertex_id
    assert edge.properties["resolution_method"] == "deterministic"
    assert edge.properties["from_role"] == "tool_bridge" and edge.properties["to_role"] == "system_of_record"
    assert GraphWriteValidator().validate(edge).passed
    assert classify_edge_type(edge.edge_type) == RelationshipLayer.EXCLUDED


@pytest.mark.parametrize(
    ("status", "evidence", "proves"),
    [("candidate", "TEMPORALLY_CORRELATED", False), ("candidate", "PROVIDER_ASSERTED", False),
     ("rejected", "UNKNOWN", False)],
)
def test_unproven_verdicts_never_reach_the_graph(status: str, evidence: str, proves: bool) -> None:
    assert build_link_mutations(_obs("a", "tool_bridge", T0), _obs("b", "system_of_record", T0),
                                _verdict(status, evidence, proves), "acv_x") == []


@pytest.mark.asyncio
async def test_projector_uses_injected_persistence() -> None:
    seen = {}

    class _Result:
        graph_projection_status = "persisted"
        graph_mutations_persisted = 3

    async def persist(mutations, *, tenant_id, trace_id):
        seen.update(count=len(mutations), tenant=tenant_id, trace=trace_id)
        return _Result()

    out = await GraphProjector(persist).project(
        _obs("a", "agent_runtime", T0), _obs("b", "system_of_record", T0),
        _verdict("linked", "DETERMINISTIC_BINDING", True), "acv_9",
    )
    assert out == {"graph_projection_status": "persisted", "graph_mutations_persisted": 3}
    assert seen == {"count": 3, "tenant": "t1", "trace": "acv_9"}


# --- MCP protocol -------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_negotiates_protocol(service, tenant_id) -> None:
    reply = await handle_jsonrpc(service, tenant_id, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "grok"}},
    })
    assert reply["result"]["protocolVersion"] == "2025-03-26"
    assert reply["result"]["capabilities"] == {"tools": {"listChanged": False}}
    unknown = await handle_jsonrpc(service, tenant_id, {
        "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"},
    })
    assert unknown["result"]["protocolVersion"] == "2025-06-18"


@pytest.mark.asyncio
async def test_notifications_get_no_reply_and_tools_are_listed(service, tenant_id) -> None:
    assert await handle_jsonrpc(service, tenant_id, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = await handle_jsonrpc(service, tenant_id, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names == {t["name"] for t in TOOLS} == {
        "aether_register_task", "aether_report_tool_call", "aether_report_outcome", "aether_get_task_chain",
    }
    for tool in TOOLS:
        assert tool["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_protocol_errors(service, tenant_id) -> None:
    assert (await handle_jsonrpc(service, tenant_id, {"id": 1, "method": "ping"}))["error"]["code"] == -32600
    assert (await handle_jsonrpc(service, tenant_id, {"jsonrpc": "2.0", "id": 1, "method": "nope"}))["error"]["code"] == -32601
    bad_tool = await handle_jsonrpc(service, tenant_id, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}},
    })
    assert bad_tool["error"]["code"] == -32602
    assert (await handle_jsonrpc(service, tenant_id, {"jsonrpc": "2.0", "id": 5, "method": "ping"}))["result"] == {}


@pytest.mark.asyncio
async def test_tool_errors_are_tool_results_not_protocol_errors(service, tenant_id) -> None:
    reply = await handle_jsonrpc(service, tenant_id, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "aether_report_tool_call", "arguments": {
            "correlation_token": "not-a-token", "agent_platform": "xai_grok", "call_id": "c", "tool_name": "x"}},
    })
    assert reply["result"]["isError"] is True


@pytest.mark.asyncio
async def test_register_without_keys_reports_unavailable(tenant_id) -> None:
    from actions.agent_correlation.service import CorrelationService

    reply = await handle_jsonrpc(CorrelationService(keyring=None), tenant_id, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "aether_register_task", "arguments": {"agent_platform": "xai_grok"}},
    })
    assert reply["result"]["isError"] is True
    assert "AGENT_CORRELATION_TOKEN_KEYS" in reply["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_get_task_chain_tool(service, tenant_id) -> None:
    task = await service.register_task(tenant_id, agent_platform="anthropic")
    reply = await handle_jsonrpc(service, tenant_id, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "aether_get_task_chain", "arguments": {"task_ref": task["task_ref"]}},
    })
    chain = reply["result"]["structuredContent"]
    assert chain["task"]["task_ref"] == task["task_ref"]
    assert any("system-of-record" in g for g in chain["gaps"])
