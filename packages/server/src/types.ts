// Server SDK types — mirrors the shared consent model.

export type ConsentPurpose =
  | 'analytics'
  | 'marketing'
  | 'personalization'
  | 'web3'
  | 'agent'
  | 'commerce'
  | 'credit'
  | 'location'
  | 'financial_activity';

export interface ServerConsentState {
  analytics: boolean;
  marketing: boolean;
  personalization: boolean;
  web3: boolean;
  agent: boolean;
  commerce: boolean;
  /** Always requires explicit opt-in — never granted by grantAll(). */
  credit: boolean;
  /** Always requires explicit opt-in — never granted by grantAll(). */
  location: boolean;
  /** Always requires explicit opt-in — gates agent trading orders, fills, positions, portfolio, and performance snapshots. */
  financial_activity: boolean;
}

/**
 * Per-batch ingestion health counters (Truth Kernel §2.8).
 *
 * `accepted` / `duplicate` / `rejected` are parsed from the backend
 * BatchResponse (packages/shared/ingestion-contract.ts). `dropped_by_consent`
 * and `queue_depth` are SDK-side truths surfaced alongside them: the server SDK
 * does not consent-drop locally (consent is sent as a hint), so
 * `dropped_by_consent` is 0 unless a future local gate drops events;
 * `queue_depth` reflects the in-process queue backlog after the batch is sent.
 */
export interface BatchHealth {
  accepted: number;
  duplicate: number;
  rejected: number;
  dropped_by_consent: number;
  queue_depth: number;
}

export interface ServerEvent {
  type: string;
  userId?: string;
  anonymousId?: string;
  properties?: Record<string, unknown>;
  context?: Record<string, unknown>;
  timestamp?: string;
  messageId?: string;
}

export interface AetherServerConfig {
  writeKey: string;
  endpoint?: string;
  /** Consent state for server-side events. */
  consent?: Partial<ServerConsentState>;
  /** Max events in memory before flushing. Default 100. */
  flushAt?: number;
  /** Flush interval in ms. Default 5000. */
  flushInterval?: number;
  /** Max queue size. Default 1000. */
  maxQueueSize?: number;
  /** User-Agent header value. */
  userAgent?: string;
  /**
   * Called after each successfully delivered batch with per-batch ingestion
   * health counters (Truth Kernel §2.8).
   */
  onBatchResult?: (health: BatchHealth) => void;
}
