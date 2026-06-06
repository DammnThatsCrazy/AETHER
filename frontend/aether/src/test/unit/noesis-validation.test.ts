import { describe, expect, it } from 'vitest';
import { noesisResponsePayloadSchema } from '@aether-app/features/noesis/use-noesis-query';

function makeValidResponse(overrides: Record<string, unknown> = {}) {
  return {
    answer: 'Found 3 alerts.',
    mode: 'deterministic',
    intent: 'alert_lookup',
    confidence: 0.95,
    entities: [],
    results: [{ id: 'alert-1', status: 'open' }],
    graph: { nodes: [], edges: [], highlights: [] },
    actions: [{ type: 'refine_query', prompt: 'Narrow by tenant' }],
    warnings: [],
    ...overrides,
  };
}

describe('noesisResponsePayloadSchema', () => {
  it('parses a valid response', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse());
    expect(result.success).toBe(true);
  });

  it('parses a fallback response', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse({ mode: 'fallback', confidence: 0.3 }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.mode).toBe('fallback');
    }
  });

  it('parses a response with graph context', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse({
      graph: {
        nodes: [{ id: 'n1', label: 'User' }],
        edges: [{ source: 'n1', target: 'n2' }],
        highlights: ['n1'],
      },
    }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.graph.nodes).toHaveLength(1);
      expect(result.data.graph.edges).toHaveLength(1);
      expect(result.data.graph.highlights).toEqual(['n1']);
    }
  });

  it('parses a response with warnings', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse({
      warnings: ['Rate limit approaching', 'Partial results'],
    }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.warnings).toHaveLength(2);
    }
  });

  it('parses a response with error', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse({
      error: { code: 'TIMEOUT', message: 'Query timed out' },
    }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.error?.code).toBe('TIMEOUT');
    }
  });

  it('parses a response with query_debug', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse({
      query_debug: { sql: 'SELECT * FROM users', duration_ms: 42 },
    }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.query_debug).toEqual({ sql: 'SELECT * FROM users', duration_ms: 42 });
    }
  });

  it('rejects a malformed response missing answer', () => {
    const { answer: _, ...noAnswer } = makeValidResponse();
    const result = noesisResponsePayloadSchema.safeParse(noAnswer);
    expect(result.success).toBe(false);
  });

  it('rejects a malformed response with invalid mode', () => {
    const result = noesisResponsePayloadSchema.safeParse(makeValidResponse({ mode: 'invalid_mode' }));
    expect(result.success).toBe(false);
  });

  it('parses a response with empty results using defaults', () => {
    const result = noesisResponsePayloadSchema.safeParse({
      answer: 'No results.',
      mode: 'deterministic',
      intent: 'search',
      confidence: 0.8,
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.entities).toEqual([]);
      expect(result.data.results).toEqual([]);
      expect(result.data.actions).toEqual([]);
      expect(result.data.warnings).toEqual([]);
      expect(result.data.graph).toEqual({ nodes: [], edges: [], highlights: [] });
    }
  });
});
