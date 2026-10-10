# DO NOT EDIT — generated from packages/shared/contracts/comparison-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated comparison vocabulary (modes, baselines, states, severities, materiality)."""

from __future__ import annotations

COMPARISON_CONTRACT_VERSION = "1.0.0"

# What is being compared against what.
COMPARISON_MODES: tuple[str, ...] = (
    "entity_vs_entity",
    "entity_vs_history",
    "entity_vs_cohort",
    "entity_vs_expected",
    "cohort_vs_cohort",
    "scenario_vs_current",
)

# Where the baseline side of a comparison comes from.
BASELINE_TYPES: tuple[str, ...] = (
    "entity",
    "historical",
    "rolling_history",
    "cohort",
    "policy",
    "predicted",
    "manual",
    "scenario",
)

# How well the two sides could be aligned before comparing.
ALIGNMENT_OUTCOMES: tuple[str, ...] = (
    "aligned",
    "aligned_after_conversion",
    "partially_aligned",
    "not_comparable",
    "missing_unit",
    "missing_price",
    "stale_price",
    "grain_mismatch",
    "semantic_mismatch",
    "insufficient_provenance",
)

# Lifecycle states of a comparison run.
COMPARISON_RUN_STATES: tuple[str, ...] = (
    "queued",
    "resolving",
    "collecting",
    "aligning",
    "computing",
    "scoring",
    "completed",
    "completed_degraded",
    "suppressed",
    "failed",
    "cancelled",
    "expired",
)

# Severity ladder for comparison findings.
COMPARISON_SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high", "critical")

# Recommended handling of a comparison finding.
COMPARISON_DISPOSITIONS: tuple[str, ...] = (
    "informational",
    "monitor",
    "investigate",
    "decide",
    "act",
    "suppressed",
    "insufficient_evidence",
)

# How a finding's supporting facts are linked to the subject.
FACT_LINKAGE_STATES: tuple[str, ...] = (
    "linked",
    "deterministically_linked",
    "probabilistically_linked",
    "pending",
    "conflicted",
    "suppressed",
    "intentionally_unlinked",
    "orphaned",
    "revoked",
    "superseded",
)

# Strength ladder for causal claims attached to a finding.
CAUSAL_CLAIM_LEVELS: tuple[str, ...] = (
    "observed",
    "correlated",
    "temporally_associated",
    "attributed",
    "inferred",
    "counterfactual_estimate",
    "causally_supported",
)

# Dimensions along which two subjects can be compared.
COMPARISON_DIMENSIONS: tuple[str, ...] = (
    "identity",
    "relationships",
    "devices",
    "sessions",
    "behavior",
    "journeys",
    "campaigns",
    "attribution",
    "wallets",
    "economic_activity",
    "agent_behavior",
    "fraud_risk",
    "trust",
    "consent",
    "governance",
    "outcomes",
    "data_quality",
    "reconciliation",
    "geography",
    "temporal_activity",
)

# Components blended into a finding's materiality score.
MATERIALITY_COMPONENTS: tuple[str, ...] = (
    "economic_impact",
    "risk_impact",
    "policy_impact",
    "relationship_rarity",
    "historical_deviation",
    "cohort_deviation",
    "propagation_radius",
    "confidence",
    "freshness",
    "persistence",
    "urgency",
    "strategic_entity_weight",
    "reversibility",
    "data_quality",
)

__all__ = [
    "COMPARISON_CONTRACT_VERSION",
    "COMPARISON_MODES",
    "BASELINE_TYPES",
    "ALIGNMENT_OUTCOMES",
    "COMPARISON_RUN_STATES",
    "COMPARISON_SEVERITIES",
    "COMPARISON_DISPOSITIONS",
    "FACT_LINKAGE_STATES",
    "CAUSAL_CLAIM_LEVELS",
    "COMPARISON_DIMENSIONS",
    "MATERIALITY_COMPONENTS",
]
