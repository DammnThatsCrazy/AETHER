"""Canonical vocabularies for high-cardinality principal <-> agent lineage.

Single backend source of truth for the Actor / Authority / Execution / Protocol
context vocabularies, lineage relationship types, evidence classes, confidence
factors and degradation states. ``packages/shared/agent-lineage.ts`` is the
hand-authored twin; ``tests/contracts/test_agent_lineage_parity.py`` fails on
drift. Wire fields are snake_case.

Invariants this vocabulary encodes (work order §50):
  * a source-reported principal is a claim, never canonical truth;
  * a trace is not a run;
  * unknown never becomes zero (see ``Completeness``);
  * weak evidence can cluster but never prove common control.
"""
from __future__ import annotations

ACTOR_ROLES: tuple[str, ...] = (
    "principal", "initiator", "executor", "operator",
    "beneficiary", "counterparty", "controller",
)

CONTROL_MODES: tuple[str, ...] = (
    "HUMAN_DIRECT",
    "AGENT_ASSISTED",
    "HUMAN_APPROVED_AGENT_EXECUTED",
    "STANDING_DELEGATION_AGENT_EXECUTED",
    "AGENT_AUTONOMOUS_WITHIN_POLICY",
    "AGENT_DELEGATED_TO_AGENT",
    "SYSTEM_AUTOMATION",
    "UNKNOWN",
)

AUTHORITY_TYPES: tuple[str, ...] = (
    "delegation", "mandate", "approval", "entitlement", "permission",
    "policy", "budget", "standing_authority", "provider_authorization",
    "unknown",
)

AUTHORITY_RESOLUTION_STATUSES: tuple[str, ...] = (
    "verified", "declared", "unresolved", "revoked", "expired",
    "out_of_scope", "conflicting",
)

# Agent hierarchy: Definition -> Deployment -> Instance -> Run -> Task -> Invocation
AGENT_HIERARCHY_LEVELS: tuple[str, ...] = (
    "agent_definition", "agent_deployment", "agent_instance",
    "agent_run", "task", "step", "invocation", "external_effect", "outcome",
)

# Evidence classes for agent -> principal linkage, strongest first.
PRINCIPAL_EVIDENCE_CLASSES: tuple[str, ...] = (
    "VERIFIED_AUTHORITY",
    "DETERMINISTIC_BINDING",
    "CRYPTOGRAPHICALLY_ATTESTED",
    "PROVIDER_ASSERTED",
    "TENANT_DECLARED",
    "BEHAVIORALLY_INFERRED",
    "INFRASTRUCTURE_CORRELATED",
    "TEMPORALLY_CORRELATED",
    "UNKNOWN",
)

# Only these may, on their own, establish a principal link. Everything else is
# clustering support (invariant: weak signals never independently prove control).
PRINCIPAL_PROOF_EVIDENCE_CLASSES: frozenset[str] = frozenset({
    "VERIFIED_AUTHORITY", "DETERMINISTIC_BINDING", "CRYPTOGRAPHICALLY_ATTESTED",
})

PRINCIPAL_RESOLUTION_STATUSES: tuple[str, ...] = (
    "resolved", "candidate", "conflicting", "unresolved", "rejected",
)

# Recursive lineage relationship types.
LINEAGE_RELATIONSHIP_TYPES: tuple[str, ...] = (
    "PRINCIPAL_OF", "OPERATES", "CONTROLS", "AUTHORIZED", "DELEGATED_TO",
    "SPAWNED", "SPAWNED_BY", "EXECUTED_AS", "ACTED_ON_BEHALF_OF",
    "SUPERVISES", "USES", "INVOKED", "COMMUNICATED_WITH", "PAID",
    "TRANSFERS_TO", "PRODUCED_EFFECT", "PRODUCED_OUTCOME",
    "DEPLOYED_AS", "INSTANTIATED_AS", "OWNS",
)

RELATIONSHIP_STATUSES: tuple[str, ...] = (
    "active", "revoked", "terminated", "expired", "superseded", "unknown",
)

# Factorized attribution confidence — stored separately, never collapsed.
CONFIDENCE_FACTORS: tuple[str, ...] = (
    "agent_identity_confidence",
    "instance_binding_confidence",
    "principal_link_confidence",
    "operator_link_confidence",
    "delegation_confidence",
    "authority_confidence",
    "execution_link_confidence",
    "source_quality",
    "external_effect_confidence",
    "outcome_confidence",
)

LINEAGE_STATUSES: tuple[str, ...] = (
    "complete", "partial", "cyclic", "unresolved_parent", "depth_limited",
    "truncated", "stale", "recomputing", "unavailable",
)

# Disclosed degradation states (invariant 11: truncation always disclosed).
COMPLETENESS_STATES: tuple[str, ...] = (
    "complete", "partial", "truncated", "stale", "recomputing",
    "unknown", "unavailable",
)

CLUSTER_KINDS: tuple[str, ...] = (
    "agent_fleet", "agent_swarm", "execution_cluster",
    "infrastructure_cluster", "delegation_cluster",
)

# Every cluster must state why members are grouped.
CLUSTER_BASES: tuple[str, ...] = (
    "shared_principal", "shared_delegation_root", "shared_deployment",
    "shared_operator", "shared_runtime", "shared_service_credentials",
    "shared_funding_source", "shared_wallet_lineage", "shared_infrastructure",
    "shared_tool_patterns", "temporal_coordination", "behavioral_similarity",
)

# Cluster bases that are, on their own, weak (cannot prove common control).
WEAK_CLUSTER_BASES: frozenset[str] = frozenset({
    "shared_infrastructure", "shared_tool_patterns", "temporal_coordination",
    "behavioral_similarity", "shared_runtime",
})

ATTRIBUTION_CLASSES: tuple[str, ...] = (
    "verified", "inferred", "suspected_cluster", "unresolved",
)

QUERY_MODES: tuple[str, ...] = ("interactive", "analytical", "export")

# Interactive budgets stay at the existing graph-window envelope; they bound
# what a request returns, never what Aether knows (work order §3).
INTERACTIVE_MAX_NODES = 500
INTERACTIVE_MAX_EDGES = 2000
MIN_DURABLE_DELEGATION_DEPTH = 32
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

FANOUT_RISK_SIGNALS: tuple[str, ...] = (
    "agent_spawn_velocity", "delegation_fanout", "delegation_depth",
    "ephemeral_agent_ratio", "new_agent_rate", "cross_wallet_fanout",
    "tool_fanout", "provider_fanout", "transaction_fanout", "runtime_churn",
    "identity_churn", "authority_failure_rate", "revoked_agent_activity",
    "out_of_scope_execution_rate", "shared_infrastructure_density",
    "coordinated_execution_score",
)

RISK_ATTRIBUTION_KINDS: tuple[str, ...] = (
    "agent_is_risky", "agent_in_risky_cluster", "delegated_by_risky_actor",
    "interacted_with_risky_resource", "resembles_risky_behavior",
    "confirmed_malicious",
)

RISK_PROPAGATION_KINDS: tuple[str, ...] = (
    "exposure", "association", "influence", "verified_action",
    "inferred_relationship",
)

EXECUTION_VERIFICATION_STATES: tuple[str, ...] = (
    "source_reported", "deployment_verified", "attested", "reconciled",
    "disputed", "unverified",
)
