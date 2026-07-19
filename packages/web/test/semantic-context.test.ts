import { describe, expect, it } from 'vitest';

import { SemanticContextCollector } from '../src/context/semantic-context';

// ---------------------------------------------------------------------------
// The semantic collector must NOT mint its own session/event ids — it reuses
// the canonical ids passed by the caller (SessionManager + top-level event id),
// so every event carries a single agreeing session id and event id.
// ---------------------------------------------------------------------------
describe('SemanticContextCollector', () => {
  it('uses the canonical sessionId and eventId passed in (no self-minting)', () => {
    const collector = new SemanticContextCollector('8.12.0');
    const ctx = collector.collect('sess_canonical', 'evt_canonical');
    expect(ctx.sessionId).toBe('sess_canonical');
    expect(ctx.eventId).toBe('evt_canonical');
  });

  it('reflects a NEW session id on the next event (no stale cached id)', () => {
    const collector = new SemanticContextCollector('8.12.0');
    const first = collector.collect('sess_a', 'evt_1');
    const second = collector.collect('sess_b', 'evt_2');
    expect(first.sessionId).toBe('sess_a');
    expect(second.sessionId).toBe('sess_b');
    expect(first.eventId).not.toBe(second.eventId);
  });

  it('stamps sdk version and platform', () => {
    const ctx = new SemanticContextCollector('8.12.0').collect('s', 'e');
    expect(ctx.sdkVersion).toBe('8.12.0');
    expect(ctx.platform).toBe('web');
  });
});
