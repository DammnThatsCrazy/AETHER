"""Read-only Agentic Intelligence adapter for Noesis.

The adapter only reads existing observation repositories and emits evidence
labels. It does not execute provider actions, mutate grants, revoke access, or
write graph state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

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
from shared.common.common import utc_now

AGENTIC_EVIDENCE_CLASSIFICATIONS: tuple[str, ...] = (
    "observed_fact",
    "provider_confirmed_fact",
    "deterministic_computation",
    "probabilistic_inference",
    "recommendation",
    "insufficient_evidence",
)


@dataclass(slots=True)
class AgenticNoesisAnswer:
    answer: str
    results: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    warnings: list[str]


class AgenticIntelligenceAdapter:
    """Repository-backed agentic answer builder for deterministic Noesis intents."""

    def __init__(
        self,
        *,
        activities: AgentActivityRepository | None = None,
        connections: AgentConnectionRepository | None = None,
        tools: AgentToolRepository | None = None,
        external_accounts: ExternalAccountRepository | None = None,
        risks: AgentRiskSignalRepository | None = None,
        silver_activities: SilverAgentActivityFactRepository | None = None,
        silver_connections: SilverMCPConnectionFactRepository | None = None,
        silver_tools: SilverAgentToolInvocationFactRepository | None = None,
        silver_risks: SilverAgentRiskFactRepository | None = None,
    ) -> None:
        self.activities = activities or AgentActivityRepository()
        self.connections = connections or AgentConnectionRepository()
        self.tools = tools or AgentToolRepository()
        self.external_accounts = external_accounts or ExternalAccountRepository()
        self.risks = risks or AgentRiskSignalRepository()
        self.silver_activities = silver_activities or SilverAgentActivityFactRepository()
        self.silver_connections = silver_connections or SilverMCPConnectionFactRepository()
        self.silver_tools = silver_tools or SilverAgentToolInvocationFactRepository()
        self.silver_risks = silver_risks or SilverAgentRiskFactRepository()

    async def answer(self, *, intent: str, tenant_id: str, target: str | None = None, limit: int = 10) -> AgenticNoesisAnswer:
        filters = {"tenant_id": tenant_id}
        fetched_at = utc_now()
        rows: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        warnings: list[str] = []

        if intent == "agent_inventory_lookup":
            activities = await self.activities.find_many(filters=filters, limit=max(limit * 5, 25))
            silver = await self.silver_activities.find_many(filters=filters, limit=max(limit * 5, 25))
            rows = self._dedupe_agents(activities + silver)[:limit]
            sources.extend(self._sources(fetched_at, "agent_activity_repository", "silver_agent_activity_facts"))
            claims.append(self._claim("Agent inventory is computed from observed activity facts.", "deterministic_computation", bool(rows)))
            answer = f"Found {len(rows)} observed agents in tenant scope."
        elif intent in ("agent_activity_lookup", "agent_path_lookup"):
            rows = await self.activities.find_many(filters=filters, limit=limit)
            if not rows:
                rows = await self.silver_activities.find_many(filters=filters, limit=limit)
            rows = self._filter_target(rows, target)
            sources.extend(self._sources(fetched_at, "agent_activity_repository", "silver_agent_activity_facts"))
            claims.append(self._claim("Agent activity is an observed fact from stored telemetry.", "observed_fact", bool(rows)))
            answer = f"Found {len(rows)} observed agent activity records."
        elif intent == "mcp_topology_lookup":
            rows = await self.connections.find_many(filters=filters, limit=limit)
            if not rows:
                rows = await self.silver_connections.find_many(filters=filters, limit=limit)
            rows = self._filter_target(rows, target)
            sources.extend(self._sources(fetched_at, "agent_connection_repository", "silver_mcp_connection_facts"))
            claims.append(self._claim("MCP topology is based on observed connection facts.", "observed_fact", bool(rows)))
            answer = f"Found {len(rows)} MCP connection/topology records."
        elif intent == "authorization_lookup":
            rows = await self.external_accounts.find_many(filters=filters, limit=limit)
            rows = self._filter_target(rows, target)
            sources.extend(self._sources(fetched_at, "external_account_repository"))
            claims.append(self._claim("Authorization/account access is based on observed account records.", "observed_fact", bool(rows)))
            answer = f"Found {len(rows)} observed external account or grant records."
        elif intent in ("provider_verification_lookup", "verification_mismatch_lookup"):
            tool_rows = await self.tools.find_many(filters=filters, limit=max(limit * 5, 25))
            silver_rows = await self.silver_tools.find_many(filters=filters, limit=max(limit * 5, 25))
            rows = self._provider_rows(tool_rows + silver_rows, mismatches_only=intent == "verification_mismatch_lookup")[:limit]
            sources.extend(self._sources(fetched_at, "agent_tool_repository", "silver_agent_tool_invocation_facts"))
            claim_text = "Provider verification facts prefer provider-confirmed evidence over runtime observations."
            claims.append(self._claim(claim_text, "provider_confirmed_fact" if rows else "insufficient_evidence", bool(rows)))
            answer = f"Found {len(rows)} provider verification records."
        elif intent == "permission_risk_lookup":
            rows = await self.risks.find_many(filters=filters, limit=limit)
            if not rows:
                rows = await self.silver_risks.find_many(filters=filters, limit=limit)
            rows = self._filter_target(rows, target)
            sources.extend(self._sources(fetched_at, "agent_risk_signal_repository", "silver_agent_risk_facts"))
            claims.append(self._claim("Permission risk records are recommendations backed by observation evidence.", "recommendation", bool(rows)))
            answer = f"Found {len(rows)} permission or agentic risk findings."
        else:
            warnings.append(f"Unsupported agentic Noesis intent: {intent}")
            claims.append(self._claim("No supported agentic evidence was available for this request.", "insufficient_evidence", False))
            answer = "I do not have enough supported agentic evidence to answer that request."

        if not rows:
            warnings.append("No tenant-scoped agentic evidence matched the request.")
        return AgenticNoesisAnswer(answer=answer, results=rows[:limit], claims=claims, sources=sources, warnings=warnings)

    def _sources(self, fetched_at: Any, *services: str) -> list[dict[str, Any]]:
        return [{"service": service, "resource_type": "agentic_observation", "fetched_at": fetched_at} for service in services]

    def _claim(self, claim: str, classification: str, sufficient: bool) -> dict[str, Any]:
        if classification not in AGENTIC_EVIDENCE_CLASSIFICATIONS:
            raise ValueError(f"unsupported agentic evidence classification: {classification}")
        return {
            "claim": claim,
            "classification": classification,
            "claim_type": self._claim_type(classification),
            "confidence": 0.9 if sufficient else 0.2,
        }

    def _claim_type(self, classification: str) -> str:
        return {
            "observed_fact": "fact",
            "provider_confirmed_fact": "fact",
            "deterministic_computation": "computation",
            "probabilistic_inference": "inference",
            "recommendation": "recommendation",
            "insufficient_evidence": "inference",
        }[classification]

    def _dedupe_agents(self, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        agents: list[dict[str, Any]] = []
        for row in rows:
            agent_id = str(row.get("agent_id") or row.get("agent", {}).get("agent_id") or row.get("id") or "")
            if not agent_id or agent_id in seen:
                continue
            seen.add(agent_id)
            agents.append({"agent_id": agent_id, "evidence_classification": "observed_fact", **dict(row)})
        return agents

    def _filter_target(self, rows: list[dict[str, Any]], target: str | None) -> list[dict[str, Any]]:
        if not target:
            return [self._with_classification(row, "observed_fact") for row in rows]
        needle = target.lower()
        return [self._with_classification(row, "observed_fact") for row in rows if needle in str(row).lower()]

    def _provider_rows(self, rows: list[dict[str, Any]], *, mismatches_only: bool) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in rows:
            status = str(row.get("verification_status") or row.get("verification", {}).get("verification_status") or "").lower()
            if mismatches_only and status not in {"contradicted", "mismatch", "provider_contradicted"}:
                continue
            classification = "provider_confirmed_fact" if status == "provider_confirmed" else "observed_fact"
            if status in {"contradicted", "mismatch", "provider_contradicted"}:
                classification = "provider_confirmed_fact"
            results.append(self._with_classification(row, classification))
        return results

    def _with_classification(self, row: Mapping[str, Any], classification: str) -> dict[str, Any]:
        return {"evidence_classification": classification, **dict(row)}
