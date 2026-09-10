import { describe, expect, it } from 'vitest';
import { buildDomainMap, originFor, PRODUCTION_DOMAINS } from './domains';

describe('PRODUCTION_DOMAINS', () => {
  it('matches the origins every app env.ts already defaults to', () => {
    expect(PRODUCTION_DOMAINS.olympus).toBe('https://olympuslabsml.com');
    expect(PRODUCTION_DOMAINS.aetherMarketing).toBe('https://aether.olympuslabsml.com');
    expect(PRODUCTION_DOMAINS.aetherApp).toBe('https://app.olympuslabsml.com');
    expect(PRODUCTION_DOMAINS.docs).toBe('https://docs.olympuslabsml.com');
    expect(PRODUCTION_DOMAINS.status).toBe('https://status.olympuslabsml.com');
    expect(PRODUCTION_DOMAINS.kyber).toBe('https://kyber.olympuslabsml.com');
  });
});

describe('buildDomainMap', () => {
  it('returns the production defaults with no overrides', () => {
    expect(buildDomainMap()).toEqual(PRODUCTION_DOMAINS);
  });

  it('overrides only the supplied keys', () => {
    const map = buildDomainMap({ olympus: 'https://olympus.invalid' });
    expect(map.olympus).toBe('https://olympus.invalid');
    expect(map.aetherMarketing).toBe(PRODUCTION_DOMAINS.aetherMarketing);
  });
});

describe('originFor', () => {
  it('looks up an origin by subdomain key', () => {
    const map = buildDomainMap();
    expect(originFor(map, 'docs')).toBe(map.docs);
  });
});
