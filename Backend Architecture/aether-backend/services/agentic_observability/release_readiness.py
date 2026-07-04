"""Agentic Intelligence release-readiness gate.

This module is intentionally conservative: it prevents AETHER from reporting the
Agentic Intelligence program as GA-ready until every required product,
security, privacy, operational, and end-to-end proof area is implemented and
validated. It is read-only and never executes provider actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ReleaseCapability:
    capability: str
    owner_area: str
    status: str
    required_evidence: tuple[str, ...]
    implemented_evidence: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status == "complete" and not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "owner_area": self.owner_area,
            "status": self.status,
            "complete": self.complete,
            "required_evidence": list(self.required_evidence),
            "implemented_evidence": list(self.implemented_evidence),
            "blockers": list(self.blockers),
        }


class AgenticReleaseReadinessService:
    """Read-only GA certification matrix for Agentic Intelligence."""

    release_gate = "internal_preview"

    def capabilities(self) -> list[ReleaseCapability]:
        return [
            ReleaseCapability(
                capability="canonical_ingestion_and_outbox",
                owner_area="backend_data_pipeline",
                status="partial",
                required_evidence=(
                    "all agentic compatibility routes use Bronze->Silver->canonical_activity->outbox",
                    "replay is idempotent across tenant, event, time range, provider, connection, and dead-letter scopes",
                    "reconciliation detects every missing stage required by the release scenario",
                ),
                implemented_evidence=(
                    "generic agent events create Bronze, typed Silver, canonical_activity, and graph outbox rows",
                    "Kyber pipeline health, lineage, and read-only reconciliation diagnostics exist",
                ),
                blockers=(
                    "replay workflows are not productized",
                    "all compatibility endpoints have not been proven through the canonical pipeline",
                ),
            ),
            ReleaseCapability(
                capability="mcp_gateway_middleware_and_proxy",
                owner_area="sdk_mcp_platform",
                status="missing",
                required_evidence=(
                    "TypeScript and Python MCP middleware cover initialize, tools/list, tools/call, resources, prompts, cancellation, progress, reconnect, disconnect, and errors",
                    "remote MCP gateway preserves MCP semantics with TLS/auth passthrough and tenant isolation",
                    "local stdio proxy manages process lifecycle and redacts secrets",
                ),
                blockers=("no production MCP gateway, middleware parity suite, or stdio proxy is present",),
            ),
            ReleaseCapability(
                capability="provider_connector_lifecycle",
                owner_area="connectors_security",
                status="partial",
                required_evidence=(
                    "durable provider registry and authorization registry exist",
                    "X connector supports account connection, scope lifecycle, webhook/API verification, backfill, reconciliation, and deletion propagation",
                    "provider truth hierarchy and contradiction precedence are enforced durably",
                ),
                implemented_evidence=(
                    "provider-neutral adapter protocol, X reference normalization, verification state enum, permission findings, and read-only boundary are present",
                ),
                blockers=(
                    "no durable OAuth/account lifecycle registry is complete",
                    "X connector is a read-only reference adapter rather than a production connector lifecycle",
                ),
            ),
            ReleaseCapability(
                capability="delegated_authority_graph",
                owner_area="graph_intelligence",
                status="partial",
                required_evidence=(
                    "actor, topology, authorization, evidence, and economic/outcome graph planes are implemented",
                    "temporal authorization and connection edges support historical queries",
                    "risk signals and path intelligence are evidence-backed and tenant-isolated",
                ),
                implemented_evidence=("provider-neutral graph projection helper records and outbox projection foundation exist",),
                blockers=("complete delegated-authority entity/edge model, temporal queries, identity merge/split, and risk engine are not complete",),
            ),
            ReleaseCapability(
                capability="profiles_journeys_clusters_campaigns_outcomes",
                owner_area="product_intelligence_surfaces",
                status="missing",
                required_evidence=(
                    "Human, Organization, and Agent Profile 360 consume agentic evidence",
                    "Journey v2 includes first-class agentic steps and transitions",
                    "Cluster360, campaign attribution, outcomes, and exports include tenant-safe agentic evidence",
                ),
                blockers=("agentic data is not fully propagated to Profile 360, Journey v2, Cluster360, campaign, outcome, and export surfaces",),
            ),
            ReleaseCapability(
                capability="noesis_agentic_intelligence",
                owner_area="noesis",
                status="partial",
                required_evidence=(
                    "all required agentic query families are implemented",
                    "every claim is labeled as observed fact, provider-confirmed fact, deterministic computation, probabilistic inference, recommendation, or insufficient evidence",
                    "unsupported claims and unsupported causality are refused",
                ),
                implemented_evidence=("deterministic read-only adapter and initial intent registration exist",),
                blockers=("full evidence paths, historical comparison, contradiction explanation, and unsupported-claim refusal are not fully proven",),
            ),
            ReleaseCapability(
                capability="kyber_frontend_onboarding_alerts",
                owner_area="operator_and_tenant_product",
                status="missing",
                required_evidence=(
                    "Kyber command center supports fleet overview, tenant drill-down, lineage, replay, rebuild, reconcile, quarantine, audit package export, and RBAC",
                    "tenant frontend supports integrations, agent fleet, detail, permission center, activity explorer, MCP topology, alerts, and onboarding",
                    "health and alerting cover SDK, gateway, MCP, provider, queues, graph, journey, profile, and reconciliation",
                ),
                blockers=("complete Kyber command center, tenant frontend, onboarding, and alert workflows are not implemented",),
            ),
            ReleaseCapability(
                capability="security_privacy_billing_rollout",
                owner_area="governance_release",
                status="missing",
                required_evidence=(
                    "static no-execution import/dependency checks and secret scanners are CI-gated",
                    "consent, retention, DSR export/deletion, graph tombstoning, and evidence redaction work end-to-end",
                    "agentic meters, entitlements, rollout controls, emergency disable, performance tests, chaos tests, and release certification are complete",
                ),
                blockers=("security hardening, privacy lifecycle, billing, rollout, load/chaos, and GA certification are not complete",),
            ),
            ReleaseCapability(
                capability="release_level_end_to_end_scenario",
                owner_area="quality_release",
                status="missing",
                required_evidence=(
                    "39-step product scenario passes from human/org through agent, MCP, provider verification, graph, journey, profiles, cluster, campaign, outcome, Noesis, Kyber, revocation, DSR, replay, outage, cross-tenant isolation, and no-execution proof",
                ),
                blockers=("release-level automated E2E scenario is not implemented",),
            ),
        ]

    def readiness(self) -> dict[str, Any]:
        capabilities = self.capabilities()
        blockers = [
            {"capability": item.capability, "blockers": list(item.blockers)}
            for item in capabilities
            if item.blockers
        ]
        complete_count = sum(1 for item in capabilities if item.complete)
        return {
            "product": "aether_agentic_intelligence",
            "release_gate": self.release_gate,
            "ga_ready": complete_count == len(capabilities),
            "complete_capabilities": complete_count,
            "total_capabilities": len(capabilities),
            "capabilities": [item.as_dict() for item in capabilities],
            "blockers": blockers,
            "next_required_gate": "design_partner_ready" if not blockers else "close_blockers_before_design_partner",
        }
