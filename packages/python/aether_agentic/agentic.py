"""
Aether Agentic Python SDK — observation envelope builders.

INVARIANT: execution_by_aether is always False. These helpers build observation-only envelopes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


@dataclass
class AgentEventEnvelope:
    tenant_id: str
    event_name: str
    source: dict[str, Any]
    actor: dict[str, Any]
    object: dict[str, Any]
    action: dict[str, Any]
    agent: Optional[dict[str, Any]] = None
    economics: Optional[dict[str, Any]] = None
    runtime: Optional[dict[str, Any]] = None
    correlation: Optional[dict[str, Any]] = None
    mcp: Optional[dict[str, Any]] = None
    authorization: Optional[dict[str, Any]] = None
    verification: Optional[dict[str, Any]] = None
    privacy: Optional[dict[str, Any]] = None
    execution_by_aether: Literal[False] = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def build_agent_event(
    *,
    tenant_id: str,
    event_name: str,
    source: dict[str, Any],
    actor: dict[str, Any],
    object: dict[str, Any],
    action: dict[str, Any],
    agent: Optional[dict[str, Any]] = None,
    economics: Optional[dict[str, Any]] = None,
    runtime: Optional[dict[str, Any]] = None,
    correlation: Optional[dict[str, Any]] = None,
    mcp: Optional[dict[str, Any]] = None,
    authorization: Optional[dict[str, Any]] = None,
    verification: Optional[dict[str, Any]] = None,
    privacy: Optional[dict[str, Any]] = None,
) -> AgentEventEnvelope:
    if economics and economics.get("is_execution_by_aether") is True:
        raise ValueError("economics.is_execution_by_aether must be False")
    if economics:
        economics = {**economics, "is_execution_by_aether": False}
    return AgentEventEnvelope(
        tenant_id=tenant_id,
        event_name=event_name,
        source=source,
        actor=actor,
        object=object,
        action=action,
        agent=agent,
        economics=economics,
        runtime=runtime,
        correlation=correlation,
        mcp=mcp,
        authorization=authorization,
        verification=verification,
        privacy=privacy,
        execution_by_aether=False,
    )


def build_mcp_observation(
    *,
    tenant_id: str,
    server_name: str,
    agent_id: Optional[str] = None,
    server_url: Optional[str] = None,
    tools: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "server_name": server_name,
        "server_url": server_url,
        "tools": tools or [],
        "execution_by_aether": False,
    }


def build_tool_invocation(
    *,
    tenant_id: str,
    tool_name: str,
    agent_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    status: str = "observed",
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "tool_name": tool_name,
        "agent_id": agent_id,
        "duration_ms": duration_ms,
        "status": status,
        "execution_by_aether": False,
    }


def build_risk_signal(
    *,
    tenant_id: str,
    risk_level: str,
    agent_id: Optional[str] = None,
    reason_codes: Optional[list[str]] = None,
    policy_flags: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "risk_level": risk_level,
        "reason_codes": reason_codes or [],
        "policy_flags": policy_flags or [],
    }
