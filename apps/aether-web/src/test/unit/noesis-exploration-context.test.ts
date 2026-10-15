import { describe, expect, it } from 'vitest';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import {
  buildNoesisRequestContext,
  exactContextHandoffLimitations,
  NOESIS_EXPLORATION_CONTEXT_FILTER,
} from '@aether-app/features/noesis/exploration-context';

const context: ExplorationContextV1 = {
  version: '1',
  scope: { tenant_id: 'tenant-a', surface: '/noesis' },
  population: {
    logic: 'AND',
    expressions: [{ field: 'entity.id', op: 'in', value: ['user-1', 'user-2'] }],
  },
  temporal: {
    mode: 'window',
    field: 'occurred_at',
    range: {
      kind: 'instant',
      start: '2026-07-01T00:00:00Z',
      endExclusive: '2026-07-02T00:00:00Z',
    },
    timezone: 'America/New_York',
    authority: 'viewer',
  },
  selection: {
    selected: [{ kind: 'human', id: 'user-1' }],
  },
  truth: {
    include_evidence: true,
    include_provenance: true,
    minimum_confidence: 0.8,
  },
};

describe('Noesis exploration context', () => {
  it('carries the canonical context exactly without promoting tenant authority', () => {
    const request = buildNoesisRequestContext(context, '/noesis');

    expect(request).not.toHaveProperty('tenant_id');
    expect(request.current_page).toBe('/noesis');
    expect(request.selected_entity_id).toBe('user-1');
    expect(request.selected_entity_type).toBe('human');
    expect(request.filters[NOESIS_EXPLORATION_CONTEXT_FILTER]).toEqual(context);
  });

  it('does not collapse multiple selected subjects into one implicit subject', () => {
    const request = buildNoesisRequestContext({
      ...context,
      selection: {
        selected: [
          { kind: 'human', id: 'user-1' },
          { kind: 'human', id: 'user-2' },
        ],
      },
    }, '/noesis');

    expect(request.selected_entity_id).toBeUndefined();
    expect(request.filters[NOESIS_EXPLORATION_CONTEXT_FILTER]).toEqual({
      ...context,
      selection: {
        selected: [
          { kind: 'human', id: 'user-1' },
          { kind: 'human', id: 'user-2' },
        ],
      },
    });
  });

  it('refuses to imply all-matching, investigation, or export support', () => {
    const emptySelection = exactContextHandoffLimitations({
      ...context,
      selection: { selected: [] },
    });
    expect(emptySelection.investigation).toContain('backend selection token');

    const selected = exactContextHandoffLimitations(context);
    expect(selected.investigation).toContain('Unavailable');
    expect(selected.export).toContain('cannot accept');
  });
});
