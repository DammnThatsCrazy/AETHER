"""
Tenant isolation tests: An observation written for tenant A must not be
readable by tenant B through any observability repository.

Uses in-memory stores (AETHER_ENV=local).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAgentActivityTenantIsolation:
    def test_activity_not_visible_cross_tenant(self):
        from repositories.agentic_observability_repos import AgentActivityRepository

        repo = AgentActivityRepository()
        obs_id = "obs-tenant-isolation-test"
        record = {
            "observation_id": obs_id,
            "tenant_id": "tenant-A",
            "event_name": "agent_activity_observed",
        }
        _run(repo.insert(obs_id, record))

        # Direct ID lookup should work for tenant-A
        found = _run(repo.find_by_id(obs_id))
        assert found is not None
        assert found["tenant_id"] == "tenant-A"

        # find_many with tenant-B filter should return nothing
        results = _run(repo.find_many(filters={"tenant_id": "tenant-B"}, limit=100))
        obs_ids = [r.get("observation_id") for r in results]
        assert obs_id not in obs_ids, (
            "Observation for tenant-A must not be returned in tenant-B query"
        )


class TestX402InteractionTenantIsolation:
    def test_x402_interaction_not_visible_cross_tenant(self):
        from repositories.agentic_observability_repos import X402InteractionRepository

        repo = X402InteractionRepository()
        obs_id = "x402-tenant-isolation-test"
        record = {
            "interaction_id": obs_id,
            "tenant_id": "tenant-A",
            "resource_url": "https://api.example.com/paid",
        }
        _run(repo.insert(obs_id, record))

        # Tenant-B query returns nothing
        results = _run(repo.find_many(filters={"tenant_id": "tenant-B"}, limit=100))
        ids = [r.get("interaction_id") for r in results]
        assert obs_id not in ids


class TestExternalAccountTenantIsolation:
    def test_external_account_not_visible_cross_tenant(self):
        from repositories.agentic_observability_repos import ExternalAccountRepository

        repo = ExternalAccountRepository()
        obs_id = "ext-acct-tenant-isolation-test"
        record = {
            "observation_id": obs_id,
            "tenant_id": "tenant-A",
            "agent_id": "agent-1",
            "provider": "robinhood",
        }
        _run(repo.insert(obs_id, record))

        results = _run(repo.find_many(filters={"tenant_id": "tenant-B"}, limit=100))
        ids = [r.get("observation_id") for r in results]
        assert obs_id not in ids


class TestAgentMessageTenantIsolation:
    def test_message_not_visible_cross_tenant(self):
        from repositories.agentic_observability_repos import AgentMessageRepository

        repo = AgentMessageRepository()
        obs_id = "msg-tenant-isolation-test"
        record = {
            "message_id": obs_id,
            "tenant_id": "tenant-A",
            "direction": "inbound",
        }
        _run(repo.insert(obs_id, record))

        results = _run(repo.find_many(filters={"tenant_id": "tenant-B"}, limit=100))
        ids = [r.get("message_id") for r in results]
        assert obs_id not in ids
