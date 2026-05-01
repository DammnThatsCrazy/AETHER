// =============================================================================
// Aether SDK — Shared Consent Contract
// Canonical consent purposes gated by the ingestion validator and by the
// per-SDK event queues. See docs/source-of-truth/CONSENT_MODEL.md.
// =============================================================================

/**
 * Canonical consent purposes. Web SDK, native SDKs, and the backend validator
 * MUST all recognize these exact five strings.
 *
 * - analytics: track/page/screen/identify/heartbeat/error/performance/conversion
 * - marketing: conversion/experiment/campaign-derived attribution
 * - web3: wallet, transaction, on-chain action, token/nft/defi signals
 * - agent: agent_task, agent_decision, A2H notifications
 * - commerce: payment, approval, entitlement, access, x402
 */
export type ConsentPurpose =
  | 'analytics'
  | 'marketing'
  | 'web3'
  | 'agent'
  | 'commerce';

export const CONSENT_PURPOSES: readonly ConsentPurpose[] = [
  'analytics',
  'marketing',
  'web3',
  'agent',
  'commerce',
] as const;

/** Consent state stored locally by each SDK and stamped onto every event. */
export interface ConsentState {
  analytics: boolean;
  marketing: boolean;
  web3: boolean;
  agent: boolean;
  commerce: boolean;
  updatedAt: string;
  policyVersion: string;
}

export interface ConsentConfig {
  purposes: ConsentPurpose[];
  policyUrl: string;
  policyVersion: string;
}

/** Default (no consent granted) state — used by every SDK at init. */
export const DEFAULT_CONSENT_STATE: Omit<ConsentState, 'updatedAt' | 'policyVersion'> = {
  analytics: false,
  marketing: false,
  web3: false,
  agent: false,
  commerce: false,
};
