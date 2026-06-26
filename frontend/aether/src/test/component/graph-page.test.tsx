import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { RelationshipPath } from '@aether/shared/operational-intelligence';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    me: {
      profile: vi.fn().mockResolvedValue({ tenant_id: 't1' }),
    },
    graphIntelligence: {
      paths: vi.fn().mockResolvedValue({
        data: {
          paths: [{
            path_id: 'deadbeef12345678',
            tenant_id: 't1',
            source_id: 'node-X',
            target_id: 'node-Y',
            ordered_node_ids: ['node-X', 'node-Y'],
            ordered_edge_ids: ['node-X:node-Y:CONNECTS'],
            nodes: [
              { id: 'node-X', kind: 'human', label: 'Xander', hop: 0 },
              { id: 'node-Y', kind: 'agent', label: 'Ybot', hop: 1 },
            ],
            edges: [
              { id: 'e1', type: 'CONNECTS', from: 'node-X', to: 'node-Y', layer: 'H2A', hop: 0, confidence: 0.85 },
            ],
            hop_count: 1,
            path_confidence: 0.85,
            evidence_coverage: 0.75,
            classification: 'observed',
            layer_sequence: ['H2A'],
            score_breakdown: { geometric_mean_confidence: 0.85, min_edge_confidence: 0.85, hop_penalty: 0.85, causality_penalty: 0.0, overall: 0.72, scoring_version: '1', components: {} },
            computed_at: new Date('2026-01-01T00:00:00Z').toISOString(),
          } as RelationshipPath],
          explanations: [],
        },
      }),
      explain: vi.fn().mockResolvedValue({ data: null }),
    },
    investigations: {
      create: vi.fn().mockResolvedValue({ data: { id: 'case-1' } }),
    },
  },
}));

vi.mock('@aether-app/features/graph/use-graph-data', () => ({
  useGraphData: () => ({
    nodes: [
      { id: 'node-X', kind: 'human', label: 'Xander', trustScore: 0.9, riskScore: 0.1, metadata: {} },
      { id: 'node-Y', kind: 'agent', label: 'Ybot', trustScore: 0.7, riskScore: 0.2, metadata: {} },
    ],
    edges: [{ id: 'e1', source: 'node-X', target: 'node-Y', relationType: 'CONNECTS', interactionClass: 'H2A', weight: 0.85, metadata: {} }],
    clusters: [],
    isLoading: false,
    error: null,
    activeLayer: 'all',
    setActiveLayer: vi.fn(),
    overlay: 'none',
    setOverlay: vi.fn(),
    getNeighbors: vi.fn().mockReturnValue([]),
  }),
}));

vi.mock('@aether-app/components/graph/graph-canvas', () => ({
  GraphCanvas: ({ onSelectNode }: { onSelectNode: (n: unknown) => void }) => (
    <div data-testid="graph-canvas">
      <button onClick={() => onSelectNode({ id: 'node-X', kind: 'human', label: 'Xander', trustScore: 0.9, riskScore: 0.1, metadata: {} })}>
        Select node-X
      </button>
      <button onClick={() => onSelectNode({ id: 'node-Y', kind: 'agent', label: 'Ybot', trustScore: 0.7, riskScore: 0.2, metadata: {} })}>
        Select node-Y
      </button>
    </div>
  ),
}));

import { GraphPage } from '@aether-app/pages/graph/graph-page';

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <GraphPage />
    </MemoryRouter>,
  );
}

describe('GraphPage — path API integration', () => {
  it('renders graph canvas and page title', () => {
    renderWithRouter();
    expect(screen.getByText('Entity Graph')).toBeInTheDocument();
    expect(screen.getByTestId('graph-canvas')).toBeInTheDocument();
  });

  it('calls paths API (not local BFS) when two nodes selected in path mode', async () => {
    const { api } = await import('@aether-app/lib/api/endpoints');
    renderWithRouter();
    fireEvent.click(screen.getByText('Path finder'));
    fireEvent.click(screen.getByText('Select node-X'));
    fireEvent.click(screen.getByText('Select node-Y'));

    await waitFor(() => {
      expect(api.graphIntelligence.paths).toHaveBeenCalledWith(
        expect.objectContaining({
          source_id: 'node-X',
          target_id: 'node-Y',
        }),
      );
    });
  });

  it('shows PathInspector when a path is found', async () => {
    renderWithRouter();
    fireEvent.click(screen.getByText('Path finder'));
    fireEvent.click(screen.getByText('Select node-X'));
    fireEvent.click(screen.getByText('Select node-Y'));

    await waitFor(() => {
      expect(screen.getByText(/deadbeef/)).toBeInTheDocument();
    });
  });

  it('shows no-path error message when API returns empty paths', async () => {
    const { api } = await import('@aether-app/lib/api/endpoints');
    vi.mocked(api.graphIntelligence.paths).mockResolvedValueOnce({ data: { paths: [], explanations: [] } });
    renderWithRouter();
    fireEvent.click(screen.getByText('Path finder'));
    fireEvent.click(screen.getByText('Select node-X'));
    fireEvent.click(screen.getByText('Select node-Y'));

    await waitFor(() => {
      expect(screen.getByText('No path found between the selected nodes.')).toBeInTheDocument();
    });
  });

  it('shows traversal mode buttons in path mode', () => {
    renderWithRouter();
    fireEvent.click(screen.getByText('Path finder'));
    expect(screen.getByRole('button', { name: 'Shortest' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Strongest' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'K-Shortest' })).toBeInTheDocument();
  });
});
