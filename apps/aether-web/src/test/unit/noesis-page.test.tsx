import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, mutate, saveView } = vi.hoisted(() => ({
  get: vi.fn(),
  mutate: vi.fn(),
  saveView: vi.fn(),
}));
vi.mock('@aether-app/lib/api/rest/client', () => ({ restClient: { get } }));

vi.mock('@aether-app/features/noesis', () => ({
  buildNoesisRequestContext: (context: unknown, currentPage: string) => ({
    current_page: currentPage,
    filters: { exploration_context_v1: context },
  }),
  NoesisContextActions: () => <div>Exact exploration context</div>,
  useNoesisQuery: () => ({
    mutate,
    isLoading: false,
    error: null,
  }),
}));

vi.mock('@aether/ui/exploration', () => ({
  useExplorationContext: () => ({
    version: '1',
    scope: { tenant_id: 'tenant-a', surface: '/noesis' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  }),
  useExplorationClient: () => ({ saveView }),
}));

import { NoesisPage } from '@aether-app/pages/noesis/noesis-page';

describe('NoesisPage (Aether)', () => {
  beforeEach(() => {
    mutate.mockResolvedValue({
      answer: 'Here are your alerts.',
      mode: 'deterministic',
      intent: 'alert_lookup',
      confidence: 0.9,
      entities: [],
      results: [],
      graph: { nodes: [], edges: [], highlights: [] },
      actions: [],
      warnings: [],
    });
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
    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({
      message: 'Show alerts',
      conversationId: expect.any(String),
      context: expect.objectContaining({
        current_page: '/',
        filters: expect.objectContaining({
          exploration_context_v1: expect.objectContaining({
            scope: { tenant_id: 'tenant-a', surface: '/noesis' },
          }),
        }),
      }),
    }));
  });

  it('discloses unavailable metadata instead of substituting fixture prompts', async () => {
    get.mockRejectedValue(new Error('noesis offline'));
    render(<NoesisPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Noesis metadata unavailable');
    expect(screen.queryByText('Show reward opportunities.')).not.toBeInTheDocument();
  });
});
