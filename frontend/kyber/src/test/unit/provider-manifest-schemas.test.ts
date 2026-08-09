/**
 * KYBER provider-connections — manifest contract schemas + pure selectors.
 *
 * The admin providers route shape (the contract with Team C's backend) is:
 *   { identity, display_name, category, readiness:{level}, availability:{
 *     environments }, authentication:{type}, capabilities:[...], certification_state }
 *
 * These tests pin that exact shape: valid entries parse, required fields are
 * enforced, readiness level stays within 0-5 (0 is the backend's unscored
 * fallback emitted by _admin_provider_item), and the selectors never lie about
 * environment visibility or certification (empty != passed).
 */
import { describe, expect, it } from 'vitest';
import {
  connectionsOverviewSchema,
  environmentAvailabilitySchema,
  isProviderVisible,
  providerCatalogEntrySchema,
  providerCatalogListSchema,
  providerCertified,
  providerEnvironments,
  runtimeHealthSchema,
} from '@kyber/features/provider-connections';

const VALID_ENTRY = {
  identity: 'payments.stripe.payouts',
  display_name: 'Stripe Payouts',
  category: 'payments',
  readiness: { level: 4, state: 'sandbox_validated' },
  availability: {
    environments: { local: true, integration: true, staging: false, production: false },
    tenant_self_service: false,
    kyber_managed: true,
  },
  authentication: { type: 'oauth2' },
  capabilities: { auth: true, account: true, pull: true, webhook: false, report: false, stream: false, reconciliation: false },
  certification_state: 'certified',
  source: 'plugin',
};

describe('providerCatalogEntrySchema', () => {
  it('accepts a valid contract-shape entry', () => {
    const result = providerCatalogEntrySchema.parse(VALID_ENTRY);
    expect(result.identity).toBe('payments.stripe.payouts');
    expect(result.display_name).toBe('Stripe Payouts');
    expect(result.readiness.level).toBe(4);
    expect(result.capabilities.auth).toBe(true);
    expect(result.capabilities.webhook).toBe(false);
    expect(result.certification_state).toBe('certified');
    expect(result.source).toBe('plugin');
  });

  it('rejects missing required fields', () => {
    expect(() => providerCatalogEntrySchema.parse({ ...VALID_ENTRY, identity: undefined })).toThrow();
    expect(() => providerCatalogEntrySchema.parse({ ...VALID_ENTRY, display_name: undefined })).toThrow();
    expect(() => providerCatalogEntrySchema.parse({ ...VALID_ENTRY, certification_state: undefined })).toThrow();
    expect(() => providerCatalogEntrySchema.parse({ ...VALID_ENTRY, capabilities: undefined })).toThrow();
  });

  it('rejects readiness levels outside 0-5', () => {
    expect(() => providerCatalogEntrySchema.parse({ ...VALID_ENTRY, readiness: { level: 6 } })).toThrow();
    expect(() => providerCatalogEntrySchema.parse({ ...VALID_ENTRY, readiness: { level: -1 } })).toThrow();
  });

  it('accepts the backend level:0 unscored fallback', () => {
    const result = providerCatalogEntrySchema.parse({ ...VALID_ENTRY, readiness: { level: 0 } });
    expect(result.readiness.level).toBe(0);
  });

  it('accepts an empty capabilities badge set', () => {
    const result = providerCatalogEntrySchema.parse({ ...VALID_ENTRY, capabilities: {} });
    expect(Object.keys(result.capabilities)).toHaveLength(0);
  });

  it('rejects a missing readiness block', () => {
    expect(() =>
      providerCatalogEntrySchema.parse({ ...VALID_ENTRY, readiness: undefined }),
    ).toThrow();
  });
});

describe('providerCatalogListSchema', () => {
  it('accepts the { providers, count } envelope and returns valid entries + no issues', () => {
    const result = providerCatalogListSchema.parse({ providers: [VALID_ENTRY], count: 1 });
    expect(result.providers).toHaveLength(1);
    expect(result.issues).toHaveLength(0);
    expect(result.providers[0]?.identity).toBe('payments.stripe.payouts');
  });

  it('rejects a bare array — the backend always emits the envelope', () => {
    expect(() => providerCatalogListSchema.parse([VALID_ENTRY])).toThrow();
  });

  it('requires count to be a number (no nullish count)', () => {
    expect(() => providerCatalogListSchema.parse({ providers: [VALID_ENTRY] })).toThrow();
  });

  it('tolerates a malformed entry: surfaces it as an issue, keeps the valid ones', () => {
    const result = providerCatalogListSchema.parse({
      providers: [VALID_ENTRY, { identity: 'only-identity' }],
      count: 2,
    });
    expect(result.providers).toHaveLength(1);
    expect(result.providers[0]?.identity).toBe('payments.stripe.payouts');
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0]?.identity).toBe('only-identity');
    expect(result.issues[0]?.status).toBe('invalid');
  });

  it('tags an out-of-range readiness as an issue instead of killing the catalog', () => {
    const result = providerCatalogListSchema.parse({
      providers: [VALID_ENTRY, { ...VALID_ENTRY, identity: 'legacy.broken', readiness: { level: 6 } }],
      count: 2,
    });
    expect(result.providers).toHaveLength(1);
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0]?.identity).toBe('legacy.broken');
    expect(result.issues[0]?.status).toBe('invalid');
  });

  it('tags a non-boolean capability as an issue instead of killing the catalog', () => {
    const result = providerCatalogListSchema.parse({
      providers: [VALID_ENTRY, { ...VALID_ENTRY, identity: 'legacy.bad-cap', capabilities: { auth: 'yes' } }],
      count: 2,
    });
    expect(result.providers).toHaveLength(1);
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0]?.identity).toBe('legacy.bad-cap');
  });
});

describe('runtimeHealthSchema', () => {
  it('parses the registry summary', () => {
    const result = runtimeHealthSchema.parse({ providers_loaded: 12, legacy_count: 3, native_count: 9 });
    expect(result.providers_loaded).toBe(12);
    expect(result.native_count).toBe(9);
  });
});

describe('connectionsOverviewSchema', () => {
  it('parses identity -> state -> count', () => {
    const result = connectionsOverviewSchema.parse({
      providers: { 'payments.stripe.payouts': { enabled: 2, disabled: 1 } },
      total: 3,
    });
    expect(result.total).toBe(3);
  });
});

describe('environmentAvailabilitySchema', () => {
  it('defaults absent environments to false', () => {
    const result = environmentAvailabilitySchema.parse({});
    expect(result.local).toBe(false);
    expect(result.production).toBe(false);
  });
});

describe('provider manifest selectors', () => {
  it('isProviderVisible reflects claimed environments', () => {
    expect(isProviderVisible(VALID_ENTRY)).toBe(true);
    expect(
      isProviderVisible({
        ...VALID_ENTRY,
        availability: { environments: { local: false, integration: false, staging: false, production: false } },
      }),
    ).toBe(false);
  });

  it('providerEnvironments orders by stability, production first', () => {
    const entry = {
      ...VALID_ENTRY,
      availability: {
        environments: { production: true, local: true, staging: false, integration: false },
      },
    };
    expect(providerEnvironments(entry)).toEqual(['production', 'local']);
  });

  it('providerCertified never treats a missing state as passed', () => {
    expect(providerCertified(VALID_ENTRY)).toBe(true);
    expect(providerCertified({ ...VALID_ENTRY, certification_state: 'uncertified' })).toBe(false);
    expect(providerCertified({ ...VALID_ENTRY, certification_state: '' })).toBe(false);
    expect(providerCertified({ ...VALID_ENTRY, certification_state: 'CERTIFIED' })).toBe(true);
  });
});
