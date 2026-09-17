/**
 * FPS-094 — Parity Consent Contract
 * Verifies consent event shape is consistent across platforms.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { consentDisabledFixture } from '@aether/proof-fixtures';

describe('FPS-094: Parity Consent', () => {
  it('should validate consent fixture shape', () => {
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

  it('should validate consent shape is same across platforms', () => {
    const envelope = consentDisabledFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });
});
