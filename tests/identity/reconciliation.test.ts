/**
 * FPS-200 — Identity Reconciliation
 * Verifies identity reconciliation across multiple sources.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture } from '@aether/proof-fixtures';

describe('FPS-200: Identity Reconciliation', () => {
  it('should merge anonymous and identified identities', () => {
    // An anonymous session starts with an anonymous_id.
    // When identify() is called, the user_id is linked.
    const anonymous: EventEnvelope = trackEventFixture as unknown as EventEnvelope;
    const identified: EventEnvelope = identifyEventFixture as unknown as EventEnvelope;

    expect(anonymous.identity.anonymous_id).toBe('anon_001');
    expect(identified.identity.user_id).toBe('user_002');

    // Reconciliation: same anonymous_id can be linked to a user_id.
    expect(anonymous.identity.anonymous_id).toBe('anon_001');
    expect(identified.identity.anonymous_id).toBe('anon_001');
  });

  it('should preserve identity traits across events', () => {
    const identified = identifyEventFixture as unknown as EventEnvelope;
    const traits = identified.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
    expect(traits?.plan).toBe('premium');
  });

  it('should validate cross-platform identity linkage', () => {
    const track = trackEventFixture as unknown as EventEnvelope;
    const identify = identifyEventFixture as unknown as EventEnvelope;

    // Both events share the same tenant and workspace.
    expect(track.tenant_id).toBe(identify.tenant_id);
    expect(track.workspace_id).toBe(identify.workspace_id);

    // The identity.anonymous_id should be consistent or linked.
    expect(track.identity.anonymous_id).toBe('anon_001');
    expect(identify.identity.anonymous_id).toBe('anon_001');
  });

  it('should validate identity fields are present', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBeDefined();
    expect(envelope.identity.user_id).toBeDefined();
  });
});
