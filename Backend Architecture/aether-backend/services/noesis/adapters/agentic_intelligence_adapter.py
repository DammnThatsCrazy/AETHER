"""
Noesis Agentic Intelligence Adapter — deterministic intent routing for agentic read-only queries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from repositories.agentic_observability_repos import (
    AgentActivityRepository,
    AgentConnectionRepository,
    AgentRiskSignalRepository,
    AgentToolRepository,
    ExternalAccountRepository,
)
from services.agentic_observability.product_surfaces import AgenticProductSurfacesService
from services.agentic_observability.reconciliation import AgenticReconciliationService
from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.agentic_intelligence")

AGENTIC_EVIDENCE_CLASSIFICATIONS = (
    "observed_fact",
    "provider_confirmed_fact",
    "provider_unverified_fact",
    "reconciled_fact",
    "inferred",
    "insufficient_evidence",
)


@dataclass
class AgenticNoesisAnswer:
    intent: str
    answer: str
    results: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _claim(text: str, classification: str, sufficient: bool = True) -> dict[str, Any]:
    assert classification in AGENTIC_EVIDENCE_CLASSIFICATIONS, (
        f"Invalid classification {classification!r}"
    )
    return {"text": text, "classification": classification, "sufficient": sufficient}


class AgenticIntelligenceAdapter:
    def __init__(self) -> None:
        self._activity_repo = AgentActivityRepository()
        self._connection_repo = AgentConnectionRepository()
        self._tool_repo = AgentToolRepository()
        self._risk_repo = AgentRiskSignalRepository()
        self._account_repo = ExternalAccountRepository()
        self._surfaces = AgenticProductSurfacesService()
        self._reconcile = AgenticReconciliationService()

    async def answer(
        self,
        intent: str,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 100,
    ) -> AgenticNoesisAnswer:
        if intent == "agent_inventory_lookup":
            rows = await self._activity_repo.find_many(
                filters={"tenant_id": tenant_id}, limit=limit
            )
            agent_ids = list({r.get("agent_id") for r in rows if r.get("agent_id")})
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(agent_ids)} distinct agents for tenant {tenant_id}",
                results=[{"agent_id": a} for a in agent_ids],
                claims=[_claim(f"{len(agent_ids)} agents observed", "observed_fact")],
                sources=["obs_agent_activities"],
            )

        if intent == "agent_activity_lookup":
            filters: dict[str, Any] = {"tenant_id": tenant_id}
            if target:
                filters["agent_id"] = target
            rows = await self._activity_repo.find_many(filters=filters, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(rows)} activity records",
                results=rows,
                claims=[_claim(f"{len(rows)} observed activities", "observed_fact")],
                sources=["obs_agent_activities"],
            )

        if intent == "agent_path_lookup":
            filters = {"tenant_id": tenant_id}
            if target:
                filters["agent_id"] = target
            rows = await self._activity_repo.find_many(filters=filters, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Activity path: {len(rows)} steps for agent {target or 'all'}",
                results=rows,
                claims=[_claim(f"{len(rows)} observed steps in path", "observed_fact")],
                sources=["obs_agent_activities"],
            )

        if intent == "mcp_topology_lookup":
            filters = {"tenant_id": tenant_id}
            if target:
                filters["agent_id"] = target
            rows = await self._connection_repo.find_many(filters=filters, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(rows)} MCP connections",
                results=rows,
                claims=[_claim(f"{len(rows)} MCP connections observed", "observed_fact")],
                sources=["obs_agent_connections"],
            )

        if intent == "authorization_lookup":
            rows = await self._account_repo.find_many(
                filters={"tenant_id": tenant_id}, limit=limit
            )
            filtered = [r for r in rows if not target or r.get("agent_id") == target]
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(filtered)} authorization records",
                results=filtered,
                claims=[_claim(f"{len(filtered)} account/authorization observations", "observed_fact")],
                sources=["obs_external_accounts"],
            )

        if intent == "provider_verification_lookup":
            rows = await self._activity_repo.find_many(
                filters={"tenant_id": tenant_id}, limit=limit
            )
            verified = [
                r for r in rows
                if isinstance(r.get("risk"), dict) and r["risk"].get("requires_review") is False
            ]
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(verified)} provider-verified observations",
                results=verified,
                claims=[_claim(f"{len(verified)} provider-verified records", "provider_confirmed_fact")],
                sources=["obs_agent_activities"],
            )

        if intent == "verification_mismatch_lookup":
            rows = await self._activity_repo.find_many(
                filters={"tenant_id": tenant_id}, limit=limit
            )
            mismatches = [
                r for r in rows
                if isinstance(r.get("risk"), dict) and r["risk"].get("requires_review") is True
            ]
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(mismatches)} verification mismatches requiring review",
                results=mismatches,
                claims=[_claim(f"{len(mismatches)} observations flagged for review", "observed_fact")],
                sources=["obs_agent_activities"],
            )

        if intent == "permission_risk_lookup":
            filters = {"tenant_id": tenant_id}
            if target:
                filters["agent_id"] = target
            risk_rows = await self._risk_repo.find_many(filters=filters, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Found {len(risk_rows)} risk signals",
                results=risk_rows,
                claims=[_claim(f"{len(risk_rows)} permission risk signals observed", "observed_fact")],
                sources=["obs_agent_risk_signals"],
            )

        if intent == "agent_profile360_lookup":
            if not target:
                return AgenticNoesisAnswer(
                    intent=intent,
                    answer="agent_id is required for profile360 lookup",
                    warnings=["Missing target agent_id"],
                    claims=[_claim("No agent_id provided", "insufficient_evidence", sufficient=False)],
                )
            profile = await self._surfaces.agent_profile360(tenant_id, target, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Agent Profile 360 for {target}",
                results=[profile],
                claims=[_claim("Profile assembled from observed facts", "observed_fact")],
                sources=["obs_agent_activities", "obs_external_accounts", "silver_agent_activity_facts"],
            )

        if intent == "journey_agentic_steps_lookup":
            if not target:
                return AgenticNoesisAnswer(
                    intent=intent,
                    answer="agent_id is required for journey steps lookup",
                    warnings=["Missing target agent_id"],
                    claims=[_claim("No agent_id provided", "insufficient_evidence", sufficient=False)],
                )
            journey = await self._surfaces.journey_v2_agentic_steps(tenant_id, target, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Journey steps for agent {target}: {journey['step_count']} steps",
                results=[journey],
                claims=[
                    _claim(
                        f"{journey['step_count']} agentic steps in canonical activity",
                        "reconciled_fact",
                    )
                ],
                sources=["canonical_activity"],
            )

        if intent == "campaign_agentic_influence_lookup":
            if not target:
                return AgenticNoesisAnswer(
                    intent=intent,
                    answer="campaign_id is required for campaign influence lookup",
                    warnings=["Missing target campaign_id"],
                    claims=[_claim("No campaign_id provided", "insufficient_evidence", sufficient=False)],
                )
            influence = await self._surfaces.campaign_agentic_influence(tenant_id, target, limit=limit)
            return AgenticNoesisAnswer(
                intent=intent,
                answer=f"Campaign agentic influence for {target}: {influence['agentic_step_count']} steps",
                results=[influence],
                claims=[
                    _claim(
                        f"{influence['agentic_step_count']} agentic steps attributed to campaign",
                        "reconciled_fact",
                    )
                ],
                sources=["canonical_activity"],
            )

        return AgenticNoesisAnswer(
            intent=intent,
            answer=f"Intent {intent!r} is not supported by the agentic intelligence adapter",
            warnings=[f"Unsupported intent: {intent}"],
            claims=[_claim(f"Intent {intent!r} not recognized", "insufficient_evidence", sufficient=False)],
        )
