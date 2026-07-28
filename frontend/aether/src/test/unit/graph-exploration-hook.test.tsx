import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ExplorationClient } from '@aether/ui/exploration';
import { ExplorationProvider } from '@aether/ui/exploration';
import { useGraphData } from '@aether-app/features/graph/use-graph-data';

describe('canonical graph exploration hook', () => {
  it('uses provider tenant authority and maps the confirmed graph adapter shape', async () => {
    const queryLatest = vi.fn().mockResolvedValue({
      contract_version: '1',
      query_id: 'query-1',
      normalized_context: {
        version: '1',
        scope: { tenant_id: 'tenant-authority', surface: 'graph' },
        temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
      },
      data: {
        nodes: [
          { id: 'human-1', kind: 'User', label: 'Human one', properties: {} },
          { id: 'agent-1', kind: 'Agent', label: 'Agent one', properties: {} },
        ],
        edges: [
          {
            id: 'edge-1',
            type: 'DELEGATES',
            from: 'human-1',
            to: 'agent-1',
            directed: true,
            properties: {},
          },
        ],
      },
      completeness: { complete: true, sampled: false, truncated: false },
      truth: { overall_state: 'ready', dimensions: [], freshness_watermark: '2026-07-28T00:00:00Z' },
      applicability: { entries: [] },
      execution: { duration_ms: 2, cache_status: 'miss', adapters: ['graph'] },
      warnings: [],
    });
    const client = { queryLatest } as unknown as ExplorationClient;
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ExplorationProvider
        tenantId="tenant-authority"
        surface="graph"
        client={client}
      >
        {children}
      </ExplorationProvider>
    );

    const { result } = renderHook(() => useGraphData(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.nodes.map(node => node.id)).toEqual(['human-1', 'agent-1']);
    expect(result.current.edges).toEqual([
      expect.objectContaining({
        id: 'edge-1',
        source: 'human-1',
        target: 'agent-1',
        interactionClass: 'H2A',
      }),
    ]);
    expect(result.current.truth?.overall_state).toBe('ready');

    const request = queryLatest.mock.calls[0]?.[0];
    expect(request.context.scope).toEqual({
      tenant_id: 'tenant-authority',
      surface: 'graph',
    });
  });
});
