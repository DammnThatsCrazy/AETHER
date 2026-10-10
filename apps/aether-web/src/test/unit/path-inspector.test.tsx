import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PathInspector } from '@aether-app/components/graph/path-inspector';
import type { RelationshipPath, PathExplanation } from '@aether/shared/operational-intelligence';

const MOCK_PATH: RelationshipPath = {
  path_id: 'abcdef1234567890',
  tenant_id: 't1',
  source_id: 'node-A',
  target_id: 'node-B',
  ordered_node_ids: ['node-A', 'node-B'],
  ordered_edge_ids: ['node-A:node-B:CONNECTS'],
  nodes: [
    { id: 'node-A', kind: 'human', label: 'Alice', hop: 0 },
    { id: 'node-B', kind: 'agent', label: 'BotX', hop: 1 },
  ],
  edges: [
    { id: 'e1', type: 'CONNECTS', from: 'node-A', to: 'node-B', layer: 'H2A', hop: 0, confidence: 0.9 },
  ],
  hop_count: 1,
  path_confidence: 0.9,
  evidence_coverage: 0.8,
  classification: 'observed',
  layer_sequence: ['H2A'],
  score_breakdown: {
    geometric_mean_confidence: 0.9,
    min_edge_confidence: 0.9,
    hop_penalty: 0.85,
    causality_penalty: 0.0,
    overall: 0.77,
    scoring_version: '1',
    components: {},
  },
  computed_at: new Date('2026-01-01T00:00:00Z').toISOString(),
};

const MOCK_EXPLANATION: PathExplanation = {
  path_id: 'abcdef1234567890',
  summary: 'Alice and BotX are connected via H2A layer.',
  why_connected: 'BotX notified Alice of a risk alert.',
  hop_narrative: ['Alice → BotX via CONNECTS (H2A)'],
  supporting_evidence: [{ type: 'event', id: 'ev-1' }],
  contradictory_evidence: [],
  score_breakdown: MOCK_PATH.score_breakdown,
  classification: 'observed',
  causal_language_allowed: true,
  policy_ids: [],
  computed_at: MOCK_PATH.computed_at,
};

describe('PathInspector', () => {
  it('renders the path id in the header', () => {
    render(<PathInspector path={MOCK_PATH} onClose={vi.fn()} />);
    expect(screen.getByText(/abcdef12/)).toBeInTheDocument();
  });

  it('renders all four tabs', () => {
    render(<PathInspector path={MOCK_PATH} onClose={vi.fn()} />);
    expect(screen.getByRole('tab', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Hops' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Score' })).toBeInTheDocument();
  });

  it('shows classification badge with icon and label on Overview tab', () => {
    render(<PathInspector path={MOCK_PATH} onClose={vi.fn()} />);
    // The badge text is visible (icon + label in a span)
    expect(screen.getByText('Observed')).toBeInTheDocument();
  });

  it('shows layer badge on Overview tab', () => {
    render(<PathInspector path={MOCK_PATH} onClose={vi.fn()} />);
    expect(screen.getByText('H2A')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();
    render(<PathInspector path={MOCK_PATH} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('Close path inspector'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('shows Load explanation button when no explanation and handler provided', () => {
    const onLoad = vi.fn().mockResolvedValue(undefined);
    render(<PathInspector path={MOCK_PATH} onLoadExplanation={onLoad} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByRole('button', { name: 'Load explanation' })).toBeInTheDocument();
  });

  it('shows explanation content when explanation is provided', () => {
    render(
      <PathInspector
        path={MOCK_PATH}
        explanation={MOCK_EXPLANATION}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText('BotX notified Alice of a risk alert.')).toBeInTheDocument();
  });

  it('shows Save to investigation button when handler provided', () => {
    const onSave = vi.fn();
    render(
      <PathInspector
        path={MOCK_PATH}
        onSaveToInvestigation={onSave}
        onClose={vi.fn()}
      />,
    );
    const btn = screen.getByLabelText(/Save path abcdef12 to investigation/);
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onSave).toHaveBeenCalledWith('abcdef1234567890');
  });

  it('shows score breakdown on Score tab', () => {
    render(<PathInspector path={MOCK_PATH} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Score' }));
    expect(screen.getByText('Overall score')).toBeInTheDocument();
    expect(screen.getByText('Geometric mean confidence')).toBeInTheDocument();
  });

  it('shows hops on Hops tab', () => {
    render(<PathInspector path={MOCK_PATH} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Hops' }));
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('BotX')).toBeInTheDocument();
  });
});
