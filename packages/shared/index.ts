// =============================================================================
// Aether SDK — Shared Contracts (canonical source of truth)
// All SDK packages (web, ios, android, react-native) MUST align to these.
// =============================================================================

export * from './schema-version';
export * from './sdk-version';
export * from './provenance';
export * from './consent';
export * from './consent-receipt';
export * from './integration-consent';
export * from './measurement-contract';
export * from './wallet';
export * from './identity';
export * from './entities';
export * from './commerce';
export * from './agent';
export * from './x402-lifecycle';
export * from './events'; // includes reward enablement event types (A6)
// Canonical envelope context v1 — declared explicitly as public SDK surface so
// every SDK/consumer discovers the additive envelope shape from the barrel
// (these are also covered by the star export above; the explicit list documents
// intent and keeps the public envelope contract greppable).
export type {
  ApplicationContext,
  OperatingSystemContext,
  NetworkContext,
  SemanticInputContext,
  SemanticHints,
  SamplingContext,
  CorrelationContext,
  SequenceContext,
} from './events';
export * from './agentic-observability'; // agentic observability contracts
export * from './capabilities';
export * from './economic';
export * from './economic-metrics';
export * from './contextual';
export * from './graph-relationships';
export * from './graph-contract';
export * from './intelligence';
export * from './financials';
export * from './profile360-contract';
export * from './operational-intelligence'; // includes Phase 20 path intelligence types (RelationshipPath, PathQuery, PathExplanation, TraversalSnapshot, DeepTraversalJob)
export * from './decision-outcome-intelligence';

// Existing partial contracts (already referenced by RN SDK).
export * from './ecommerce-types';
export * from './feature-flag-types';
export * from './feedback-types';
export * from './solution-packages';
export * from './gtm-pricing';
export * from './customer-onboarding';
export * from './security-governance';
export * from './suggestions';
export * from './connector-taxonomy';
export * from './campaign-exploration-contract';
export * from './acquisition-evidence';
export * from './traffic-source';

export * from './semantic-sentiment';
export * from './derivatives';
export * from './stablecoin';
export * from './stablecoin-intelligence';

// First-release intelligence/telemetry/payments contracts (8.12.0)
export * from './agent-deployment';
export * from './ai-execution';
export * from './payment-rails';
export * from './payment-catalog';
export * from './card-linked-payments';
export * from './targeting-intelligence';
export * from './interoperability';

// Canonical financial value semantics (USD-first, native-preserving)
export * from './value';

// Production-readiness platform contracts
export * from './ingestion-contract';
export * from './problem-details';
export * from './dimension-state';
export * from './temporal';
export * from './temporal-policy';
export * from './exploration-contract';
export * from './continuation';
export * from './sync-event';
export * from './delivery-receipt';
export * from './notification';
export * from './imports';

// Unified-platform registries (generated from packages/shared/contracts/*.json
// by scripts/generate_platform_contracts.py)
export * from './interaction-contract';
export * from './context-capsule';
export * from './graph-mutation';
export * from './filter-fields';
export * from './surface-capabilities';
export * from './comparison-contract';
