/**
 * Sync state for a connector integration.
 */
export interface ConnectorSyncState {
  /** Unique connector identifier. */
  connector_id: string;

  /** The platform the connector integrates with. */
  platform: string;

  /** The connector type (e.g., "shopify", "stripe", "hubspot"). */
  connector_type: string;

  /** Current sync status. */
  status: 'idle' | 'syncing' | 'success' | 'partial' | 'error' | 'auth_failure' | 'pending' | 'disabled';

  /** When the connector was last configured or connected. */
  connected_at?: string;

  /** When the last sync attempt started. */
  last_sync_started_at?: string;

  /** When the last sync completed. */
  last_sync_completed_at?: string;

  /** Total records synced in the last successful run. */
  last_sync_record_count?: number;

  /** Total records synced across all runs. */
  total_synced_records?: number;

  /** Error message from the last failed sync, if any. */
  last_error?: string;

  /** Error code from the last failed sync, if any. */
  last_error_code?: string;

  /** Cursor or bookmark for incremental sync. */
  sync_cursor?: string;

  /** The last time the sync cursor was updated. */
  cursor_updated_at?: string;

  /** Whether the connector is authenticated and usable. */
  is_connected: boolean;

  /** Configuration for the connector. */
  config?: ConnectorConfig;

  /** Health metrics for the connector. */
  health?: ConnectorHealth;

  /** Settings for the connector. */
  settings?: {
    sync_interval_ms?: number;
    batch_size?: number;
    retry_count?: number;
    enabled?: boolean;
  };
}

/**
 * Connector configuration details.
 */
export interface ConnectorConfig {
  /** The environment the connector is configured for. */
  environment: 'development' | 'staging' | 'production';

  /** Workspace this connector belongs to. */
  workspace_id: string;

  /** Tenant this connector belongs to. */
  tenant_id: string;

  /** Custom configuration fields. */
  options?: Record<string, unknown>;

  /** OAuth or API credentials (stored securely, references only). */
  credential_type?: 'oauth' | 'api_key' | 'basic' | 'none';
}

/**
 * Connector health metrics.
 */
export interface ConnectorHealth {
  /** Whether the connector is healthy. */
  healthy: boolean;

  /** Last health check timestamp. */
  last_check_at?: string;

  /** Uptime percentage (0–1). */
  uptime?: number;

  /** Average sync latency in milliseconds. */
  avg_latency_ms?: number;

  /** Number of consecutive failures. */
  consecutive_failures?: number;
}
