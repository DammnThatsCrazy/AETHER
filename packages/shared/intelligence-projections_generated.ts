/**
 * DO NOT EDIT — generated from packages/shared/contracts/intelligence-projection-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const intelligenceProjectionsContractVersion = '1.0.0' as const;

/** Registered intelligence projections (sorted). */
export const intelligenceProjectionIds = [
  'agent360',
  'campaign360',
  'cluster360',
  'communication360',
  'connection360',
  'economic360',
  'episode360',
  'execution360',
  'fraud360',
  'geographic360',
  'infrastructure360',
  'outcome360',
  'population360',
  'profile360',
  'relationship360',
  'risk360',
  'social360',
  'source360',
  'support360',
  'temporal360',
] as const;
export type IntelligenceProjectionId = typeof intelligenceProjectionIds[number];

/** Projection kinds a 360 may be (sorted). */
export const intelligenceProjectionKinds = [
  'agentic_360',
  'context_360',
  'entity_360',
  'infrastructure_360',
  'measurement_360',
  'operational_workbench',
  'relationship_360',
  'risk_360',
  'sequence_360',
] as const;
export type IntelligenceProjectionKind = typeof intelligenceProjectionKinds[number];

/** Implementation states — repo metadata, NOT readiness (sorted). */
export const intelligenceProjectionImplementationStates = [
  'deprecated',
  'implemented',
  'in_flight',
  'registered',
] as const;
export type IntelligenceProjectionImplementationState = typeof intelligenceProjectionImplementationStates[number];

/** Section states a projection result section may carry (sorted). */
export const intelligenceProjectionSectionStates = [
  'available',
  'degraded',
  'empty',
  'missing',
  'not_applicable',
  'stale',
  'suppressed',
  'unknown',
] as const;
export type IntelligenceProjectionSectionState = typeof intelligenceProjectionSectionStates[number];

/** Subject kinds a projection may be asked about (sorted). */
export const intelligenceProjectionSubjectKinds = [
  'agent',
  'campaign',
  'cluster',
  'connection',
  'deployment',
  'entity',
  'episode',
  'infrastructure',
  'journey',
  'population',
  'relationship',
  'source',
] as const;
export type IntelligenceProjectionSubjectKind = typeof intelligenceProjectionSubjectKinds[number];

/** One pending declaration ({id, kind, reason, resolvesInProjection}). */
export interface PendingResolution {
  id: string;
  kind: string;
  reason: string;
  resolvesInProjection: string;
}

export interface ProjectionReadinessRequirements {
  requiresImplementation: boolean;
  requiresDependencies: boolean;
  requiresTenantEntitlement: boolean;
  requiresProviderReadiness: boolean;
  requiresEvidenceHealth: boolean;
}

export interface ProjectionSecurity {
  tenantScoped: boolean;
  requiresAuthorization: boolean;
  requiresHistoricalConsentEvaluation: boolean;
  exportClass: string;
  distillationRisk: string;
}

export interface ProjectionCostProfile {
  class: string;
  supportsAsync: boolean;
}

export interface ProjectionCommercialClassification {
  sellableCapability: boolean;
  meterRefs: readonly string[];
  costClassRefs: readonly string[];
}

export interface ProjectionLegacyBindings {
  routes: readonly string[];
  surfaceIds: readonly string[];
  services: readonly string[];
  migrationMode: string;
  migrationBlueprint: string;
}

/** One registered intelligence projection (mirrors the registry schema). */
export interface IntelligenceProjectionDefinition {
  id: IntelligenceProjectionId;
  displayName: string;
  projectionKind: IntelligenceProjectionKind;
  implementationState: IntelligenceProjectionImplementationState;
  implementationBlueprint: string;
  ownsCanonicalTruth: false;
  subjectKinds: readonly IntelligenceProjectionSubjectKind[];
  canonicalAuthorities: readonly string[];
  hardDependencies: readonly string[];
  projectionDependencies: readonly string[];
  optionalProjectionDependencies: readonly string[];
  inputRefs: readonly string[];
  outputSections: readonly string[];
  supportedTemporalModes: readonly string[];
  surfaceIds: readonly string[];
  capabilityKeys: readonly string[];
  metricRefs: readonly string[];
  graphMutationPolicy: 'read_only' | 'canonical_gateway_only';
  requiresEvidence: boolean;
  requiresDimensionState: boolean;
  requiresFreshness: boolean;
  requiresLimitations: boolean;
  tenantScoped: boolean;
  policyScoped: boolean;
  readinessRequirements: ProjectionReadinessRequirements;
  security: ProjectionSecurity;
  costProfile: ProjectionCostProfile;
  commercialClassification: ProjectionCommercialClassification;
  legacyBindings: ProjectionLegacyBindings;
  deprecatedReason: string | null;
  successorId: string | null;
  pendingAuthority: readonly PendingResolution[];
  pendingReference: readonly PendingResolution[];
}

export const intelligenceProjectionDefinitions: Record<
  IntelligenceProjectionId,
  IntelligenceProjectionDefinition
> = {
  agent360: {
    id: 'agent360',
    displayName: 'Agent 360',
    projectionKind: 'agentic_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/agent360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity'],
    canonicalAuthorities: ['agent_access', 'agent_entities', 'agent_entity', 'agent_executions', 'economic_facts', 'evidence', 'graph', 'identity', 'observations', 'outcome_facts'],
    hardDependencies: ['agentic_runtime_access', 'contract_spine', 'identity_resolution', 'temporal_kernel'],
    projectionDependencies: ['profile360'],
    optionalProjectionDependencies: ['economic360', 'outcome360'],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphResult', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['profile360'],
    capabilityKeys: ['agent360.explore', 'agent360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/agent', '/v1/agents', '/v1/profile360'],
      surfaceIds: ['profile360'],
      services: ['services/api/actions/agent'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/agent360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  campaign360: {
    id: 'campaign360',
    displayName: 'Campaign 360',
    projectionKind: 'measurement_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/campaign360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['campaign', 'episode', 'population', 'source'],
    canonicalAuthorities: ['attribution_credits', 'campaign_facts', 'communication', 'economic', 'journeys', 'outcomes', 'population', 'touchpoints'],
    hardDependencies: ['attribution_architecture', 'contract_spine', 'measurement_outcome_contract'],
    projectionDependencies: ['communication360', 'economic360', 'episode360', 'outcome360', 'population360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphResult', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'outcomes', 'state', 'summary'],
    supportedTemporalModes: ['compare', 'relative', 'window'],
    surfaceIds: ['campaign360', 'comparison_workbench'],
    capabilityKeys: ['campaign360.explore', 'campaign360.read'],
    metricRefs: ['attributed_conversions', 'conversion_rate', 'revenue', 'touchpoints'],
    graphMutationPolicy: 'canonical_gateway_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'high'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/campaign-quality', '/v1/campaign-sources', '/v1/campaigns', '/v1/mapping-review'],
      surfaceIds: ['campaign360', 'comparison_workbench'],
      services: ['services/api/journeys/campaign'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/campaign360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  cluster360: {
    id: 'cluster360',
    displayName: 'Cluster 360',
    projectionKind: 'operational_workbench',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/cluster360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['cluster', 'entity', 'population'],
    canonicalAuthorities: ['cluster_definitions', 'cluster_membership', 'computation', 'graph', 'population'],
    hardDependencies: ['computation_substrate', 'exploration_fabric'],
    projectionDependencies: ['population360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'FilterExpression', 'GraphResult', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'health', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'window'],
    surfaceIds: ['cluster360', 'graph'],
    capabilityKeys: ['cluster360.explore', 'cluster360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/clusters'],
      surfaceIds: ['cluster360', 'graph'],
      services: ['services/api/graph/cluster'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/cluster360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  communication360: {
    id: 'communication360',
    displayName: 'Communication 360',
    projectionKind: 'sequence_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/communication360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'campaign', 'episode', 'journey', 'source'],
    canonicalAuthorities: ['campaign_touchpoints', 'communication_facts', 'entities', 'evidence', 'outcomes'],
    hardDependencies: ['contract_spine', 'temporal_kernel'],
    projectionDependencies: ['episode360', 'outcome360', 'profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['profile360', 'timeline'],
    capabilityKeys: ['communication360.explore', 'communication360.read'],
    metricRefs: ['citation_retention_rate', 'claim_retention_rate', 'contradiction_rate', 'email_click_rate', 'email_open_rate', 'email_reply_rate', 'evidence_retention_rate', 'omission_rate', 'semantic_drift', 'unsupported_addition_rate'],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/comms', '/v1/contact', '/v1/delivery', '/v1/notifications'],
      surfaceIds: ['profile360', 'timeline'],
      services: ['services/api/journeys/comms'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/communication360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  connection360: {
    id: 'connection360',
    displayName: 'Connection 360',
    projectionKind: 'operational_workbench',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/connection360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['connection', 'source'],
    canonicalAuthorities: ['connection_config', 'connection_permissions', 'credential_readiness', 'managed_integration_lifecycle', 'provider_health', 'source_coverage', 'sync_state'],
    hardDependencies: ['reconciled_control_plane', 'upr'],
    projectionDependencies: ['source360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'MutationIntent', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['coverage', 'evidence', 'health', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['connection360'],
    capabilityKeys: ['connection360.explore', 'connection360.read'],
    metricRefs: [],
    graphMutationPolicy: 'canonical_gateway_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/client-sync', '/v1/integrations', '/v1/provider-connections'],
      surfaceIds: ['connection360'],
      services: ['services/api/connectors/provider_runtime'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/connection360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [
      {
        id: 'reconciled_control_plane',
        kind: 'spine',
        reason: 'harness control-plane rollup (PR #529) merged; reconciled control-plane spine not yet formalized as a projection-plane authority',
        resolvesInProjection: 'connection360'
      }
    ],
    pendingReference: []
  },
  economic360: {
    id: 'economic360',
    displayName: 'Value 360',
    projectionKind: 'measurement_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/economic360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'campaign', 'entity', 'episode', 'journey', 'source'],
    canonicalAuthorities: ['ai_execution_facts', 'commerce', 'currency_value_normalization', 'economic_facts', 'graph', 'outcome_facts', 'payments'],
    hardDependencies: ['measurement_outcome_contract', 'temporal_kernel'],
    projectionDependencies: ['outcome360', 'profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphResult', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'outcomes', 'state', 'summary'],
    supportedTemporalModes: ['compare', 'relative', 'window'],
    surfaceIds: ['campaign360', 'economic360', 'product_intelligence'],
    capabilityKeys: ['economic360.explore', 'economic360.read'],
    metricRefs: ['agent_execution_cost', 'ai_execution_cost', 'campaign_cac', 'campaign_ltv', 'campaign_roas', 'campaign_spend', 'entity_execution_cost', 'revenue'],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'high'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/economic', '/v1/profile'],
      surfaceIds: ['campaign360', 'economic360', 'product_intelligence'],
      services: ['services/api/value/economic'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/economic360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  episode360: {
    id: 'episode360',
    displayName: 'Episode 360',
    projectionKind: 'sequence_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/episode360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['campaign', 'entity', 'episode', 'journey'],
    canonicalAuthorities: ['episode_facts', 'events', 'evidence', 'graph', 'journeys', 'temporal'],
    hardDependencies: ['contract_spine', 'journey_continuity', 'temporal_kernel'],
    projectionDependencies: ['profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['episode_context', 'evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['relative', 'window'],
    surfaceIds: ['journeys', 'timeline'],
    capabilityKeys: ['episode360.explore', 'episode360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/events', '/v1/journeys'],
      surfaceIds: ['journeys', 'timeline'],
      services: ['services/api/ingestion/events', 'services/api/journeys/journeys'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/episode360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [
      {
        id: 'journey_continuity',
        kind: 'spine',
        reason: 'journey continuity plane not yet formalized',
        resolvesInProjection: 'episode360'
      }
    ],
    pendingReference: []
  },
  execution360: {
    id: 'execution360',
    displayName: 'Execution 360',
    projectionKind: 'sequence_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/execution360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity', 'episode'],
    canonicalAuthorities: ['actions', 'agent_entities', 'economic_facts', 'episode_facts', 'events', 'evidence', 'execution_facts', 'graph', 'outcome_facts', 'resources', 'temporal_kernel', 'tools'],
    hardDependencies: ['agentic_runtime_access', 'temporal_kernel'],
    projectionDependencies: ['agent360', 'episode360', 'outcome360', 'temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['episode_context', 'evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['timeline'],
    capabilityKeys: ['execution360.explore', 'execution360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/agent', '/v1/agents', '/v1/computations', '/v1/flows', '/v1/jobs'],
      surfaceIds: ['timeline'],
      services: ['services/api/actions/agent', 'services/api/value/flows', 'services/api/workers/jobs'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/execution360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  fraud360: {
    id: 'fraud360',
    displayName: 'Fraud 360',
    projectionKind: 'risk_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/fraud360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity', 'relationship'],
    canonicalAuthorities: ['economic_facts', 'evidence', 'execution_facts', 'fraud_synthesis', 'graph_motifs', 'identity', 'relationship_facts', 'risk_outputs', 'social_observations'],
    hardDependencies: ['evidence_provenance', 'model_governance'],
    projectionDependencies: ['profile360', 'risk360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'health', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['fraud360', 'graph'],
    capabilityKeys: ['fraud360.explore', 'fraud360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'high'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/fraud'],
      surfaceIds: ['fraud360', 'graph'],
      services: ['services/api/intelligence/fraud'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/fraud360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  geographic360: {
    id: 'geographic360',
    displayName: 'Geographic 360',
    projectionKind: 'context_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/geographic360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['entity', 'population', 'source'],
    canonicalAuthorities: ['context_capsules', 'entity_graph', 'geo_observations', 'locations', 'temporal'],
    hardDependencies: ['context_capsule_semantics', 'temporal_kernel'],
    projectionDependencies: ['profile360', 'temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['compare', 'relative', 'window'],
    surfaceIds: ['geographic360'],
    capabilityKeys: ['geographic360.explore', 'geographic360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/geo'],
      surfaceIds: ['geographic360'],
      services: ['services/api/graph/geo'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/geographic360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  infrastructure360: {
    id: 'infrastructure360',
    displayName: 'Infrastructure 360',
    projectionKind: 'infrastructure_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/infrastructure360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['deployment', 'infrastructure'],
    canonicalAuthorities: ['deployments', 'infrastructure_facts', 'infrastructure_state'],
    hardDependencies: ['contract_spine', 'infrastructure_model', 'temporal_kernel'],
    projectionDependencies: [],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['deployments', 'evidence', 'findings', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'compare', 'relative', 'window'],
    surfaceIds: ['infrastructure360'],
    capabilityKeys: ['infrastructure360.explore', 'infrastructure360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/infrastructure'],
      surfaceIds: ['infrastructure360'],
      services: ['services/api/graph/infrastructure'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/infrastructure360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  outcome360: {
    id: 'outcome360',
    displayName: 'Outcome 360',
    projectionKind: 'measurement_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/outcome360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'campaign', 'episode', 'journey', 'population'],
    canonicalAuthorities: ['evidence', 'graph', 'measurement_contract', 'outcome_facts'],
    hardDependencies: ['measurement_outcome_contract', 'temporal_kernel'],
    projectionDependencies: ['temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphResult', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'outcomes', 'state', 'summary'],
    supportedTemporalModes: ['compare', 'relative', 'window'],
    surfaceIds: ['campaign360', 'outcome360'],
    capabilityKeys: ['outcome360.explore', 'outcome360.read'],
    metricRefs: ['journey_completion_rate'],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'high'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/attribution', '/v1/conversions', '/v1/journeys', '/v1/measurement', '/v1/spend'],
      surfaceIds: ['campaign360', 'outcome360'],
      services: ['services/api/journeys/measurement'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/outcome360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  population360: {
    id: 'population360',
    displayName: 'Population 360',
    projectionKind: 'context_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/population360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['cluster', 'entity', 'population'],
    canonicalAuthorities: ['cluster_definitions', 'cohort_membership', 'entities', 'evidence', 'population_definitions', 'temporal'],
    hardDependencies: ['contract_spine', 'grouping_membership'],
    projectionDependencies: ['profile360', 'relationship360', 'temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'GraphResult', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['relative', 'window'],
    surfaceIds: ['population360'],
    capabilityKeys: ['population360.explore', 'population360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/population'],
      surfaceIds: ['population360'],
      services: ['services/api/identity/population'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/population360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  profile360: {
    id: 'profile360',
    displayName: 'Profile 360',
    projectionKind: 'entity_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/profile360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity', 'episode', 'journey'],
    canonicalAuthorities: ['entity_registry', 'episode_facts', 'evidence', 'graph', 'identity', 'journeys', 'observations', 'temporal'],
    hardDependencies: ['contract_spine', 'evidence_provenance', 'identity_resolution', 'temporal_kernel'],
    projectionDependencies: [],
    optionalProjectionDependencies: ['risk360'],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'interactions', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['profile360'],
    capabilityKeys: ['profile360.explore', 'profile360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/profile', '/v1/profile360'],
      surfaceIds: ['profile360'],
      services: ['services/api/identity/profile'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/profile360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  relationship360: {
    id: 'relationship360',
    displayName: 'Relationship 360',
    projectionKind: 'relationship_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/relationship360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity', 'episode', 'population', 'relationship', 'source'],
    canonicalAuthorities: ['cohort_membership', 'evidence', 'graph', 'identity', 'relationship_facts', 'temporal'],
    hardDependencies: ['identity_resolution', 'relationship_fidelity', 'temporal_kernel'],
    projectionDependencies: ['profile360', 'temporal360'],
    optionalProjectionDependencies: ['communication360', 'economic360', 'risk360', 'social360'],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'interactions', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['graph', 'profile360'],
    capabilityKeys: ['relationship360.explore', 'relationship360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/entities', '/v1/graph', '/v1/semantic'],
      surfaceIds: ['graph', 'profile360'],
      services: ['services/api/graph/operational_intelligence', 'services/api/intelligence/semantic_intelligence'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/relationship360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  risk360: {
    id: 'risk360',
    displayName: 'Risk 360',
    projectionKind: 'risk_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/risk360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'cluster', 'entity', 'population', 'relationship', 'source'],
    canonicalAuthorities: ['cluster_membership', 'economic_facts', 'entity_graph', 'evidence', 'model_governance', 'risk_outputs'],
    hardDependencies: ['computation_substrate', 'evidence_provenance', 'model_governance'],
    projectionDependencies: ['cluster360', 'economic360', 'profile360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'health', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['comparison_workbench', 'graph', 'risk360'],
    capabilityKeys: ['risk360.explore', 'risk360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'high'
    },
    costProfile: {
      class: 'heavy',
      supportsAsync: true
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/capability-risk', '/v1/risk-overlays'],
      surfaceIds: ['comparison_workbench', 'graph', 'risk360'],
      services: ['services/api/graph/risk_overlay'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/risk360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  social360: {
    id: 'social360',
    displayName: 'Social 360',
    projectionKind: 'relationship_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/architecture/blueprints/social360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity', 'population', 'relationship', 'source'],
    canonicalAuthorities: ['agent_entities', 'cohort_membership', 'evidence', 'graph', 'identity', 'relationship_facts', 'social_observations', 'source_facts'],
    hardDependencies: ['relationship_fidelity', 'temporal_kernel', 'upr'],
    projectionDependencies: ['profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'interactions', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['profile360'],
    capabilityKeys: ['social360.explore', 'social360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/profile'],
      surfaceIds: ['profile360'],
      services: ['services/api/identity/profile'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/architecture/blueprints/social360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  source360: {
    id: 'source360',
    displayName: 'Source 360',
    projectionKind: 'operational_workbench',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/source360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'connection', 'entity', 'source'],
    canonicalAuthorities: ['evidence', 'ingestion_health', 'provider_registry', 'source_coverage', 'source_provenance', 'source_schema'],
    hardDependencies: ['upr'],
    projectionDependencies: [],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['coverage', 'evidence', 'health', 'state', 'summary'],
    supportedTemporalModes: ['relative', 'window'],
    surfaceIds: ['campaign360'],
    capabilityKeys: ['source360.explore', 'source360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/imports', '/v1/kyber', '/v1/providers'],
      surfaceIds: ['campaign360'],
      services: ['services/api/ingestion/imports'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/source360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  support360: {
    id: 'support360',
    displayName: 'Support 360',
    projectionKind: 'context_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/architecture/blueprints/support360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['entity'],
    canonicalAuthorities: ['communication_facts', 'evidence'],
    hardDependencies: ['contract_spine', 'temporal_kernel'],
    projectionDependencies: [],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['window'],
    surfaceIds: ['support360'],
    capabilityKeys: ['support360.explore', 'support360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: true,
      exportClass: 'governed',
      distillationRisk: 'high'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/experience360/frames'],
      surfaceIds: ['support360'],
      services: ['services/api/journeys/support360'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/architecture/blueprints/support360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
  temporal360: {
    id: 'temporal360',
    displayName: 'Temporal 360',
    projectionKind: 'context_360',
    implementationState: 'implemented',
    implementationBlueprint: 'docs/architecture/blueprints/temporal360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['entity', 'relationship'],
    canonicalAuthorities: ['graph_snapshots', 'mutation_history', 'temporal_kernel', 'validity_state'],
    hardDependencies: ['contract_spine', 'graph_history_replay'],
    projectionDependencies: [],
    optionalProjectionDependencies: [],
    inputRefs: ['GraphResult', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'compare', 'relative', 'window'],
    surfaceIds: ['temporal360'],
    capabilityKeys: ['temporal360.explore', 'temporal360.read'],
    metricRefs: [],
    graphMutationPolicy: 'read_only',
    requiresEvidence: true,
    requiresDimensionState: true,
    requiresFreshness: true,
    requiresLimitations: true,
    tenantScoped: true,
    policyScoped: true,
    readinessRequirements: {
      requiresImplementation: true,
      requiresDependencies: true,
      requiresTenantEntitlement: true,
      requiresProviderReadiness: false,
      requiresEvidenceHealth: true
    },
    security: {
      tenantScoped: true,
      requiresAuthorization: true,
      requiresHistoricalConsentEvaluation: false,
      exportClass: 'governed',
      distillationRisk: 'moderate'
    },
    costProfile: {
      class: 'moderate',
      supportsAsync: false
    },
    commercialClassification: {
      sellableCapability: true,
      meterRefs: [],
      costClassRefs: []
    },
    legacyBindings: {
      routes: ['/v1/graph', '/v1/preferences'],
      surfaceIds: ['temporal360'],
      services: ['services/api/shared/temporal'],
      migrationMode: 'converged',
      migrationBlueprint: 'docs/architecture/blueprints/temporal360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: []
  },
};

export interface ProjectionDependencyGraphEntry {
  required: readonly IntelligenceProjectionId[];
  optional: readonly IntelligenceProjectionId[];
}

export const projectionDependencyGraph: Record<
  IntelligenceProjectionId,
  ProjectionDependencyGraphEntry
> = {
  agent360: { required: ['profile360'], optional: ['economic360', 'outcome360'] },
  campaign360: { required: ['communication360', 'economic360', 'episode360', 'outcome360', 'population360'], optional: [] },
  cluster360: { required: ['population360'], optional: [] },
  communication360: { required: ['episode360', 'outcome360', 'profile360', 'relationship360'], optional: [] },
  connection360: { required: ['source360'], optional: [] },
  economic360: { required: ['outcome360', 'profile360', 'relationship360'], optional: [] },
  episode360: { required: ['profile360', 'relationship360'], optional: [] },
  execution360: { required: ['agent360', 'episode360', 'outcome360', 'temporal360'], optional: [] },
  fraud360: { required: ['profile360', 'risk360'], optional: [] },
  geographic360: { required: ['profile360', 'temporal360'], optional: [] },
  infrastructure360: { required: [], optional: [] },
  outcome360: { required: ['temporal360'], optional: [] },
  population360: { required: ['profile360', 'relationship360', 'temporal360'], optional: [] },
  profile360: { required: [], optional: ['risk360'] },
  relationship360: { required: ['profile360', 'temporal360'], optional: ['communication360', 'economic360', 'risk360', 'social360'] },
  risk360: { required: ['cluster360', 'economic360', 'profile360'], optional: [] },
  social360: { required: ['profile360', 'relationship360'], optional: [] },
  source360: { required: [], optional: [] },
  support360: { required: [], optional: [] },
  temporal360: { required: [], optional: [] },
};

export const pendingAuthorities: Partial<
  Record<IntelligenceProjectionId, readonly PendingResolution[]>
> = {
  connection360: [
    {
      id: 'reconciled_control_plane',
      kind: 'spine',
      reason: 'harness control-plane rollup (PR #529) merged; reconciled control-plane spine not yet formalized as a projection-plane authority',
      resolvesInProjection: 'connection360'
    }
  ],
  episode360: [
    {
      id: 'journey_continuity',
      kind: 'spine',
      reason: 'journey continuity plane not yet formalized',
      resolvesInProjection: 'episode360'
    }
  ],
};

export const pendingReferences: Partial<
  Record<IntelligenceProjectionId, readonly PendingResolution[]>
> = {
};

export const product360SurfaceCatalogVersion = "0.1.0" as const;

/** Productized 360 surfaces; distinct from the technical projection provider registry. */
export const PRODUCT_360_SURFACE_IDS = [
  'account360',
  'agent360',
  'campaign360',
  'commerce360',
  'communications360',
  'episode360',
  'execution360',
  'identity360',
  'journey360',
  'location360',
  'memory360',
  'profile360',
  'risk360',
  'signals360',
  'social360',
  'support360',
  'value360',
  'workflow360',
] as const;
export type Product360SurfaceId = typeof PRODUCT_360_SURFACE_IDS[number];

/** Aggregate 360 frame states; section states remain projection-owned. */
export const EXPERIENCE_360_FRAME_STATES = [
  'conflicted',
  'degraded',
  'empty',
  'missing',
  'partial',
  'ready',
  'stale',
  'suppressed',
  'unavailable',
  'unknown',
] as const;
export type Experience360FrameState = typeof EXPERIENCE_360_FRAME_STATES[number];

export type Product360SlotRequirement = 'required' | 'optional';
export type Product360BindingRole = 'primary' | 'supporting';
export type Product360DirectProviderKind = 'surface_authority_reader' | 'surface_frame_provider';
export interface Product360SlotProjectionBinding {
  projectionId: IntelligenceProjectionId;
  role: Product360BindingRole;
  subjectKinds: readonly IntelligenceProjectionSubjectKind[];
  sectionIds: readonly string[];
}
export interface Product360DomainSlot {
  id: string;
  requirement: Product360SlotRequirement;
  description: string;
  canonicalAuthorityRefs: readonly string[];
  projectionBindings: readonly Product360SlotProjectionBinding[];
}
export interface Product360ProviderBinding {
  projectionId: IntelligenceProjectionId;
  role: Product360BindingRole;
  bindingStatus: 'catalog_only';
  providerImplementationState: IntelligenceProjectionImplementationState;
}
export interface Product360DirectProviderBinding {
  providerClass: string;
  providerKind: Product360DirectProviderKind;
  bindingStatus: 'runtime_wired';
  subjectKinds: readonly IntelligenceProjectionSubjectKind[];
  domainSlotIds: readonly string[];
  implementationRef: string;
  runtimeBindingRef: string;
}
export interface Product360SurfaceDefinition {
  id: Product360SurfaceId;
  displayName: string;
  description: string;
  contractStatus: 'draft_pending_source_alignment' | 'reconstructed_pending_source_alignment' | 'source_aligned';
  subjectKinds: readonly IntelligenceProjectionSubjectKind[];
  domainSlots: readonly Product360DomainSlot[];
  projectionBindings: readonly Product360ProviderBinding[];
  directProviderBindings?: readonly Product360DirectProviderBinding[];
  sourceOfTruth: { canonicalAuthorities: readonly string[]; ownsCanonicalTruth: false; prohibitedOwnership: readonly string[] };
  freshnessPolicy: { required: true; maxAgeSeconds: number | null; sourceTimestamps: string; missingTimestamp: string; onStale: string; requirementStatus: string };
  policyBehavior: { tenantScopeRequired: true; authorizationBeforeRead: true; policyEvaluation: string; historicalConsentEvaluation: string; redactionBehavior: string; requirementStatus: string };
  backendCapabilities: { required: readonly string[]; projectionCapabilityKeys: readonly string[]; providerCapabilityStatus: string };
  lensContract: { expectedCount: number | null; lensIds: readonly string[]; sourceAlignmentStatus: string };
}
export const PRODUCT_360_SURFACE_DEFINITIONS: Record<
  Product360SurfaceId,
  Product360SurfaceDefinition
> = {
  account360: {
    id: 'account360',
    displayName: 'Account 360',
    description: 'Governed account-level view composed from canonical entity, relationship, economic, and evidence authorities.',
    contractStatus: 'reconstructed_pending_source_alignment',
    subjectKinds: ['entity'],
    domainSlots: [
      {
        id: 'account_identity_and_state',
        requirement: 'required',
        description: 'Resolved account identity and state.',
        canonicalAuthorityRefs: ['entity_registry', 'identity'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'account_relationships',
        requirement: 'required',
        description: 'Relationships associated with the account.',
        canonicalAuthorityRefs: ['graph', 'relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'interactions', 'summary']
          }
        ]
      },
      {
        id: 'economic_context',
        requirement: 'optional',
        description: 'Economic facts associated with the account.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'economic_facts'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'evidence_and_limitations',
        requirement: 'required',
        description: 'Evidence and coverage for account context.',
        canonicalAuthorityRefs: ['evidence'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'findings']
          }
        ]
      }
    ],
    projectionBindings: [
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'relationship360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    directProviderBindings: [
      {
        providerClass: 'Account360Provider',
        providerKind: 'surface_frame_provider',
        bindingStatus: 'runtime_wired',
        subjectKinds: ['entity'],
        domainSlotIds: ['account_identity_and_state'],
        implementationRef: 'services/api/identity/account360_provider.py',
        runtimeBindingRef: 'services/api/shared/intelligence_projections/frame_runtime.py'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['ai_execution_facts', 'economic_facts', 'entity_registry', 'evidence', 'graph', 'identity', 'relationship_facts'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['economic360.explore', 'economic360.read', 'profile360.explore', 'profile360.read', 'relationship360.explore', 'relationship360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    }
  },
  agent360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['agent360.explore', 'agent360.read', 'communication360.explore', 'communication360.read', 'economic360.explore', 'economic360.read', 'execution360.explore', 'execution360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read', 'relationship360.explore', 'relationship360.read', 'risk360.explore', 'risk360.read', 'social360.explore', 'social360.read', 'source360.explore', 'source360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of an agent identity, actor attribution, authority and delegation, execution activity, communications, risk, evidence, and measured outcomes.',
    displayName: 'Agent 360',
    domainSlots: [
      {
        id: 'actions_tools_resources',
        requirement: 'required',
        description: 'Observed actions, tools, and resource activity.',
        canonicalAuthorityRefs: ['actions', 'resources', 'tools'],
        projectionBindings: [
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'interactions']
          }
        ]
      },
      {
        canonicalAuthorityRefs: ['agent_entities', 'identity'],
        description: 'Canonical actor and subject attribution attached to agent activity.',
        id: 'actor_attribution',
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state']
          },
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state']
          }
        ],
        requiredFrameMetadata: ['slotActorAttribution'],
        requirement: 'required'
      },
      {
        id: 'agent_identity',
        requirement: 'required',
        description: 'Agent identity and canonical entity context.',
        canonicalAuthorityRefs: ['agent_entity', 'identity'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['state', 'summary']
          },
          {
            projectionId: 'profile360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        canonicalAuthorityRefs: ['agent_access', 'identity'],
        description: 'Agent access, authority context, and delegation lineage.',
        id: 'authority_and_delegation',
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state']
          }
        ],
        requiredFrameMetadata: ['slotActorAttribution', 'slotAuthorityDecision'],
        requirement: 'required'
      },
      {
        id: 'business_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes linked to the agent activity.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['agent'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'communications',
        requirement: 'optional',
        description: 'Observed agent messages joined through tenant-scoped inbox records, alongside communication events associated with agent work.',
        canonicalAuthorityRefs: ['communication_facts', 'observations'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent'],
            sectionIds: ['evidence', 'interactions']
          },
          {
            projectionId: 'communication360',
            role: 'primary',
            subjectKinds: ['agent'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      },
      {
        id: 'economic_cost_and_settlement',
        requirement: 'optional',
        description: 'Economic facts and authoritative payment or commerce evidence.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'commerce', 'economic_facts', 'payments'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'summary']
          }
        ]
      },
      {
        id: 'execution_lifecycle',
        requirement: 'required',
        description: 'Execution lifecycle evidence and temporal trace.',
        canonicalAuthorityRefs: ['agent_executions', 'execution_facts'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'timeline']
          },
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state', 'timeline']
          }
        ]
      },
      {
        id: 'risk_and_contagion',
        requirement: 'optional',
        description: 'Risk, fraud, social, and relationship context with source evidence.',
        canonicalAuthorityRefs: ['agent_entities', 'identity', 'relationship_facts', 'risk_outputs', 'social_observations'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'interactions']
          },
          {
            projectionId: 'risk360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'findings']
          },
          {
            projectionId: 'social360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'findings']
          }
        ]
      },
      {
        id: 'source_evidence_lineage',
        requirement: 'required',
        description: 'Evidence and source provenance for claims included in the frame.',
        canonicalAuthorityRefs: ['evidence', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence']
          },
          {
            projectionId: 'source360',
            role: 'primary',
            subjectKinds: ['agent'],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'temporal_relationship_context',
        requirement: 'optional',
        description: 'Temporal state and relationship context surrounding agent activity.',
        canonicalAuthorityRefs: ['graph', 'relationship_facts', 'temporal_kernel'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['interactions', 'timeline']
          },
          {
            projectionId: 'temporal360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'agent360',
    lensContract: {
      expectedCount: 8,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'agent360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'communication360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'execution360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'relationship360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'risk360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'social360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'source360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'temporal360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['actions', 'agent_access', 'agent_entities', 'agent_entity', 'agent_executions', 'ai_execution_facts', 'commerce', 'communication_facts', 'economic_facts', 'evidence', 'execution_facts', 'graph', 'identity', 'observations', 'outcome_facts', 'payments', 'relationship_facts', 'resources', 'risk_outputs', 'social_observations', 'source_provenance', 'temporal_kernel', 'tools'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'entity']
  },
  campaign360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['campaign360.explore', 'campaign360.read', 'cluster360.explore', 'cluster360.read', 'communication360.explore', 'communication360.read', 'economic360.explore', 'economic360.read', 'episode360.explore', 'episode360.read', 'outcome360.explore', 'outcome360.read', 'population360.explore', 'population360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed campaign view of campaign facts, touchpoints, journeys, communications, attribution, outcomes, and optional economic context.',
    displayName: 'Campaign 360',
    domainSlots: [
      {
        id: 'attribution_and_outcomes',
        requirement: 'required',
        description: 'Attribution credits and measured outcomes.',
        canonicalAuthorityRefs: ['attribution_credits', 'outcome_facts', 'outcomes'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'population', 'source'],
            sectionIds: ['findings', 'outcomes']
          },
          {
            projectionId: 'outcome360',
            role: 'supporting',
            subjectKinds: ['campaign', 'episode', 'population'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'campaign_identity_and_state',
        requirement: 'required',
        description: 'Campaign facts and state.',
        canonicalAuthorityRefs: ['campaign_facts'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'population', 'source'],
            sectionIds: ['evidence', 'state', 'summary']
          }
        ]
      },
      {
        id: 'economic_context',
        requirement: 'optional',
        description: 'Economic facts associated with campaigns.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'economic', 'economic_facts'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'supporting',
            subjectKinds: ['campaign', 'episode', 'population', 'source'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          },
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'source'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'journey_and_episode_context',
        requirement: 'required',
        description: 'Journeys and episodes associated with campaign activity.',
        canonicalAuthorityRefs: ['episode_facts', 'journeys'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode'],
            sectionIds: ['evidence', 'timeline']
          }
        ]
      },
      {
        id: 'population_context',
        requirement: 'optional',
        description: 'Population context for campaign reach and measurement.',
        canonicalAuthorityRefs: ['population', 'population_definitions'],
        projectionBindings: [
          {
            projectionId: 'cluster360',
            role: 'supporting',
            subjectKinds: ['population'],
            sectionIds: ['evidence', 'state', 'summary']
          },
          {
            projectionId: 'population360',
            role: 'primary',
            subjectKinds: ['population'],
            sectionIds: ['findings', 'state', 'summary']
          }
        ]
      },
      {
        id: 'touchpoints_and_communications',
        requirement: 'required',
        description: 'Campaign touchpoints and linked communication evidence.',
        canonicalAuthorityRefs: ['campaign_touchpoints', 'communication_facts', 'touchpoints'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'population', 'source'],
            sectionIds: ['evidence', 'outcomes']
          },
          {
            projectionId: 'communication360',
            role: 'supporting',
            subjectKinds: ['campaign', 'episode', 'source'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'campaign360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'campaign360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'cluster360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'communication360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'episode360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'population360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['ai_execution_facts', 'attribution_credits', 'campaign_facts', 'campaign_touchpoints', 'communication_facts', 'economic', 'economic_facts', 'episode_facts', 'journeys', 'outcome_facts', 'outcomes', 'population', 'population_definitions', 'touchpoints'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['campaign', 'episode', 'population', 'source']
  },
  commerce360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['campaign360.explore', 'campaign360.read', 'economic360.explore', 'economic360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of commerce and payment facts, economic value, attributed outcomes, and supporting evidence.',
    displayName: 'Commerce 360',
    domainSlots: [
      {
        id: 'attribution_and_campaign_context',
        requirement: 'optional',
        description: 'Campaign attribution associated with commerce activity.',
        canonicalAuthorityRefs: ['attribution_credits', 'campaign_facts'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'commerce_and_payment_facts',
        requirement: 'required',
        description: 'Commerce and payment facts with authoritative source evidence.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'commerce', 'economic_facts', 'payments'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['campaign', 'entity', 'journey'],
            sectionIds: ['evidence', 'outcomes', 'state', 'summary']
          }
        ]
      },
      {
        id: 'economic_value_and_normalization',
        requirement: 'required',
        description: 'Economic value and currency normalization context.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'currency_value_normalization', 'economic_facts'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['campaign', 'entity', 'journey'],
            sectionIds: ['evidence', 'summary']
          }
        ]
      },
      {
        id: 'entity_context',
        requirement: 'required',
        description: 'Resolved entity context for commerce subjects.',
        canonicalAuthorityRefs: ['entity_registry', 'identity'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'state', 'summary']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes associated with commerce facts.',
        canonicalAuthorityRefs: ['measurement_contract', 'outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['campaign'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'commerce360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'campaign360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['ai_execution_facts', 'attribution_credits', 'campaign_facts', 'commerce', 'currency_value_normalization', 'economic_facts', 'entity_registry', 'identity', 'measurement_contract', 'outcome_facts', 'payments'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['campaign', 'entity', 'journey']
  },
  communications360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['campaign360.explore', 'campaign360.read', 'communication360.explore', 'communication360.read', 'episode360.explore', 'episode360.read', 'outcome360.explore', 'outcome360.read', 'source360.explore', 'source360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of communication facts, delivery and engagement evidence, campaign and journey context, and applicable consent policy.',
    displayName: 'Communications 360',
    domainSlots: [
      {
        id: 'campaign_context',
        requirement: 'optional',
        description: 'Campaign touchpoints associated with communications.',
        canonicalAuthorityRefs: ['campaign_facts', 'campaign_touchpoints'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'source'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          },
          {
            projectionId: 'communication360',
            role: 'supporting',
            subjectKinds: ['campaign', 'episode', 'journey', 'source'],
            sectionIds: ['evidence', 'state']
          }
        ]
      },
      {
        id: 'communication_events',
        requirement: 'required',
        description: 'Communication facts and evidence about events and interactions.',
        canonicalAuthorityRefs: ['communication_facts', 'evidence'],
        projectionBindings: [
          {
            projectionId: 'communication360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'journey', 'source'],
            sectionIds: ['evidence', 'interactions', 'summary', 'timeline']
          }
        ]
      },
      {
        id: 'journey_and_episode_context',
        requirement: 'optional',
        description: 'Journey and episode context for communication activity.',
        canonicalAuthorityRefs: ['episode_facts', 'events', 'journeys'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'journey'],
            sectionIds: ['evidence', 'timeline']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes associated with communications.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'journey'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'source_and_policy_context',
        requirement: 'required',
        description: 'Source lineage for communications; consent and policy are evaluated by their governing authorities.',
        canonicalAuthorityRefs: ['provider_registry', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'source360',
            role: 'primary',
            subjectKinds: ['source'],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'communications360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'campaign360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'communication360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'episode360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'source360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['campaign_facts', 'campaign_touchpoints', 'communication_facts', 'episode_facts', 'events', 'evidence', 'journeys', 'outcome_facts', 'provider_registry', 'source_provenance'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['campaign', 'episode', 'journey', 'source']
  },
  episode360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['campaign360.explore', 'campaign360.read', 'communication360.explore', 'communication360.read', 'episode360.explore', 'episode360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read', 'relationship360.explore', 'relationship360.read', 'source360.explore', 'source360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed time-bounded view of related events and journey activity, with entity context, evidence, and optional outcomes.',
    displayName: 'Episode 360',
    domainSlots: [
      {
        id: 'communication_context',
        requirement: 'optional',
        description: 'Communication events associated with the episode.',
        canonicalAuthorityRefs: ['communication_facts'],
        projectionBindings: [
          {
            projectionId: 'communication360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      },
      {
        id: 'entity_and_relationship_context',
        requirement: 'required',
        description: 'Canonical identity for entity and episode subjects, campaign identity for campaign subjects, and graph relationships where the subject has a supported entity graph.',
        canonicalAuthorityRefs: ['campaign_facts', 'episode_facts', 'graph', 'identity', 'relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign'],
            sectionIds: ['evidence', 'state', 'summary']
          },
          {
            projectionId: 'episode360',
            role: 'supporting',
            subjectKinds: ['campaign', 'entity', 'episode'],
            sectionIds: ['episode_context']
          },
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['entity', 'episode'],
            sectionIds: ['evidence', 'state', 'summary']
          },
          {
            projectionId: 'relationship360',
            role: 'supporting',
            subjectKinds: ['entity', 'episode'],
            sectionIds: ['evidence', 'interactions']
          }
        ]
      },
      {
        id: 'episode_identity_and_state',
        requirement: 'required',
        description: 'Episode identity, state, and canonical episode facts.',
        canonicalAuthorityRefs: ['episode_facts'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['campaign', 'entity', 'episode'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'event_and_journey_timeline',
        requirement: 'required',
        description: 'Ordered event, journey, and temporal context.',
        canonicalAuthorityRefs: ['events', 'journeys', 'temporal_kernel'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['campaign', 'entity', 'episode'],
            sectionIds: ['timeline']
          },
          {
            projectionId: 'temporal360',
            role: 'supporting',
            subjectKinds: ['entity'],
            sectionIds: ['state', 'timeline']
          }
        ]
      },
      {
        id: 'evidence_and_source_lineage',
        requirement: 'required',
        description: 'Evidence and source lineage for episode facts.',
        canonicalAuthorityRefs: ['evidence', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['campaign', 'entity', 'episode'],
            sectionIds: ['evidence']
          },
          {
            projectionId: 'source360',
            role: 'supporting',
            subjectKinds: [],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes linked to the episode.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'episode360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'campaign360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'communication360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'episode360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'relationship360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'source360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'temporal360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['campaign_facts', 'communication_facts', 'episode_facts', 'events', 'evidence', 'graph', 'identity', 'journeys', 'outcome_facts', 'relationship_facts', 'source_provenance', 'temporal_kernel'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['campaign', 'entity', 'episode']
  },
  execution360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['agent360.explore', 'agent360.read', 'economic360.explore', 'economic360.read', 'episode360.explore', 'episode360.read', 'execution360.explore', 'execution360.read', 'outcome360.explore', 'outcome360.read', 'source360.explore', 'source360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of one execution lifecycle, attributed actors and delegation, action/tool/resource activity, evidence, and outcomes.',
    displayName: 'Execution 360',
    domainSlots: [
      {
        id: 'action_tool_resource_trace',
        requirement: 'required',
        description: 'Observed actions, tools, and resources in the execution.',
        canonicalAuthorityRefs: ['actions', 'resources', 'tools'],
        projectionBindings: [
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'episode'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      },
      {
        canonicalAuthorityRefs: ['agent_access', 'agent_entities', 'identity'],
        description: 'Agent and actor attribution plus authority context.',
        id: 'actor_and_delegation',
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state']
          },
          {
            projectionId: 'execution360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity', 'episode'],
            sectionIds: ['evidence', 'state']
          }
        ],
        requiredFrameMetadata: ['slotActorAttribution', 'slotAuthorityDecision'],
        requirement: 'required'
      },
      {
        id: 'economic_and_business_outcomes',
        requirement: 'optional',
        description: 'Exact AI execution costs and separately measured business outcomes linked to a run.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'economic_facts', 'outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'episode'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          },
          {
            projectionId: 'outcome360',
            role: 'supporting',
            subjectKinds: ['episode'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'evidence_and_lineage',
        requirement: 'required',
        description: 'Evidence and source trace for execution claims.',
        canonicalAuthorityRefs: ['evidence', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'episode'],
            sectionIds: ['evidence']
          },
          {
            projectionId: 'source360',
            role: 'supporting',
            subjectKinds: [],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'execution_identity_and_state',
        requirement: 'required',
        description: 'Execution identity, lifecycle state, and execution facts.',
        canonicalAuthorityRefs: ['agent_executions', 'execution_facts'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'timeline']
          },
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'episode'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'temporal_and_episode_context',
        requirement: 'required',
        description: 'Execution time context and associated episode.',
        canonicalAuthorityRefs: ['episode_facts', 'events', 'temporal_kernel'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'supporting',
            subjectKinds: ['entity', 'episode'],
            sectionIds: ['evidence', 'timeline']
          },
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent'],
            sectionIds: ['episode_context', 'evidence', 'timeline']
          },
          {
            projectionId: 'temporal360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['state', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'execution360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'agent360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'episode360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'execution360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'source360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'temporal360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['actions', 'agent_access', 'agent_entities', 'agent_executions', 'ai_execution_facts', 'economic_facts', 'episode_facts', 'events', 'evidence', 'execution_facts', 'identity', 'outcome_facts', 'resources', 'source_provenance', 'temporal_kernel', 'tools'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'entity', 'episode']
  },
  identity360: {
    id: 'identity360',
    displayName: 'Identity 360',
    description: 'Governed view of resolved identities, source identifiers, actor bindings, relationships, and supporting evidence.',
    contractStatus: 'reconstructed_pending_source_alignment',
    subjectKinds: ['agent', 'entity', 'source'],
    domainSlots: [
      {
        id: 'actor_and_agent_binding',
        requirement: 'optional',
        description: 'Agent identity and actor binding evidence.',
        canonicalAuthorityRefs: ['agent_access', 'agent_entities', 'agent_entity'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state']
          },
          {
            projectionId: 'execution360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state']
          }
        ]
      },
      {
        id: 'identity_evidence',
        requirement: 'required',
        description: 'Evidence and limitations associated with the identity view.',
        canonicalAuthorityRefs: ['evidence'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence']
          }
        ]
      },
      {
        id: 'relationship_identity_context',
        requirement: 'optional',
        description: 'Relationship facts associated with the resolved entity.',
        canonicalAuthorityRefs: ['graph', 'relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'interactions']
          }
        ]
      },
      {
        id: 'resolved_subject_identity',
        requirement: 'required',
        description: 'Resolved identity and entity registry state.',
        canonicalAuthorityRefs: ['entity_registry', 'identity'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'source_identifier_lineage',
        requirement: 'required',
        description: 'Source provenance and source identifiers supporting identity resolution.',
        canonicalAuthorityRefs: ['provider_registry', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'source360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['coverage', 'evidence', 'summary']
          }
        ]
      }
    ],
    projectionBindings: [
      {
        projectionId: 'agent360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'execution360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'relationship360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'source360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    directProviderBindings: [
      {
        providerClass: 'Identity360Provider',
        providerKind: 'surface_authority_reader',
        bindingStatus: 'runtime_wired',
        subjectKinds: ['agent', 'entity', 'source'],
        domainSlotIds: ['identity_evidence', 'relationship_identity_context', 'resolved_subject_identity', 'source_identifier_lineage'],
        implementationRef: 'services/api/identity/identity/identity360_provider.py',
        runtimeBindingRef: 'services/api/shared/intelligence_projections/frame_runtime.py'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['agent_access', 'agent_entities', 'agent_entity', 'entity_registry', 'evidence', 'graph', 'identity', 'provider_registry', 'relationship_facts', 'source_provenance'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['agent360.explore', 'agent360.read', 'execution360.explore', 'execution360.read', 'profile360.explore', 'profile360.read', 'relationship360.explore', 'relationship360.read', 'source360.explore', 'source360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    }
  },
  journey360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['communication360.explore', 'communication360.read', 'episode360.explore', 'episode360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed temporal view of journey state, stages, events, handoffs, and measured outcomes.',
    displayName: 'Journey 360',
    domainSlots: [
      {
        id: 'communication_handoffs',
        requirement: 'optional',
        description: 'Communication events associated with journey stages.',
        canonicalAuthorityRefs: ['communication_facts'],
        projectionBindings: [
          {
            projectionId: 'communication360',
            role: 'primary',
            subjectKinds: ['episode', 'journey'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      },
      {
        id: 'entity_context',
        requirement: 'required',
        description: 'Resolved linked user-profile context for entity, journey, or episode subjects; parent identity is not substituted for the requested subject.',
        canonicalAuthorityRefs: ['episode_facts', 'graph', 'identity', 'journeys'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['entity', 'episode', 'journey'],
            sectionIds: ['evidence', 'state', 'summary']
          }
        ]
      },
      {
        id: 'events_and_episode_context',
        requirement: 'required',
        description: 'Events and episode facts associated with the journey.',
        canonicalAuthorityRefs: ['episode_facts', 'events'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['entity', 'episode', 'journey'],
            sectionIds: ['evidence', 'timeline']
          }
        ]
      },
      {
        id: 'journey_state_and_path',
        requirement: 'required',
        description: 'Journey state and ordered path context.',
        canonicalAuthorityRefs: ['journeys', 'temporal_kernel'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['entity', 'episode', 'journey'],
            sectionIds: ['state', 'summary', 'timeline']
          },
          {
            projectionId: 'temporal360',
            role: 'supporting',
            subjectKinds: ['entity'],
            sectionIds: ['state', 'timeline']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes associated with the journey.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['episode'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'journey360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'communication360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'episode360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'temporal360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['communication_facts', 'episode_facts', 'events', 'graph', 'identity', 'journeys', 'outcome_facts', 'temporal_kernel'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['entity', 'episode', 'journey']
  },
  location360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['geographic360.explore', 'geographic360.read', 'population360.explore', 'population360.read', 'profile360.explore', 'profile360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of locations and geographic observations linked to entities, populations, and temporal context.',
    displayName: 'Location 360',
    domainSlots: [
      {
        id: 'entity_graph_context',
        requirement: 'required',
        description: 'Entity graph context linked to locations.',
        canonicalAuthorityRefs: ['entity_graph', 'graph'],
        projectionBindings: [
          {
            projectionId: 'geographic360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'source'],
            sectionIds: ['findings', 'summary']
          },
          {
            projectionId: 'profile360',
            role: 'supporting',
            subjectKinds: ['entity'],
            sectionIds: ['findings', 'summary']
          }
        ]
      },
      {
        id: 'geographic_observations',
        requirement: 'required',
        description: 'Observed geographic facts and their temporal context.',
        canonicalAuthorityRefs: ['geo_observations', 'temporal'],
        projectionBindings: [
          {
            projectionId: 'geographic360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'source'],
            sectionIds: ['evidence', 'timeline']
          }
        ]
      },
      {
        id: 'location_identity_and_state',
        requirement: 'required',
        description: 'Location registry and geographic context.',
        canonicalAuthorityRefs: ['context_capsules', 'locations'],
        projectionBindings: [
          {
            projectionId: 'geographic360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'source'],
            sectionIds: ['evidence', 'state', 'summary']
          }
        ]
      },
      {
        id: 'population_context',
        requirement: 'optional',
        description: 'Population context for a location.',
        canonicalAuthorityRefs: ['cohort_membership', 'population_definitions'],
        projectionBindings: [
          {
            projectionId: 'population360',
            role: 'primary',
            subjectKinds: ['entity', 'population'],
            sectionIds: ['findings', 'state', 'summary']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'location360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'geographic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'population360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['cohort_membership', 'context_capsules', 'entity_graph', 'geo_observations', 'graph', 'locations', 'population_definitions', 'temporal'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['entity', 'population', 'source']
  },
  memory360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['agent360.explore', 'agent360.read', 'episode360.explore', 'episode360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read', 'relationship360.explore', 'relationship360.read', 'source360.explore', 'source360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed temporal and evidentiary view of entity and agent history, episodes, and observed state; it does not own memory truth.',
    displayName: 'Memory 360',
    domainSlots: [
      {
        id: 'entity_and_agent_context',
        requirement: 'required',
        description: 'Entity and agent context for history attribution.',
        canonicalAuthorityRefs: ['agent_entity', 'agent_executions', 'identity'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state', 'summary']
          },
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'episodes_events_and_journeys',
        requirement: 'required',
        description: 'Episode, event, and journey context.',
        canonicalAuthorityRefs: ['episode_facts', 'events', 'journeys'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['entity', 'episode', 'journey'],
            sectionIds: ['evidence', 'summary', 'timeline']
          }
        ]
      },
      {
        id: 'evidence_and_provenance',
        requirement: 'required',
        description: 'Evidence and source provenance for retained history claims.',
        canonicalAuthorityRefs: ['evidence', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['entity', 'episode', 'journey'],
            sectionIds: ['evidence']
          },
          {
            projectionId: 'source360',
            role: 'supporting',
            subjectKinds: [],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes related to retained history.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['episode'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'relationship_context',
        requirement: 'optional',
        description: 'Relationship context associated with the subject history.',
        canonicalAuthorityRefs: ['relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      },
      {
        id: 'temporal_history',
        requirement: 'required',
        description: 'Temporal state, validity, and mutation history.',
        canonicalAuthorityRefs: ['mutation_history', 'temporal_kernel', 'validity_state'],
        projectionBindings: [
          {
            projectionId: 'temporal360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'state', 'summary', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'memory360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'agent360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'episode360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'relationship360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'source360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'temporal360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['agent_entity', 'agent_executions', 'episode_facts', 'events', 'evidence', 'identity', 'journeys', 'mutation_history', 'outcome_facts', 'relationship_facts', 'source_provenance', 'temporal_kernel', 'validity_state'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'entity', 'episode', 'journey']
  },
  profile360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['economic360.explore', 'economic360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read', 'relationship360.explore', 'relationship360.read', 'risk360.explore', 'risk360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed entity-level contextual frame combining identity, observations, relationships, evidence, and optional risk and value context.',
    displayName: 'Profile 360',
    domainSlots: [
      {
        id: 'economic_value_context',
        requirement: 'optional',
        description: 'Economic facts and measured outcomes.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'economic_facts', 'outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          },
          {
            projectionId: 'outcome360',
            role: 'supporting',
            subjectKinds: [],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'entity_identity',
        requirement: 'required',
        description: 'Resolved entity identity and registry context.',
        canonicalAuthorityRefs: ['entity_registry', 'identity'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'evidence_and_limitations',
        requirement: 'required',
        description: 'Evidence supporting the displayed profile claims.',
        canonicalAuthorityRefs: ['evidence'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'findings']
          }
        ]
      },
      {
        id: 'observed_state_and_activity',
        requirement: 'required',
        description: 'Observed state and temporal activity with explicit provenance.',
        canonicalAuthorityRefs: ['graph', 'observations', 'temporal'],
        projectionBindings: [
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['interactions', 'state', 'timeline']
          }
        ]
      },
      {
        id: 'relationship_context',
        requirement: 'optional',
        description: 'Relationships around the entity.',
        canonicalAuthorityRefs: ['relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'interactions', 'timeline']
          }
        ]
      },
      {
        id: 'risk_context',
        requirement: 'optional',
        description: 'Governed risk and fraud context.',
        canonicalAuthorityRefs: ['model_governance', 'risk_outputs'],
        projectionBindings: [
          {
            projectionId: 'risk360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'findings', 'summary']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'profile360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'outcome360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'relationship360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'risk360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['ai_execution_facts', 'economic_facts', 'entity_registry', 'evidence', 'graph', 'identity', 'model_governance', 'observations', 'outcome_facts', 'relationship_facts', 'risk_outputs', 'temporal'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'entity']
  },
  risk360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['economic360.explore', 'economic360.read', 'execution360.explore', 'execution360.read', 'fraud360.explore', 'fraud360.read', 'relationship360.explore', 'relationship360.read', 'risk360.explore', 'risk360.read', 'social360.explore', 'social360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of risk findings, evidence, relationship and economic exposure, with explicit coverage and uncertainty.',
    displayName: 'Risk 360',
    domainSlots: [
      {
        id: 'economic_exposure',
        requirement: 'optional',
        description: 'Economic facts associated with the risk subject and network.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'economic_facts'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'execution_exposure',
        requirement: 'optional',
        description: 'Execution facts associated with an agent or execution subject.',
        canonicalAuthorityRefs: ['execution_facts'],
        projectionBindings: [
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'summary', 'timeline']
          }
        ]
      },
      {
        id: 'fraud_and_social_patterns',
        requirement: 'optional',
        description: 'Fraud synthesis, graph motifs, and social observations.',
        canonicalAuthorityRefs: ['fraud_synthesis', 'graph_motifs', 'social_observations'],
        projectionBindings: [
          {
            projectionId: 'fraud360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'relationship'],
            sectionIds: ['evidence', 'findings', 'health']
          },
          {
            projectionId: 'social360',
            role: 'supporting',
            subjectKinds: ['entity', 'relationship'],
            sectionIds: ['evidence', 'findings']
          }
        ]
      },
      {
        id: 'relationship_network_context',
        requirement: 'required',
        description: 'Entity graph and relationship evidence relevant to risk.',
        canonicalAuthorityRefs: ['entity_graph', 'graph', 'relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'relationship'],
            sectionIds: ['evidence', 'interactions', 'summary']
          },
          {
            projectionId: 'risk360',
            role: 'supporting',
            subjectKinds: ['cluster', 'entity', 'relationship'],
            sectionIds: ['evidence', 'summary']
          }
        ]
      },
      {
        id: 'risk_assessment_state',
        requirement: 'required',
        description: 'Risk outputs, model governance context, and assessment state.',
        canonicalAuthorityRefs: ['model_governance', 'risk_outputs'],
        projectionBindings: [
          {
            projectionId: 'risk360',
            role: 'primary',
            subjectKinds: ['agent', 'cluster', 'entity', 'relationship'],
            sectionIds: ['findings', 'health', 'state', 'summary']
          }
        ]
      },
      {
        id: 'risk_evidence_and_limitations',
        requirement: 'required',
        description: 'Evidence and limitations supporting risk findings.',
        canonicalAuthorityRefs: ['evidence'],
        projectionBindings: [
          {
            projectionId: 'risk360',
            role: 'primary',
            subjectKinds: ['agent', 'cluster', 'entity', 'relationship'],
            sectionIds: ['evidence', 'findings']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'risk360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'execution360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'fraud360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'relationship360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'risk360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'social360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['ai_execution_facts', 'economic_facts', 'entity_graph', 'evidence', 'execution_facts', 'fraud_synthesis', 'graph', 'graph_motifs', 'model_governance', 'relationship_facts', 'risk_outputs', 'social_observations'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'cluster', 'entity', 'relationship']
  },
  signals360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['connection360.explore', 'connection360.read', 'fraud360.explore', 'fraud360.read', 'outcome360.explore', 'outcome360.read', 'risk360.explore', 'risk360.read', 'social360.explore', 'social360.read', 'source360.explore', 'source360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of risk, fraud, source, social, and outcome signals with evidence and freshness status.',
    displayName: 'Signals 360',
    domainSlots: [
      {
        id: 'fraud_and_network_signals',
        requirement: 'optional',
        description: 'Fraud synthesis, motifs, social observations, and network context.',
        canonicalAuthorityRefs: ['fraud_synthesis', 'graph_motifs', 'relationship_facts', 'social_observations'],
        projectionBindings: [
          {
            projectionId: 'fraud360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'relationship'],
            sectionIds: ['evidence', 'findings', 'health']
          },
          {
            projectionId: 'social360',
            role: 'supporting',
            subjectKinds: ['entity', 'relationship'],
            sectionIds: ['evidence', 'findings']
          }
        ]
      },
      {
        id: 'measured_outcome_signals',
        requirement: 'optional',
        description: 'Measured outcomes available as governed signal inputs.',
        canonicalAuthorityRefs: ['measurement_contract', 'outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: [],
            sectionIds: ['findings', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'risk_signals',
        requirement: 'required',
        description: 'Risk outputs and signal findings.',
        canonicalAuthorityRefs: ['risk_outputs'],
        projectionBindings: [
          {
            projectionId: 'risk360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'relationship', 'source'],
            sectionIds: ['evidence', 'findings', 'health', 'summary']
          }
        ]
      },
      {
        id: 'source_signals_and_coverage',
        requirement: 'required',
        description: 'Source provenance and coverage of signal inputs.',
        canonicalAuthorityRefs: ['ingestion_health', 'source_coverage', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'connection360',
            role: 'supporting',
            subjectKinds: ['source'],
            sectionIds: ['coverage', 'evidence', 'state']
          },
          {
            projectionId: 'source360',
            role: 'primary',
            subjectKinds: ['agent', 'entity', 'source'],
            sectionIds: ['coverage', 'evidence', 'health', 'summary']
          }
        ]
      },
      {
        id: 'temporal_signal_context',
        requirement: 'optional',
        description: 'Temporal context for signal observations.',
        canonicalAuthorityRefs: ['temporal_kernel'],
        projectionBindings: [
          {
            projectionId: 'temporal360',
            role: 'primary',
            subjectKinds: ['entity', 'relationship'],
            sectionIds: ['evidence', 'state', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'signals360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'connection360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'fraud360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'risk360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'social360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'source360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'temporal360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['fraud_synthesis', 'graph_motifs', 'ingestion_health', 'measurement_contract', 'outcome_facts', 'relationship_facts', 'risk_outputs', 'social_observations', 'source_coverage', 'source_provenance', 'temporal_kernel'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'entity', 'relationship', 'source']
  },
  social360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['geographic360.explore', 'geographic360.read', 'population360.explore', 'population360.read', 'relationship360.explore', 'relationship360.read', 'social360.explore', 'social360.read', 'source360.explore', 'source360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of social observations, source-backed relationships, evidence, and optional population or geographic context.',
    displayName: 'Social 360',
    domainSlots: [
      {
        id: 'evidence_and_coverage',
        requirement: 'required',
        description: 'Evidence and source coverage for social claims.',
        canonicalAuthorityRefs: ['cohort_membership', 'evidence', 'identity', 'source_coverage'],
        projectionBindings: [
          {
            projectionId: 'social360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'relationship', 'source'],
            sectionIds: ['evidence', 'findings']
          },
          {
            projectionId: 'source360',
            role: 'supporting',
            subjectKinds: ['source'],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'geographic_context',
        requirement: 'optional',
        description: 'Location context for social observations.',
        canonicalAuthorityRefs: ['geo_observations', 'locations'],
        projectionBindings: [
          {
            projectionId: 'geographic360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'source'],
            sectionIds: ['evidence', 'summary', 'timeline']
          }
        ]
      },
      {
        id: 'population_context',
        requirement: 'optional',
        description: 'Population and cohort context for social observations.',
        canonicalAuthorityRefs: ['cohort_membership', 'population_definitions'],
        projectionBindings: [
          {
            projectionId: 'population360',
            role: 'primary',
            subjectKinds: ['entity', 'population'],
            sectionIds: ['evidence', 'state', 'summary']
          }
        ]
      },
      {
        id: 'relationship_graph',
        requirement: 'required',
        description: 'Relationship facts and graph context.',
        canonicalAuthorityRefs: ['cohort_membership', 'graph', 'identity', 'relationship_facts'],
        projectionBindings: [
          {
            projectionId: 'relationship360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'relationship', 'source'],
            sectionIds: ['evidence', 'interactions', 'summary']
          }
        ]
      },
      {
        id: 'social_observations_and_sources',
        requirement: 'required',
        description: 'Social observations and their source facts.',
        canonicalAuthorityRefs: ['cohort_membership', 'identity', 'social_observations', 'source_facts'],
        projectionBindings: [
          {
            projectionId: 'social360',
            role: 'primary',
            subjectKinds: ['entity', 'population', 'relationship', 'source'],
            sectionIds: ['evidence', 'interactions', 'summary', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'social360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'geographic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'population360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'relationship360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'social360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'source360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['cohort_membership', 'evidence', 'geo_observations', 'graph', 'identity', 'locations', 'population_definitions', 'relationship_facts', 'social_observations', 'source_coverage', 'source_facts'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['entity', 'population', 'relationship', 'source']
  },
  support360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['agent360.explore', 'agent360.read', 'episode360.explore', 'episode360.read', 'outcome360.explore', 'outcome360.read', 'profile360.explore', 'profile360.read', 'risk360.explore', 'risk360.read', 'source360.explore', 'source360.read', 'support360.explore', 'support360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed support context composed from communications, episodes and journeys, entity identity, and evidence.',
    displayName: 'Support 360',
    domainSlots: [
      {
        id: 'entity_and_agent_context',
        requirement: 'required',
        description: 'Identity and agent context associated with support activity.',
        canonicalAuthorityRefs: ['agent_entity', 'identity'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['evidence', 'state', 'summary']
          },
          {
            projectionId: 'profile360',
            role: 'primary',
            subjectKinds: ['agent', 'entity'],
            sectionIds: ['state', 'summary']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'optional',
        description: 'Measured support outcomes where an authoritative provider exists.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['episode'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'risk_context',
        requirement: 'optional',
        description: 'Risk context from its governing projection, subject to policy.',
        canonicalAuthorityRefs: ['risk_outputs'],
        projectionBindings: [
          {
            projectionId: 'risk360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'findings', 'summary']
          }
        ]
      },
      {
        id: 'source_lineage_and_coverage',
        requirement: 'required',
        description: 'Source provenance and coverage for support context.',
        canonicalAuthorityRefs: ['source_coverage', 'source_provenance'],
        projectionBindings: [
          {
            projectionId: 'source360',
            role: 'primary',
            subjectKinds: ['source'],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'support_communications',
        requirement: 'required',
        description: 'Communication events and interaction evidence.',
        canonicalAuthorityRefs: ['communication_facts', 'evidence'],
        projectionBindings: [
          {
            projectionId: 'support360',
            role: 'primary',
            subjectKinds: ['entity'],
            sectionIds: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline']
          }
        ]
      },
      {
        id: 'support_episode_and_journey',
        requirement: 'required',
        description: 'Episode and journey context for support interactions.',
        canonicalAuthorityRefs: ['episode_facts', 'events', 'journeys'],
        projectionBindings: [
          {
            projectionId: 'episode360',
            role: 'primary',
            subjectKinds: ['entity', 'episode'],
            sectionIds: ['evidence', 'state', 'summary', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'support360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'agent360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'episode360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'profile360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'risk360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'source360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'support360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['agent_entity', 'communication_facts', 'episode_facts', 'events', 'evidence', 'identity', 'journeys', 'outcome_facts', 'risk_outputs', 'source_coverage', 'source_provenance'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'entity', 'episode', 'source']
  },
  value360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['campaign360.explore', 'campaign360.read', 'economic360.explore', 'economic360.read', 'outcome360.explore', 'outcome360.read', 'temporal360.explore', 'temporal360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed view of economic facts, payment and commerce evidence, attribution, and measured outcomes; missing values remain explicit.',
    displayName: 'Value 360',
    domainSlots: [
      {
        id: 'campaign_and_attribution_context',
        requirement: 'optional',
        description: 'Campaign facts and attribution credits associated with value.',
        canonicalAuthorityRefs: ['attribution_credits', 'campaign_facts'],
        projectionBindings: [
          {
            projectionId: 'campaign360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'economic_facts_and_state',
        requirement: 'required',
        description: 'Economic facts and value state with currency normalization provenance.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'currency_value_normalization', 'economic_facts'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'journey'],
            sectionIds: ['evidence', 'state', 'summary']
          }
        ]
      },
      {
        id: 'measured_outcomes',
        requirement: 'required',
        description: 'Measured outcome facts linked to economic value.',
        canonicalAuthorityRefs: ['measurement_contract', 'outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'journey'],
            sectionIds: ['evidence', 'outcomes', 'summary']
          }
        ]
      },
      {
        id: 'payments_and_commerce_evidence',
        requirement: 'required',
        description: 'Payment and commerce evidence from the corresponding authorities.',
        canonicalAuthorityRefs: ['ai_execution_facts', 'commerce', 'payments'],
        projectionBindings: [
          {
            projectionId: 'economic360',
            role: 'primary',
            subjectKinds: ['campaign', 'episode', 'journey'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      },
      {
        id: 'temporal_context',
        requirement: 'optional',
        description: 'Temporal context for value facts and comparisons.',
        canonicalAuthorityRefs: ['temporal_kernel'],
        projectionBindings: [
          {
            projectionId: 'temporal360',
            role: 'primary',
            subjectKinds: [],
            sectionIds: ['state', 'timeline']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'value360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'campaign360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'economic360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'temporal360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['ai_execution_facts', 'attribution_credits', 'campaign_facts', 'commerce', 'currency_value_normalization', 'economic_facts', 'measurement_contract', 'outcome_facts', 'payments', 'temporal_kernel'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['campaign', 'episode', 'journey']
  },
  workflow360: {
    backendCapabilities: {
      required: ['experience360.evidence.provenance', 'experience360.frame.compose', 'experience360.freshness.evaluate', 'experience360.policy.evaluate', 'experience360.tenant_scope.enforce'],
      projectionCapabilityKeys: ['agent360.explore', 'agent360.read', 'connection360.explore', 'connection360.read', 'execution360.explore', 'execution360.read', 'infrastructure360.explore', 'infrastructure360.read', 'outcome360.explore', 'outcome360.read', 'source360.explore', 'source360.read'],
      providerCapabilityStatus: 'registry_requirements_not_route_attestation'
    },
    contractStatus: 'reconstructed_pending_source_alignment',
    description: 'Governed operational view of agent executions, actions and tools, integration lifecycle, evidence, and optional outcomes.',
    displayName: 'Workflow 360',
    domainSlots: [
      {
        id: 'actors_actions_and_resources',
        requirement: 'required',
        description: 'Agent actors, actions, tools, and resources participating in workflow activity.',
        canonicalAuthorityRefs: ['actions', 'agent_access', 'agent_entities', 'resources', 'tools'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent'],
            sectionIds: ['evidence', 'state']
          },
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'episode'],
            sectionIds: ['evidence', 'interactions']
          }
        ]
      },
      {
        id: 'deployment_infrastructure_context',
        requirement: 'optional',
        description: 'Infrastructure and deployment context for workflows whose execution is associated with a registered deployment.',
        canonicalAuthorityRefs: ['deployments', 'infrastructure_facts', 'infrastructure_state'],
        projectionBindings: [
          {
            projectionId: 'infrastructure360',
            role: 'primary',
            subjectKinds: [],
            sectionIds: ['deployments', 'evidence', 'findings']
          }
        ]
      },
      {
        id: 'evidence_and_source_lineage',
        requirement: 'required',
        description: 'Evidence and source coverage for workflow state.',
        canonicalAuthorityRefs: ['evidence', 'source_coverage'],
        projectionBindings: [
          {
            projectionId: 'source360',
            role: 'primary',
            subjectKinds: ['connection'],
            sectionIds: ['coverage', 'evidence']
          }
        ]
      },
      {
        id: 'integration_and_sync_context',
        requirement: 'required',
        description: 'Connection lifecycle and sync state for workflow integrations.',
        canonicalAuthorityRefs: ['connection_config', 'managed_integration_lifecycle', 'provider_health', 'sync_state'],
        projectionBindings: [
          {
            projectionId: 'connection360',
            role: 'primary',
            subjectKinds: ['connection'],
            sectionIds: ['coverage', 'health', 'state', 'summary']
          }
        ]
      },
      {
        id: 'workflow_execution_state',
        requirement: 'required',
        description: 'Execution facts and lifecycle state for workflow activity.',
        canonicalAuthorityRefs: ['agent_executions', 'execution_facts'],
        projectionBindings: [
          {
            projectionId: 'agent360',
            role: 'supporting',
            subjectKinds: ['agent'],
            sectionIds: ['evidence', 'timeline']
          },
          {
            projectionId: 'execution360',
            role: 'primary',
            subjectKinds: ['agent', 'episode'],
            sectionIds: ['state', 'summary', 'timeline']
          }
        ]
      },
      {
        id: 'workflow_outcomes',
        requirement: 'optional',
        description: 'Measured outcomes associated with workflow execution.',
        canonicalAuthorityRefs: ['outcome_facts'],
        projectionBindings: [
          {
            projectionId: 'outcome360',
            role: 'primary',
            subjectKinds: ['episode'],
            sectionIds: ['evidence', 'outcomes']
          }
        ]
      }
    ],
    freshnessPolicy: {
      required: true,
      maxAgeSeconds: null,
      sourceTimestamps: 'preserve',
      missingTimestamp: 'unknown',
      onStale: 'mark_affected_slots_stale',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    id: 'workflow360',
    lensContract: {
      expectedCount: null,
      lensIds: [],
      sourceAlignmentStatus: 'pending_source_alignment'
    },
    policyBehavior: {
      tenantScopeRequired: true,
      authorizationBeforeRead: true,
      policyEvaluation: 'per_projection_before_composition',
      historicalConsentEvaluation: 'required_when_applicable',
      redactionBehavior: 'suppress_disallowed_slot_without_inference',
      requirementStatus: 'contract_requirement_not_provider_attestation'
    },
    projectionBindings: [
      {
        projectionId: 'agent360',
        role: 'supporting',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'connection360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'execution360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      },
      {
        projectionId: 'infrastructure360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'outcome360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'implemented'
      },
      {
        projectionId: 'source360',
        role: 'primary',
        bindingStatus: 'catalog_only',
        providerImplementationState: 'in_flight'
      }
    ],
    sourceOfTruth: {
      canonicalAuthorities: ['actions', 'agent_access', 'agent_entities', 'agent_executions', 'connection_config', 'deployments', 'evidence', 'execution_facts', 'infrastructure_facts', 'infrastructure_state', 'managed_integration_lifecycle', 'outcome_facts', 'provider_health', 'resources', 'source_coverage', 'sync_state', 'tools'],
      ownsCanonicalTruth: false,
      prohibitedOwnership: ['economic_facts', 'execution_facts', 'graph', 'identity', 'observations', 'risk_outputs', 'source_provenance']
    },
    subjectKinds: ['agent', 'connection', 'episode']
  },
};
