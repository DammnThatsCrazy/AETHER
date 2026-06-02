// =============================================================================
// Aether SDK — Shared Contracts (canonical source of truth)
// All SDK packages (web, ios, android, react-native) MUST align to these.
// =============================================================================

export * from './schema-version';
export * from './provenance';
export * from './consent';
export * from './wallet';
export * from './identity';
export * from './entities';
export * from './commerce';
export * from './agent';
export * from './events';
export * from './capabilities';
export * from './economic';
export * from './contextual';
export * from './graph-relationships';
export * from './intelligence';
export * from './financials';
export * from './profile360-contract';
export * from './operational-intelligence';
export * from './decision-outcome-intelligence';

// Existing partial contracts (already referenced by RN SDK).
export * from './ecommerce-types';
export * from './feature-flag-types';
export * from './feedback-types';
export * from './solution-packages';
export * from './customer-success';
