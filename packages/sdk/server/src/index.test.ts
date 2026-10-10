import { describe, it, expect } from 'vitest';
import { AetherServerSDK } from './index';

describe('AetherServerSDK', () => {
  it('initializes with default consent state (all false)', () => {
    const sdk = new AetherServerSDK({ apiKey: 'test-key', endpoint: 'http://localhost' });
    const consent = sdk.getConsent();
    expect(consent.analytics).toBe(false);
    expect(consent.marketing).toBe(false);
    expect(consent.personalization).toBe(false);
    expect(consent.web3).toBe(false);
    expect(consent.agent).toBe(false);
    expect(consent.commerce).toBe(false);
    expect(consent.credit).toBe(false);
    expect(consent.location).toBe(false);
    sdk.shutdown();
  });

  it('grantAll() grants non-explicit-opt-in purposes only', () => {
    const sdk = new AetherServerSDK({ apiKey: 'test-key', endpoint: 'http://localhost' });
    sdk.grantAll();
    const consent = sdk.getConsent();
    expect(consent.analytics).toBe(true);
    expect(consent.marketing).toBe(true);
    expect(consent.personalization).toBe(true);
    expect(consent.web3).toBe(true);
    expect(consent.agent).toBe(true);
    expect(consent.commerce).toBe(true);
    // credit and location must remain false — explicit opt-in only
    expect(consent.credit).toBe(false);
    expect(consent.location).toBe(false);
    sdk.shutdown();
  });

  it('grant(["credit"]) explicitly grants credit', () => {
    const sdk = new AetherServerSDK({ apiKey: 'test-key', endpoint: 'http://localhost' });
    sdk.grant(['credit']);
    const consent = sdk.getConsent();
    expect(consent.credit).toBe(true);
    sdk.shutdown();
  });

  it('revoke() removes granted purposes', () => {
    const sdk = new AetherServerSDK({ apiKey: 'test-key', endpoint: 'http://localhost' });
    sdk.grantAll();
    sdk.revoke(['analytics', 'marketing']);
    const consent = sdk.getConsent();
    expect(consent.analytics).toBe(false);
    expect(consent.marketing).toBe(false);
    expect(consent.personalization).toBe(true);
    sdk.shutdown();
  });
});

describe('consent registry parity', () => {
  it('covers exactly the registry purpose vocabulary, deny-by-default', async () => {
    const { CONSENT_PURPOSES, EXPLICIT_OPT_IN_PURPOSES } = await import('@aether/shared/consent');
    const sdk = new AetherServerSDK({ apiKey: 'test-key', endpoint: 'http://localhost' });
    const consent = sdk.getConsent() as unknown as Record<string, boolean>;
    // The hand-written copy of this vocabulary shipped 9 of 12 purposes;
    // this pins the SDK's consent state to the generated registry contract.
    expect(Object.keys(consent).sort()).toEqual([...CONSENT_PURPOSES].sort());
    for (const p of CONSENT_PURPOSES) expect(consent[p]).toBe(false);

    sdk.grantAll();
    const granted = sdk.getConsent() as unknown as Record<string, boolean>;
    for (const p of CONSENT_PURPOSES) {
      expect(granted[p]).toBe(!EXPLICIT_OPT_IN_PURPOSES.includes(p));
    }
    sdk.shutdown();
  });
});
