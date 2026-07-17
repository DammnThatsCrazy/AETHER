/**
 * DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const temporalPolicyVersion = '1.0.0' as const;

export const temporalEnforcementModes = ['off', 'shadow', 'warn', 'enforce'] as const;
export type TemporalEnforcementMode = typeof temporalEnforcementModes[number];

export const temporalDispositions = ['accept', 'accept_with_warning', 'quarantine', 'reject'] as const;
export type TemporalDisposition = typeof temporalDispositions[number];

/** Disposition applied to each stable temporal reason code. */
export const temporalReasonDispositions = {
  clock_skew_warning: 'accept_with_warning',
  delivery_lag_warning: 'accept_with_warning',
  local_time_ambiguous: 'quarantine',
  local_time_nonexistent: 'reject',
  temporal_authority_missing: 'reject',
  temporal_policy_violation: 'reject',
  temporal_provenance_missing: 'accept_with_warning',
  timestamp_future: 'reject',
  timestamp_invalid: 'reject',
  timestamp_naive: 'reject',
  timestamp_too_old: 'quarantine',
  timezone_invalid: 'reject',
  timezone_offset_mismatch: 'reject',
} as const;

export interface TemporalFamilyBounds {
  maxFutureSkewMs: number;
  warnSkewMs: number;
  maxLatenessMs: number;
}

/** Complete (default-resolved) temporal bounds per event family. */
export const temporalFamilyBounds: Record<string, TemporalFamilyBounds> = {
  agent: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  b2b: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  commerce: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  comms: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 1209600000 },
  consent: { maxFutureSkewMs: 60000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  core: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  credit: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  derivatives: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 2592000000 },
  ecommerce: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  exposure: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  friction: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  identity: { maxFutureSkewMs: 60000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  identity_lc: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  interaction: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  interop: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 2592000000 },
  journey: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  location: { maxFutureSkewMs: 60000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  outcome: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  reward: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  server: { maxFutureSkewMs: 60000, warnSkewMs: 5000, maxLatenessMs: 604800000 },
  stablecoin: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 2592000000 },
  wallet: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 },
  web3_lc: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 2592000000 },
  x402: { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 2592000000 },
};

export const temporalDefaultBounds: TemporalFamilyBounds = { maxFutureSkewMs: 300000, warnSkewMs: 30000, maxLatenessMs: 604800000 };
