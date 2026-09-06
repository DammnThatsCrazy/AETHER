/**
 * DO NOT EDIT — generated from packages/shared/contracts/spine-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const spineRegistryContractVersion = '1.0.0' as const;

/** Registered spines (sorted). */
export const spineIds = [
  'aether_surfaces',
  'agentic_runtime_access',
  'attribution_architecture',
  'common_spine_envelope',
  'computation_substrate',
  'connector_normalization',
  'consent',
  'context_capsule',
  'context_capsule_semantics',
  'contract_spine',
  'decision_contracts',
  'evidence_provenance',
  'exploration_fabric',
  'graph',
  'graph_history_replay',
  'grouping_membership',
  'identity_resolution',
  'infrastructure_model',
  'irrl_naming_overlay',
  'journey_continuity',
  'kyber',
  'measurement_outcome_contract',
  'model_governance',
  'platform_authority',
  'projection_plane',
  'reconciled_control_plane',
  'relationship_fidelity',
  'rights_irrl',
  'spine_composition_kernel',
  'spine_conformance_contract',
  'spine_registry',
  'temporal_kernel',
  'tenant_readiness',
  'upr',
] as const;
export type SpineId = typeof spineIds[number];

/** Plane a spine may be anchored to (sorted). */
export const spinePlanes = [
  'decision_action',
  'governance_contract',
  'horizontal_controls',
  'intelligence_projection',
  'interaction_product',
  'observation_acquisition',
  'relationship_graph',
  'resolution_canonical_data',
] as const;
export type SpinePlane = typeof spinePlanes[number];

/** Kinds a spine may be (sorted). */
export const spineKinds = [
  'composition_authority',
  'program_capability',
  'protective_overlay',
  'runtime_authority',
  'truth_authority',
] as const;
export type SpineKind = typeof spineKinds[number];

/** Implementation states — repo metadata, NOT readiness (sorted). */
export const spineImplementationStates = [
  'canonical',
  'deprecated',
  'implemented',
  'in_flight',
  'pending',
] as const;
export type SpineImplementationState = typeof spineImplementationStates[number];

/** Graph-mutation policies a spine may declare (sorted). */
export const spineGraphMutationPolicies = ['canonical_gateway_only', 'read_only'] as const;
export type SpineGraphMutationPolicy = typeof spineGraphMutationPolicies[number];

/** Canonical 14-item conformance contract ids (sorted). */
export const spineConformanceCheckIds = [
  'api_event_ui_kyber_integration',
  'authority_non_ownership_statement',
  'canonical_contract_registration',
  'dependency_dag_validation',
  'evidence_restatement_behavior',
  'graph_mutation_policy',
  'migration_recompute_rollback_compatibility',
  'port_adapter_declaration',
  'positive_negative_replay_isolation_golden_tests',
  'readiness_entitlement_integration',
  'security_compliance_observability_evidence',
  'temporal_watermark_behavior',
  'tenant_consent_rights_retention_residency_export',
  'typed_degradation_behavior',
] as const;
export type SpineConformanceCheckId = typeof spineConformanceCheckIds[number];
