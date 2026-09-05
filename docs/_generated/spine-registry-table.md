<!-- DO NOT EDIT — generated from packages/shared/contracts/spine-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Spine Registry

Contract version: `1.0.0`

Canonical Aether spine registry (Spine Composition Kernel, ADR-011). Every spine is a governed authority or cross-cutting control boundary — no spine is a private platform inside the platform. `implementationState` is repo metadata, never readiness.

## Planes

`decision_action`, `governance_contract`, `horizontal_controls`, `intelligence_projection`, `interaction_product`, `observation_acquisition`, `relationship_graph`, `resolution_canonical_data`

## Spine kinds

`composition_authority`, `program_capability`, `protective_overlay`, `runtime_authority`, `truth_authority`

## Implementation states

`canonical`, `deprecated`, `implemented`, `in_flight`, `pending`

## Graph mutation policies

`canonical_gateway_only`, `read_only`

## Conformance checks

`api_event_ui_kyber_integration`, `authority_non_ownership_statement`, `canonical_contract_registration`, `dependency_dag_validation`, `evidence_restatement_behavior`, `graph_mutation_policy`, `migration_recompute_rollback_compatibility`, `port_adapter_declaration`, `positive_negative_replay_isolation_golden_tests`, `readiness_entitlement_integration`, `security_compliance_observability_evidence`, `temporal_watermark_behavior`, `tenant_consent_rights_retention_residency_export`, `typed_degradation_behavior`

## Spines

| Spine | Display name | Plane | Kind | State | Graph policy | Surfaces | Conformance |
|---|---|---|---|---|---|---|---|
| `aether_surfaces` | Aether surfaces / Noesis | interaction_product | runtime_authority | implemented | canonical_gateway_only | `campaign360`, `graph`, `journeys`, `profile360`, `timeline` | 14 open |
| `agentic_runtime_access` | Agent / Execution contracts | decision_action | runtime_authority | implemented | canonical_gateway_only | — | 14 open |
| `attribution_architecture` | Attribution Architecture | intelligence_projection | composition_authority | implemented | read_only | `campaign360`, `outcome360` | 14 open |
| `common_spine_envelope` | Common spine envelope (program capability) | governance_contract | program_capability | in_flight | read_only | — | — |
| `computation_substrate` | Computation Substrate | decision_action | runtime_authority | implemented | canonical_gateway_only | — | 14 open |
| `connector_normalization` | Connector Normalization + SDK & Universal Alignment | observation_acquisition | runtime_authority | implemented | read_only | `connection360` | 14 open |
| `consent` | Consent / Privacy / Deletion | resolution_canonical_data | protective_overlay | implemented | canonical_gateway_only | — | 14 open |
| `context_capsule` | Context Capsule | resolution_canonical_data | truth_authority | implemented | read_only | `geo` | 14 open |
| `context_capsule_semantics` | Context Capsule Semantics | resolution_canonical_data | truth_authority | implemented | read_only | `geo` | 14 open |
| `contract_spine` | Contract Spine (Truth Kernel: TS contracts + JSON registries + Pydantic mirrors + generation gates) | governance_contract | truth_authority | implemented | read_only | — | 14 open |
| `decision_contracts` | Findings / Investigations / Decision contracts | decision_action | composition_authority | implemented | read_only | — | 14 open |
| `evidence_provenance` | Evidence / Lineage / Truth-State / Restatement | resolution_canonical_data | truth_authority | implemented | canonical_gateway_only | — | 14 open |
| `exploration_fabric` | Lens / Projection Algebra + Exploration Fabric | intelligence_projection | composition_authority | implemented | read_only | `campaign360`, `comparison_workbench`, `graph`, `profile360` | 14 open |
| `graph` | Graph Mutation / State Transition / History | relationship_graph | truth_authority | implemented | canonical_gateway_only | `graph` | 14 open |
| `graph_history_replay` | Graph History Replay | relationship_graph | truth_authority | implemented | read_only | `temporal_observatory`, `timeline` | 14 open |
| `grouping_membership` | Grouping Membership | relationship_graph | truth_authority | implemented | canonical_gateway_only | `cluster360`, `comparison_workbench` | 14 open |
| `identity_resolution` | Identity Resolution | resolution_canonical_data | truth_authority | implemented | canonical_gateway_only | `profile360` | 14 open |
| `infrastructure_model` | Infrastructure Model | resolution_canonical_data | truth_authority | implemented | read_only | `infrastructure360` | 14 open |
| `irrl_naming_overlay` | IRRL naming overlay (program capability) | governance_contract | program_capability | in_flight | read_only | — | — |
| `journey_continuity` | journey_continuity (pending projection spine) | intelligence_projection | truth_authority | pending | read_only | `journeys`, `timeline` | 14 open |
| `kyber` | Kyber (operator control surface) | decision_action | runtime_authority | implemented | canonical_gateway_only | — | 14 open |
| `measurement_outcome_contract` | Measurement / Metrics / Algebra | intelligence_projection | composition_authority | implemented | read_only | `campaign360`, `comparison_workbench`, `economic360`, `outcome360` | 14 open |
| `model_governance` | ML / model contracts | intelligence_projection | composition_authority | implemented | read_only | — | 14 open |
| `platform_authority` | Platform Authority | governance_contract | runtime_authority | implemented | read_only | — | 14 open |
| `projection_plane` | 360 projections | intelligence_projection | composition_authority | in_flight | read_only | `campaign360`, `cluster360`, `comparison_workbench`, `connection360`, `economic360`, `geo`, `graph`, `journeys`, `outcome360`, `product_intelligence`, `profile360`, `temporal_observatory`, `timeline` | 14 open |
| `reconciled_control_plane` | reconciled_control_plane (pending projection spine) | decision_action | runtime_authority | pending | read_only | `connection360` | 14 open |
| `relationship_fidelity` | Relational Intelligence / Relationship Fidelity | relationship_graph | truth_authority | implemented | canonical_gateway_only | `graph` | 14 open |
| `rights_irrl` | Rights / IRRL runtime | governance_contract | truth_authority | in_flight | canonical_gateway_only | — | 14 open |
| `spine_composition_kernel` | Spine Composition Kernel (program capability) | governance_contract | program_capability | in_flight | read_only | — | — |
| `spine_conformance_contract` | 14-item conformance contract (program capability) | governance_contract | program_capability | in_flight | read_only | — | — |
| `spine_registry` | spine-registry (program capability) | governance_contract | program_capability | in_flight | read_only | — | — |
| `temporal_kernel` | Temporal Kernel | resolution_canonical_data | truth_authority | implemented | canonical_gateway_only | `temporal_observatory`, `timeline` | 14 open |
| `tenant_readiness` | Product Runtime / Tenant Activation & Readiness | decision_action | runtime_authority | implemented | read_only | — | 14 open |
| `upr` | Universal Provider Runtime | observation_acquisition | runtime_authority | implemented | canonical_gateway_only | `connection360` | 14 open |
