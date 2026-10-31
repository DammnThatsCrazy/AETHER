/**
 * High-cardinality principal <-> agent lineage contract (v1).
 *
 * Hand-authored twin of `services/api/shared/agent_lineage/{vocabulary,models}.py`
 * (drift-tested by `tests/contracts/test_agent_lineage_parity.py`). The lineage
 * projection is a DERIVED read model: the canonical graph and Bronze/Silver
 * evidence stay authoritative. Interactive budgets bound what a request returns,
 * never what Aether knows. Unknown is `null`, never `0`.
 *
 * HARD RULE: every field is snake_case (the parity scraper cannot capture camelCase).
 */

export const agentLineageContractVersion = '1' as const;

export const actorRoles = [
  'principal',
  'initiator',
  'executor',
  'operator',
  'beneficiary',
  'counterparty',
  'controller',
] as const;

export const controlModes = [
  'HUMAN_DIRECT',
  'AGENT_ASSISTED',
  'HUMAN_APPROVED_AGENT_EXECUTED',
  'STANDING_DELEGATION_AGENT_EXECUTED',
  'AGENT_AUTONOMOUS_WITHIN_POLICY',
  'AGENT_DELEGATED_TO_AGENT',
  'SYSTEM_AUTOMATION',
  'UNKNOWN',
] as const;

export const authorityTypes = [
  'delegation',
  'mandate',
  'approval',
  'entitlement',
  'permission',
  'policy',
  'budget',
  'standing_authority',
  'provider_authorization',
  'unknown',
] as const;

export const authorityResolutionStatuses = [
  'verified',
  'declared',
  'unresolved',
  'revoked',
  'expired',
  'out_of_scope',
  'conflicting',
] as const;

export const agentHierarchyLevels = [
  'agent_definition',
  'agent_deployment',
  'agent_instance',
  'agent_run',
  'task',
  'step',
  'invocation',
  'external_effect',
  'outcome',
] as const;

export const principalEvidenceClasses = [
  'VERIFIED_AUTHORITY',
  'DETERMINISTIC_BINDING',
  'CRYPTOGRAPHICALLY_ATTESTED',
  'PROVIDER_ASSERTED',
  'TENANT_DECLARED',
  'BEHAVIORALLY_INFERRED',
  'INFRASTRUCTURE_CORRELATED',
  'TEMPORALLY_CORRELATED',
  'UNKNOWN',
] as const;

export const principalResolutionStatuses = [
  'resolved',
  'candidate',
  'conflicting',
  'unresolved',
  'rejected',
] as const;

export const lineageRelationshipTypes = [
  'PRINCIPAL_OF',
  'OPERATES',
  'CONTROLS',
  'AUTHORIZED',
  'DELEGATED_TO',
  'SPAWNED',
  'SPAWNED_BY',
  'EXECUTED_AS',
  'ACTED_ON_BEHALF_OF',
  'SUPERVISES',
  'USES',
  'INVOKED',
  'COMMUNICATED_WITH',
  'PAID',
  'TRANSFERS_TO',
  'PRODUCED_EFFECT',
  'PRODUCED_OUTCOME',
  'DEPLOYED_AS',
  'INSTANTIATED_AS',
  'OWNS',
] as const;

export const relationshipStatuses = [
  'active',
  'revoked',
  'terminated',
  'expired',
  'superseded',
  'unknown',
] as const;

export const confidenceFactors = [
  'agent_identity_confidence',
  'instance_binding_confidence',
  'principal_link_confidence',
  'operator_link_confidence',
  'delegation_confidence',
  'authority_confidence',
  'execution_link_confidence',
  'source_quality',
  'external_effect_confidence',
  'outcome_confidence',
] as const;

export const lineageStatuses = [
  'complete',
  'partial',
  'cyclic',
  'unresolved_parent',
  'depth_limited',
  'truncated',
  'stale',
  'recomputing',
  'unavailable',
] as const;

export const completenessStates = [
  'complete',
  'partial',
  'truncated',
  'stale',
  'recomputing',
  'unknown',
  'unavailable',
] as const;

export const clusterKinds = [
  'agent_fleet',
  'agent_swarm',
  'execution_cluster',
  'infrastructure_cluster',
  'delegation_cluster',
] as const;

export const clusterBases = [
  'shared_principal',
  'shared_delegation_root',
  'shared_deployment',
  'shared_operator',
  'shared_runtime',
  'shared_service_credentials',
  'shared_funding_source',
  'shared_wallet_lineage',
  'shared_infrastructure',
  'shared_tool_patterns',
  'temporal_coordination',
  'behavioral_similarity',
] as const;

export const attributionClasses = [
  'verified',
  'inferred',
  'suspected_cluster',
  'unresolved',
] as const;

export const queryModes = [
  'interactive',
  'analytical',
  'export',
] as const;

export const fanoutRiskSignals = [
  'agent_spawn_velocity',
  'delegation_fanout',
  'delegation_depth',
  'ephemeral_agent_ratio',
  'new_agent_rate',
  'cross_wallet_fanout',
  'tool_fanout',
  'provider_fanout',
  'transaction_fanout',
  'runtime_churn',
  'identity_churn',
  'authority_failure_rate',
  'revoked_agent_activity',
  'out_of_scope_execution_rate',
  'shared_infrastructure_density',
  'coordinated_execution_score',
] as const;

export const riskAttributionKinds = [
  'agent_is_risky',
  'agent_in_risky_cluster',
  'delegated_by_risky_actor',
  'interacted_with_risky_resource',
  'resembles_risky_behavior',
  'confirmed_malicious',
] as const;

export const riskPropagationKinds = [
  'exposure',
  'association',
  'influence',
  'verified_action',
  'inferred_relationship',
] as const;

export const executionVerificationStates = [
  'source_reported',
  'deployment_verified',
  'attested',
  'reconciled',
  'disputed',
  'unverified',
] as const;

export const principalProofEvidenceClasses = [
  'VERIFIED_AUTHORITY',
  'DETERMINISTIC_BINDING',
  'CRYPTOGRAPHICALLY_ATTESTED',
] as const;

export const weakClusterBases = [
  'shared_runtime',
  'shared_infrastructure',
  'shared_tool_patterns',
  'temporal_coordination',
  'behavioral_similarity',
] as const;

export const interactiveMaxNodes = 500;
export const interactiveMaxEdges = 2000;
export const minDurableDelegationDepth = 32;
export const defaultPageSize = 100;
export const maxPageSize = 500;

export type ActorRole = (typeof actorRoles)[number];
export type ControlMode = (typeof controlModes)[number];
export type AuthorityType = (typeof authorityTypes)[number];
export type AuthorityResolutionStatus = (typeof authorityResolutionStatuses)[number];
export type AgentHierarchyLevel = (typeof agentHierarchyLevels)[number];
export type PrincipalEvidenceClass = (typeof principalEvidenceClasses)[number];
export type PrincipalResolutionStatus = (typeof principalResolutionStatuses)[number];
export type LineageRelationshipType = (typeof lineageRelationshipTypes)[number];
export type RelationshipStatus = (typeof relationshipStatuses)[number];
export type ConfidenceFactorName = (typeof confidenceFactors)[number];
export type LineageStatus = (typeof lineageStatuses)[number];
export type CompletenessState = (typeof completenessStates)[number];
export type ClusterKind = (typeof clusterKinds)[number];
export type ClusterBasisKind = (typeof clusterBases)[number];
export type AttributionClass = (typeof attributionClasses)[number];
export type QueryMode = (typeof queryModes)[number];
export type FanoutRiskSignal = (typeof fanoutRiskSignals)[number];
export type RiskAttributionKind = (typeof riskAttributionKinds)[number];
export type RiskPropagationKind = (typeof riskPropagationKinds)[number];
export type ExecutionVerificationState = (typeof executionVerificationStates)[number];

type Nullable<T> = T | null;

export interface ConfidenceFactors {
  agent_identity_confidence: Nullable<number>;
  instance_binding_confidence: Nullable<number>;
  principal_link_confidence: Nullable<number>;
  operator_link_confidence: Nullable<number>;
  delegation_confidence: Nullable<number>;
  authority_confidence: Nullable<number>;
  execution_link_confidence: Nullable<number>;
  source_quality: Nullable<number>;
  external_effect_confidence: Nullable<number>;
  outcome_confidence: Nullable<number>;
}

export interface Disclosure {
  as_of: Nullable<string>;
  computed_at: Nullable<string>;
  evidence_window_start: Nullable<string>;
  evidence_window_end: Nullable<string>;
  projection_version: string;
  completeness: CompletenessState;
  truncated: boolean;
  truncation_reasons: string[];
}

export interface ActorContext {
  principal: Nullable<string>;
  initiator: Nullable<string>;
  executor: Nullable<string>;
  operator: Nullable<string>;
  beneficiary: Nullable<string>;
  counterparty: Nullable<string>;
  controller: Nullable<string>;
  reported_principal_ref: Nullable<string>;
  reported_principal_namespace: Nullable<string>;
  canonical_principal_entity_id: Nullable<string>;
  principal_resolution_method: Nullable<string>;
  principal_resolution_status: Nullable<PrincipalResolutionStatus>;
  principal_confidence: Nullable<number>;
  principal_evidence_refs: string[];
}

export interface AuthorityContext {
  authority_type: Nullable<AuthorityType>;
  authority_ref: Nullable<string>;
  grantor_entity_id: Nullable<string>;
  grantee_entity_id: Nullable<string>;
  scope: Nullable<string>;
  resource_scope: Nullable<string>;
  action_scope: Nullable<string>;
  budget: Nullable<string>;
  currency: Nullable<string>;
  valid_from: Nullable<string>;
  valid_until: Nullable<string>;
  delegation_allowed: Nullable<boolean>;
  maximum_delegation_depth: Nullable<number>;
  policy_id: Nullable<string>;
  policy_version: Nullable<string>;
  approval_ref: Nullable<string>;
  mandate_ref: Nullable<string>;
  revocation_ref: Nullable<string>;
  revoked_at: Nullable<string>;
  authority_resolution_status: Nullable<AuthorityResolutionStatus>;
  authority_evidence_refs: string[];
}

export interface ExecutionContext {
  source_run_id: Nullable<string>;
  canonical_run_id: Nullable<string>;
  trace_id: Nullable<string>;
  span_id: Nullable<string>;
  parent_span_id: Nullable<string>;
  root_run_id: Nullable<string>;
  parent_run_id: Nullable<string>;
  agent_definition_id: Nullable<string>;
  agent_deployment_id: Nullable<string>;
  agent_instance_id: Nullable<string>;
  task_id: Nullable<string>;
  control_mode: Nullable<ControlMode>;
  delegation_depth: Nullable<number>;
  external_effect_ref: Nullable<string>;
  execution_verification_state: Nullable<ExecutionVerificationState>;
}

export interface ProtocolContext {
  protocol: Nullable<string>;
  protocol_version: Nullable<string>;
  adapter: Nullable<string>;
  adapter_version: Nullable<string>;
}

export interface LineageRow {
  tenant_id: string;
  principal_entity_id: string;
  agent_entity_id: string;
  agent_definition_id: Nullable<string>;
  agent_instance_id: Nullable<string>;
  root_agent_id: Nullable<string>;
  parent_agent_id: Nullable<string>;
  root_run_id: Nullable<string>;
  parent_run_id: Nullable<string>;
  relationship_type: LineageRelationshipType;
  relationship_status: RelationshipStatus;
  depth: number;
  direct_or_indirect: 'direct' | 'indirect';
  authority_ref: Nullable<string>;
  authority_type: Nullable<AuthorityType>;
  authority_resolution_status: Nullable<AuthorityResolutionStatus>;
  attribution_class: AttributionClass;
  evidence_class: PrincipalEvidenceClass;
  lineage_status: LineageStatus;
  first_seen: Nullable<string>;
  last_seen: Nullable<string>;
  active_state: 'active' | 'inactive' | 'revoked' | 'terminated' | 'unknown';
  confidence: ConfidenceFactors;
  evidence_count: number;
  evidence_refs: string[];
  evidence_digest: Nullable<string>;
  source_namespaces: string[];
  risk_signal_count: Nullable<number>;
  economic_activity_present: Nullable<boolean>;
  communication_activity_present: Nullable<boolean>;
  last_reconciled_at: Nullable<string>;
  projection_version: string;
}

/** Unknown is `null`, never `0`. */
export interface LineageSummary {
  tenant_id: string;
  principal_entity_id: string;
  unique_agent_definitions: Nullable<number>;
  agent_instances: Nullable<number>;
  agent_runs: Nullable<number>;
  active_agents: Nullable<number>;
  historical_agents: Nullable<number>;
  direct_agents: Nullable<number>;
  indirect_agents: Nullable<number>;
  probabilistic_agents: Nullable<number>;
  unresolved_agents: Nullable<number>;
  revoked_agents: Nullable<number>;
  out_of_scope_agents: Nullable<number>;
  unknown_state_agents: Nullable<number>;
  risk_flagged_agents: Nullable<number>;
  max_delegation_depth: Nullable<number>;
  cyclic_agents: Nullable<number>;
  tools_used: Nullable<number>;
  services_used: Nullable<number>;
  verified_links: Nullable<number>;
  inferred_links: Nullable<number>;
  disclosure: Disclosure;
}

export interface AgentLineageCounts {
  direct_child_count: Nullable<number>;
  recursive_descendant_count: Nullable<number>;
  active_descendant_count: Nullable<number>;
  risk_descendant_count: Nullable<number>;
  max_descendant_depth: Nullable<number>;
  disclosure: Disclosure;
}

export interface ClusterBasis {
  basis: ClusterBasisKind;
  detail: Nullable<string>;
  evidence_refs: string[];
}

export interface LineageCluster {
  cluster_id: string;
  kind: ClusterKind;
  label: Nullable<string>;
  member_count: number;
  active_count: Nullable<number>;
  risk_flagged_count: Nullable<number>;
  bases: ClusterBasis[];
  attribution_class: AttributionClass;
  implies_common_control: boolean;
  sample_agent_ids: string[];
  next_cursor: Nullable<string>;
}

export interface TreeNode {
  agent_entity_id: string;
  depth: number;
  descendant_count: Nullable<number>;
  collapsed: boolean;
  lineage_status: LineageStatus;
  relationship_type: Nullable<LineageRelationshipType>;
  attribution_class: AttributionClass;
  children: TreeNode[];
  next_cursor: Nullable<string>;
}

export interface Page<T> {
  items: T[];
  next_cursor: Nullable<string>;
  page_size: number;
  total_estimate: Nullable<number>;
  disclosure: Disclosure;
}
