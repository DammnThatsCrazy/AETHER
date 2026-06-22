// Server SDK types — mirrors the shared consent model.

export type ConsentPurpose =
  | 'analytics'
  | 'marketing'
  | 'personalization'
  | 'web3'
  | 'agent'
  | 'commerce'
  | 'credit'
  | 'location';

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
}
