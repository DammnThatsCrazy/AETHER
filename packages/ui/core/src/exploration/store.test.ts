import { describe, it, expect } from 'vitest';
import type { ExplorationContextV1, ExplorationResultEnvelope } from '@aether/shared/exploration-contract';
import type { ExplorationTrailEntry, GraphObjectRef, GraphScope } from '@aether/shared/graph-context-contract';
import { createExplorationStore, createGraphExplorationStore, explorationActions, graphExplorationActions } from './store';

function ctx(): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: 't1', surface: 'graph' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  };
}

const scope: GraphScope = { tenant_id: 't1', workspace_id: 'w1', environment_id: 'staging' };
const object = (id: string, activeScope = scope): GraphObjectRef => ({ ...activeScope, kind: 'entity', id });
const trail = (id: string, activeScope = scope): ExplorationTrailEntry => ({ object: object(id, activeScope), action: 'open', occurred_at: '2026-01-01T00:00:00Z' });

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

  it('keeps graph context, selection, and history coherent through shared actions', () => {
    const store = createGraphExplorationStore(ctx(), scope);
    const actions = graphExplorationActions(store);
    actions.selectObject(object('entity-1'));
    actions.appendHistory(trail('entity-1'));
    actions.setPopulation({ logic: 'AND', expressions: [{ field: 'risk.score', op: 'gte', value: 0.8 }] });

    expect(store.getState().graphContext.selection.selected).toEqual([object('entity-1')]);
    expect(store.getState().context.selection?.selected).toEqual([{ kind: 'entity', id: 'entity-1' }]);
    expect(store.getState().graphContext.exploration_trail).toEqual([trail('entity-1')]);
    expect(store.getState().history.entries).toEqual([trail('entity-1')]);
    expect(store.getState().graphContext.population?.expressions).toHaveLength(1);
  });

  it('adopts server-normalized context in both exploration and graph views', () => {
    const store = createGraphExplorationStore(ctx(), scope);
    const normalized: ExplorationContextV1 = { ...ctx(), dimensions: ['events'] };
    const envelope: ExplorationResultEnvelope<unknown> = {
      contract_version: '1', query_id: 'q-graph', normalized_context: normalized, data: null,
      completeness: { complete: true, sampled: false, truncated: false },
      truth: { overall_state: 'ready', dimensions: [] }, applicability: { entries: [] },
      execution: { duration_ms: 1, cache_status: 'miss', adapters: [] }, warnings: [],
    };
    graphExplorationActions(store).setResult(envelope);
    expect(store.getState().context.dimensions).toEqual(['events']);
    expect(store.getState().graphContext.dimensions).toEqual(['events']);
    expect(store.getState().status).toBe('ready');
  });

  it('clears all scoped graph artifacts on a same-tenant workspace switch', () => {
    const store = createGraphExplorationStore({ ...ctx(), anchors: [{ kind: 'entity', id: 'entity-1' }] }, scope);
    const actions = graphExplorationActions(store);
    actions.selectObject(object('entity-1'));
    actions.appendHistory(trail('entity-1'));
    actions.setLoading();
    const nextScope: GraphScope = { ...scope, workspace_id: 'w2' };
    actions.setScopedContext({ ...ctx(), anchors: [{ kind: 'entity', id: 'entity-1' }] }, nextScope);

    expect(store.getState().graphContext.scope.workspace_id).toBe('w2');
    expect(store.getState().graphContext.anchors).toEqual([]);
    expect(store.getState().graphContext.selection.selected).toEqual([]);
    expect(store.getState().graphContext.exploration_trail).toEqual([]);
    expect(store.getState().history.entries).toEqual([]);
    expect(store.getState().result).toBeNull();
    expect(store.getState().status).toBe('idle');
  });
});
