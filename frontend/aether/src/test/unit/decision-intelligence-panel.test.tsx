// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const runtime = vi.hoisted(() => ({
  recordDecision: vi.fn(),
  logAction: vi.fn(),
}));

vi.mock('@aether-app/features/auth', () => ({
  useAuth: () => ({ user: { id: 'authenticated-user' } }),
}));

vi.mock('@aether-app/features/intelligence', () => ({
  useRecommendations: () => ({
    data: {
      items: [{
        recommendation_id: 'rec-1',
        recommendation_type: 'retention',
        status: 'active',
        recommended_action: { action_key: 'retain', action_type: 'manual', label: 'Review account' },
        confidence: { overall: 0.8 },
        data_freshness: { status: 'fresh' },
      }],
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  usePlaybooks: () => ({ data: { items: [] }, isLoading: false, error: null, refetch: vi.fn() }),
  useRecommendationInvestigation: () => ({ data: null, isLoading: false, error: null }),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { intelligence: {
    recordDecision: (...args: unknown[]) => runtime.recordDecision(...args),
    logAction: (...args: unknown[]) => runtime.logAction(...args),
  } },
}));

import { DecisionIntelligencePanel } from '@aether-app/components/decision-intelligence-panel';

describe('DecisionIntelligencePanel governed action planning', () => {
  beforeEach(() => {
    runtime.recordDecision.mockReset().mockResolvedValue({ decision_id: 'decision-1' });
    runtime.logAction.mockReset().mockResolvedValue({ action_id: 'action-1', status: 'planned' });
  });

  it('records approval before creating a planned action and does not dispatch', async () => {
    render(<DecisionIntelligencePanel />);

    await userEvent.click(screen.getByRole('button', { name: 'Approve & plan action' }));

    await waitFor(() => expect(runtime.logAction).toHaveBeenCalledTimes(1));
    expect(runtime.recordDecision).toHaveBeenCalledWith('rec-1', expect.objectContaining({
      actor_id: 'authenticated-user',
      selected_action_key: 'retain',
      decision_status: 'approved',
    }));
    expect(runtime.logAction).toHaveBeenCalledWith(expect.objectContaining({
      decision_id: 'decision-1',
      status: 'planned',
    }));
    expect(screen.getByText(/Configure a tenant target before dispatch/)).toBeInTheDocument();
  });

  it('does not plan an action when approval fails', async () => {
    runtime.recordDecision.mockRejectedValue(new Error('Approval unavailable.'));
    render(<DecisionIntelligencePanel />);

    await userEvent.click(screen.getByRole('button', { name: 'Approve & plan action' }));

    expect(await screen.findByText('Approval unavailable.')).toBeInTheDocument();
    expect(runtime.logAction).not.toHaveBeenCalled();
  });
});
