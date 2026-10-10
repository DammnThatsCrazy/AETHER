// @aether/proof-connectors — connector state types
// FPS-061–FPS-063: connector lifecycle state machine

export type ConnectorStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'backfilling'
  | 'syncing'
  | 'error';

export type CredentialStatus = 'missing' | 'valid' | 'expired' | 'invalid';

export type TokenRefreshStatus = 'valid' | 'expired' | 'refreshing' | 'failed';

export type BackfillStatus = 'idle' | 'running' | 'completed' | 'failed';

export type IncrementalSyncStatus = 'idle' | 'running' | 'completed' | 'failed';

export type WebhookStatus = 'idle' | 'replaying' | 'completed' | 'failed';

export interface SyncState {
  recordsReceived: number;
  recordsAccepted: number;
  recordsRejected: number;
  recordsNormalized: number;
  recordsWritten: number;
  lastError: string | null;
  degradedReason: string | null;
  lastSyncAt: number | null;
}

export interface ConnectorState {
  // Lifecycle status
  status: ConnectorStatus;
  provider: 'stripe' | 'shopify' | 'email' | null;

  // Credential & auth
  credentialStatus: CredentialStatus;
  tokenRefreshStatus: TokenRefreshStatus;

  // Operation statuses
  backfillStatus: BackfillStatus;
  incrementalSyncStatus: IncrementalSyncStatus;
  webhookStatus: WebhookStatus;

  // Sync metrics
  sync: SyncState;

  // Action tracking
  lastAction: string | null;
  lastActionResult: Record<string, unknown> | null;

  // UI-modal state (payload viewers, provider selector, etc.)
  showRawPayload: boolean;
  showNormalizedPayload: boolean;
  showGraphWrites: boolean;
  rawPayload: unknown;
  normalizedPayload: unknown;
  graphWrites: unknown;
  providerSelectorOpen: boolean;

  // SDK integration
  sdkInitialized: boolean;
  sdkVersion: string;
}

export type ConnectorProvider = 'stripe' | 'shopify' | 'email';

export type ConnectorAction =
  | 'connect'
  | 'disconnect'
  | 'reconnect'
  | 'backfill'
  | 'incremental_sync'
  | 'webhook_replay'
  | 'token_expiration'
  | 'provider_error'
  | 'view_raw'
  | 'view_normalized'
  | 'view_graph';

export interface ConnectorEvent {
  eventType: string;
  provider: ConnectorProvider | null;
  timestamp: number;
  properties?: Record<string, unknown>;
}

export interface NormalizedEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  source: string;
  data: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  type: string;
  properties?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  weight?: number;
  properties?: Record<string, unknown>;
  created_at?: string;
}

export interface GraphWrites {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const initialConnectorState: ConnectorState = {
  status: 'disconnected',
  provider: null,
  credentialStatus: 'missing',
  tokenRefreshStatus: 'valid',
  backfillStatus: 'idle',
  incrementalSyncStatus: 'idle',
  webhookStatus: 'idle',
  sync: {
    recordsReceived: 0,
    recordsAccepted: 0,
    recordsRejected: 0,
    recordsNormalized: 0,
    recordsWritten: 0,
    lastError: null,
    degradedReason: null,
    lastSyncAt: null,
  },
  lastAction: null,
  lastActionResult: null,
  showRawPayload: false,
  showNormalizedPayload: false,
  showGraphWrites: false,
  rawPayload: null,
  normalizedPayload: null,
  graphWrites: null,
  providerSelectorOpen: false,
  sdkInitialized: false,
  sdkVersion: '0.1.0-alpha.0',
};
