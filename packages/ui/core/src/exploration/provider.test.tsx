// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { useEffect } from 'react';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import type { GraphScope } from '@aether/shared/graph-context-contract';
import { ExplorationProvider, GraphContextProvider, useExploration, useExplorationContext, useGraphActions, useGraphContext, useGraphHistory, useGraphSelection } from './provider';
import { encodeExplorationContext } from './url-codec';

afterEach(cleanup);

function base(surface = 'graph'): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: 't1', surface },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  };
}

/** Probe that surfaces the live context + toQuery() into the DOM. */
function Probe() {
  const ctx = useExplorationContext();
  const { toQuery } = useExploration();
  return (
    <div>
      <span data-testid="surface">{ctx.scope.surface}</span>
      <span data-testid="pop">{JSON.stringify(ctx.population ?? null)}</span>
      <span data-testid="query">{toQuery()}</span>
    </div>
  );
}

describe('ExplorationProvider URL authority', () => {
  it('decodes the initial query on mount', () => {
    const withFilter: ExplorationContextV1 = {
      ...base(),
      population: { logic: 'AND', expressions: [{ field: 'risk.score', op: 'gte', value: 0.8 }] },
    };
    const { getByTestId } = render(
      <ExplorationProvider tenantId="t1" surface="graph" query={encodeExplorationContext(withFilter)}>
        <Probe />
      </ExplorationProvider>,
    );
    expect(getByTestId('surface').textContent).toBe('graph');
    expect(getByTestId('pop').textContent).toContain('risk.score');
  });

  it('re-decodes when the host changes the query without remounting (back/forward)', () => {
    const withFilter: ExplorationContextV1 = {
      ...base(),
      population: { logic: 'AND', expressions: [{ field: 'risk.score', op: 'gte', value: 0.8 }] },
    };
    const qEmpty = encodeExplorationContext(base());
    const qFilter = encodeExplorationContext(withFilter);

    const { getByTestId, rerender } = render(
      <ExplorationProvider tenantId="t1" surface="graph" query={qEmpty}>
        <Probe />
      </ExplorationProvider>,
    );
    expect(getByTestId('pop').textContent).toBe('null');

    // Same provider instance, new authoritative URL — the store must resync.
    rerender(
      <ExplorationProvider tenantId="t1" surface="graph" query={qFilter}>
        <Probe />
      </ExplorationProvider>,
    );
    expect(getByTestId('pop').textContent).toContain('risk.score');
    expect(getByTestId('query').textContent).toBe(qFilter);
  });

  it('resyncs the surface on cross-surface nav under one layout', () => {
    const { getByTestId, rerender } = render(
      <ExplorationProvider tenantId="t1" surface="graph">
        <Probe />
      </ExplorationProvider>,
    );
    expect(getByTestId('surface').textContent).toBe('graph');

    rerender(
      <ExplorationProvider tenantId="t1" surface="geo">
        <Probe />
      </ExplorationProvider>,
    );
    expect(getByTestId('surface').textContent).toBe('geo');
  });

  it('does not clobber state when the query round-trips unchanged', () => {
    const withFilter: ExplorationContextV1 = {
      ...base(),
      population: { logic: 'AND', expressions: [{ field: 'risk.score', op: 'gte', value: 0.8 }] },
    };
    const q = encodeExplorationContext(withFilter);
    const { getByTestId, rerender } = render(
      <ExplorationProvider tenantId="t1" surface="graph" query={q}>
        <Probe />
      </ExplorationProvider>,
    );
    // Re-render with the identical query (a self-initiated URL push) — still there.
    rerender(
      <ExplorationProvider tenantId="t1" surface="graph" query={q}>
        <Probe />
      </ExplorationProvider>,
    );
    expect(getByTestId('pop').textContent).toContain('risk.score');
  });
});

describe('GraphContextProvider host scope authority', () => {
  const scope: GraphScope = { tenant_id: 't1', workspace_id: 'w1', environment_id: 'staging' };

  function GraphProbe() {
    const context = useGraphContext();
    const selection = useGraphSelection();
    const history = useGraphHistory();
    const actions = useGraphActions();
    useEffect(() => {
      actions.appendHistory({
        object: { tenant_id: 't1', environment_id: 'staging', kind: 'entity', id: 'root' },
        action: 'open', occurred_at: '2026-01-01T00:00:00Z',
      });
    }, [actions]);
    return (
      <div>
        <span data-testid="graph-scope">{context.scope.tenant_id}/{context.scope.workspace_id}/{context.scope.environment_id}</span>
        <span data-testid="graph-surface">{context.scope.surface}</span>
        <span data-testid="graph-anchors">{context.anchors.map((anchor) => anchor.id).join(',')}</span>
        <span data-testid="graph-selection">{selection.selected.length}</span>
        <span data-testid="graph-history">{history.entries.length}</span>
      </div>
    );
  }

  it('requires a complete host GraphScope', () => {
    expect(() => render(
      <GraphContextProvider scope={{ tenant_id: 't1', workspace_id: '', environment_id: 'staging' }}>
        <GraphProbe />
      </GraphContextProvider>,
    )).toThrow('workspace_id');
  });

  it('clears anchors, selection, and trail on a same-tenant workspace switch', () => {
    const shareable = encodeExplorationContext({
      ...base(), anchors: [{ kind: 'entity', id: 'root' }],
      selection: { selected: [{ kind: 'entity', id: 'root' }] },
    });
    const { getByTestId, rerender } = render(
      <GraphContextProvider scope={scope} query={shareable}>
        <GraphProbe />
      </GraphContextProvider>,
    );
    expect(getByTestId('graph-scope').textContent).toBe('t1/w1/staging');
    expect(getByTestId('graph-anchors').textContent).toBe('root');
    expect(getByTestId('graph-selection').textContent).toBe('1');
    expect(getByTestId('graph-history').textContent).toBe('1');

    rerender(
      <GraphContextProvider scope={{ ...scope, workspace_id: 'w2' }} query={shareable}>
        <GraphProbe />
      </GraphContextProvider>,
    );
    expect(getByTestId('graph-scope').textContent).toBe('t1/w2/staging');
    expect(getByTestId('graph-anchors').textContent).toBe('');
    expect(getByTestId('graph-selection').textContent).toBe('0');
    expect(getByTestId('graph-history').textContent).toBe('0');
  });

  it('preserves safe graph state across routes inside the same authority scope', () => {
    const graphQuery = encodeExplorationContext({
      ...base('graph'),
      anchors: [{ kind: 'entity', id: 'root' }],
      selection: { selected: [{ kind: 'entity', id: 'root' }] },
    });
    const profileQuery = encodeExplorationContext({
      ...base('profile360'),
      anchors: [{ kind: 'entity', id: 'root' }],
      selection: { selected: [{ kind: 'entity', id: 'root' }] },
    });
    const { getByTestId, rerender } = render(
      <GraphContextProvider scope={scope} surface="graph" query={graphQuery}>
        <GraphProbe />
      </GraphContextProvider>,
    );
    expect(getByTestId('graph-history').textContent).toBe('1');

    rerender(
      <GraphContextProvider scope={scope} surface="profile360" query={profileQuery}>
        <GraphProbe />
      </GraphContextProvider>,
    );

    expect(getByTestId('graph-surface').textContent).toBe('profile360');
    expect(getByTestId('graph-anchors').textContent).toBe('root');
    expect(getByTestId('graph-selection').textContent).toBe('1');
    expect(getByTestId('graph-history').textContent).toBe('1');
  });
});
