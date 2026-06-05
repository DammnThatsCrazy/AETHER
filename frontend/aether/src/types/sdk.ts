/**
 * Tenant-facing SDK fleet & remote-config types.
 *
 * These mirror the backend contracts exposed by the tenant-scoped SDK
 * services:
 *   - services/sdk_health  →  /v1/diagnostics/sdk/*
 *   - services/sdk_config  →  /v1/config/sdk/*
 *
 * They intentionally match the shapes used by the internal Kyber operator
 * console (frontend/kyber/src/types/sdk-health.ts) so a tenant sees the same
 * fleet view of their own SDKs that operators see across all tenants.
 */

export type SDKPlatform = 'web' | 'ios' | 'android' | 'react-native' | 'node' | 'other';

export type SDKHealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'silent' | 'unknown';

export interface SDKHealthScore {
  readonly sdk_id: string;
  readonly tenant_id: string;
  readonly composite: number; // 0–100
  readonly connectivity: number; // 0–1
  readonly throughput: number; // 0–1
  readonly integrity: number; // 0–1
  readonly auth_consent: number; // 0–1
  readonly freshness: number; // 0–1
  readonly status: SDKHealthStatus;
  readonly last_heartbeat_at: string;
  readonly computed_at: string;
}

export interface SDKFleetStatus {
  readonly tenant_id: string;
  readonly total_instances: number;
  readonly healthy_count: number;
  readonly degraded_count: number;
  readonly unhealthy_count: number;
  readonly silent_count: number;
  readonly avg_health_score: number;
  readonly platforms: Record<string, number>;
  readonly versions: Record<string, number>;
  readonly computed_at: string;
}

export interface SilentSDK {
  readonly sdk_id: string;
  readonly platform?: SDKPlatform;
  readonly sdk_version?: string;
  readonly last_heartbeat_at?: string;
}

export interface SDKManifest {
  readonly manifest_version: string;
  readonly min_sdk_version: string;
  readonly schema_version: string;
  readonly rollout_percentage: number;
  readonly features: Record<string, boolean>;
  readonly endpoints: Record<string, string>;
  readonly flags: Record<string, unknown>;
  readonly published_at: string;
  readonly signature: string;
}

export interface SDKRolloutStatus {
  readonly tenant_id: string;
  readonly current_version: string | null;
  readonly current_rollout_pct: number | null;
  readonly previous_version: string | null;
  readonly has_rollback_available: boolean;
  readonly current_published_at: string | null;
}

export interface PublishManifestInput {
  min_sdk_version?: string;
  schema_version?: string;
  rollout_percentage?: number;
  features?: Record<string, boolean>;
  endpoints?: Record<string, string>;
  flags?: Record<string, unknown>;
}
