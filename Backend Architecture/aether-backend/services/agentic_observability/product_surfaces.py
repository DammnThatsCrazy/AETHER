"""Read-only Agentic Intelligence product surface aggregations.

These adapters bridge canonical agentic observations into product surfaces
without adding execution capability. They only read tenant-scoped repositories
and canonical_activity rows that were already created by ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from shared.common.common import utc_now


@dataclass(slots=True)
class AgenticSurfaceEvidence:
    surface: str
    evidence_classification: str
    source_repositories: list[str]
    generated_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "evidence_classification": self.evidence_classification,
            "source_repositories": self.source_repositories,
            "generated_at": self.generated_at,
        }


class AgenticProductSurfacesService:
    """Tenant-scoped read model for agentic Profile/Journey/Campaign surfaces."""

    def __init__(
        self,
        *,
        activities: AgentActivityRepository | None = None,
        connections: AgentConnectionRepository | None = None,
        tools: AgentToolRepository | None = None,
        accounts: ExternalAccountRepository | None = None,
        risks: AgentRiskSignalRepository | None = None,
        silver_activities: SilverAgentActivityFactRepository | None = None,
        silver_connections: SilverMCPConnectionFactRepository | None = None,
        silver_tools: SilverAgentToolInvocationFactRepository | None = None,
        silver_risks: SilverAgentRiskFactRepository | None = None,
        canonical_activity: ActivityRepository | None = None,
    ) -> None:
        self.activities = activities or AgentActivityRepository()
        self.connections = connections or AgentConnectionRepository()
        self.tools = tools or AgentToolRepository()
        self.accounts = accounts or ExternalAccountRepository()
        self.risks = risks or AgentRiskSignalRepository()
        self.silver_activities = silver_activities or SilverAgentActivityFactRepository()
        self.silver_connections = silver_connections or SilverMCPConnectionFactRepository()
        self.silver_tools = silver_tools or SilverAgentToolInvocationFactRepository()
        self.silver_risks = silver_risks or SilverAgentRiskFactRepository()
        self.canonical_activity = canonical_activity or ActivityRepository()

    async def agent_profile360(self, *, tenant_id: str, agent_id: str, limit: int = 25) -> dict[str, Any]:
        """Build Agent Profile 360 evidence from observed agentic telemetry."""
        filters = {"tenant_id": tenant_id, "agent_id": agent_id}
        activity_rows = await self._rows_for_agent(self.activities, tenant_id, agent_id, limit)
        activity_rows += await self._rows(self.silver_activities, filters, limit)
        connection_rows = await self._rows(self.connections, filters, limit)
        connection_rows += await self._rows(self.silver_connections, filters, limit)
        tool_rows = await self._rows(self.tools, filters, limit)
        tool_rows += await self._rows(self.silver_tools, filters, limit)
        account_rows = await self._rows(self.accounts, filters, limit)
        risk_rows = await self._rows(self.risks, filters, limit)
        risk_rows += await self._rows(self.silver_risks, filters, limit)
        canonical_rows = await self.canonical_activity.list_agentic_by_agent(tenant_id, agent_id, limit=limit)

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "profile_type": "agent_profile_360",
            "counts": {
                "activities": len(activity_rows),
                "mcp_connections": len(connection_rows),
                "tools": len(tool_rows),
                "external_accounts_or_grants": len(account_rows),
                "risk_signals": len(risk_rows),
                "canonical_activities": len(canonical_rows),
            },
            "evidence": {
                "activities": self._classified(activity_rows, "observed_fact"),
                "mcp_connections": self._classified(connection_rows, "observed_fact"),
                "tools": self._provider_classified(tool_rows),
                "external_accounts_or_grants": self._classified(account_rows, "observed_fact"),
                "risk_signals": self._classified(risk_rows, "recommendation"),
                "canonical_activities": self._classified(canonical_rows, "observed_fact"),
            },
            "surface_evidence": self._surface_evidence(
                "agent_profile360",
                [
                    "obs_agent_activities",
                    "obs_agent_connections",
                    "obs_agent_tools",
                    "obs_external_accounts",
                    "obs_agent_risk_signals",
                    "canonical_activity",
                    "silver_agent_*_facts",
                ],
            ),
        }

    async def journey_v2_agentic_steps(self, *, tenant_id: str, agent_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Return Unified Journey v2-compatible observed agentic steps."""
        rows = await self.canonical_activity.list_agentic_steps(tenant_id, agent_id=agent_id, limit=limit)
        steps = [
            {
                "step_id": str(row.get("activity_id") or row.get("idempotency_key") or row.get("source_event_id")),
                "tenant_id": row.get("tenant_id"),
                "agent_id": row.get("agent_id"),
                "campaign_id": row.get("campaign_id"),
                "activity_type": row.get("activity_type"),
                "activity_status": row.get("activity_status"),
                "occurred_at": row.get("occurred_at"),
                "source_event_id": row.get("source_event_id"),
                "silver_fact_id": row.get("silver_fact_id"),
                "silver_table": row.get("silver_table"),
                "evidence_classification": "observed_fact",
            }
            for row in rows
        ]
        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "journey_version": "v2",
            "steps": steps,
            "count": len(steps),
            "surface_evidence": self._surface_evidence("journey_v2_agentic_steps", ["canonical_activity"]),
        }

    async def campaign_agentic_influence(self, *, tenant_id: str, campaign_id: str, limit: int = 50) -> dict[str, Any]:
        """Summarize agent-generated campaign touchpoints from canonical activity."""
        rows = await self.canonical_activity.list_agentic_by_campaign(tenant_id, campaign_id, limit=limit)
        agents = sorted({str(row.get("agent_id")) for row in rows if row.get("agent_id")})
        activity_types = sorted({str(row.get("activity_type")) for row in rows if row.get("activity_type")})
        return {
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "agentic_touchpoint_count": len(rows),
            "agent_ids": agents,
            "activity_types": activity_types,
            "touchpoints": self._classified(rows, "observed_fact"),
            "attribution_status": "eligible_for_modeling" if rows else "insufficient_evidence",
            "surface_evidence": self._surface_evidence("campaign_agentic_influence", ["canonical_activity"]),
        }

    async def _rows(self, repo: Any, filters: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        return await repo.find_many(filters=filters, limit=limit)

    async def _rows_for_agent(self, repo: Any, tenant_id: str, agent_id: str, limit: int) -> list[dict[str, Any]]:
        direct = await repo.find_many(filters={"tenant_id": tenant_id, "agent_id": agent_id}, limit=limit)
        if direct:
            return direct
        rows = await repo.find_many(filters={"tenant_id": tenant_id}, limit=max(limit * 5, 100))
        return [
            row for row in rows
            if row.get("agent_id") == agent_id
            or row.get("actor", {}).get("actor_id") == agent_id
            or row.get("agent", {}).get("agent_id") == agent_id
        ][:limit]

    def _classified(self, rows: list[dict[str, Any]], classification: str) -> list[dict[str, Any]]:
        return [{"evidence_classification": classification, **row} for row in rows]

    def _provider_classified(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        classified: list[dict[str, Any]] = []
        for row in rows:
            status = str(row.get("verification_status") or row.get("verification", {}).get("verification_status") or "").lower()
            classification = "provider_confirmed_fact" if status in {"provider_confirmed", "confirmed", "provider_contradicted", "contradicted"} else "observed_fact"
            classified.append({"evidence_classification": classification, **row})
        return classified

    def _surface_evidence(self, surface: str, source_repositories: list[str]) -> dict[str, Any]:
        return AgenticSurfaceEvidence(
            surface=surface,
            evidence_classification="deterministic_computation",
            source_repositories=source_repositories,
            generated_at=utc_now().isoformat(),
        ).as_dict()
