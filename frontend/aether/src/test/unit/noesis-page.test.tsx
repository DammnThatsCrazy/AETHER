import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@aether-app/features/noesis', () => ({
  useNoesisQuery: () => ({
    mutate: vi.fn().mockResolvedValue({
      answer: 'Here are your alerts.',
      mode: 'deterministic',
      intent: 'alert_lookup',
      confidence: 0.9,
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

import { NoesisPage } from '@aether-app/pages/noesis/noesis-page';

describe('NoesisPage (Aether)', () => {
  it('renders with correct title', () => {
    render(<NoesisPage />);
    expect(screen.getByText('Ask Aether')).toBeInTheDocument();
  });

  it('shows suggested prompts', () => {
    render(<NoesisPage />);
    expect(screen.getByText('Show my highest-value user segments.')).toBeInTheDocument();
    expect(screen.getByText('Show reward opportunities.')).toBeInTheDocument();
  });

  it('submits a prompt', async () => {
    render(<NoesisPage />);
    const textarea = screen.getByPlaceholderText(/Ask about your graph/);
    await userEvent.type(textarea, 'Show alerts');
    const submitButton = screen.getByRole('button', { name: 'Ask Noesis' });
    await userEvent.click(submitButton);
    expect(screen.getByText('Show alerts')).toBeInTheDocument();
  });
});
