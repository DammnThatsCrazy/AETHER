// =============================================================================
// Aether SDK — Universal financial normalization contracts (C1) tests
//
// Covers:
//   • namespaced canonical id validity (fiat/crypto/stablecoin/token; symbols
//     and legacy ids rejected)
//   • toDecimalString: decimal strings + integers + bigints accepted; exact
//     floats round-trip; non-exact floats / exponent floats / non-finite are
//     rejected with an explicit error (never silently truncated)
//   • canonical asset id !== symbol invariant
//   • CanonicalNativeValue narrowing guard + assertion
//   • ValuationSnapshot reporting_amount null semantics (null != "0")
//   • runtime-array members match the unions (compile-time array literals +
//     runtime deep-equality)
// =============================================================================

import { describe, expect, it } from 'vitest';

import {
  assertCanonicalNative,
  ASSET_KINDS,
  classifyEconomicRole,
  ECONOMIC_ROLES,
  FIAT_REFERENCE_SEED,
  isCanonicalNativeValue,
  isNamespacedAssetId,
  PRICE_STATUSES,
  RESOLUTION_STATUSES,
  toDecimalString,
  VALUATION_BASIS,
  VALUATION_METHOD_EXTENDED,
} from './index';
import type {
  AssetKind,
  CanonicalNativeValue,
  ChainStatus,
  EconomicRole,
  PriceStatus,
  ResolutionStatus,
  ValuationBasis,
  ValuationMethodExtended,
} from './index';
import { ALIAS_VERIFICATION_STATUSES, UNRESOLVED_REASONS, CHAIN_STATUSES } from './index';
import type { AliasVerificationStatus, UnresolvedReason } from './index';

// ── compile-time exhaustiveness: the unions and their runtime arrays are the
//    same set of string literals (each array is `as const satisfies`, so a new
//    union member that is missing from its array fails typechecking here).
type _Expect<T extends true> = T;
type _Covered<U extends string, A extends readonly U[]> = Exclude<U, A[number]> extends never
  ? true
  : false;

type _TAssetKinds = _Expect<_Covered<AssetKind, typeof ASSET_KINDS>>;
type _TChainStatuses = _Expect<_Covered<ChainStatus, typeof CHAIN_STATUSES>>;
type _TResolutionStatuses = _Expect<_Covered<ResolutionStatus, typeof RESOLUTION_STATUSES>>;
type _TEconomicRoles = _Expect<_Covered<EconomicRole, typeof ECONOMIC_ROLES>>;
type _TPriceStatuses = _Expect<_Covered<PriceStatus, typeof PRICE_STATUSES>>;
type _TValuationBasis = _Expect<_Covered<ValuationBasis, typeof VALUATION_BASIS>>;
type _TValuationMethodExtended = _Expect<
  _Covered<ValuationMethodExtended, typeof VALUATION_METHOD_EXTENDED>
>;
type _TAliasVerificationStatuses = _Expect<
  _Covered<AliasVerificationStatus, typeof ALIAS_VERIFICATION_STATUSES>
>;
type _TUnresolvedReasons = _Expect<_Covered<UnresolvedReason, typeof UNRESOLVED_REASONS>>;

// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _onlyExhaustivenessGuardTypes = [
  _TAssetKinds,
  _TChainStatuses,
  _TResolutionStatuses,
  _TEconomicRoles,
  _TPriceStatuses,
  _TValuationBasis,
  _TValuationMethodExtended,
  _TAliasVerificationStatuses,
  _TUnresolvedReasons,
];

describe('financial-assets namespaced identity', () => {
  it('accepts namespaced canonical asset ids', () => {
    expect(isNamespacedAssetId('fiat:USD')).toBe(true);
    expect(isNamespacedAssetId('crypto:ETH')).toBe(true);
    expect(isNamespacedAssetId('stablecoin:USDC')).toBe(true);
    // token chain segment may itself contain a colon (CAIP-2 eip155:8453)
    expect(isNamespacedAssetId('token:eip155:8453:0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')).toBe(true);
  });

  it('rejects symbols, legacy ids, deployments and empty values', () => {
    expect(isNamespacedAssetId('USDC')).toBe(false); // bare symbol — alias, not identity
    expect(isNamespacedAssetId('usdc')).toBe(false); // legacy id — bridged later by alias rows
    expect(isNamespacedAssetId('USD')).toBe(false);
    expect(isNamespacedAssetId('deploy:fiat:USD@eip155:1:native')).toBe(false);
    expect(isNamespacedAssetId('fiat:')).toBe(false);
    expect(isNamespacedAssetId('token:eip155:8453:')).toBe(false);
    expect(isNamespacedAssetId('')).toBe(false);
  });
});

describe('toDecimalString', () => {
  it('accepts decimal strings (trimmed, otherwise verbatim)', () => {
    expect(toDecimalString('1234.56')).toBe('1234.56');
    expect(toDecimalString('0.1')).toBe('0.1'); // decimal STRING is exact by declaration
    expect(toDecimalString('  42  ')).toBe('42');
    expect(toDecimalString('-7.25')).toBe('-7.25');
  });

  it('accepts integers and bigints', () => {
    expect(toDecimalString(42)).toBe('42');
    expect(toDecimalString(0)).toBe('0');
    expect(toDecimalString(123456789012345678901234567890n)).toBe('123456789012345678901234567890');
  });

  it('accepts floats that are exactly representable as their decimal string', () => {
    expect(toDecimalString(0.5)).toBe('0.5');
    expect(toDecimalString(2.25)).toBe('2.25');
    expect(toDecimalString(100)).toBe('100');
    expect(toDecimalString(1.5)).toBe('1.5');
  });

  it('rejects floats that do not round-trip exactly as decimals', () => {
    // 0.1, 0.2, 1/3 are binary artifacts whose shortest string is not their
    // exact decimal value — accepted floats would silently truncate.
    expect(() => toDecimalString(0.1)).toThrow(/not exactly representable/);
    expect(() => toDecimalString(0.2)).toThrow(/not exactly representable/);
    expect(() => toDecimalString(1 / 3)).toThrow(/not exactly representable/);
  });

  it('rejects exponent-notation floats, non-finite numbers and non-decimal strings', () => {
    expect(() => toDecimalString(1e21)).toThrow(/exponent notation/);
    expect(() => toDecimalString(0.0000001)).toThrow(/exponent notation/);
    expect(() => toDecimalString(NaN)).toThrow(/not a finite number/);
    expect(() => toDecimalString(Infinity)).toThrow(/not a finite number/);
    expect(() => toDecimalString('abc')).toThrow(/not a decimal string/);
    expect(() => toDecimalString('1,000.00')).toThrow(/not a decimal string/);
    expect(() => toDecimalString('1e3')).toThrow(/not a decimal string/);
  });
});

describe('canonical identity invariants', () => {
  it('keeps canonical asset id distinct from symbol', () => {
    const eth: CanonicalNativeValue = {
      amount: '1.25',
      currency: 'ETH',
      canonical_asset_id: 'crypto:ETH',
      asset_symbol: 'ETH',
    };
    expect(eth.canonical_asset_id).not.toBe(eth.asset_symbol);
    expect(isNamespacedAssetId(eth.canonical_asset_id)).toBe(true);
    expect(isNamespacedAssetId(eth.asset_symbol as string)).toBe(false);
  });

  it('seeds every fiat row under its namespaced id (id !== symbol)', () => {
    expect(FIAT_REFERENCE_SEED.length).toBe(16);
    const usd = FIAT_REFERENCE_SEED.find((r) => r.iso_code === 'USD');
    expect(usd).toMatchObject({ numeric_code: '840', minor_units: 2 });
    const jpy = FIAT_REFERENCE_SEED.find((r) => r.iso_code === 'JPY');
    expect(jpy).toMatchObject({ numeric_code: '392', minor_units: 0 });
    for (const row of FIAT_REFERENCE_SEED) {
      const id = `fiat:${row.iso_code}`;
      expect(isNamespacedAssetId(id)).toBe(true);
      expect(id).not.toBe(row.symbol);
    }
  });
});

describe('CanonicalNativeValue guards (value.ts additive contract)', () => {
  it('narrows values that carry a non-empty canonical_asset_id', () => {
    const canonical: CanonicalNativeValue = {
      amount: '25.00',
      currency: 'USDC',
      canonical_asset_id: 'stablecoin:USDC',
      deployment_id: 'deploy:stablecoin:USDC@eip155:8453:0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    };
    const symbolOnly = { amount: '25.00', currency: 'USDC', asset_symbol: 'USDC' };

    expect(isCanonicalNativeValue(canonical)).toBe(true);
    expect(isCanonicalNativeValue(symbolOnly)).toBe(false);
    expect(() => assertCanonicalNative(canonical)).not.toThrow();
    expect(() => assertCanonicalNative(symbolOnly)).toThrow(/canonical_asset_id is required/);
  });
});

describe('ValuationSnapshot null reporting_amount semantics', () => {
  it('keeps unavailable reporting_amount null — never coerced to "0"', () => {
    const snapshot = {
      valuation_id: 'val_1',
      tenant_id: 'tenant_a',
      canonical_asset_id: 'crypto:ETH',
      economic_role: 'asset_holding' as const,
      native_amount: '1.25',
      native_currency: 'ETH',
      reporting_asset_id: 'fiat:USD',
      reporting_amount: null, // unavailable
      valuation_basis: 'event_time' as const,
      price_status: 'missing_rate' as const,
      valuation_method: 'unavailable' as const,
      computed_at: '2026-09-02T00:00:00Z',
      effective_at: '2026-09-02T00:00:00Z',
    };
    expect(snapshot.reporting_amount).toBeNull();
    expect(snapshot.reporting_amount).not.toBe('0');
    expect(snapshot.price_status).toBe('missing_rate');
    expect(snapshot.valuation_method).toBe('unavailable');
  });
});

describe('runtime arrays match unions exactly', () => {
  it('ASSET_KINDS', () => {
    expect(ASSET_KINDS).toEqual(['fiat', 'crypto', 'stablecoin', 'token']);
  });
  it('CHAIN_STATUSES', () => {
    expect(CHAIN_STATUSES).toEqual(['active', 'deprecated', 'paused', 'under_review']);
  });
  it('RESOLUTION_STATUSES', () => {
    expect(RESOLUTION_STATUSES).toEqual([
      'resolved_chain_contract',
      'resolved_namespaced_id',
      'resolved_legacy_alias',
      'resolved_symbol_verified',
      'resolved_symbol_context',
      'collision_unresolvable',
      'unresolved_recorded',
    ]);
  });
  it('ECONOMIC_ROLES', () => {
    expect(ECONOMIC_ROLES).toEqual([
      'payment', 'settlement', 'charge', 'fee', 'cost', 'revenue',
      'refund', 'reversal', 'dispute', 'liability', 'asset_holding',
      'exposure', 'compensation', 'unknown',
    ]);
  });
  it('PRICE_STATUSES', () => {
    expect(PRICE_STATUSES).toEqual([
      'normal', 'provider_conflict', 'stale_rate', 'missing_rate', 'outlier',
      'fallback', 'manual', 'unavailable',
    ]);
  });
  it('VALUATION_BASIS', () => {
    expect(VALUATION_BASIS).toEqual([
      'transaction_time', 'event_time', 'settlement_time', 'observation_time',
    ]);
  });
  it('VALUATION_METHOD_EXTENDED lists existing ValuationMethod members + additive members', () => {
    expect(VALUATION_METHOD_EXTENDED).toEqual([
      'fiat_identity', 'fx_rate', 'market_price', 'provider_reported',
      'stablecoin_peg_verified', 'manual', 'unavailable',
      'oracle', 'venue_exec', 'primary_market', 'stablecoin_peg',
    ]);
  });
  it('ALIAS_VERIFICATION_STATUSES and UNRESOLVED_REASONS', () => {
    expect(ALIAS_VERIFICATION_STATUSES).toEqual(['verified', 'unverified', 'contested', 'retired']);
    expect(UNRESOLVED_REASONS).toEqual([
      'unknown_symbol', 'ambiguous_symbol', 'unknown_chain', 'unknown_contract',
      'no_registry_entry', 'malformed_reference',
    ]);
  });
});

describe('classifyEconomicRole', () => {
  it('classifies bare strings and hint fields, defaulting to unknown', () => {
    expect(classifyEconomicRole('payment')).toBe('payment');
    expect(classifyEconomicRole('REVENUE')).toBe('revenue');
    expect(classifyEconomicRole({ economic_role: 'fee' })).toBe('fee');
    expect(classifyEconomicRole({ role: 'settlement' })).toBe('settlement');
    expect(classifyEconomicRole({ purpose: 'liability' })).toBe('liability');
    expect(classifyEconomicRole(undefined)).toBe('unknown');
    expect(classifyEconomicRole('not-a-role')).toBe('unknown');
    expect(classifyEconomicRole(42)).toBe('unknown');
  });
});
