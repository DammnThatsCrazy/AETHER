# DO NOT EDIT — generated from packages/shared/contracts/spine-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated canonical spine registry (Spine Composition Kernel, ADR-011)."""

from __future__ import annotations

SPINE_REGISTRY_CONTRACT_VERSION = "1.0.0"

# Registered spines (sorted).
SPINE_IDS: tuple[str, ...] = (
    "aether_surfaces",
    "agentic_runtime_access",
    "attribution_architecture",
    "common_spine_envelope",
    "computation_substrate",
    "connector_normalization",
    "consent",
    "context_capsule",
    "context_capsule_semantics",
    "contract_spine",
    "decision_contracts",
    "evidence_provenance",
    "exploration_fabric",
    "graph",
    "graph_history_replay",
    "grouping_membership",
    "identity_resolution",
    "infrastructure_model",
    "irrl_naming_overlay",
    "journey_continuity",
    "kyber",
    "measurement_outcome_contract",
    "model_governance",
    "platform_authority",
    "projection_plane",
    "reconciled_control_plane",
    "relationship_fidelity",
    "rights_irrl",
    "spine_composition_kernel",
    "spine_conformance_contract",
    "spine_registry",
    "temporal_kernel",
    "tenant_readiness",
    "upr",
)

# Plane a spine may be anchored to.
SPINE_PLANES: tuple[str, ...] = (
    "decision_action",
    "governance_contract",
    "horizontal_controls",
    "intelligence_projection",
    "interaction_product",
    "observation_acquisition",
    "relationship_graph",
    "resolution_canonical_data",
)

# Kinds a spine may be.
SPINE_KINDS: tuple[str, ...] = (
    "composition_authority",
    "program_capability",
    "protective_overlay",
    "runtime_authority",
    "truth_authority",
)

# Implementation states — repo metadata, NOT readiness.
SPINE_IMPLEMENTATION_STATES: tuple[str, ...] = (
    "canonical",
    "deprecated",
    "implemented",
    "in_flight",
    "pending",
)

# Graph-mutation policies a spine may declare.
SPINE_GRAPH_MUTATION_POLICIES: tuple[str, ...] = ("canonical_gateway_only", "read_only")

# Canonical 14-item conformance contract ids.
SPINE_CONFORMANCE_CHECK_IDS: tuple[str, ...] = (
    "api_event_ui_kyber_integration",
    "authority_non_ownership_statement",
    "canonical_contract_registration",
    "dependency_dag_validation",
    "evidence_restatement_behavior",
    "graph_mutation_policy",
    "migration_recompute_rollback_compatibility",
    "port_adapter_declaration",
    "positive_negative_replay_isolation_golden_tests",
    "readiness_entitlement_integration",
    "security_compliance_observability_evidence",
    "temporal_watermark_behavior",
    "tenant_consent_rights_retention_residency_export",
    "typed_degradation_behavior",
)

__all__ = [
    "SPINE_CONFORMANCE_CHECK_IDS",
    "SPINE_GRAPH_MUTATION_POLICIES",
    "SPINE_IDS",
    "SPINE_IMPLEMENTATION_STATES",
    "SPINE_KINDS",
    "SPINE_PLANES",
    "SPINE_REGISTRY_CONTRACT_VERSION",
]
