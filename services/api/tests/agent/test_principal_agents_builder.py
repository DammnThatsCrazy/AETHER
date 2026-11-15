"""Shared principal-agents builder (route + Profile 360): grants scoped, no identity merge."""
from __future__ import annotations

import pytest

from actions.agent import behavior_read_model
from intelligence.agent_behavior.facts import AgentFact

pytestmark = pytest.mark.asyncio
T = "tenant-pa"


class Grants:
    def __init__(self, rows):
        self.rows = rows
        self.filters = None

    async def find_many(self, filters, limit):
        self.filters = filters
        return self.rows


def _fact(i, agent, principal=None):
    return AgentFact(event_id=f"e{i}", event_type="agent.tool.called", tenant_id=T, agent_ref=agent,
                     occurred_at=f"2026-11-14T10:0{i}:00Z", principal_id=principal)


async def test_only_this_tenants_active_grants_link_agents(monkeypatch):
    loads = []

    async def fake_load(tenant_id, ref):
        loads.append((tenant_id, ref))
        return [_fact(1, ref), _fact(1, ref)], ref == "agent-b"

    monkeypatch.setattr(behavior_read_model, "load_behavior_facts", fake_load)
    repo = Grants([
        {"tenant_id": T, "grantor_entity_id": "person-1", "grantee_entity_id": "agent-a"},
        {"tenant_id": T, "grantor_entity_id": "person-1", "grantee_entity_id": "agent-b"},
        {"tenant_id": T, "grantor_entity_id": "person-1", "grantee_entity_id": "agent-x",
         "revoked_at": "2026-11-01T00:00:00Z"},
        {"tenant_id": "other", "grantor_entity_id": "person-1", "grantee_entity_id": "agent-y"},
    ])
    data = await behavior_read_model.build_principal_agents(T, "person-1", grants_repo=repo)
    assert repo.filters == {"tenant_id": T, "grantor_entity_id": "person-1"}
    assert loads == [(T, "agent-a"), (T, "agent-b")]
    assert [a["agent_ref"] for a in data["agents"]] == ["agent-a", "agent-b"]
    assert all(a["link_basis"] == "recorded_grant" for a in data["agents"])
    assert data["identity_merge"] == "not_performed"
    assert data["source_truncated"] is True
    assert data["agents_capped_at"] == behavior_read_model.PRINCIPAL_AGENTS_CAP
