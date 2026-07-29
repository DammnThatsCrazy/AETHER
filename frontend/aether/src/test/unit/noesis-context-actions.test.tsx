import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { saveView } = vi.hoisted(() => ({ saveView: vi.fn() }));
const mountedContext = {
  version: '1' as const,
  scope: { tenant_id: 'tenant-a', surface: '/noesis' },
  population: {
    logic: 'AND' as const,
    expressions: [{ field: 'entity.id', op: 'eq' as const, value: 'user-1' }],
  },
  temporal: {
    mode: 'window' as const,
    field: 'occurred_at' as const,
    range: {
      kind: 'instant' as const,
      start: '2026-07-01T00:00:00Z',
      endExclusive: '2026-07-02T00:00:00Z',
    },
    timezone: 'UTC',
  },
  selection: { selected: [{ kind: 'human', id: 'user-1' }] },
  truth: { include_evidence: true, include_provenance: true },
};

vi.mock('@aether/ui/exploration', () => ({
  useExplorationContext: () => mountedContext,
  useExplorationClient: () => ({ saveView }),
}));

import { NoesisContextActions } from '@aether-app/features/noesis/noesis-context-actions';

describe('NoesisContextActions', () => {
  beforeEach(() => {
    saveView.mockResolvedValue({
      view_id: 'view-1',
      name: 'Investigation seed',
      context: mountedContext,
      created_by: 'user-a',
      saved_at: '2026-07-28T00:00:00Z',
    });
  });

  it('saves the exact mounted context through the durable saved-view API', async () => {
    render(<NoesisContextActions />);
    const name = screen.getByLabelText('Saved view name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Investigation seed');
    await userEvent.click(screen.getByRole('button', { name: 'Save exact context' }));

    expect(saveView).toHaveBeenCalledWith({
      name: 'Investigation seed',
      context: mountedContext,
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Saved exact context');
  });

  it('discloses unsupported investigation and export handoffs', () => {
    render(<NoesisContextActions />);
    expect(screen.getByText(/Investigation: Unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Query export: Unavailable/)).toBeInTheDocument();
  });
});
