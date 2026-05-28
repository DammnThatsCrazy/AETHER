// =============================================================================
// Aether SDK — Vendor Integration Config Types
// =============================================================================

export type AuthType =
  | 'oauth2_client_creds'
  | 'oauth2_pkce'
  | 'api_key'
  | 'bearer'
  | 'basic';

export interface RetryPolicy {
  readonly max_attempts: number;
  /** Base delay in milliseconds for exponential backoff */
  readonly base_delay_ms: number;
  readonly max_delay_ms: number;
}

/**
 * Self-describing integration config stored in PostgreSQL vendor_configs table.
 * Queryable via GET /v1/providers/categories.
 */
export interface VendorConfig {
  readonly provider_name: string;
  readonly endpoint_base: string;
  readonly auth_type: AuthType;
  readonly required_scopes: string[];
  readonly sandbox_endpoint?: string;
  /** Cron expression for nightly data sync */
  readonly nightly_sync_cron: string;
  readonly rate_limit_per_min: number;
  readonly retry_policy: RetryPolicy;
  /** Consent purpose that must be granted before data can be fetched */
  readonly consent_purpose_required: string;
  /** How long fetched data remains valid before re-fetch */
  readonly data_freshness_ttl_minutes: number;
}
