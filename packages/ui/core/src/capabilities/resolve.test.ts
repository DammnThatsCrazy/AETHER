import { describe, it, expect } from 'vitest';

import { isDestinationVisible, isDomainExcluded, resolveDestinationAvailability } from './resolve';
import type { Capabilities } from './types';

function caps(
  releaseOver: Partial<Capabilities['release']> = {},
  flags: Record<string, boolean> = {},
): Capabilities {
  return {
    tenant_id: 't',
    release: {
      deployment_profile: 'production-lean',
      environment: 'production',
      release_class: 'production',
      enforcement: {
        policy_enforcement: true,
        route_registry_enforced: true,
        kyber_operator_gate: true,
      },
      enabled_route_prefixes: ['/v1/profile360'],
      excluded_domains: ['stablecoin', 'derivatives', 'payments'],
      ...releaseOver,
    },
    profile_sub_resources: [],
    providers: [],
    consent_purposes_granted: [],
    consent_purposes_all: [],
    feature_flags: flags,
    evaluated_at: '2026-01-01T00:00:00Z',
  };
}

describe('resolveDestinationAvailability', () => {
  it('is available with no requirement', () => {
    expect(resolveDestinationAvailability(caps(), undefined)).toBe('available');
  });

  it('fails closed before required capabilities load', () => {
    expect(resolveDestinationAvailability(null, { domain: 'stablecoins' })).toBe('unavailable');
    expect(resolveDestinationAvailability(null, undefined)).toBe('available');
  });

  it('marks an excluded domain not_in_release (plural matches singular)', () => {
    expect(resolveDestinationAvailability(caps(), { domain: 'stablecoins' })).toBe('not_in_release');
    expect(resolveDestinationAvailability(caps(), { domain: 'derivatives' })).toBe('not_in_release');
    expect(resolveDestinationAvailability(caps(), { domain: 'payments' })).toBe('not_in_release');
  });

  it('leaves a non-excluded domain available', () => {
    expect(resolveDestinationAvailability(caps(), { domain: 'profile' })).toBe('available');
  });

  it('disables an explicitly-off flag, allows on, and fails closed for unknown', () => {
    expect(
      resolveDestinationAvailability(caps({}, { connectors_enabled: false }), {
        flag: 'connectors_enabled',
      }),
    ).toBe('disabled');
    expect(
      resolveDestinationAvailability(caps({}, { connectors_enabled: true }), {
        flag: 'connectors_enabled',
      }),
    ).toBe('available');
    expect(resolveDestinationAvailability(caps(), { flag: 'unknown_flag' })).toBe('unavailable');
  });
});

describe('isDomainExcluded / isDestinationVisible', () => {
  it('isDomainExcluded is plural-aware', () => {
    expect(isDomainExcluded(caps(), 'stablecoins')).toBe(true);
    expect(isDomainExcluded(caps(), 'stablecoin')).toBe(true);
    expect(isDomainExcluded(caps(), 'identity')).toBe(false);
  });

  it('isDestinationVisible is false for excluded, disabled, and unavailable', () => {
    expect(isDestinationVisible(caps(), { domain: 'payments' })).toBe(false);
    expect(isDestinationVisible(caps(), { domain: 'identity' })).toBe(true);
    expect(isDestinationVisible(null, { domain: 'identity' })).toBe(false);
  });
});
