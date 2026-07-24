"""Service-level tests for the capability catalog (PR 2, Phase A).

Proves the maintained-materialization semantics end-to-end against the in-memory backend:
idempotent replay, distinct-observation counting, camelCase payload extraction, honest kind
derivation, capability-signal gating, tenant-scoped fail-closed reads, and cross-tenant Kyber
aggregation. No Postgres required.
"""

from __future__ import annotations

import pytest

from services.agent_access_intelligence.catalog_service import CapabilityCatalogService
from services.agent_access_intelligence.models import CapabilityKind
from shared.common.common import NotFoundError


def _fact(**over):
    row = {
        "tenant_id": "t1",
        "source_event_id": "e1",
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "srvX",
        "server_url": "https://x.example",
        "provider": "acme",
        "protocol_version": "2025-06-18",
        "risk_level": "low",
        "payload": {},
    }
    row.update(over)
    return row


@pytest.fixture
def svc():
    return CapabilityCatalogService()


async def test_records_capability_and_installation(svc):
    result = await svc.record_from_fact(_fact())
    assert result["recorded"] is True
    assert result["capability_kind"] == CapabilityKind.MCP_TOOL.value

    caps = await svc.list_capabilities("t1")
    assert len(caps) == 1
    cap = caps[0]
    assert cap["tool_name"] == "search"
    assert cap["server_name"] == "srvX"
    assert cap["provider"] == "acme"
    assert cap["observation_count"] == 1
    assert cap["first_seen_at"] == "2026-07-24T00:00:00Z"

    insts = await svc.list_installations("t1")
    assert len(insts) == 1
    assert insts[0]["agent_id"] == "agentA"
    assert result["capability_id"] in insts[0]["capability_ids"]


async def test_replay_same_event_is_idempotent(svc):
    await svc.record_from_fact(_fact(source_event_id="e1"))
    await svc.record_from_fact(_fact(source_event_id="e1"))  # replay
    caps = await svc.list_capabilities("t1")
    assert len(caps) == 1
    assert caps[0]["observation_count"] == 1


async def test_distinct_observations_increment_count_single_row(svc):
    await svc.record_from_fact(_fact(source_event_id="e1"))
    await svc.record_from_fact(_fact(source_event_id="e2"))
    await svc.record_from_fact(_fact(source_event_id="e3", occurred_at="2026-07-25T00:00:00Z"))
    caps = await svc.list_capabilities("t1")
    assert len(caps) == 1
    assert caps[0]["observation_count"] == 3
    # last_seen advances, first_seen preserved.
    assert caps[0]["last_seen_at"] == "2026-07-25T00:00:00Z"
    assert caps[0]["first_seen_at"] == "2026-07-24T00:00:00Z"


async def test_camelcase_payload_only_extraction(svc):
    """A persisted silver row exposes tool/server/provider ONLY via payload camelCase."""
    row = {
        "tenant_id": "t1",
        "source_event_id": "e9",
        "source_event_type": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "payload": {
            "agentId": "agentZ",
            "toolName": "transfer",
            "serverName": "srvQ",
            "serverUrl": "https://q.example",
            "provider": "beta",
            "protocolVersion": "2025-06-18",
            "riskLevel": "high",
        },
    }
    result = await svc.record_from_fact(row)
    assert result["recorded"] is True
    cap = (await svc.list_capabilities("t1"))[0]
    assert cap["tool_name"] == "transfer"
    assert cap["server_name"] == "srvQ"
    assert cap["provider"] == "beta"
    assert cap["latest_risk_level"] == "high"


async def test_generic_lifecycle_event_not_recorded(svc):
    result = await svc.record_from_fact(
        {"tenant_id": "t1", "source_event_id": "eL", "event_name": "agent_task_started",
         "payload": {"agentId": "agentA"}}
    )
    assert result["recorded"] is False
    assert await svc.list_capabilities("t1") == []


@pytest.mark.parametrize(
    "over,expected",
    [
        ({}, CapabilityKind.MCP_TOOL.value),  # tool + server
        ({"server_name": None, "server_url": None}, CapabilityKind.PROVIDER_ACTION.value),  # tool only
        (
            {"tool_name": None, "server_name": None, "server_url": None,
             "event_name": "agent_portfolio_snapshot_observed"},
            CapabilityKind.ACCOUNT.value,
        ),  # account/portfolio event with provider, no tool/server
        (
            {"tool_name": None, "event_name": "agent_mcp_connection_observed"},
            CapabilityKind.RESOURCE.value,
        ),  # server only, no tool
    ],
)
async def test_kind_derivation(svc, over, expected):
    result = await svc.record_from_fact(_fact(**over))
    assert result["recorded"] is True
    assert result["capability_kind"] == expected


async def test_cross_tenant_read_is_fail_closed(svc):
    result = await svc.record_from_fact(_fact(tenant_id="t1"))
    cap_id = result["capability_id"]
    # Same id must not be readable by another tenant.
    with pytest.raises(NotFoundError):
        await svc.get_capability("t2", cap_id)
    # And a t2 observation never appears in t1's listing.
    await svc.record_from_fact(_fact(tenant_id="t2", source_event_id="z1"))
    assert len(await svc.list_capabilities("t1")) == 1
    assert len(await svc.list_capabilities("t2")) == 1


async def test_list_filters_by_provider(svc):
    await svc.record_from_fact(_fact(source_event_id="a", provider="acme", tool_name="search", server_name="s1"))
    await svc.record_from_fact(_fact(source_event_id="b", provider="beta", tool_name="pay", server_name="s2"))
    acme = await svc.list_capabilities("t1", provider="acme")
    assert len(acme) == 1 and acme[0]["provider"] == "acme"


async def test_overview_counts(svc):
    await svc.record_from_fact(_fact(source_event_id="a", tool_name="search", server_name="s1", provider="acme"))
    await svc.record_from_fact(
        _fact(source_event_id="b", tool_name=None, server_name=None, server_url=None,
              event_name="agent_portfolio_snapshot_observed", provider="beta")
    )
    ov = await svc.catalog_overview("t1")
    assert ov["capability_count"] == 2
    assert ov["by_kind"].get(CapabilityKind.MCP_TOOL.value) == 1
    assert ov["by_kind"].get(CapabilityKind.ACCOUNT.value) == 1


async def test_kyber_health_aggregates_cross_tenant(svc):
    await svc.record_from_fact(_fact(tenant_id="t1", source_event_id="a"))
    await svc.record_from_fact(_fact(tenant_id="t2", source_event_id="b"))
    health = await svc.catalog_health()
    assert health["total_capabilities"] == 2
    assert health["tenant_count"] == 2


async def test_installation_provenance_not_leaked(svc):
    """The private dedup field is stripped from the public installation payload."""
    await svc.record_from_fact(_fact())
    inst = (await svc.list_installations("t1"))[0]
    assert not any(k.startswith("_") for k in inst)


async def test_server_url_credentials_are_sanitized(svc):
    await svc.record_from_fact(
        _fact(source_event_id="su", server_url="https://user:apikey@mcp.example.com/mcp?token=abc123&mode=live")
    )
    url = (await svc.list_capabilities("t1"))[0]["server_url"]
    assert "user:" not in url and "apikey" not in url  # userinfo stripped
    assert "abc123" not in url and "REDACTED" in url    # secret query param redacted
    assert "mode=live" in url                            # benign param preserved
    assert url.startswith("https://mcp.example.com")


async def test_private_dedup_field_not_leaked_on_capability(svc):
    seeded = await svc.record_from_fact(_fact())
    cap = (await svc.list_capabilities("t1"))[0]
    assert not any(k.startswith("_") for k in cap)
    detail = await svc.get_capability("t1", seeded["capability_id"])
    assert "_dedup_source_event_ids" not in detail


async def test_overview_reports_sampled_flag(svc):
    await svc.record_from_fact(_fact())
    ov = await svc.catalog_overview("t1")
    assert ov["sampled"] is False  # tiny inventory fits the sample window
