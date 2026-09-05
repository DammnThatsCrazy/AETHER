/**
 * DO NOT EDIT — generated from packages/shared/contracts/relationship-predicate-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const relationshipPredicateRegistryVersion = '1.0.0' as const;

/** Families a relationship predicate may belong to. */
export const relationshipPredicateFamilies = [
  'AGENTIC',
  'BEHAVIORAL',
  'CAMPAIGN',
  'COMMUNICATION',
  'ECONOMIC',
  'ORGANIZATIONAL',
  'RISK_CONTEXT',
  'SEMANTIC',
  'SOCIAL',
  'STRUCTURAL',
  'TEMPORAL_GEO',
] as const;
export type RelationshipPredicateFamily = typeof relationshipPredicateFamilies[number];

/** Directionality a relationship predicate may express. */
export const relationshipPredicateDirectionality = [
  'DIRECTED',
  'RECIPROCAL_PAIR',
  'UNDIRECTED',
] as const;
export type RelationshipPredicateDirectionality = typeof relationshipPredicateDirectionality[number];

/** Reciprocity semantics a relationship predicate may declare. */
export const relationshipPredicateReciprocitySemantics = [
  'NON_RECIPROCAL',
  'RECIPROCAL_IF_OPPOSITE',
  'DERIVED_FROM_EVIDENCE',
] as const;
export type RelationshipPredicateReciprocitySemantics = typeof relationshipPredicateReciprocitySemantics[number];

/** Transitivity / path-composition classes a relationship predicate may declare. */
export const relationshipPredicateTransitivityClasses = [
  'NON_TRANSITIVE',
  'PATH_COMPOSABLE',
  'PROPAGATION_ELIGIBLE',
  'DELEGATION_COMPOSABLE',
  'ATTRIBUTION_ELIGIBLE',
  'INFERENTIAL_ONLY',
] as const;
export type RelationshipPredicateTransitivityClass = typeof relationshipPredicateTransitivityClasses[number];

/** Evidence proof-level floors a relationship predicate may require. */
export const relationshipPredicateProofLevels = [
  'provider_declared',
  'provider_observed',
  'verified_authoritative',
  'aggregated_independent',
  'inferred_with_limitations',
] as const;
export type RelationshipPredicateProofLevel = typeof relationshipPredicateProofLevels[number];

/** Graph registration state of a relationship predicate. */
export const relationshipPredicateGraphRegistrationStates = [
  'REGISTERED',
  'PENDING_M6_REGISTRATION',
] as const;
export type RelationshipPredicateGraphRegistrationState = typeof relationshipPredicateGraphRegistrationStates[number];

/** Validity semantics a relationship predicate may declare. */
export const relationshipPredicateValiditySemantics = [
  'BITEMPORAL_WINDOW',
  'EVENT_INSTANT',
] as const;
export type RelationshipPredicateValiditySemantics = typeof relationshipPredicateValiditySemantics[number];

/** Claim types a relationship predicate may reference. */
export const relationshipPredicateClaimTypes = [
  'observed',
  'verified',
  'resolved',
  'derived',
  'inferred',
  'predicted',
  'correlated',
  'temporally_supported',
  'disputed',
] as const;
export type RelationshipPredicateClaimType = typeof relationshipPredicateClaimTypes[number];

/** Strength semantics a relationship predicate may declare. */
export const relationshipPredicateStrengthSemantics = [
  'EXISTENCE_ONLY',
  'EXISTENCE_DURATION',
  'DIMENSIONAL_FIDELITY',
] as const;
export type RelationshipPredicateStrengthSemantics = typeof relationshipPredicateStrengthSemantics[number];

/** Sensitive-inference policies a relationship predicate may declare. */
export const relationshipPredicateSensitiveInferencePolicies = [
  'STANDARD',
  'SENSITIVE_GUARDED',
] as const;
export type RelationshipPredicateSensitiveInferencePolicy = typeof relationshipPredicateSensitiveInferencePolicies[number];

/** Actor kinds a relationship predicate may allow as source or target. */
export const relationshipPredicateActorKinds = [
  'AGENT',
  'BRAND',
  'COMPANY',
  'ENTITY',
  'FINANCIAL_ACCOUNT',
  'FUND_ENTITY',
  'GOVERNANCE_ORG',
  'HOUSEHOLD',
  'LEGAL_ENTITY',
  'MARKETPLACE',
  'MEDIA_ENTITY',
  'ORGANIZATION',
  'USER',
  'WALLET',
] as const;
export type RelationshipPredicateActorKind = typeof relationshipPredicateActorKinds[number];

/** Sensitive relationship labels the spine must not over-claim. */
export const relationshipPredicateSensitiveRelationshipLabels = [
  'family_member',
  'romantic_partner',
  'close_friend',
  'medical_relationship',
  'religious_affiliation',
  'political_affiliation',
] as const;
export type RelationshipPredicateSensitiveRelationshipLabel = typeof relationshipPredicateSensitiveRelationshipLabels[number];

/** Canonical relationship-predicate catalog (JSON file order). */
export const relationshipPredicates = [
  {
    predicate: 'FOLLOWS',
    version: 1,
    label: 'follows',
    description: 'A follows B\'s social account. A single provider-observed follow is an authoritative existence fact (blueprint §28) but never establishes closeness; strength, persistence and reciprocity are tracked separately.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY', 'COMPANY', 'ORGANIZATION'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['NON_TRANSITIVE', 'PROPAGATION_ELIGIBLE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'FOLLOWS_SOCIAL',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_DURATION',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'MUTUAL_SOCIAL_CONNECTION',
    version: 1,
    label: 'mutual social connection',
    description: 'Reciprocal social connection: A FOLLOWS B and B FOLLOWS A observed independently. Derived by the mutual-social-connection motif (blueprint §45 M1); claim_type derived, never observed directly.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY', 'COMPANY', 'ORGANIZATION'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'DERIVED_FROM_EVIDENCE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 2,
      proofLevelFloor: 'aggregated_independent',
      requiresOppositeDirectedEvidence: true
    },
    graphEdgeType: 'MUTUAL_SOCIAL_CONNECTION',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_DURATION',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'SUBSCRIBES_TO',
    version: 1,
    label: 'subscribes to',
    description: 'A subscribes to B\'s social content or channel. Distinct from economic service-plan subscriptions (EdgeType.SUBSCRIBES_TO). A durable social-relationship predicate requiring provider subscription events.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'SOCIAL_SUBSCRIBES_TO',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_DURATION',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'INTERACTS_WITH',
    version: 1,
    label: 'interacts with',
    description: 'Durable recurring social interaction between A and B. Individual likes/reactions/mentions/replies are relationship evidence, NOT individual graph edges (blueprint §51); the durable predicate is an aggregate requiring recurring, temporally-dispersed, independent observations (§29).',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY', 'COMPANY'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'aggregated_independent',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 3,
      proofLevelFloor: 'aggregated_independent',
      temporalDispersionRequired: true
    },
    graphEdgeType: 'SOCIAL_INTERACTS_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_DURATION',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'COLLABORATES_WITH',
    version: 1,
    label: 'collaborates with',
    description: 'Verified collaboration between A and B (co-authored work, joint appearance, coordinated output). Selectively promoted high-value event; requires corroborating evidence, not mere co-presence.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY', 'COMPANY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'verified',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      corroborationRequired: true,
      minimumIndependentObservations: 2,
      proofLevelFloor: 'verified_authoritative'
    },
    graphEdgeType: 'COLLABORATES_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_DURATION',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'PARTICIPATES_WITH',
    version: 1,
    label: 'participates with',
    description: 'A and B repeatedly participate in the same social spaces/events. Bounded language; NOT co-presence closeness and never an inferred personal relationship label.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'aggregated_independent',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 2,
      proofLevelFloor: 'aggregated_independent',
      temporalDispersionRequired: true
    },
    graphEdgeType: 'PARTICIPATES_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'COMMUNITY_ASSOCIATION',
    version: 1,
    label: 'community association',
    description: 'A and B share community membership AND interact within it (blueprint §45 M4 shared-community+interaction motif). Derived, not a friendship claim.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 2,
      proofLevelFloor: 'aggregated_independent',
      sharedMembershipRequired: true
    },
    graphEdgeType: 'COMMUNITY_ASSOCIATION',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'RECURRING_SOCIAL_INTERACTION',
    version: 1,
    label: 'recurring social interaction',
    description: 'Aggregate promotion result (blueprint §29) over repeated independent social interactions: interaction count, temporal duration, reciprocity, variety and source independence all feed promotion. Never promoted from a single observation.',
    family: 'SOCIAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY', 'COMPANY'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      interactionVarietyConsidered: true,
      minimumIndependentObservations: 3,
      proofLevelFloor: 'aggregated_independent',
      temporalDispersionRequired: true
    },
    graphEdgeType: 'RECURRING_SOCIAL_INTERACTION',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'DIMENSIONAL_FIDELITY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'RECIPROCAL_COMMUNICATION',
    version: 1,
    label: 'reciprocal communication',
    description: 'Aggregate reciprocal communication relationship over policy-defined duration with independent interactions in both directions (blueprint §29, §45 M2). Consumes Communication360 facts; never duplicated into a second comms store.',
    family: 'COMMUNICATION',
    allowedSourceKinds: ['USER', 'ENTITY', 'AGENT'],
    allowedTargetKinds: ['USER', 'ENTITY', 'AGENT'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'DERIVED_FROM_EVIDENCE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 2,
      proofLevelFloor: 'aggregated_independent',
      requiresBidirectionalEvidence: true,
      temporalDispersionRequired: true
    },
    graphEdgeType: 'RECIPROCAL_COMMUNICATION',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'DIMENSIONAL_FIDELITY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'RECURRING_CO_PRESENCE',
    version: 1,
    label: 'recurring co-presence',
    description: 'A and B share a geographic context across multiple independent temporal episodes (blueprint §45 M3). Explicitly NOT friendship and not inferred from a single co-location.',
    family: 'TEMPORAL_GEO',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'SENSITIVE_GUARDED',
    defaultEvidenceRequirements: {
      episodeIndependenceRequired: true,
      minimumIndependentObservations: 2,
      proofLevelFloor: 'aggregated_independent'
    },
    graphEdgeType: 'RECURRING_CO_PRESENCE',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'PERSISTENT_MULTI_CONTEXT_ASSOCIATION',
    version: 1,
    label: 'persistent multi-context association',
    description: 'Independent social, communication, economic and/or temporal-geographic evidence of A and B across time (blueprint §45 M10). The bounded-language alternative to a \'friend\' label; never automatically friend.',
    family: 'BEHAVIORAL',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'DERIVED_FROM_EVIDENCE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentContexts: 2,
      minimumIndependentObservations: 3,
      proofLevelFloor: 'aggregated_independent',
      temporalDispersionRequired: true
    },
    graphEdgeType: 'PERSISTENT_MULTI_CONTEXT_ASSOCIATION',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'DIMENSIONAL_FIDELITY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'SHARES_AFFINITY_WITH',
    version: 1,
    label: 'shares affinity with',
    description: 'Behavioral/semantic affinity relationship. MUST NEVER participate in identity merging (blueprint §22 behavioral family) and never promotes to inferred closeness on weak evidence.',
    family: 'BEHAVIORAL',
    allowedSourceKinds: ['USER', 'ENTITY', 'AGENT'],
    allowedTargetKinds: ['USER', 'ENTITY', 'AGENT'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['INFERENTIAL_ONLY', 'PROPAGATION_ELIGIBLE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'inferred',
    sensitiveInferencePolicy: 'SENSITIVE_GUARDED',
    defaultEvidenceRequirements: {
      limitationsRecorded: true,
      proofLevelFloor: 'inferred_with_limitations'
    },
    graphEdgeType: 'SHARES_AFFINITY_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'DIMENSIONAL_FIDELITY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'AGENT_MEDIATED_PRINCIPAL_INTERACTION',
    version: 1,
    label: 'agent-mediated principal interaction',
    description: 'Principal-level interaction between two humans mediated by their agents (Human A delegates → Agent A transacts → Agent B acts_for Human B; blueprint §45 M6). Output of the agent-mediated motif; the observed interaction is between agents, the predicate is bounded to the principals.',
    family: 'AGENTIC',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'derived',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      agentChainRequired: true,
      proofLevelFloor: 'aggregated_independent'
    },
    graphEdgeType: 'AGENT_MEDIATED_PRINCIPAL_INTERACTION',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'EVENT_INSTANT',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'MEMBER_OF',
    version: 1,
    label: 'member of',
    description: 'A is a member of organization/community C. Canonical H2H graph edge exists (Entity → Organization). Supports the shared-membership motif (blueprint §23).',
    family: 'STRUCTURAL',
    allowedSourceKinds: ['USER', 'ENTITY', 'AGENT'],
    allowedTargetKinds: ['ORGANIZATION', 'COMPANY', 'GOVERNANCE_ORG', 'MARKETPLACE', 'MEDIA_ENTITY'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'verified_authoritative'
    },
    graphEdgeType: 'MEMBER_OF',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'PAYS',
    version: 1,
    label: 'pays',
    description: 'Economic transfer from A to B (blueprint §22 economic family). Canonical A2A graph edge exists. PATH_COMPOSABLE for agent-economic flow tracing.',
    family: 'ECONOMIC',
    allowedSourceKinds: ['USER', 'ENTITY', 'AGENT', 'FINANCIAL_ACCOUNT', 'WALLET'],
    allowedTargetKinds: ['USER', 'ENTITY', 'AGENT', 'FINANCIAL_ACCOUNT', 'WALLET'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['PATH_COMPOSABLE', 'PROPAGATION_ELIGIBLE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'PAYS',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'EVENT_INSTANT',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'REFERRED_BY',
    version: 1,
    label: 'referred by',
    description: 'A was exposed to / converted from a campaign attributable to B (blueprint §22 campaign family). Campaign attribution edge; never a durable social relationship claim.',
    family: 'CAMPAIGN',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY', 'BRAND', 'MEDIA_ENTITY'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: true,
    inferenceAllowed: true,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'REFERRED_BY',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'CO_EXPOSED',
    version: 1,
    label: 'co-exposed',
    description: 'A and B were exposed to the same campaign/reward condition (blueprint §22 campaign family). Incentive-context signal, not a relationship and never evidence of shared intrinsic interest by itself.',
    family: 'CAMPAIGN',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      incentiveExposureRequired: true,
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'CO_EXPOSED',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'SHARES_RISK_CONTEXT_WITH',
    version: 1,
    label: 'shares risk context with',
    description: 'A and B share risk context (blueprint §22 risk-context family). Explicitly NOT an automatic fraud claim; emits indicators under the graph_motifs canonical authority when fraud-supported.',
    family: 'RISK_CONTEXT',
    allowedSourceKinds: ['USER', 'ENTITY', 'AGENT', 'WALLET', 'FINANCIAL_ACCOUNT'],
    allowedTargetKinds: ['USER', 'ENTITY', 'AGENT', 'WALLET', 'FINANCIAL_ACCOUNT'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE', 'INFERENTIAL_ONLY'],
    directFactAllowed: false,
    inferenceAllowed: true,
    claimTypeFloor: 'correlated',
    sensitiveInferencePolicy: 'SENSITIVE_GUARDED',
    defaultEvidenceRequirements: {
      limitationsRecorded: true,
      proofLevelFloor: 'aggregated_independent'
    },
    graphEdgeType: 'SHARES_RISK_CONTEXT_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'CO_PRESENT_WITH',
    version: 1,
    label: 'co-present with',
    description: 'A and B share a geographic context within a single episode (blueprint §22 temporal/geographic family). A raw co-presence event relationship; feeds the recurring-co-presence motif (M3). Single episode is never promoted to a durable relationship.',
    family: 'TEMPORAL_GEO',
    allowedSourceKinds: ['USER', 'ENTITY'],
    allowedTargetKinds: ['USER', 'ENTITY'],
    directionality: 'UNDIRECTED',
    reciprocitySemantics: 'NON_RECIPROCAL',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'SENSITIVE_GUARDED',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'CO_PRESENT_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'EVENT_INSTANT',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
  {
    predicate: 'COMMUNICATES_WITH',
    version: 1,
    label: 'communicates with',
    description: 'Directed communication contact from A to B over a window (blueprint §22 communication family). Canonical cross-domain graph edge exists (Agent/Profile → Entity/Service/Agent); feeds the reciprocal-communication motif (M2). Contact ≠ closeness; reciprocity and persistence are derived.',
    family: 'COMMUNICATION',
    allowedSourceKinds: ['USER', 'ENTITY', 'AGENT'],
    allowedTargetKinds: ['USER', 'ENTITY', 'AGENT'],
    directionality: 'DIRECTED',
    reciprocitySemantics: 'RECIPROCAL_IF_OPPOSITE',
    transitivityClasses: ['NON_TRANSITIVE'],
    directFactAllowed: true,
    inferenceAllowed: false,
    claimTypeFloor: 'observed',
    sensitiveInferencePolicy: 'STANDARD',
    defaultEvidenceRequirements: {
      minimumIndependentObservations: 1,
      proofLevelFloor: 'provider_observed'
    },
    graphEdgeType: 'COMMUNICATES_WITH',
    graphRegistrationState: 'REGISTERED',
    validitySemantics: 'BITEMPORAL_WINDOW',
    strengthSemantics: 'EXISTENCE_ONLY',
    owner: 'relational-intelligence-spine'
  },
] as const;
