// =============================================================================
// Aether SDK — Shared Provenance & Rail Metadata
// Every canonical event may carry provenance so Web2, Web3, and hybrid flows
// fit the same model. See docs/source-of-truth/EVENT_REGISTRY.md.
// =============================================================================

/** Who or what performed the action. */
export type ActorKind = 'human' | 'org' | 'wallet' | 'agent' | 'service' | 'system';

/** Where the event originated. */
export type SourceKind = 'sdk' | 'connector' | 'backend' | 'inferred' | 'import';

/** Which SDK surface produced the event (when source_kind='sdk'). */
export type SourcePlatform = 'web' | 'ios' | 'android' | 'react-native' | 'server';

/**
 * Payment / value-transfer rail. Covers Web2, Web3, and internal flows.
 * - fiat: card/ACH/bank rails not tied to a specific processor
 * - stripe: Stripe-specific fiat rail
 * - invoice: off-platform invoice / net-terms billing
 * - onchain: native on-chain transfer (no x402 semantics)
 * - x402: HTTP 402 / agentic commerce rail
 * - internal_credit: non-monetary platform credits
 */
export type Rail = 'fiat' | 'stripe' | 'invoice' | 'onchain' | 'x402' | 'internal_credit';

/** Whether a signal was directly observed or inferred by the backend. */
export type Observation = 'observed' | 'inferred';

/** Standard provenance block attachable to any canonical event's properties. */
export interface Provenance {
  source_kind: SourceKind;
  source_platform?: SourcePlatform;
  actor_kind?: ActorKind;
  rail?: Rail;
  observation?: Observation;
  /** Optional external identifier — e.g. Stripe charge id, tx hash, x402 id. */
  external_ref?: string;
}
