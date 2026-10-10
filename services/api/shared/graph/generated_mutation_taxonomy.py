# DO NOT EDIT — generated from packages/shared/contracts/graph-mutation-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated graph-mutation taxonomy (mutation types, actors, causality, explanations)."""

from __future__ import annotations

GRAPH_MUTATION_CONTRACT_VERSION = "1.0.0"

# Every way the graph plane may change (append-only ledger vocabulary).
GRAPH_MUTATION_TYPES: tuple[str, ...] = (
    "node_created",
    "node_versioned",
    "node_tombstoned",
    "node_restored",
    "edge_created",
    "edge_versioned",
    "edge_expired",
    "edge_tombstoned",
    "identity_merged",
    "identity_split",
    "identity_redirected",
    "cluster_created",
    "cluster_member_added",
    "cluster_member_removed",
    "cluster_merged",
    "cluster_split",
    "score_versioned",
    "attribution_versioned",
    "policy_state_changed",
    "consent_state_changed",
    "model_version_changed",
    "projection_rebuilt",
    "historical_correction_applied",
)

# Who (or what) performed a graph mutation.
MUTATION_ACTOR_KINDS: tuple[str, ...] = (
    "service",
    "human",
    "agent",
    "system",
    "provider",
    "import",
)

# Strength of the causal claim attached to a mutation.
MUTATION_CAUSALITY_CLASSES: tuple[str, ...] = (
    "observed_sequence",
    "declared_reason",
    "policy_cause",
    "authorized_delegation",
    "attributed_influence",
    "inferred_influence",
    "direct_cause",
    "correlation_only",
    "unknown",
)

# How a mutation (or decision) is explained to reviewers.
MUTATION_EXPLANATION_TYPES: tuple[str, ...] = (
    "observed_trigger",
    "declared_reason",
    "policy_cause",
    "authorized_delegation",
    "attributed_influence",
    "inferred_influence",
    "experimental_incrementality",
    "direct_cause",
    "correlation_only",
    "unknown",
)

__all__ = [
    "GRAPH_MUTATION_CONTRACT_VERSION",
    "GRAPH_MUTATION_TYPES",
    "MUTATION_ACTOR_KINDS",
    "MUTATION_CAUSALITY_CLASSES",
    "MUTATION_EXPLANATION_TYPES",
]
