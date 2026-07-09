// =============================================================================
// Cluster Targeting Intelligence — observation-first targeting contracts
// =============================================================================
// Aether observes whether intended cluster targeting happened, whether it
// worked, whether exclusions leaked, and what journey differences emerged.
// Aether does not execute campaigns, buy ads, bid, or target inside external
// campaign platforms; execution stays with the tenant's external systems.
//
// Every targeting recommendation traces:
//   TargetingIntent → TargetingEligibilitySnapshot → TargetingObservation
//   → TargetingOutcomeSnapshot → Suggestion → Outcome
// =============================================================================

import type { EntityRef } from './entities';
import type { EvidenceRef, TimeRangeFilter } from './operational-intelligence';

export const TARGETING_INTELLIGENCE_SCHEMA_VERSION = 'targeting.intelligence.v1' as const;

export const targetingIntentSources = [
  'tenant_declared',
  'provider_observed',
  'suggestion_generated',
  'operator_reviewed',
  'system_inferred',
] as const;
export type TargetingIntentSource = typeof targetingIntentSources[number];

export const targetingExecutionBoundaries = [
  'external_execution_required',
  'observed_only',
] as const;
export type TargetingExecutionBoundary = typeof targetingExecutionBoundaries[number];

export const targetingEvidenceClasses = [
  'tenant_declared',
  'provider_observed',
  'sdk_observed',
  'comms_observed',
  'campaign_observed',
  'graph_observed',
  'identity_inferred',
  'model_inferred',
  'operator_reviewed',
] as const;
export type TargetingEvidenceClass = typeof targetingEvidenceClasses[number];

export const exclusionReasonCodes = [
  'consent_blocked',
  'regulatory_or_policy',
  'fraud_risk',
  'churn_sensitive',
  'frequency_cap',
  'low_confidence_identity',
  'manual_tenant_exclusion',
  'negative_holdout',
  'overexposed',
  'provider_mapping_low_confidence',
  'operator_suppressed',
  'unknown',
] as const;
export type ExclusionReasonCode = typeof exclusionReasonCodes[number];

export const holdoutReasons = [
  'measurement_control',
  'risk_control',
  'tenant_manual',
  'operator_review',
  'model_validation',
] as const;
export type HoldoutReason = typeof holdoutReasons[number];

/**
 * Conflict precedence, strictest safe rule first: consent blocks beat
 * regulatory/policy blocks beat fraud-risk exclusions beat tenant manual
 * exclusions beat holdouts beat inclusions beat reference inclusion.
 */
export const targetingConflictResolutions = [
  'hard_consent_block',
  'regulatory_policy_block',
  'fraud_risk_exclusion',
  'tenant_manual_exclusion',
  'holdout_control',
  'inclusion',
  'similarity_reference_inclusion',
] as const;
export type TargetingConflictResolution = typeof targetingConflictResolutions[number];

export interface ClusterTargetingRule {
  clusterId: string;
  ruleType: 'include' | 'exclude' | 'reference' | 'holdout' | 'suppress';
  reasonCode?: ExclusionReasonCode | HoldoutReason | string;
  confidenceScore?: number;
  evidenceRefs: EvidenceRef[];
}

export interface TargetingIntent {
  id: string;
  tenantId: string;
  orgId?: string;
  campaignId?: string;

  source: TargetingIntentSource;
  executionBoundary: TargetingExecutionBoundary;
  executionByAether: false;
  externalExecutionRequired: true;

  includeClusters: string[];
  includeEntities?: EntityRef[];
  referenceClusters?: string[];
  excludeClusters: string[];
  suppressEntities?: EntityRef[];
  holdoutClusters?: string[];

  rules: ClusterTargetingRule[];

  maxHopDepth: 1 | 2 | 3;
  graphMode:
    | 'neighborhood'
    | 'attribution'
    | 'decision_outcome'
    | 'evidence'
    | 'multi_source';

  minIdentityConfidence: number;
  minClusterMembershipScore: number;
  minPathConfidence: number;
  minEvidenceCoverage: number;

  createdBy?: string;
  createdAt: string;
  updatedAt: string;

  evidenceRefs: EvidenceRef[];
  policyDecisionIds?: string[];
}

export interface TargetingEligibilitySnapshot {
  snapshotId: string;
  tenantId: string;
  campaignId?: string;
  targetingIntentId: string;

  asOf: string;
  graphWatermark?: string;

  eligibleClusters: string[];
  eligibleEntities: EntityRef[];
  excludedClusters: string[];
  suppressedEntities: EntityRef[];
  holdoutClusters: string[];

  identityConfidenceThreshold: number;
  clusterMembershipThreshold: number;
  pathConfidenceThreshold: number;
  evidenceCoverageThreshold: number;

  clusterMemberCounts: Record<string, number>;
  evidenceRefs: EvidenceRef[];

  createdAt: string;
}

export interface ProviderMappingQuality {
  campaignId?: string;
  provider?: string;
  mappingRate: number;
  providerSyncFreshness: 'live' | 'recent' | 'stale' | 'unknown';
  unresolvedAliasCount: number;
  touchpointResolutionRate: number;
  identityResolutionRate: number;
  clusterAssignmentRate: number;
  qualityScore: number;
  blocksSuggestions: boolean;
  reasons: string[];
  computedAt: string;
}

export interface TargetingObservation {
  observationId: string;
  tenantId: string;
  campaignId: string;
  targetingIntentId?: string;
  eligibilitySnapshotId?: string;

  sourceProvider?: string;
  sourceCampaignRef?: string;

  reachedClusters: string[];
  reachedEntities: EntityRef[];

  reachedIncludedClusters: string[];
  reachedReferenceClusters: string[];
  reachedExcludedClusters: string[];
  reachedHoldoutClusters: string[];

  providerMappingQuality: ProviderMappingQuality;

  observedAt: string;
  computedAt: string;
  evidenceRefs: EvidenceRef[];
}

export type ExclusionLeakageLikelyCause =
  | 'provider_ignored_exclusion'
  | 'tenant_uploaded_wrong_audience'
  | 'identity_resolved_after_launch'
  | 'cluster_overlap'
  | 'lookalike_expansion'
  | 'utm_mapping_error'
  | 'unknown';

export interface ExclusionLeakageFinding {
  findingId: string;
  tenantId: string;
  campaignId: string;
  targetingIntentId?: string;
  clusterId: string;

  reasonCode: ExclusionReasonCode;
  excludedEntityCount: number;
  reachedEntityCount: number;
  leakageRate: number;

  likelyCauses: ExclusionLeakageLikelyCause[];

  severity: 'info' | 'low' | 'medium' | 'high' | 'critical';
  evidenceRefs: EvidenceRef[];
  computedAt: string;
}

export interface TargetingHoldout {
  holdoutId: string;
  tenantId: string;
  campaignId?: string;
  targetingIntentId: string;
  clusterIds: string[];
  reason: HoldoutReason;
  contaminated: boolean;
  contaminationRate?: number;
  startAt: string;
  endAt?: string;
  evidenceRefs: EvidenceRef[];
}

export interface ClusterJourneyDelta {
  deltaId: string;
  tenantId: string;
  campaignId: string;
  clusterId: string;

  comparedToClusterIds?: string[];
  holdoutClusterIds?: string[];

  beforeWindow: TimeRangeFilter;
  afterWindow: TimeRangeFilter;

  populationStageDeltas: Record<string, number>;
  commsStageDeltas?: Record<string, number>;

  reachedCount: number;
  engagedCount: number;
  convertedCount: number;
  attributedCount: number;

  nonProgressedCount: number;
  progressedElsewhereCount: number;

  evidenceRefs: EvidenceRef[];
  computedAt: string;
}

export interface ClusterTargetingImpact {
  tenantId: string;
  campaignId: string;
  clusterId: string;

  memberCount: number;
  eligibleCount: number;
  reachedCount: number;
  engagedCount: number;
  convertedCount: number;
  attributedCount: number;

  spendUsd?: number;
  revenueUsd?: number;
  roas?: number;
  ltvDelta?: number;

  complaintRate?: number;
  unsubscribeRate?: number;
  churnSignalRate?: number;
  fraudSignalRate?: number;
  overexposureScore?: number;

  identityConfidence?: number;
  clusterMembershipConfidence?: number;
  evidenceCoverage: number;

  computedAt: string;
  evidenceRefs: EvidenceRef[];
}

export interface TargetingOutcomeSnapshot {
  snapshotId: string;
  tenantId: string;
  campaignId: string;
  targetingIntentId?: string;
  eligibilitySnapshotId?: string;
  observationId?: string;

  positiveOutcomes: {
    conversions: number;
    revenue: number;
    roas?: number;
    ltvDelta?: number;
    journeyProgression: number;
  };

  negativeOutcomes: {
    unsubscribes: number;
    complaints: number;
    churnSignals: number;
    fraudSignals: number;
    refunds: number;
    supportBurden: number;
    overexposureSignals: number;
  };

  clusterImpacts: ClusterTargetingImpact[];
  leakageFindings: ExclusionLeakageFinding[];
  journeyDeltas: ClusterJourneyDelta[];

  confidenceScore: number;
  evidenceCoverage: number;
  /** Path Intelligence classification; causal language requires classifier support. */
  pathClassification?: string;

  computedAt: string;
  evidenceRefs: EvidenceRef[];
}

/**
 * Evidence-backed implementation package a tenant exports into their own
 * external campaign platform. Aether never executes this package.
 */
export interface TargetingRecommendationExportPackage {
  exportId: string;
  tenantId: string;
  suggestionId?: string;
  targetingIntentId?: string;
  campaignId?: string;

  includeClusterIds: string[];
  referenceClusterIds: string[];
  excludeClusterIds: string[];
  holdoutClusterIds: string[];

  implementationNotes: string[];
  externalExecutionRequired: true;
  executionByAether: false;

  evidenceRefs: EvidenceRef[];
  generatedAt: string;
}
