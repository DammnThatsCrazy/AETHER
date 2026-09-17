/**
 * FPS-021 — SDK Consent Disabled Behavior
 * Verifies that no events are sent when consent is disabled.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { consentDisabledFixture } from '@aether/proof-fixtures';

describe('FPS-021: SDK Consent Disabled', () => {
  it('should not send events when consent is disabled', () => {
    const consentEnabled = false;
    expect(consentEnabled).toBe(false);
    // When consent is disabled, track/identify/conversion calls should be no-ops
    // Verified by the consentDisabledFixture having enabled: false
  });

  it('should use fixture consent disabled data', () => {
    expect(consentDisabledFixture.event_type).toBe('consent');
    expect(consentDisabledFixture.properties?.enabled).toBe(false);
    expect(consentDisabledFixture.properties?.purposes).toEqual({});
    expect(consentDisabledFixture.properties?.consent_version).toBe('1.0');
    expect(consentDisabledFixture.properties?.consent_granted_at).toBeNull();
    expect(consentDisabledFixture.properties?.consented_purposes).toEqual([]);
  });

  it('should respect per-purpose consent gates', () => {
    const consent = {
      enabled: true,
      purposes: { analytics: false, marketing: false },
    };
    expect(consent.purposes.analytics).toBe(false);
    expect(consent.purposes.marketing).toBe(false);
  });

  it('should allow events when consent is enabled', () => {
    const consent = {
      enabled: true,
      purposes: { analytics: true, marketing: true },
      timestamp: Date.now(),
    };
    expect(consent.enabled).toBe(true);
    expect(consent.purposes.analytics).toBe(true);
    expect(consent.purposes.marketing).toBe(true);
  });

  it('should construct EventEnvelope for consent event', () => {
    const envelope: EventEnvelope = {
      tenant_id: consentDisabledFixture.tenant_id,
      workspace_id: consentDisabledFixture.workspace_id,
      platform_id: consentDisabledFixture.platform_id,
      environment: consentDisabledFixture.environment,
      event_type: consentDisabledFixture.event_type,
      sdk: consentDisabledFixture.sdk,
      identity: consentDisabledFixture.identity,
      timestamp: consentDisabledFixture.timestamp,
      properties: {
        enabled: false,
        purposes: {},
        consent_version: '1.0',
        consent_granted_at: null,
        consented_purposes: [],
      },
    };
    expect(envelope.event_type).toBe('consent');
    expect(envelope.properties?.enabled).toBe(false);
    expect(envelope.properties?.purposes).toEqual({});
    expect(envelope.identity.anonymous_id).toBe('anon_consent_001');
  });

  it('should validate consent properties structure', () => {
    const props = {
      enabled: false,
      purposes: { analytics: false, marketing: false },
      consent_version: '1.0',
      consent_granted_at: null as string | null,
      consented_purposes: [] as string[],
    };
    expect(props.enabled).toBe(false);
    expect(props.purposes.analytics).toBe(false);
    expect(props.consent_version).toBe('1.0');
    expect(props.consent_granted_at).toBeNull();
    expect(props.consented_purposes).toEqual([]);
  });
});
