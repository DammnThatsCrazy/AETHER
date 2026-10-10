import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import type { RelationshipPath, PathExplanation } from '@aether/shared/operational-intelligence';
import { PathInspector } from '@kyber/components/graph/path-inspector';

const SCORE_BREAKDOWN = {
  geometric_mean_confidence: 0.9,
  min_edge_confidence: 0.9,
  hop_penalty: 0.85,
  causality_penalty: 0.0,
  overall: 0.77,
  scoring_version: '1',
  components: {},
};

const BASE_PATH: RelationshipPath = {
  path_id: 'deadbeef12345678abcdef00',
  tenant_id: 't1',
  source_id: 'node-A',
  target_id: 'node-B',
  ordered_node_ids: ['node-A', 'node-B'],
  ordered_edge_ids: ['e1'],
  nodes: [
    { id: 'node-A', kind: 'human', label: 'Alice', hop: 0 },
    { id: 'node-B', kind: 'agent', label: 'Bot', hop: 1 },
  ],
  edges: [
    { id: 'e1', type: 'DELEGATES', from: 'node-A', to: 'node-B', layer: 'H2A', hop: 0, confidence: 0.9 },
  ],
  hop_count: 1,
  path_confidence: 0.9,
  evidence_coverage: 0.8,
  classification: 'observed',
  layer_sequence: ['H2A'],
  score_breakdown: SCORE_BREAKDOWN,
  computed_at: '2026-01-01T00:00:00Z',
};

const BASE_EXPLANATION: PathExplanation = {
  path_id: 'deadbeef12345678abcdef00',
  summary: 'Alice delegates to Bot',
  why_connected: 'Alice directly delegates authority to Bot via H2A relationship.',
  hop_narrative: ['Alice → DELEGATES → Bot'],
  supporting_evidence: [{ type: 'event', id: 'ev1' }],
  contradictory_evidence: [],
  score_breakdown: SCORE_BREAKDOWN,
  classification: 'observed',
  causal_language_allowed: true,
  policy_ids: [],
  computed_at: '2026-01-01T00:00:00Z',
};

describe('PathInspector — overview tab', () => {
  it('renders truncated path_id in header', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    expect(screen.getByText('#deadbeef')).toBeInTheDocument();
  });

  it('renders observed classification badge label', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    expect(screen.getByText('Observed')).toBeInTheDocument();
  });

  it('renders correlated classification badge label', () => {
    render(<PathInspector path={{ ...BASE_PATH, classification: 'correlated' }} onClose={vi.fn()} />);
    expect(screen.getByText('Correlated')).toBeInTheDocument();
  });

  it('renders inferred classification badge label', () => {
    render(<PathInspector path={{ ...BASE_PATH, classification: 'inferred' }} onClose={vi.fn()} />);
    expect(screen.getByText('Inferred')).toBeInTheDocument();
  });

  it('renders layer_sequence badges on overview tab', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    expect(screen.getByText('H2A')).toBeInTheDocument();
  });

  it('shows hop count', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();
    render(<PathInspector path={BASE_PATH} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close path inspector' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe('PathInspector — hops tab', () => {
  it('renders node kinds and edge type in hop list', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Hops' }));
    expect(screen.getByText('human')).toBeInTheDocument();
    expect(screen.getByText('DELEGATES')).toBeInTheDocument();
    expect(screen.getByText('agent')).toBeInTheDocument();
  });

  it('shows node labels in hop list', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Hops' }));
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bot')).toBeInTheDocument();
  });
});

describe('PathInspector — evidence tab', () => {
  it('shows "Load explanation" button when no explanation provided', () => {
    const onLoad = vi.fn().mockResolvedValue(undefined);
    render(<PathInspector path={BASE_PATH} onLoadExplanation={onLoad} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByRole('button', { name: 'Load explanation' })).toBeInTheDocument();
  });

  it('calls onLoadExplanation when the button is clicked', async () => {
    const onLoad = vi.fn().mockResolvedValue(undefined);
    render(<PathInspector path={BASE_PATH} onLoadExplanation={onLoad} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    fireEvent.click(screen.getByRole('button', { name: 'Load explanation' }));
    await waitFor(() => expect(onLoad).toHaveBeenCalledOnce());
  });

  it('renders why_connected text when explanation is provided', () => {
    render(<PathInspector path={BASE_PATH} explanation={BASE_EXPLANATION} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText('Alice directly delegates authority to Bot via H2A relationship.')).toBeInTheDocument();
  });

  it('shows causal-language restriction notice when causal_language_allowed is false', () => {
    const noLang = { ...BASE_EXPLANATION, causal_language_allowed: false };
    render(<PathInspector path={{ ...BASE_PATH, classification: 'correlated' }} explanation={noLang} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText(/causal language not permitted/i)).toBeInTheDocument();
  });
});

describe('PathInspector — score tab', () => {
  it('renders overall score progress bar', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Score' }));
    expect(screen.getByRole('progressbar', { name: 'Overall score' })).toBeInTheDocument();
  });

  it('shows scoring version', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Score' }));
    expect(screen.getByText('v1')).toBeInTheDocument();
  });
});

describe('PathInspector — save to investigation', () => {
  it('renders Save to investigation button when callback provided', () => {
    render(<PathInspector path={BASE_PATH} onSaveToInvestigation={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /save path.*to investigation/i })).toBeInTheDocument();
  });

  it('calls onSaveToInvestigation with path_id when clicked', () => {
    const onSave = vi.fn();
    render(<PathInspector path={BASE_PATH} onSaveToInvestigation={onSave} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /save path.*to investigation/i }));
    expect(onSave).toHaveBeenCalledWith('deadbeef12345678abcdef00');
  });

  it('does not render save button when no callback provided', () => {
    render(<PathInspector path={BASE_PATH} onClose={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /save.*investigation/i })).not.toBeInTheDocument();
  });
});
