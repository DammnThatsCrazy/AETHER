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
  'outcome360',
  'population360',
  'profile360',
  'relationship360',
  'risk360',
  'social360',
  'source360',
  'temporal360',
] as const;
export type IntelligenceProjectionId = typeof intelligenceProjectionIds[number];

/** Projection kinds a 360 may be (sorted). */
export const intelligenceProjectionKinds = [
  'agentic_360',
  'context_360',
  'entity_360',
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
  'entity',
  'episode',
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
    canonicalAuthorities: ['agent_access', 'agent_entity', 'agent_executions', 'economic_facts', 'evidence', 'graph', 'identity', 'outcome_facts'],
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
      services: ['Backend Architecture/aether-backend/services/agent'],
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
      services: ['Backend Architecture/aether-backend/services/campaign'],
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
      services: ['Backend Architecture/aether-backend/services/cluster'],
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
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/communication360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['campaign', 'episode', 'source'],
    canonicalAuthorities: ['campaign_touchpoints', 'communication_facts', 'entities', 'evidence', 'outcomes'],
    hardDependencies: ['contract_spine', 'temporal_kernel'],
    projectionDependencies: ['episode360', 'outcome360', 'profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['profile360', 'timeline'],
    capabilityKeys: ['communication360.explore', 'communication360.read'],
    metricRefs: ['email_click_rate', 'email_open_rate', 'email_reply_rate'],
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
      services: ['Backend Architecture/aether-backend/services/comms'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/communication360.md'
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
      services: ['Backend Architecture/aether-backend/services/provider_runtime'],
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
    displayName: 'Economic 360',
    projectionKind: 'measurement_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/economic360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['campaign', 'episode', 'source'],
    canonicalAuthorities: ['commerce', 'currency_value_normalization', 'economic_facts', 'graph', 'outcome_facts', 'payments'],
    hardDependencies: ['measurement_outcome_contract', 'temporal_kernel'],
    projectionDependencies: ['outcome360', 'profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphResult', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'outcomes', 'state', 'summary'],
    supportedTemporalModes: ['compare', 'relative', 'window'],
    surfaceIds: ['campaign360', 'economic360', 'product_intelligence'],
    capabilityKeys: ['economic360.explore', 'economic360.read'],
    metricRefs: ['revenue'],
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
      services: ['Backend Architecture/aether-backend/services/economic'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/economic360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [],
    pendingReference: [
      {
        id: 'campaign_cac',
        kind: 'metric',
        reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
        resolvesInProjection: 'economic360'
      },
      {
        id: 'campaign_ltv',
        kind: 'metric',
        reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
        resolvesInProjection: 'economic360'
      },
      {
        id: 'campaign_roas',
        kind: 'metric',
        reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
        resolvesInProjection: 'economic360'
      },
      {
        id: 'campaign_spend',
        kind: 'metric',
        reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
        resolvesInProjection: 'economic360'
      }
    ]
  },
  episode360: {
    id: 'episode360',
    displayName: 'Episode 360',
    projectionKind: 'sequence_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/episode360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['campaign', 'entity', 'episode'],
    canonicalAuthorities: ['episode_facts', 'events', 'evidence', 'graph', 'journeys', 'temporal'],
    hardDependencies: ['contract_spine', 'journey_continuity', 'temporal_kernel'],
    projectionDependencies: ['profile360', 'relationship360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
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
      services: ['Backend Architecture/aether-backend/services/events', 'Backend Architecture/aether-backend/services/journeys'],
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
    canonicalAuthorities: ['actions', 'agent_entities', 'economic_facts', 'evidence', 'execution_facts', 'graph', 'outcome_facts', 'resources', 'tools'],
    hardDependencies: ['agentic_runtime_access', 'temporal_kernel'],
    projectionDependencies: ['agent360', 'episode360', 'outcome360', 'temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'interactions', 'outcomes', 'state', 'summary', 'timeline'],
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
      services: ['Backend Architecture/aether-backend/services/agent', 'Backend Architecture/aether-backend/services/flows', 'Backend Architecture/aether-backend/services/jobs'],
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
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/fraud360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity', 'relationship'],
    canonicalAuthorities: ['economic_facts', 'evidence', 'execution_facts', 'fraud_synthesis', 'graph_motifs', 'identity', 'relationship_facts', 'risk_outputs', 'social_observations'],
    hardDependencies: ['evidence_provenance', 'model_governance'],
    projectionDependencies: ['profile360', 'risk360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'health', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['graph'],
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
      surfaceIds: ['graph'],
      services: ['Backend Architecture/aether-backend/services/fraud'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/fraud360.md'
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
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/geographic360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['entity', 'population', 'source'],
    canonicalAuthorities: ['context_capsules', 'entity_graph', 'geo_observations', 'locations', 'temporal'],
    hardDependencies: ['context_capsule_semantics', 'temporal_kernel'],
    projectionDependencies: ['profile360', 'temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['compare', 'relative', 'window'],
    surfaceIds: ['geo'],
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
      surfaceIds: ['geo'],
      services: ['Backend Architecture/aether-backend/services/geo'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/geographic360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [
      {
        id: 'context_capsule_semantics',
        kind: 'spine',
        reason: 'context-capsule plane not yet formalized',
        resolvesInProjection: 'geographic360'
      }
    ],
    pendingReference: []
  },
  outcome360: {
    id: 'outcome360',
    displayName: 'Outcome 360',
    projectionKind: 'measurement_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/outcome360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['campaign', 'episode', 'population'],
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
      routes: ['/v1/attribution', '/v1/conversions', '/v1/journeys', '/v1/measurement', '/v1/resolution', '/v1/spend'],
      surfaceIds: ['campaign360', 'outcome360'],
      services: ['Backend Architecture/aether-backend/services/measurement'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/outcome360.md'
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
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/population360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['cluster', 'entity', 'population'],
    canonicalAuthorities: ['cluster_definitions', 'cohort_membership', 'entities', 'evidence', 'population_definitions', 'temporal'],
    hardDependencies: ['contract_spine', 'grouping_membership'],
    projectionDependencies: ['profile360', 'relationship360', 'temporal360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'GraphResult', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['relative', 'window'],
    surfaceIds: ['cluster360', 'comparison_workbench'],
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
      surfaceIds: ['cluster360', 'comparison_workbench'],
      services: ['Backend Architecture/aether-backend/services/population'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/population360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [
      {
        id: 'grouping_membership',
        kind: 'spine',
        reason: 'canonical grouping/membership contract not yet formalized',
        resolvesInProjection: 'population360'
      }
    ],
    pendingReference: []
  },
  profile360: {
    id: 'profile360',
    displayName: 'Profile 360',
    projectionKind: 'entity_360',
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/profile360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['agent', 'entity'],
    canonicalAuthorities: ['entity_registry', 'evidence', 'graph', 'identity', 'observations', 'temporal'],
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
      services: ['Backend Architecture/aether-backend/services/profile'],
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
    subjectKinds: ['entity', 'relationship'],
    canonicalAuthorities: ['evidence', 'graph', 'identity', 'relationship_facts', 'temporal'],
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
      services: ['Backend Architecture/aether-backend/services/operational_intelligence', 'Backend Architecture/aether-backend/services/semantic_intelligence'],
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
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/risk360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['cluster', 'entity', 'population', 'relationship'],
    canonicalAuthorities: ['cluster_membership', 'economic_facts', 'entity_graph', 'evidence', 'model_governance', 'risk_outputs'],
    hardDependencies: ['computation_substrate', 'evidence_provenance', 'model_governance'],
    projectionDependencies: ['cluster360', 'economic360', 'profile360'],
    optionalProjectionDependencies: [],
    inputRefs: ['EntityRef', 'EvidenceRef', 'FilterExpression', 'GraphSnapshotRef', 'PageRequest', 'RelationshipRef', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'health', 'state', 'summary'],
    supportedTemporalModes: ['as_of', 'relative', 'window'],
    surfaceIds: ['comparison_workbench', 'graph'],
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
      surfaceIds: ['comparison_workbench', 'graph'],
      services: ['Backend Architecture/aether-backend/services/risk_overlay'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/risk360.md'
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
    implementationBlueprint: 'docs/blueprints/social360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['entity', 'relationship'],
    canonicalAuthorities: ['evidence', 'graph', 'relationship_facts', 'social_observations', 'source_facts'],
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
      services: ['Backend Architecture/aether-backend/services/social'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/social360.md'
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
    subjectKinds: ['connection', 'source'],
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
      services: ['Backend Architecture/aether-backend/services/imports'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/source360.md'
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
    implementationState: 'in_flight',
    implementationBlueprint: 'docs/blueprints/temporal360.md',
    ownsCanonicalTruth: false,
    subjectKinds: ['entity', 'relationship'],
    canonicalAuthorities: ['graph_snapshots', 'mutation_history', 'temporal_kernel', 'validity_state'],
    hardDependencies: ['contract_spine', 'graph_history_replay'],
    projectionDependencies: [],
    optionalProjectionDependencies: [],
    inputRefs: ['GraphResult', 'GraphSnapshotRef', 'PageRequest', 'TimeRangeFilter'],
    outputSections: ['evidence', 'findings', 'state', 'summary', 'timeline'],
    supportedTemporalModes: ['as_of', 'compare', 'relative', 'window'],
    surfaceIds: ['temporal_observatory', 'timeline'],
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
      surfaceIds: ['temporal_observatory', 'timeline'],
      services: ['Backend Architecture/aether-backend/shared/temporal'],
      migrationMode: 'adapter',
      migrationBlueprint: 'docs/blueprints/temporal360.md'
    },
    deprecatedReason: null,
    successorId: null,
    pendingAuthority: [
      {
        id: 'graph_history_replay',
        kind: 'spine',
        reason: 'bitemporal ledger exists; graph-history replay API not yet built',
        resolvesInProjection: 'temporal360'
      }
    ],
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
  outcome360: { required: ['temporal360'], optional: [] },
  population360: { required: ['profile360', 'relationship360', 'temporal360'], optional: [] },
  profile360: { required: [], optional: ['risk360'] },
  relationship360: { required: ['profile360', 'temporal360'], optional: ['communication360', 'economic360', 'risk360', 'social360'] },
  risk360: { required: ['cluster360', 'economic360', 'profile360'], optional: [] },
  social360: { required: ['profile360', 'relationship360'], optional: [] },
  source360: { required: [], optional: [] },
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
  geographic360: [
    {
      id: 'context_capsule_semantics',
      kind: 'spine',
      reason: 'context-capsule plane not yet formalized',
      resolvesInProjection: 'geographic360'
    }
  ],
  population360: [
    {
      id: 'grouping_membership',
      kind: 'spine',
      reason: 'canonical grouping/membership contract not yet formalized',
      resolvesInProjection: 'population360'
    }
  ],
  temporal360: [
    {
      id: 'graph_history_replay',
      kind: 'spine',
      reason: 'bitemporal ledger exists; graph-history replay API not yet built',
      resolvesInProjection: 'temporal360'
    }
  ],
};

export const pendingReferences: Partial<
  Record<IntelligenceProjectionId, readonly PendingResolution[]>
> = {
  economic360: [
    {
      id: 'campaign_cac',
      kind: 'metric',
      reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
      resolvesInProjection: 'economic360'
    },
    {
      id: 'campaign_ltv',
      kind: 'metric',
      reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
      resolvesInProjection: 'economic360'
    },
    {
      id: 'campaign_roas',
      kind: 'metric',
      reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
      resolvesInProjection: 'economic360'
    },
    {
      id: 'campaign_spend',
      kind: 'metric',
      reason: 'economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json',
      resolvesInProjection: 'economic360'
    }
  ],
};
