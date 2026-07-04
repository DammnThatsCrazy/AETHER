"""
Agentic Release Readiness Service — GA certification matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReleaseCapability:
    name: str
    status: str
    description: str
    blockers: list[str] = field(default_factory=list)
    completed_items: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.status == "complete" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "complete": self.complete,
            "description": self.description,
            "blockers": list(self.blockers),
            "completed_items": list(self.completed_items),
        }


class AgenticReleaseReadinessService:
    def capabilities(self) -> list[ReleaseCapability]:
        return [
            ReleaseCapability(
                name="canonical_ingestion_and_outbox",
                status="partial",
                description="Bronze→Silver→CanonicalActivity→ProjectionOutbox medallion pipeline",
                completed_items=[
                    "AgenticIngestionPipeline implemented",
                    "Bronze write via AgenticBronzeObservationRepository",
                    "Silver fact dispatch by event name",
                    "CanonicalActivity write via ActivityRepository.upsert",
                    "Outbox enqueue per graph mutation",
                    "AgenticGraphOutboxWorker with retry/backoff/dead-letter",
                    "Pipeline: _sanitize redacts sensitive keys before Bronze write",
                ],
                blockers=[
                    "Replay workflows for failed Bronze records not implemented",
                    "Compatibility endpoint coverage for v1→v2 event envelope not verified",
                ],
            ),
            ReleaseCapability(
                name="mcp_gateway_middleware_and_proxy",
                status="missing",
                description="Production MCP gateway, parity suite, and stdio proxy",
                completed_items=[
                    "MCP connection observation endpoint (/v1/observability/agent/mcp)",
                    "MCPConnectionObserved model",
                    "AgentConnectionRepository storage",
                    "MCPObservationContext v2 context field on AgenticObservationRecord",
                ],
                blockers=[
                    "No production MCP gateway implemented",
                    "No MCP parity test suite",
                    "No stdio proxy implementation",
                    "No MCP middleware for request/response interception",
                ],
            ),
            ReleaseCapability(
                name="provider_connector_lifecycle",
                status="partial",
                description="Durable OAuth/account lifecycle registry; provider adapters",
                completed_items=[
                    "XReferenceAdapter implemented (read-only)",
                    "ProviderRegistry singleton with X adapter registered",
                    "AuthorizationGrantRecord, ExternalAccountRecord models",
                    "AuthorizationContext v2 field on AgenticObservationRecord",
                    "VerificationContext v2 field on AgenticObservationRecord",
                    "compute_permission_findings: write_scope_unused, expired_grant, revoked_grant_used, unexpected_new_scope",
                    "build_provider_graph_projection without writing",
                ],
                blockers=[
                    "No durable OAuth/account lifecycle registry",
                    "X connector is read-only reference only — no production provider",
                    "No account refresh/revocation lifecycle management",
                ],
            ),
            ReleaseCapability(
                name="delegated_authority_graph",
                status="partial",
                description="Entity/edge model, temporal queries, identity merge/split, risk engine",
                completed_items=[
                    "Graph mutation outbox pattern implemented",
                    "AgenticProjectionOutboxRepository persists mutations",
                    "AgenticGraphOutboxWorker projects vertex/edge into graph",
                    "build_provider_graph_projection defines entity model",
                ],
                blockers=[
                    "No temporal graph query engine",
                    "No identity merge/split resolution",
                    "No delegated authority risk scoring engine beyond basic signals",
                    "No entity deduplication across providers",
                ],
            ),
            ReleaseCapability(
                name="profiles_journeys_clusters_campaigns_outcomes",
                status="partial",
                description="Agent Profile 360, Journey v2 agentic steps, Campaign influence",
                completed_items=[
                    "agent_profile360 assembles from 9 repos (5 obs + 4 silver + canonical)",
                    "journey_v2_agentic_steps reads canonical_activity.list_agentic_steps",
                    "campaign_agentic_influence reads canonical_activity.list_agentic_by_campaign",
                    "Evidence classification: observed_fact vs provider_confirmed_fact",
                ],
                blockers=[
                    "No Human/Org/Cluster360 integration for agentic overlay",
                    "Attribution execution for agent-mediated conversions not proven",
                    "No outcome modeling for agentic journeys",
                    "No export/bulk-read API for Profile360",
                ],
            ),
            ReleaseCapability(
                name="noesis_agentic_intelligence",
                status="partial",
                description="Deterministic intent routing for agentic intelligence queries",
                completed_items=[
                    "AgenticIntelligenceAdapter with 11 deterministic intents",
                    "agent_inventory_lookup, agent_activity_lookup, agent_path_lookup",
                    "mcp_topology_lookup, authorization_lookup",
                    "provider_verification_lookup, verification_mismatch_lookup",
                    "permission_risk_lookup, agent_profile360_lookup",
                    "journey_agentic_steps_lookup, campaign_agentic_influence_lookup",
                    "Unknown intent → insufficient_evidence classification",
                    "All claims validated against AGENTIC_EVIDENCE_CLASSIFICATIONS",
                ],
                blockers=[
                    "Historical comparison across time windows not implemented",
                    "Contradiction explanation for verification mismatches not proven across all query families",
                    "Unsupported-causality refusal not tested beyond unknown intent path",
                ],
            ),
            ReleaseCapability(
                name="kyber_frontend_onboarding_alerts",
                status="partial",
                description="Kyber operator UI, alert workflows, tenant onboarding",
                completed_items=[
                    "Kyber admin read endpoints: /v1/admin/kyber/agentic-observability/{overview,agents/{id},risk}",
                    "AgentRiskSignalRepository persists risk signals",
                    "Risk signal observation endpoint (/v1/observability/agent/risk-signals)",
                ],
                blockers=[
                    "No UI flows for agent monitoring",
                    "No alert workflow engine for risk signal escalation",
                    "No quarantine/rebuild flows",
                    "No RBAC-specific flows for tenant admin vs. operator",
                    "No onboarding wizard for tenant agent registration",
                ],
            ),
            ReleaseCapability(
                name="security_privacy_billing_rollout",
                status="partial",
                description="CI-gated security scanning, DSR, usage metering, rollout controls",
                completed_items=[
                    "DSR preview and export via AgenticGovernanceService",
                    "Usage metering across all observation tables",
                    "Rollout controls reading AgenticObservabilityConfig feature flags",
                    "Security and privacy controls summary",
                    "Operator audit package assembler",
                    "Release candidate evidence package",
                    "_SENSITIVE_KEYS redaction in ingestion pipeline",
                    "PrivacyContext v2 field on AgenticObservationRecord",
                ],
                blockers=[
                    "No CI-gated static security scanning",
                    "No graph tombstone execution for DSR",
                    "No performance/chaos gate certification",
                    "No GA certification report generated by CI",
                ],
            ),
            ReleaseCapability(
                name="release_level_end_to_end_scenario",
                status="partial",
                description="Full 39-step E2E scenario covering all surfaces",
                completed_items=[
                    "Backend pipeline verified: observe → bronze → silver → canonical → outbox",
                    "Risk signal evaluation and merge",
                    "Kyber admin read coverage",
                    "Noesis adapter integration",
                    "Governance DSR and metering integration",
                    "Provider framework HMAC webhook validation",
                    "Contract v2 envelope with runtime/correlation/mcp/authorization/verification/privacy",
                ],
                blockers=[
                    "Frontend flows not verified",
                    "Authorization revocation E2E not tested",
                    "Replay repair workflow not demonstrated",
                    "Outage drill scenarios not documented",
                    "Cluster360 integration not verified",
                    "Cross-tenant browser isolation flows not verified",
                ],
            ),
        ]

    def readiness(self) -> dict[str, Any]:
        caps = self.capabilities()
        complete_count = sum(1 for c in caps if c.complete)
        all_blockers = [b for c in caps for b in c.blockers]
        return {
            "release_gate": "internal_preview",
            "ga_ready": False,
            "capabilities_total": len(caps),
            "capabilities_complete": complete_count,
            "capabilities_partial": sum(1 for c in caps if c.status == "partial"),
            "capabilities_missing": sum(1 for c in caps if c.status == "missing"),
            "blocker_count": len(all_blockers),
            "capabilities": [c.as_dict() for c in caps],
        }
