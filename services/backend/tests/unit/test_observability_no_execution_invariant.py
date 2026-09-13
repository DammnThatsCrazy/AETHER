"""
Invariant tests: All 4 observability service route sets must reject
execution_by_aether=True with HTTP 422.

This is the primary regression gate for the architectural invariant:
  AETHER observes. AETHER does not execute.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal FastAPI app with just the 4 observability routers
# ---------------------------------------------------------------------------

def _build_app():
    from fastapi import FastAPI
    app = FastAPI()
    from services.agentic_observability.routes import mcp_router as agentic_mcp_router
    from services.agentic_observability.routes import router as agentic_obs_router
    from services.protocol_observability.routes import router as protocol_obs_router
    from services.agent_comm_observability.routes import router as comm_obs_router
    from services.external_account_observability.routes import router as ext_account_obs_router
    app.include_router(agentic_obs_router)
    # The MCP observation endpoint lives on its own router (flag-gated in
    # main.py); without it the MCP no-execution invariant is untested.
    app.include_router(agentic_mcp_router)
    app.include_router(protocol_obs_router)
    app.include_router(comm_obs_router)
    app.include_router(ext_account_obs_router)
    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_build_app())


# ---------------------------------------------------------------------------
# 1. Agentic Observability — execution_by_aether=True → 422
# ---------------------------------------------------------------------------

class TestAgenticObservabilityNoExecution:
    def test_agent_events_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent/events", json={
            "tenant_id": "t1",
            "event_name": "agent_activity_observed",
            "source": {"provider": "custom"},
            "actor": {"actor_type": "agent"},
            "object": {"object_type": "tool"},
            "action": {"name": "run", "status": "observed"},
            "provenance": {"raw_event_hash": "abc", "normalized_by": "test", "schema_version": "1.0"},
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_agent_accounts_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent/accounts", json={
            "tenant_id": "t1",
            "agent_id": "agent-1",
            "external_account_id": "acct-1",
            "provider": "custom",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_agent_tools_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent/tools", json={
            "tenant_id": "t1",
            "agent_id": "agent-1",
            "tool_name": "some_tool",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_agent_mcp_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent/mcp", json={
            "tenant_id": "t1",
            "agent_id": "agent-1",
            "mcp_server_url": "https://mcp.example.com",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_economics_field_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent/events", json={
            "tenant_id": "t1",
            "event_name": "agent_activity_observed",
            "source": {"provider": "custom"},
            "actor": {"actor_type": "agent"},
            "object": {"object_type": "tool"},
            "action": {"name": "run", "status": "observed"},
            "provenance": {"raw_event_hash": "abc", "normalized_by": "test", "schema_version": "1.0"},
            "economics": {"is_execution_by_aether": True, "amount": 100},
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 2. Protocol Observability — execution_by_aether=True → 422
# ---------------------------------------------------------------------------

class TestProtocolObservabilityNoExecution:
    def test_x402_interactions_rejects_execution(self, client):
        resp = client.post("/v1/observability/x402/interactions", json={
            "tenant_id": "t1",
            "resource_url": "https://api.example.com/resource",
            "provider": "x402",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_x402_signatures_rejects_execution(self, client):
        resp = client.post("/v1/observability/x402/signatures", json={
            "tenant_id": "t1",
            "interaction_id": "int-1",
            "signer_address": "0xabc",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_x402_settlements_rejects_execution(self, client):
        resp = client.post("/v1/observability/x402/settlements", json={
            "tenant_id": "t1",
            "interaction_id": "int-1",
            "tx_hash": "0xdeadbeef",
            "settlement_by_external": True,
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 3. Agent Comm Observability — execution_by_aether=True → 422
# ---------------------------------------------------------------------------

class TestAgentCommObservabilityNoExecution:
    def test_inboxes_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent-comm/inboxes", json={
            "tenant_id": "t1",
            "agent_id": "agent-1",
            "provider": "agentmail",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_messages_rejects_execution(self, client):
        resp = client.post("/v1/observability/agent-comm/messages", json={
            "tenant_id": "t1",
            "agent_id": "agent-1",
            "direction": "inbound",
            "has_attachments": False,
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 4. External Account Observability — execution_by_aether=True → 422
# ---------------------------------------------------------------------------

class TestExternalAccountObservabilityNoExecution:
    def test_external_accounts_rejects_execution(self, client):
        resp = client.post("/v1/observability/external-accounts", json={
            "tenant_id": "t1",
            "agent_id": "agent-1",
            "provider": "robinhood",
            "account_type": "brokerage",
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_order_observations_rejects_execution(self, client):
        resp = client.post("/v1/observability/external-accounts/order-observations", json={
            "tenant_id": "t1",
            "brokerage_account_id": "acct-1",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "executed_externally": True,
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_brokerage_trade_intent_rejects_execution(self, client):
        resp = client.post("/v1/observability/external-accounts/brokerage", json={
            "tenant_id": "t1",
            "brokerage_account_id": "acct-1",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "submitted_externally": True,
            "execution_by_aether": True,
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
