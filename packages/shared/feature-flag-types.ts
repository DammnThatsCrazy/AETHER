// =============================================================================
// Aether SDK — Shared Feature Flag Types
// Canonical type definitions used by Web, iOS, Android, and React Native SDKs
// =============================================================================

export interface FeatureFlag {
  key: string;
  enabled: boolean;
  value?: unknown;
  variant?: string;
  source: 'remote' | 'local' | 'default' | 'override';
}

export interface FlagDefinition {
  key: string;
  defaultValue: boolean | unknown;
  description?: string;
}

export const FLAG_RESOLUTION_PRIORITY = ['override', 'remote', 'local', 'default'] as const;


export const DECISION_OUTCOME_FEATURE_FLAGS = {
  recommendations: 'AETHER_RECOMMENDATIONS_ENABLED',
  decisionRecords: 'AETHER_DECISION_RECORDS_ENABLED',
  outcomeFeedback: 'AETHER_OUTCOME_FEEDBACK_ENABLED',
  playbooks: 'AETHER_PLAYBOOKS_ENABLED',
  kyberRecommendationObservability: 'KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED',
} as const;
