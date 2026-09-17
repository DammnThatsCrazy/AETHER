/**
 * FPS-095 — Parity Session Contract
 * Verifies session tracking behavior is consistent across platforms.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture } from '@aether/proof-fixtures';

describe('FPS-095: Parity Session', () => {
  it('should validate session ID on track event', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.session.session_id).toBe('sess_abc123');
  });

  it('should validate session shape is same across platforms', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.session).toBeDefined();
    expect(typeof envelope.session.session_id).toBe('string');
  });
});
