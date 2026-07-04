"""
Agentic Product Surfaces — Agent Profile 360, Journey v2, Campaign influence.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.agentic_observability_repos import (
    AgentActivityRepository,
    AgentConnectionRepository,
    AgentRiskSignalRepository,
    AgentToolRepository,
    ExternalAccountRepository,
    SilverAgentActivityFactRepository,
    SilverAgentRiskFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
)
from services.measurement.repositories.activity_repo import ActivityRepository
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.product_surfaces")


class AgenticProductSurfacesService:
    def __init__(self) -> None:
        self._activities = AgentActivityRepository()
        self._connections = AgentConnectionRepository()
        self._tools = AgentToolRepository()
        self._risks = AgentRiskSignalRepository()
        self._accounts = ExternalAccountRepository()
        self._silver_activity = SilverAgentActivityFactRepository()
        self._silver_tool = SilverAgentToolInvocationFactRepository()
        self._silver_mcp = SilverMCPConnectionFactRepository()
        self._silver_risk = SilverAgentRiskFactRepository()
        self._canonical = ActivityRepository()

    async def agent_profile360(
        self, tenant_id: str, agent_id: str, limit: int = 100
    ) -> dict[str, Any]:
        q = {"tenant_id": tenant_id, "agent_id": agent_id}
        raw_activities = await self._activities.find_many(filters=q, limit=limit)
        raw_connections = await self._connections.find_many(filters=q, limit=limit)
        raw_tools = await self._tools.find_many(filters=q, limit=limit)
        raw_risks = await self._risks.find_many(filters=q, limit=limit)
        raw_accounts = await self._accounts.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id}, limit=limit
        )
        silver_acts = await self._silver_activity.find_many(filters=q, limit=limit)
        silver_tools = await self._silver_tool.find_many(filters=q, limit=limit)
        silver_mcp = await self._silver_mcp.find_many(filters=q, limit=limit)
        silver_risks = await self._silver_risk.find_many(filters=q, limit=limit)
        canonical_steps = await self._canonical.list_agentic_by_agent(tenant_id, agent_id, limit=limit)

        evidence: list[dict[str, Any]] = []
        for row in raw_activities:
            evidence.append({
                "evidence_classification": "observed_fact",
                "source": "obs_agent_activities",
                "data": row,
            })
        for row in raw_accounts:
            evidence.append({
                "evidence_classification": "provider_confirmed_fact",
                "source": "obs_external_accounts",
                "data": row,
            })
        for row in silver_acts:
            evidence.append({
                "evidence_classification": "observed_fact",
                "source": "silver_agent_activity_facts",
                "data": row,
            })

        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "observation_counts": {
                "activities": len(raw_activities),
                "connections": len(raw_connections),
                "tools": len(raw_tools),
                "risks": len(raw_risks),
                "external_accounts": len(raw_accounts),
            },
            "silver_counts": {
                "activity_facts": len(silver_acts),
                "tool_facts": len(silver_tools),
                "mcp_facts": len(silver_mcp),
                "risk_facts": len(silver_risks),
            },
            "canonical_steps": len(canonical_steps),
            "evidence": evidence[:limit],
            "observation_only": True,
        }

    async def journey_v2_agentic_steps(
        self, tenant_id: str, agent_id: str, limit: int = 200
    ) -> dict[str, Any]:
        steps = await self._canonical.list_agentic_steps(tenant_id, agent_id, limit=limit)
        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "step_count": len(steps),
            "steps": [
                {
                    "step_id": str(s.get("activity_id", "")),
                    "activity_type": s.get("activity_type"),
                    "occurred_at": s.get("occurred_at"),
                    "evidence_classification": "observed_fact",
                    "source_system": s.get("source_system", "agentic_observability"),
                }
                for s in steps
            ],
            "observation_only": True,
        }

    async def campaign_agentic_influence(
        self, tenant_id: str, campaign_id: str, limit: int = 200
    ) -> dict[str, Any]:
        steps = await self._canonical.list_agentic_by_campaign(tenant_id, campaign_id, limit=limit)
        return {
            "campaign_id": campaign_id,
            "tenant_id": tenant_id,
            "agentic_step_count": len(steps),
            "steps": [
                {
                    "step_id": str(s.get("activity_id", "")),
                    "agent_id": s.get("agent_id"),
                    "activity_type": s.get("activity_type"),
                    "occurred_at": s.get("occurred_at"),
                    "attribution_status": "eligible_for_modeling",
                    "evidence_classification": "observed_fact",
                }
                for s in steps
            ],
            "observation_only": True,
        }
