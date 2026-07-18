// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import { ExplorationProvider, useExploration, useExplorationContext } from './provider';
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
