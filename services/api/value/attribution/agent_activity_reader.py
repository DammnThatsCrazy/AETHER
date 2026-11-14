"""Agent-mediated activity for Value 360 (WO-092).

Resolves a *canonical* Agent to its source-reported runtime agent refs only
through the tenant-admin deployment identity binding (an exact, audited join),
then attributes the value-moving actions those refs reported. Amounts stay
``reported`` unless a rail confirms them; nothing here settles or verifies money.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from value.attribution.agent_behavior_value import attribute

_FACT_LIMIT = 1000
_VALUE_EVENTS = ("agent_transaction_", "agent_execution_")


class AgentActivityReader(Protocol):
    async def activity(self, tenant_id: str, canonical_agent_id: str) -> dict[str, Any]:
        """Tenant-scoped agent-mediated activity for one canonical Agent."""
        ...


class BindingSilverAgentActivityReader:
    """Default reader: identity binding -> Silver agent facts -> attribution."""

    async def activity(self, tenant_id: str, canonical_agent_id: str) -> dict[str, Any]:
        from actions.agent_marketplace.identity_binding import AgentDeploymentIdentityBindingRepository
        from dependencies.providers import get_cache
        from intelligence.agent_behavior.facts import normalize_rows
        from intelligence.agent_behavior.responsibility import decompose
        from repositories.repos import AnalyticsRepository

        bindings = await AgentDeploymentIdentityBindingRepository().find_many(
            filters={"tenant_id": tenant_id, "canonical_agent_entity_id": canonical_agent_id,
                     "status": "active"},
            limit=10,
        )
        bindings = [b for b in bindings if b.get("tenant_id") == tenant_id]
        if not bindings:
            return {"state": "unknown", "reason": "no_active_identity_binding"}
        analytics = AnalyticsRepository(get_cache())
        facts, truncated = [], False
        for binding in bindings:
            rows = await analytics.query_silver(
                "silver_agent_execution_facts",
                {"tenant_id": tenant_id, "agent_id": binding["source_agent_ref"]},
                limit=_FACT_LIMIT + 1,
            )
            truncated = truncated or len(rows) > _FACT_LIMIT
            exact = [r for r in rows[:_FACT_LIMIT]
                     if r.get("deployment_id") == binding.get("source_deployment_id")]
            facts.extend(normalize_rows(exact, tenant_id))
        actions = [f for f in facts if f.amount is not None and f.currency
                   and f.event_type.startswith(_VALUE_EVENTS)]
        refs = {b["source_agent_ref"] for b in bindings}
        result = attribute(
            [{"event_id": f.event_id, "amount": str(f.amount), "currency": f.currency,
              "roles": decompose(f, facts)} for f in actions],
            agent_refs=refs,
        )
        return {
            "state": "degraded" if truncated else ("available" if actions else "empty"),
            "reason": "agent_fact_read_truncated" if truncated else (
                None if actions else "no_value_moving_agent_actions_observed"),
            "binding": {"basis": "tenant_admin_deployment_identity_binding",
                        "source_agent_refs": sorted(refs)},
            "attribution": result,
        }


def unavailable(reason: str) -> dict[str, Any]:
    return {"state": "degraded", "reason": reason}


__all__ = ["AgentActivityReader", "BindingSilverAgentActivityReader", "unavailable"]
