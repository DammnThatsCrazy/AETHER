export type SDKPlatform = 'web' | 'ios' | 'android' | 'react-native' | 'node' | 'other';

export type SDKHealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'silent' | 'unknown';

export type DriftType = 'schema_drift' | 'stale_sdk' | 'replay_storm' | 'payload_anomaly';

export type DriftSeverity = 'info' | 'warning' | 'critical';

export interface SDKHealthScore {
  readonly sdk_id: string;
  readonly tenant_id: string;
  readonly composite: number;          // 0–100
  readonly connectivity: number;       // 0–1
  readonly throughput: number;         // 0–1
  readonly integrity: number;          // 0–1
  readonly auth_consent: number;       // 0–1
  readonly freshness: number;          // 0–1
  readonly status: SDKHealthStatus;
  readonly last_heartbeat_at: string;
  readonly computed_at: string;
}

export interface SDKInstance {
  readonly sdk_id: string;
  readonly platform: SDKPlatform;
  readonly sdk_version: string;
  readonly app_version: string;
  readonly queue_depth: number;
  readonly dropped_events: number;
  readonly retry_count: number;
  readonly endpoint_latency_ms: number;
  readonly ingestion_success_rate: number;
  readonly auth_valid: boolean;
  readonly consent_valid: boolean;
  readonly config_version: string;
  readonly reported_at: string;
  readonly health?: SDKHealthScore | undefined;
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

export interface DriftIncident {
  readonly incident_id: string;
  readonly tenant_id: string;
  readonly sdk_id: string;
  readonly drift_type: DriftType;
  readonly severity: DriftSeverity;
  readonly description: string;
  readonly detected_at: string;
  readonly schema_hash_expected?: string | undefined;
  readonly schema_hash_observed?: string | undefined;
  readonly sdk_version?: string | undefined;
  readonly extra?: Record<string, unknown> | undefined;
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
