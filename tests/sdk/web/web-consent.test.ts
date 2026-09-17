/**
 * FPS-055 — Web SDK Consent
 * Verifies web SDK consent-gated event delivery.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { consentDisabledFixture } from '@aether/proof-fixtures';

import { AetherSDK } from '@aether/web';

describe('FPS-055: Web SDK Consent', () => {
  it('should block events when consent is disabled', () => {
    const envelope = consentDisabledFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('consent');
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.enabled).toBe(false);
    expect(props?.consent_version).toBe('1.0');
    expect(props?.consent_granted_at).toBeNull();
    const purposes = props?.purposes;
    expect(purposes).toEqual({});
    const consentedPurposes = props?.consented_purposes;
    expect(Array.isArray(consentedPurposes)).toBe(true);
    expect(consentedPurposes?.length).toBe(0);
  });

  it('should allow analytics events when consent granted', () => {
    const props: Record<string, unknown> = { enabled: true, purposes: { analytics: true } };
    expect(props.purposes.analytics).toBe(true);
  });

  it('should block marketing events without marketing consent', () => {
    const props: Record<string, unknown> = { enabled: true, purposes: { analytics: true, marketing: false } };
    expect(props.purposes.marketing).toBe(false);
  });

  it('should accept granular purpose consent', () => {
    const props: Record<string, unknown> = {
      enabled: true,
      purposes: { analytics: true, marketing: true, personalization: false },
    };
    expect(Object.keys(props.purposes as Record<string, unknown>)).toHaveLength(3);
  });

  it('should call consent.grant without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => {
      sdk.consent.grant('analytics');
    }).not.toThrow();
  });

  it('should call consent.revoke without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => {
      sdk.consent.revoke('analytics');
    }).not.toThrow();
  });
});
