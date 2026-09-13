from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "python")
    ),
)
os.environ.setdefault("AETHER_ENV", "local")

import pytest

from aether_agentic import (
    AgentEventEnvelope,
    build_agent_event,
    build_mcp_observation,
    build_risk_signal,
    build_tool_invocation,
)

_BASE = dict(
    tenant_id="tenant-x",
    event_name="agent_activity_observed",
    source={"provider": "custom"},
    actor={"actor_type": "agent", "actor_id": "agent-1"},
    object={"object_type": "task", "object_id": "task-1"},
    action={"name": "observe", "status": "observed"},
)


def test_build_agent_event_basic():
    evt = build_agent_event(**_BASE)
    assert isinstance(evt, AgentEventEnvelope)
    assert evt.tenant_id == "tenant-x"
    assert evt.execution_by_aether is False


def test_build_agent_event_to_dict_omits_none():
    evt = build_agent_event(**_BASE)
    d = evt.to_dict()
    assert "agent" not in d
    assert "economics" not in d
    assert "runtime" not in d
    assert "mcp" not in d


def test_build_agent_event_execution_by_aether_always_false():
    evt = build_agent_event(**_BASE)
    assert evt.to_dict()["execution_by_aether"] is False


def test_build_agent_event_rejects_economics_true():
    with pytest.raises(ValueError, match="is_execution_by_aether"):
        build_agent_event(**_BASE, economics={"is_execution_by_aether": True})


def test_build_agent_event_forces_economics_false():
    evt = build_agent_event(
        **_BASE,
        economics={"is_execution_by_aether": False, "amount": 10, "currency": "USD"},
    )
    assert evt.economics["is_execution_by_aether"] is False
    assert evt.economics["amount"] == 10


def test_build_agent_event_runtime_context():
    evt = build_agent_event(**_BASE, runtime={"runtime_id": "rt-1", "environment": "production"})
    assert evt.runtime["runtime_id"] == "rt-1"
    assert "runtime" in evt.to_dict()


def test_build_agent_event_correlation_context():
    evt = build_agent_event(**_BASE, correlation={"trace_id": "tr-abc"})
    assert evt.correlation["trace_id"] == "tr-abc"


def test_build_agent_event_mcp_context():
    evt = build_agent_event(**_BASE, mcp={"server_name": "my-mcp", "tool_name": "bash"})
    assert evt.mcp["server_name"] == "my-mcp"


def test_build_agent_event_authorization_context():
    evt = build_agent_event(**_BASE, authorization={"grant_id": "g-1", "scope": ["read"]})
    assert evt.authorization["grant_id"] == "g-1"


def test_build_agent_event_verification_context():
    evt = build_agent_event(**_BASE, verification={"verification_status": "confirmed"})
    assert evt.verification["verification_status"] == "confirmed"


def test_build_agent_event_privacy_context():
    evt = build_agent_event(**_BASE, privacy={"privacy_class": "sensitive", "dsr_applicable": True})
    assert evt.privacy["dsr_applicable"] is True


def test_build_mcp_observation_basic():
    obs = build_mcp_observation(tenant_id="t-1", server_name="test-mcp", tools=["bash", "read"])
    assert obs["execution_by_aether"] is False
    assert obs["tools"] == ["bash", "read"]
    assert obs["server_name"] == "test-mcp"


def test_build_mcp_observation_defaults_tools_to_empty():
    obs = build_mcp_observation(tenant_id="t-1", server_name="mcp")
    assert obs["tools"] == []


def test_build_tool_invocation_basic():
    inv = build_tool_invocation(tenant_id="t-1", tool_name="write_file", agent_id="agent-2", duration_ms=42)
    assert inv["execution_by_aether"] is False
    assert inv["tool_name"] == "write_file"
    assert inv["status"] == "observed"
    assert inv["duration_ms"] == 42


def test_build_tool_invocation_custom_status():
    inv = build_tool_invocation(tenant_id="t-1", tool_name="read_file", status="succeeded_observed")
    assert inv["status"] == "succeeded_observed"


def test_build_risk_signal_basic():
    sig = build_risk_signal(tenant_id="t-1", risk_level="high", reason_codes=["exceeded_tool_budget"])
    assert sig["risk_level"] == "high"
    assert "exceeded_tool_budget" in sig["reason_codes"]
    assert sig["policy_flags"] == []


def test_build_risk_signal_defaults_lists():
    sig = build_risk_signal(tenant_id="t-1", risk_level="low")
    assert sig["reason_codes"] == []
    assert sig["policy_flags"] == []
