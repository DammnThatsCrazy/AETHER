// =============================================================================
// Aether SDK — Shared Contracts (canonical source of truth)
// All SDK packages (web, ios, android, react-native) MUST align to these.
// =============================================================================

export * from './schema-version';
export * from './sdk-version';
export * from './provenance';
export * from './consent';
export * from './wallet';
export * from './identity';
export * from './entities';
export * from './commerce';
export * from './agent';
export * from './x402-lifecycle';
export * from './events'; // includes reward enablement event types (A6)
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

// Production-readiness platform contracts
export * from './ingestion-contract';
export * from './problem-details';
export * from './dimension-state';
export * from './imports';
