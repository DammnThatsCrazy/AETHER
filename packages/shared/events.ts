// =============================================================================
// Aether SDK — Shared Event Envelope & Registry
// Canonical shapes every SDK emits and every ingestion validator accepts.
// See docs/source-of-truth/EVENT_REGISTRY.md and INGESTION_CONTRACT.md.
// =============================================================================

import type { ConsentState } from './consent';
import type { Provenance } from './provenance';

// ---------------------------------------------------------------------------
// Event families
// ---------------------------------------------------------------------------

/** The canonical event-type string union the backend validates. */
export type EventType =
  // Core analytics
  | 'track'
  | 'page'
  | 'screen'
  | 'heartbeat'
  | 'error'
  | 'performance'
  | 'experiment'
  // Identity
  | 'identify'
  | 'consent'
  // Commerce / access (Web2 + Web3 unified)
  | 'conversion'
  | 'payment_initiated'
  | 'payment_completed'
  | 'payment_failed'
  | 'approval_requested'
  | 'approval_resolved'
  | 'entitlement_granted'
  | 'entitlement_revoked'
  | 'access_granted'
  | 'access_denied'
  // Wallet / on-chain (optional)
  | 'wallet'
  | 'transaction'
  | 'contract_action'
  // Agent (optional)
  | 'agent_task'
  | 'agent_decision'
  | 'a2h_interaction'
  // x402 (optional)
  | 'x402_payment';

export type EventFamily =
  | 'core'
  | 'identity'
  | 'consent'
  | 'commerce'
  | 'wallet'
  | 'agent'
  | 'x402';

/** Map from each event type to the family it belongs to. */
export const EVENT_FAMILY: Record<EventType, EventFamily> = {
  track: 'core', page: 'core', screen: 'core', heartbeat: 'core',
  error: 'core', performance: 'core', experiment: 'core',
  identify: 'identity',
  consent: 'consent',
  conversion: 'commerce',
  payment_initiated: 'commerce', payment_completed: 'commerce', payment_failed: 'commerce',
  approval_requested: 'commerce', approval_resolved: 'commerce',
  entitlement_granted: 'commerce', entitlement_revoked: 'commerce',
  access_granted: 'commerce', access_denied: 'commerce',
  wallet: 'wallet', transaction: 'wallet', contract_action: 'wallet',
  agent_task: 'agent', agent_decision: 'agent', a2h_interaction: 'agent',
  x402_payment: 'x402',
};

/**
 * Required consent purpose for each event type. If the purpose is not
 * granted, the SDK event queue MUST drop the event before transport.
 */
export const EVENT_CONSENT_PURPOSE: Record<EventType, string> = {
  track: 'analytics', page: 'analytics', screen: 'analytics',
  heartbeat: 'analytics', error: 'analytics', performance: 'analytics',
  identify: 'analytics',
  experiment: 'marketing', conversion: 'marketing',
  consent: 'analytics',
  payment_initiated: 'commerce', payment_completed: 'commerce', payment_failed: 'commerce',
  approval_requested: 'commerce', approval_resolved: 'commerce',
  entitlement_granted: 'commerce', entitlement_revoked: 'commerce',
  access_granted: 'commerce', access_denied: 'commerce',
  wallet: 'web3', transaction: 'web3', contract_action: 'web3',
  agent_task: 'agent', agent_decision: 'agent', a2h_interaction: 'agent',
  x402_payment: 'commerce',
};

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

export interface PageContext {
  url: string;
  path: string;
  title: string;
  referrer: string;
  search?: string;
  hash?: string;
}

export interface DeviceContext {
  type: 'desktop' | 'mobile' | 'tablet';
  os?: string;
  osVersion?: string;
  browser?: string;
  browserVersion?: string;
  screenWidth?: number;
  screenHeight?: number;
  viewportWidth?: number;
  viewportHeight?: number;
  pixelRatio?: number;
  language?: string;
}

export interface CampaignContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  clickId?: string;
  referrerDomain?: string;
  referrerType?: 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'unknown';
}

export interface LibraryContext {
  name: string;
  version: string;
}

export interface EventContext {
  library: LibraryContext;
  page?: PageContext;
  device?: DeviceContext;
  campaign?: CampaignContext;
  fingerprint?: { id: string };
  ip?: string;
  locale?: string;
  timezone?: string;
  userAgent?: string;
  consent?: ConsentState;
  provenance?: Provenance;
  /** Optional tenant/org binding for B2B + hybrid companies. */
  tenantId?: string;
  orgId?: string;
}

/** The canonical event envelope every SDK emits. */
export interface BaseEvent {
  id: string;
  type: EventType;
  timestamp: string;
  sessionId: string;
  anonymousId: string;
  userId?: string;
  properties?: Record<string, unknown>;
  context: EventContext;
}

/** Ingestion batch envelope POSTed to /v1/batch. */
export interface BatchPayload {
  batch: BaseEvent[];
  sentAt: string;
  context?: { library: LibraryContext };
}
