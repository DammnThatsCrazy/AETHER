"""
Aether Agentic Python SDK — observation envelope builders.

INVARIANT: execution_by_aether is always False. These helpers build observation-only envelopes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

# External Agent Telemetry Plane V1 — mirrors packages/shared/agent-deployment.ts.
EXTERNAL_PLATFORMS = (
    "web_widget",
    "mobile_app",
    "discord_bot",
    "telegram_bot",
    "slack_app",
    "shopify_app",
    "salesforce_app",
    "custom_marketplace",
    "wallet_app",
    "browser_extension",
    "mcp_server",
    "backend_worker",
    "api_agent",
    "unknown",
)

AGENT_DEPLOYMENT_ENVIRONMENTS = ("production", "staging", "sandbox", "development")

AGENT_DEPLOYMENT_CONSENT_MODES = ("tenant_managed", "platform_managed", "aether_managed")


def build_deployment_context(
    *,
    deployment_id: str,
    agent_id: str,
    external_platform: str,
    environment: str,
    consent_mode: str,
    external_platform_account_id: Optional[str] = None,
    external_agent_id: Optional[str] = None,
    external_app_id: Optional[str] = None,
    external_channel_id: Optional[str] = None,
    external_workspace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build a validated AgentDeploymentContext dict (camelCase wire keys,
    matching packages/shared/agent-deployment.ts). Identity resolution is
    backend-owned — no canonical_entity_id is ever included."""
    if not deployment_id or not isinstance(deployment_id, str):
        raise ValueError("deployment_id is required and must be a non-empty string")
    if not agent_id or not isinstance(agent_id, str):
        raise ValueError("agent_id is required and must be a non-empty string")
    if external_platform not in EXTERNAL_PLATFORMS:
        raise ValueError(
            f'external_platform "{external_platform}" is invalid — '
            f"expected one of: {', '.join(EXTERNAL_PLATFORMS)}"
        )
    if environment not in AGENT_DEPLOYMENT_ENVIRONMENTS:
        raise ValueError(
            f'environment "{environment}" is invalid — '
            f"expected one of: {', '.join(AGENT_DEPLOYMENT_ENVIRONMENTS)}"
        )
    if consent_mode not in AGENT_DEPLOYMENT_CONSENT_MODES:
        raise ValueError(
            f'consent_mode "{consent_mode}" is invalid — '
            f"expected one of: {', '.join(AGENT_DEPLOYMENT_CONSENT_MODES)}"
        )
    context: dict[str, Any] = {
        "deploymentId": deployment_id,
        "agentId": agent_id,
        "externalPlatform": external_platform,
        "environment": environment,
        "consentMode": consent_mode,
    }
    optional = {
        "externalPlatformAccountId": external_platform_account_id,
        "externalAgentId": external_agent_id,
        "externalAppId": external_app_id,
        "externalChannelId": external_channel_id,
        "externalWorkspaceId": external_workspace_id,
    }
    context.update({k: v for k, v in optional.items() if v is not None})
    return context


# Identity resolution is backend-owned. SDKs must never emit these keys.
_FORBIDDEN_IDENTITY_KEYS = ("canonical_entity_id", "canonicalEntityId")


def _deployment_wrapper(deployment: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Wrap a validated deployment dict as envelope context, dropping
    forbidden identity keys if a caller passed them."""
    if deployment is None:
        return None
    cleaned = {k: v for k, v in deployment.items() if k not in _FORBIDDEN_IDENTITY_KEYS}
    return {"agentDeployment": cleaned}


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
    context: Optional[dict[str, Any]] = None
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
    deployment: Optional[dict[str, Any]] = None,
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
        context=_deployment_wrapper(deployment),
        execution_by_aether=False,
    )


def build_mcp_observation(
    *,
    tenant_id: str,
    server_name: str,
    agent_id: Optional[str] = None,
    server_url: Optional[str] = None,
    tools: Optional[list[str]] = None,
    deployment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    observation = {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "server_name": server_name,
        "server_url": server_url,
        "tools": tools or [],
        "execution_by_aether": False,
    }
    context = _deployment_wrapper(deployment)
    if context is not None:
        observation["context"] = context
    return observation


def build_tool_invocation(
    *,
    tenant_id: str,
    tool_name: str,
    agent_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    status: str = "observed",
    deployment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    invocation = {
        "tenant_id": tenant_id,
        "tool_name": tool_name,
        "agent_id": agent_id,
        "duration_ms": duration_ms,
        "status": status,
        "execution_by_aether": False,
    }
    context = _deployment_wrapper(deployment)
    if context is not None:
        invocation["context"] = context
    return invocation


def build_risk_signal(
    *,
    tenant_id: str,
    risk_level: str,
    agent_id: Optional[str] = None,
    reason_codes: Optional[list[str]] = None,
    policy_flags: Optional[list[str]] = None,
    deployment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    signal = {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "risk_level": risk_level,
        "reason_codes": reason_codes or [],
        "policy_flags": policy_flags or [],
    }
    context = _deployment_wrapper(deployment)
    if context is not None:
        signal["context"] = context
    return signal
