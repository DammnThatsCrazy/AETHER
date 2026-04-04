import { describe, it, expect } from 'vitest';
import { severitySchema, entityTypeSchema, healthStatusSchema, liveEventSchema } from '@shiki/lib/schemas';

describe('severitySchema', () => {
  it('accepts valid severities', () => {
    expect(severitySchema.parse('P0')).toBe('P0');
    expect(severitySchema.parse('P1')).toBe('P1');
    expect(severitySchema.parse('P2')).toBe('P2');
    expect(severitySchema.parse('P3')).toBe('P3');
    expect(severitySchema.parse('info')).toBe('info');
  });
  it('rejects invalid severity', () => {
    expect(() => severitySchema.parse('P5')).toThrow();
    expect(() => severitySchema.parse('')).toThrow();
  });
});

describe('entityTypeSchema', () => {
  it('accepts valid entity types', () => {
    const types = ['customer', 'wallet', 'agent', 'protocol', 'contract', 'cluster'];
    for (const t of types) {
      expect(entityTypeSchema.parse(t)).toBe(t);
    }
  });
  it('rejects invalid entity type', () => {
    expect(() => entityTypeSchema.parse('user')).toThrow();
  });
});

describe('healthStatusSchema', () => {
  it('accepts valid health status', () => {
    const result = healthStatusSchema.parse({
      status: 'healthy',
      lastChecked: new Date().toISOString(),
    });
    expect(result.status).toBe('healthy');
  });
  it('rejects missing fields', () => {
    expect(() => healthStatusSchema.parse({ status: 'healthy' })).toThrow();
  });
});

describe('liveEventSchema', () => {
  it('validates a complete live event', () => {
    const event = {
      id: 'evt-001',
      type: 'analytics',
      timestamp: new Date().toISOString(),
      severity: 'P2',
      title: 'Test event',
      description: 'A test event',
      source: 'test',
      pinned: false,
      metadata: {},
    };
    const result = liveEventSchema.parse(event);
    expect(result.id).toBe('evt-001');
  });
  it('rejects invalid event type', () => {
    expect(() => liveEventSchema.parse({
      id: 'evt-002',
      type: 'invalid-type',
      timestamp: new Date().toISOString(),
      severity: 'P0',
      title: 'Bad',
      description: 'Bad',
      source: 'test',
      pinned: false,
      metadata: {},
    })).toThrow();
  });
});
