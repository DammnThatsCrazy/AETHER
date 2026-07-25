import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@aether-app/lib/api/rest/client', () => ({ restClient: { get } }));

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
  beforeEach(() => {
    get.mockImplementation((path: string) => {
      if (path === '/v1/noesis/capabilities') {
        return Promise.resolve({ capabilities: [{ intent: 'segments', example_prompts: ['Backend prompt'] }] });
      }
      if (path === '/v1/noesis/conversations') return Promise.resolve({ data: [] });
      return Promise.resolve({ messages: [] });
    });
  });

  it('renders with correct title', async () => {
    render(<NoesisPage />);
    expect(screen.getByText('Ask Aether')).toBeInTheDocument();
    await screen.findByText('Backend prompt');
  });

  it('shows only backend-provided suggested prompts', async () => {
    render(<NoesisPage />);
    expect(await screen.findByText('Backend prompt')).toBeInTheDocument();
    expect(screen.queryByText('Show my highest-value user segments.')).not.toBeInTheDocument();
  });

  it('submits a prompt', async () => {
    render(<NoesisPage />);
    const textarea = screen.getByPlaceholderText(/Ask about your graph/);
    await userEvent.type(textarea, 'Show alerts');
    const submitButton = screen.getByRole('button', { name: 'Ask Noesis' });
    await userEvent.click(submitButton);
    expect(screen.getByText('Show alerts')).toBeInTheDocument();
  });

  it('discloses unavailable metadata instead of substituting fixture prompts', async () => {
    get.mockRejectedValue(new Error('noesis offline'));
    render(<NoesisPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Noesis metadata unavailable');
    expect(screen.queryByText('Show reward opportunities.')).not.toBeInTheDocument();
  });
});
