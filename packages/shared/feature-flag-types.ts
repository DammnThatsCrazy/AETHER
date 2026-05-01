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
