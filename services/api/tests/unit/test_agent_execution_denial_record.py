"""Denied agent actions must retain their server authority evidence."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent import user_agents  # noqa: E402
from actions.delegation.engine import DelegationDecision  # noqa: E402
from shared.common.common import ForbiddenError  # noqa: E402


@pytest.mark.asyncio
async def test_denied_execute_persists_decision_and_requested_scope(monkeypatch) -> None:
    tenant_id = "tenant-agent-denial"
    agent_id = "agent-denied-action"
    recorded: dict[str, Any] = {}
    published: list[Any] = []

    class ConfigRepository:
        async def find_by_id(self, requested_agent_id: str) -> dict[str, Any]:
            assert requested_agent_id == agent_id
            return {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "owner_entity_id": "owner-1",
                "constraints": {"max_amount": "10"},
            }

    class ExecutionRepository:
        async def record(self, **kwargs: Any) -> dict[str, Any]:
            recorded.update(kwargs)
            return kwargs

    class DeniedEngine:
        async def evaluate(self, **kwargs: Any) -> DelegationDecision:
            assert kwargs == {
                "grantee_entity_id": agent_id,
                "action": "transfer",
                "resource": "account:4",
                "amount": "25",
            }
            return DelegationDecision(
                allowed=False,
                reason="no_active_delegation",
            )

    class Producer:
        async def publish(self, event: Any) -> None:
            published.append(event)

    monkeypatch.setattr(user_agents, "_configs", ConfigRepository())
    monkeypatch.setattr(user_agents, "_executions", ExecutionRepository())
    settings_module = __import__("config.settings", fromlist=["settings"])
    ai_aggregation = __import__("value.economic.ai_aggregation", fromlist=["list_facts"])
    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(ai_economics=SimpleNamespace(execution_facts_enabled=True)),
    )

    async def list_facts(requested_tenant: str, **filters: Any) -> list[dict[str, Any]]:
        assert requested_tenant == tenant_id
        assert filters == {"action_id": "execution-id-a", "limit": 201}
        return [
            {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "action_id": "execution-id-a",
                "workflow_run_id": "workflow-run-a",
                "invocation_id": "invocation-a",
            }
        ]

    monkeypatch.setattr(ai_aggregation, "list_facts", list_facts)
    request = SimpleNamespace(
        state=SimpleNamespace(
            tenant=SimpleNamespace(
                tenant_id=tenant_id,
                user_id="authenticated-human-1",
                require_permission=lambda permission: None,
            )
        )
    )
    body = user_agents.AgentExecute(
        action="transfer",
        resource="account:4",
        amount="25",
        execution_id="execution-id-a",
        triggered_by_event_id="trigger-1",
    )

    with pytest.raises(ForbiddenError):
        await user_agents.execute(
            agent_id,
            body,
            request,
            engine=DeniedEngine(),
            graph=None,
            producer=Producer(),
        )

    assert recorded["tenant_id"] == tenant_id
    assert recorded["initiating_principal_user_id"] == "authenticated-human-1"
    assert recorded["workflow_run_id"] == "workflow-run-a"
    assert recorded["workflow_run_invocation_ids"] == ["invocation-a"]
    assert recorded["delegation_id"] is None
    assert recorded["policy_log"]["delegation_check"] == {
        "allowed": False,
        "delegation_id": None,
        "reason": "no_active_delegation",
        "matched_scope": None,
    }
    assert recorded["policy_log"]["constraints"] == {"max_amount": "10"}
    assert recorded["input_snapshot"] == {
        "action": "transfer",
        "resource": "account:4",
        "amount": "25",
    }
    assert len(published) == 1
    assert published[0].payload["execution_id"] == recorded["execution_id"]
