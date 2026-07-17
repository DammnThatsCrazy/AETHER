import { describe, it, expect } from 'vitest';
import type { ExplorationContextV1, ExplorationResultEnvelope } from '@aether/shared/exploration-contract';
import { createExplorationStore, explorationActions } from './store';

function ctx(): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: 't1', surface: 'graph' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  };
}

describe('exploration store', () => {
  it('adds a registry-valid filter to the population AND group', () => {
    const store = createExplorationStore(ctx());
    explorationActions(store).addFilter({ field: 'risk.score', op: 'gte', value: 0.8 });
    expect(store.getState().context.population).toEqual({
      logic: 'AND',
      expressions: [{ field: 'risk.score', op: 'gte', value: 0.8 }],
    });
  });

  it('rejects filters whose field or operator is not registered', () => {
    const store = createExplorationStore(ctx());
    const actions = explorationActions(store);
    actions.addFilter({ field: 'user.email', op: 'eq', value: 'x@y.z' }); // unknown field
    actions.addFilter({ field: 'risk.score', op: 'contains', value: 1 }); // op not registered
    expect(store.getState().context.population).toBeFalsy();
  });

  it('removes a filter and empties population to null when the last is removed', () => {
    const store = createExplorationStore(ctx());
    const actions = explorationActions(store);
    actions.addFilter({ field: 'risk.score', op: 'gte', value: 0.8 });
    actions.addFilter({ field: 'entity.type', op: 'in', value: ['human'] });
    actions.removeFilterAt(0);
    expect(store.getState().context.population).toEqual({
      logic: 'AND',
      expressions: [{ field: 'entity.type', op: 'in', value: ['human'] }],
    });
    actions.removeFilterAt(0);
    expect(store.getState().context.population).toBeNull();
  });

  it('setResult adopts the server-normalised context and marks ready', () => {
    const store = createExplorationStore(ctx());
    const normalized: ExplorationContextV1 = { ...ctx(), dimensions: ['events'] };
    const envelope: ExplorationResultEnvelope<unknown> = {
      contract_version: '1',
      query_id: 'q1',
      normalized_context: normalized,
      data: null,
      completeness: { complete: true, sampled: false, truncated: false },
      truth: { overall_state: 'ready', dimensions: [] },
      applicability: { entries: [] },
      execution: { duration_ms: 1, cache_status: 'miss', adapters: [] },
      warnings: [],
    };
    explorationActions(store).setResult(envelope);
    expect(store.getState().status).toBe('ready');
    expect(store.getState().context.dimensions).toEqual(['events']);
  });

  it('setNotEnabled renders an honest not-enabled state (no stale result)', () => {
    const store = createExplorationStore(ctx());
    const actions = explorationActions(store);
    actions.setLoading();
    actions.setNotEnabled();
    expect(store.getState().status).toBe('not_enabled');
    expect(store.getState().result).toBeNull();
  });
});
