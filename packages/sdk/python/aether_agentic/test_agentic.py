"""Tests for the Aether Agentic Python SDK observation envelope builders."""

import pytest

from aether_agentic.agentic import (
    AGENT_DEPLOYMENT_CONSENT_MODES,
    AGENT_DEPLOYMENT_ENVIRONMENTS,
    EXTERNAL_PLATFORMS,
    build_agent_event,
    build_deployment_context,
    build_mcp_observation,
    build_risk_signal,
    build_tool_invocation,
)

_BASE = {
    "tenant_id": "tenant-x",
    "event_name": "agent_activity_observed",
    "source": {"provider": "custom"},
    "actor": {"actor_type": "agent", "actor_id": "agent-1"},
    "object": {"object_type": "task", "object_id": "task-1"},
    "action": {"name": "observe", "status": "observed"},
}


def _deployment(**overrides):
    params = {
        "deployment_id": "dep-1",
        "agent_id": "agent-1",
        "external_platform": "discord_bot",
        "environment": "production",
        "consent_mode": "tenant_managed",
    }
    params.update(overrides)
    return build_deployment_context(**params)


class TestBuildDeploymentContext:
    def test_builds_valid_context_with_camelcase_wire_keys(self):
        ctx = _deployment()
        assert ctx == {
            "deploymentId": "dep-1",
            "agentId": "agent-1",
            "externalPlatform": "discord_bot",
            "environment": "production",
            "consentMode": "tenant_managed",
        }

    def test_includes_optional_fields_when_provided(self):
        ctx = _deployment(
            external_channel_id="chan-1",
            external_workspace_id="ws-1",
        )
        assert ctx["externalChannelId"] == "chan-1"
        assert ctx["externalWorkspaceId"] == "ws-1"

    def test_omits_optional_fields_when_absent(self):
        ctx = _deployment()
        assert "externalChannelId" not in ctx
        assert "externalAppId" not in ctx

    def test_rejects_empty_deployment_id(self):
        with pytest.raises(ValueError, match="deployment_id is required"):
            _deployment(deployment_id="")

    def test_rejects_empty_agent_id(self):
        with pytest.raises(ValueError, match="agent_id is required"):
            _deployment(agent_id="")

    def test_rejects_unknown_external_platform(self):
        with pytest.raises(ValueError, match='external_platform "fax_machine" is invalid'):
            _deployment(external_platform="fax_machine")

    def test_rejects_unknown_environment(self):
        with pytest.raises(ValueError, match='environment "prod" is invalid'):
            _deployment(environment="prod")

    def test_rejects_unknown_consent_mode(self):
        with pytest.raises(ValueError, match='consent_mode "nobody_managed" is invalid'):
            _deployment(consent_mode="nobody_managed")

    def test_enums_match_shared_contract_sizes(self):
        assert len(EXTERNAL_PLATFORMS) == 14
        assert len(AGENT_DEPLOYMENT_ENVIRONMENTS) == 4
        assert len(AGENT_DEPLOYMENT_CONSENT_MODES) == 3


class TestBuildAgentEvent:
    def test_execution_by_aether_is_always_false(self):
        evt = build_agent_event(**_BASE)
        assert evt.execution_by_aether is False

    def test_rejects_economics_execution_by_aether_true(self):
        with pytest.raises(ValueError, match="is_execution_by_aether must be False"):
            build_agent_event(**_BASE, economics={"is_execution_by_aether": True})

    def test_deployment_default_none_leaves_context_unset(self):
        evt = build_agent_event(**_BASE)
        assert evt.context is None
        assert "context" not in evt.to_dict()

    def test_deployment_embeds_agent_deployment_context(self):
        evt = build_agent_event(**_BASE, deployment=_deployment())
        assert evt.context == {"agentDeployment": _deployment()}
        assert evt.to_dict()["context"]["agentDeployment"]["deploymentId"] == "dep-1"
        assert evt.execution_by_aether is False

    def test_deployment_strips_canonical_entity_id(self):
        tainted = {**_deployment(), "canonical_entity_id": "ent-1", "canonicalEntityId": "ent-2"}
        evt = build_agent_event(**_BASE, deployment=tainted)
        assert "canonical_entity_id" not in evt.context["agentDeployment"]
        assert "canonicalEntityId" not in evt.context["agentDeployment"]


class TestBuildMCPObservation:
    def test_defaults_unchanged_without_deployment(self):
        obs = build_mcp_observation(tenant_id="t-1", server_name="mcp")
        assert obs["execution_by_aether"] is False
        assert obs["tools"] == []
        assert "context" not in obs

    def test_deployment_embeds_context(self):
        obs = build_mcp_observation(
            tenant_id="t-1", server_name="mcp", deployment=_deployment()
        )
        assert obs["context"]["agentDeployment"]["externalPlatform"] == "discord_bot"
        assert obs["execution_by_aether"] is False


class TestBuildToolInvocation:
    def test_defaults_unchanged_without_deployment(self):
        inv = build_tool_invocation(tenant_id="t-1", tool_name="search")
        assert inv["status"] == "observed"
        assert inv["execution_by_aether"] is False
        assert "context" not in inv

    def test_deployment_embeds_context(self):
        inv = build_tool_invocation(
            tenant_id="t-1", tool_name="search", deployment=_deployment()
        )
        assert inv["context"]["agentDeployment"]["agentId"] == "agent-1"
        assert inv["execution_by_aether"] is False


class TestBuildRiskSignal:
    def test_defaults_unchanged_without_deployment(self):
        sig = build_risk_signal(tenant_id="t-1", risk_level="low")
        assert sig["reason_codes"] == []
        assert "context" not in sig

    def test_deployment_embeds_context(self):
        sig = build_risk_signal(
            tenant_id="t-1", risk_level="high", deployment=_deployment()
        )
        assert sig["context"]["agentDeployment"]["consentMode"] == "tenant_managed"
