"""End-to-end wiring test: the Silver dispatcher hook populates the capability catalog.

Proves the out-of-band hook BUILD added to ``SilverDispatcher.project_with_outcome`` (mirroring
``SilverGraphProjector.maybe_emit``) actually materializes ``capability_catalog`` /
``capability_installations`` when an observed agent event is projected — the same path the PR 1
canonical spine drives when ``AGENTIC_OBS_CANONICAL_SPINE_ENABLED`` is on.
"""

from __future__ import annotations

import asyncio

import pytest

from repositories.repos import reset_in_memory_stores
from services.silver.dispatcher import SilverDispatcher
from services.agent_access_intelligence.catalog_service import capability_catalog_service


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _drain(tenant_id: str, *, want: int = 1, ticks: int = 100):
    """Yield to the event loop until the fire-and-forget hook has run."""
    caps: list = []
    for _ in range(ticks):
        caps = await capability_catalog_service.list_capabilities(tenant_id)
        if len(caps) >= want:
            return caps
        await asyncio.sleep(0)
    return caps


async def test_dispatcher_hook_populates_catalog():
    event = {
        "type": "agent_tool_invocation_observed",
        "messageId": "evt-1",
        "timestamp": "2026-07-24T00:00:00Z",
        "context": {"tenantId": "tenantI"},
        "properties": {
            "agentId": "agentA",
            "toolName": "search",
            "serverName": "srvX",
            "serverUrl": "https://x.example",
            "provider": "acme",
            "protocolVersion": "2025-06-18",
            "riskLevel": "low",
        },
    }
    results = await SilverDispatcher().project_with_outcome(event)
    # the agent execution projection itself must have happened
    assert any(r.table == "silver_agent_execution_facts" for r in results.results)

    caps = await _drain("tenantI", want=1)
    assert len(caps) == 1
    assert caps[0]["tool_name"] == "search"
    assert caps[0]["server_name"] == "srvX"
    assert caps[0]["provider"] == "acme"
    assert caps[0]["capability_kind"] == "mcp_tool"

    insts = await capability_catalog_service.list_installations("tenantI")
    assert len(insts) == 1
    assert insts[0]["agent_id"] == "agentA"
