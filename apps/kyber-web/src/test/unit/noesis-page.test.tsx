import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@kyber/features/noesis-command', () => ({
  useNoesisQuery: () => ({
    mutate: vi.fn().mockResolvedValue({
      answer: 'Graph health is nominal.',
      mode: 'deterministic',
      intent: 'health_check',
      confidence: 0.95,
      entities: [],
      results: [],
      graph: { nodes: [], edges: [], highlights: [] },
      actions: [],
      warnings: [],
    }),
    isLoading: false,
    error: null,
  }),
}));

import { NoesisPage } from '@kyber/pages/noesis/noesis-page';

describe('NoesisPage (Kyber)', () => {
  it('renders with correct title', () => {
    render(<NoesisPage />);
    expect(screen.getByText('Noesis Command')).toBeInTheDocument();
  });

  it('shows suggested prompts', () => {
    render(<NoesisPage />);
    expect(screen.getByText('Show tenants with unhealthy SDK telemetry.')).toBeInTheDocument();
    expect(screen.getByText('Show unresolved intelligence alerts.')).toBeInTheDocument();
  });
});
