"""Smoke tests for the canonical-spine agentic observation bridge (PR 1).

Verifies that ``ingest_observation`` writes THROUGH the durable spine (typed
Bronze + event_outbox in one transaction), is idempotent on a repeated
provider_event_id, and that the SilverDispatcher now routes the observed tool
event to a projector. Runs fully in-memory (AETHER_ENV=local).
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import _IN_MEMORY_STORES  # noqa: E402
from services.agentic_observability.pipeline import ingest_observation  # noqa: E402
from services.silver.dispatcher import SilverDispatcher  # noqa: E402


def _stores():
    bronze = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    outbox = _IN_MEMORY_STORES.setdefault("event_outbox", {})
    return bronze, outbox


def _ingest_mcp_tool():
    return asyncio.run(
        ingest_observation(
            tenant_id="tenant-smoke",
            event_name="agent_tool_invocation_observed",
            provider_id="mcp",
            integration_id="integration-1",
            environment_id="prod",
            provider_event_id="prov-evt-abc-123",
            agent_id="agent-smoke-1",
            observed_at="2026-07-24T00:00:00+00:00",
            properties={
                "agentId": "agent-smoke-1",
                "toolName": "search_web",
                "serverName": "acme-mcp",
                "serverUrl": "https://mcp.acme.test",
                "protocolVersion": "2025-06-18",
                "status": "succeeded_observed",
                "provider": "mcp",
                "objectType": "tool",
                "objectId": "search_web",
            },
        )
    )


def test_ingest_observation_writes_bronze_and_outbox_once_then_dedupes():
    bronze, outbox = _stores()
    bronze.clear()
    outbox.clear()

    first = _ingest_mcp_tool()
    assert first.status == "accepted"
    assert first.outbox_written == 1
    assert len(bronze) == 1, f"expected one bronze row, got {len(bronze)}"
    assert len(outbox) == 1, f"expected one outbox row, got {len(outbox)}"

    # The single bronze row is the observed tool event, on the validated topic.
    (bronze_row,) = list(bronze.values())
    assert bronze_row["event_type"] == "agent_tool_invocation_observed"
    assert bronze_row["tenant_id"] == "tenant-smoke"
    (outbox_row,) = list(outbox.values())
    assert outbox_row["topic"] == "aether.sdk.events.validated"
    assert outbox_row["payload"]["properties"]["toolName"] == "search_web"

    # A second identical call (same provider_event_id) is a durable duplicate:
    # same deterministic event_id, no new bronze/outbox rows, nothing re-queued.
    second = _ingest_mcp_tool()
    assert second.event_id == first.event_id
    assert second.status == "duplicate"
    assert second.outbox_written == 0
    assert len(bronze) == 1
    assert len(outbox) == 1


def test_silver_dispatcher_handles_observed_tool_event():
    assert SilverDispatcher().handles("agent_tool_invocation_observed") is True
    # And the MCP + risk observed types are routed too.
    assert SilverDispatcher().handles("agent_mcp_connection_observed") is True
    assert SilverDispatcher().handles("agent_risk_signal_observed") is True
