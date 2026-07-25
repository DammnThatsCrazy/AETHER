"""Kyber Graph — typed records for the operational graph-of-systems.

The Kyber Graph is platform topology, not a copy of tenant data. It stores how
the platform is wired — services, features, releases, tenants-as-nodes, graph
domains, incidents, commands, policies, costs — and *references* into tenant
data rather than the data itself. Detailed tenant entities stay in the tenant's
own graph and are reachable only through
:mod:`services.kyber.graph.scoped_gateway`, which requires an active
purpose-bound scope.

That boundary is the whole design. Merging every tenant's entities into one
global graph would make tenant isolation a query-time filter, and a filter is
exactly what produced the truncation defect this plane exists to avoid.

Storage is projection tables plus a repository, not a third ``GraphClient``
backend. ``GraphClient`` has no Protocol — a closed ``Optional[A | B]`` union
with ``isinstance`` branches in ``k_hop_neighbors`` and the mutation gateway —
so a third backend is a refactor of that module and its consumers.
``services/agent_access_intelligence/access_graph.py`` faced the same choice
and settled it the same way.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now

# ── Node and edge vocabulary ─────────────────────────────────────────────────
#
# Deliberately finite. Every type here is something an operator can act on or
# trace through; anything high-cardinality (events, individual profiles, orders)
# stays out and is reached through the scoped tenant gateway instead.

KyberNodeType = Literal[
    # Workforce
    "WorkforcePrincipal", "RoleBinding", "TrustedDevice", "KyberSession",
    "AccessScope", "AccessDecision",
    # Platform
    "OlympusPlatform", "Environment", "Region", "DeploymentProfile", "Service",
    "WorkerRole", "Release", "Deployment",
    # Tenant topology — the TENANT as a node, never its contents
    "Tenant", "TenantGraph", "GraphDomain", "FeatureEntitlement", "Connector",
    "SDKInstallation", "Import", "Dataset",
    # Product surfaces
    "FeatureSurface", "MeasurementDefinition", "Projection", "ModelDeployment",
    "HealthState",
    # Operations
    "Alert", "Incident", "Investigation", "CommandRequest", "CommandExecution",
    "Approval", "Verification", "Runbook",
    # Governance
    "Policy", "ConsentCoverage", "ResidencyBoundary", "AuditEvent",
    "EvidenceArtifact",
    # Business
    "Plan", "CostCenter", "RevenueAccount", "SLA",
]

KyberEdgeType = Literal[
    # Workforce authority
    "HAS_ROLE", "USES_DEVICE", "ESTABLISHED_SESSION", "REQUESTED_SCOPE",
    "AUTHORIZED_BY", "ACCESSED_TENANT", "EXECUTED_COMMAND", "APPROVED",
    "VERIFIED_BY",
    # Platform topology
    "HAS_ENVIRONMENT", "HOSTS", "RUNS", "DEPLOYED_TO", "CHANGED", "DEPENDS_ON",
    "SERVED_BY", "PRODUCED_BY",
    # Tenant topology
    "OWNS_GRAPH", "CONTAINS_DOMAIN", "EXPOSES_FEATURE", "ENTITLED_TO",
    "INGESTS_FROM", "PROJECTS_TO",
    # Operations
    "CAUSED", "AFFECTS", "DEGRADED", "RECOVERED", "DETECTED_BY",
    "GROUPED_INTO", "REMEDIATED_BY",
    # Governance
    "GOVERNED_BY", "HAS_CONSENT_COVERAGE", "RESIDES_IN", "DERIVED_FROM",
    # Business
    "GENERATES_REVENUE", "INCURS_COST", "HAS_SLA", "RISKS_RENEWAL",
]

#: Node types that may legitimately carry a ``tenant_id``. Anything else with a
#: tenant set is a modelling error — the graph would be storing tenant data.
TENANT_SCOPED_NODE_TYPES: frozenset[str] = frozenset({
    "Tenant", "TenantGraph", "GraphDomain", "FeatureEntitlement", "Connector",
    "SDKInstallation", "Import", "Dataset", "AccessScope", "AccessDecision",
    "Incident", "Alert", "CommandRequest", "CommandExecution", "Verification",
    "ConsentCoverage", "Plan", "RevenueAccount", "SLA", "Projection",
})

HealthStatus = Literal["healthy", "degraded", "failing", "unknown", "no_data"]


def now_iso() -> str:
    return utc_now().isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class KyberGraphNode(BaseModel):
    """One platform-topology node.

    ``node_key`` is the caller-supplied natural key (``service:identity-worker``,
    ``tenant:acme``) and is what edges reference. It is stable across rebuilds,
    which is what makes the projector idempotent — a replay upserts rather than
    duplicating.
    """

    node_id: str = Field(default_factory=lambda: _id("kgn"))
    node_key: str
    node_type: KyberNodeType
    environment: Optional[str] = None
    tenant_id: Optional[str] = None
    display_name: Optional[str] = None
    health: HealthStatus = "unknown"
    #: Free-form topology attributes. Never tenant record data.
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: str = Field(default_factory=now_iso)
    valid_to: Optional[str] = None
    source_event_id: Optional[str] = None
    source_offset: Optional[int] = None
    evidence_reference: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class KyberGraphEdge(BaseModel):
    """A directed relationship between two node keys."""

    edge_id: str = Field(default_factory=lambda: _id("kge"))
    source_node_key: str
    target_node_key: str
    relationship_type: KyberEdgeType
    environment: Optional[str] = None
    tenant_id: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: str = Field(default_factory=now_iso)
    valid_to: Optional[str] = None
    source_event_id: Optional[str] = None
    source_offset: Optional[int] = None
    evidence_reference: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)

    @property
    def idempotency_key(self) -> str:
        """Natural key. A replay of the same relationship must not duplicate."""
        return f"{self.source_node_key}|{self.relationship_type}|{self.target_node_key}"


class ProjectionOffset(BaseModel):
    """How far a projection has consumed one tenant's mutation ledger.

    Offsets are per tenant because ``GraphMutationLedgerRepository.list_records``
    is per tenant, and because a stuck tenant must not stall the fleet. The
    repo's own convention is that cross-tenant reads are per-tenant reads.
    """

    offset_id: str = Field(default_factory=lambda: _id("kpo"))
    projection: str
    tenant_id: str
    last_offset: int = 0
    last_run_at: Optional[str] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    updated_at: str = Field(default_factory=now_iso)


class FleetProjectionRow(BaseModel):
    """One precomputed fleet fact.

    Freshness is a first-class field because a stale row that reads as healthy
    is worse than no row: it converts "we do not know" into "it is fine".
    ``computed_at`` plus ``source_offset`` let a reader decide for itself.
    """

    row_id: str = Field(default_factory=lambda: _id("kfp"))
    projection: str
    tenant_id: str
    environment: Optional[str] = None
    region: Optional[str] = None
    dimension: Optional[str] = None
    state: HealthStatus = "unknown"
    score: Optional[float] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    source_event_id: Optional[str] = None
    source_offset: Optional[int] = None
    computed_at: str = Field(default_factory=now_iso)


class CohortDefinition(BaseModel):
    """A named cross-tenant grouping evaluated over fleet projections.

    ``minimum_size`` exists so a cohort cannot become a way to single out one
    tenant: a cohort that resolves to fewer members is suppressed rather than
    returned.
    """

    cohort_id: str = Field(default_factory=lambda: _id("kco"))
    name: str
    filters: dict[str, Any] = Field(default_factory=dict)
    minimum_size: int = 3
    created_by: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class BlastRadiusResult(BaseModel):
    """What a change can reach.

    ``exposure_known`` and ``missing_inputs`` mirror the convention the
    agent-access plane established: a partial answer is labelled partial rather
    than summed into a confident wrong number.
    """

    subject_type: str
    subject_id: str
    environment: Optional[str] = None
    exposure_known: bool = False
    missing_inputs: list[str] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    affected_features: list[str] = Field(default_factory=list)
    affected_tenants: list[str] = Field(default_factory=list)
    affected_graph_domains: list[str] = Field(default_factory=list)
    customer_visible: bool = False
    traversal_depth: int = 0
    truncated: bool = False
    confidence: float = 0.0
    evidence_references: list[str] = Field(default_factory=list)
    computed_at: str = Field(default_factory=now_iso)


__all__ = [
    "TENANT_SCOPED_NODE_TYPES",
    "BlastRadiusResult",
    "CohortDefinition",
    "FleetProjectionRow",
    "HealthStatus",
    "KyberEdgeType",
    "KyberGraphEdge",
    "KyberGraphNode",
    "KyberNodeType",
    "ProjectionOffset",
    "now_iso",
]
