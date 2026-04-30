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

// Existing partial contracts (already referenced by RN SDK).
export * from './ecommerce-types';
export * from './feature-flag-types';
export * from './feedback-types';
