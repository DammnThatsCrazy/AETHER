import { describe, expect, it } from 'vitest';
import type { BaseEvent, BatchPayload, EventContext, LibraryContext } from './events';
import { SDK_INGESTION_PATH } from './sdk-version';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeLibraryContext(): LibraryContext {
  return { name: '@aether/web', version: '8.9.0' };
}

function makeEventContext(): EventContext {
  return { library: makeLibraryContext() };
}

function makeBaseEvent(overrides?: Partial<BaseEvent>): BaseEvent {
  return {
    id: 'evt-test-1',
    type: 'track',
    timestamp: new Date().toISOString(),
    sessionId: 'session-abc',
    anonymousId: 'anon-xyz',
    context: makeEventContext(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ingestion-envelope', () => {
  // ---------------------------------------------------------------------------
  // BaseEvent construction
  // ---------------------------------------------------------------------------

  it('a valid BaseEvent can be constructed with all required fields', () => {
    const event = makeBaseEvent();
    expect(event.id).toBe('evt-test-1');
    expect(event.type).toBe('track');
    expect(event.timestamp).toBeTruthy();
    expect(event.sessionId).toBe('session-abc');
    expect(event.anonymousId).toBe('anon-xyz');
    expect(event.context.library.name).toBe('@aether/web');
    expect(event.context.library.version).toBe('8.9.0');
  });

  it('BaseEvent accepts optional userId', () => {
    const event = makeBaseEvent({ userId: 'user-123' });
    expect(event.userId).toBe('user-123');
  });

  it('BaseEvent accepts optional properties', () => {
    const event = makeBaseEvent({ properties: { foo: 'bar', count: 42 } });
    expect(event.properties?.['foo']).toBe('bar');
    expect(event.properties?.['count']).toBe(42);
  });

  it('BaseEvent type field accepts all major canonical types', () => {
    const typesToTest = ['track', 'page', 'screen', 'identify', 'consent', 'error'] as const;
    for (const t of typesToTest) {
      const event = makeBaseEvent({ type: t });
      expect(event.type).toBe(t);
    }
  });

  // ---------------------------------------------------------------------------
  // Batch envelope shape
  // ---------------------------------------------------------------------------

  it('the batch envelope shape { batch: BaseEvent[], sentAt: string } is type-valid', () => {
    const event1 = makeBaseEvent({ id: 'evt-1' });
    const event2 = makeBaseEvent({ id: 'evt-2', type: 'page' });

    const envelope: BatchPayload = {
      batch: [event1, event2],
      sentAt: new Date().toISOString(),
    };

    expect(envelope.batch).toHaveLength(2);
    expect(envelope.batch[0].id).toBe('evt-1');
    expect(envelope.batch[1].type).toBe('page');
    expect(envelope.sentAt).toBeTruthy();
    // sentAt must be a string (ISO date)
    expect(typeof envelope.sentAt).toBe('string');
  });

  it('batch envelope accepts optional top-level context', () => {
    const envelope: BatchPayload = {
      batch: [makeBaseEvent()],
      sentAt: new Date().toISOString(),
      context: { library: makeLibraryContext() },
    };
    expect(envelope.context?.library.name).toBe('@aether/web');
  });

  it('batch envelope can contain an empty batch array', () => {
    const envelope: BatchPayload = {
      batch: [],
      sentAt: new Date().toISOString(),
    };
    expect(envelope.batch).toHaveLength(0);
  });

  // ---------------------------------------------------------------------------
  // SDK ingestion path
  // ---------------------------------------------------------------------------

  it("SDK_INGESTION_PATH is '/v1/batch'", () => {
    expect(SDK_INGESTION_PATH).toBe('/v1/batch');
  });

  it('SDK_INGESTION_PATH starts with a forward slash', () => {
    expect(SDK_INGESTION_PATH.startsWith('/')).toBe(true);
  });
});
