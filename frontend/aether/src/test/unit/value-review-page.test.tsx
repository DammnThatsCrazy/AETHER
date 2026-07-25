import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ValueReviewPage } from '@aether-app/pages/value-review';

const { overview } = vi.hoisted(() => ({ overview: vi.fn() }));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { valueReview: { overview } },
}));

describe('Aether Value Review page', () => {
  beforeEach(() => overview.mockReset());

  it('renders tenant value review metrics and next steps', async () => {
    overview.mockResolvedValue({ observed_value: 10000, expected_value: 12000, pending_value: 2000, outcome_capture_rate: 0.75, recommendations_acted_upon: 4, outcomes_observed: 3, incomplete_loops: 1, recommended_next_steps: ['Prepare value review'], setup_gaps: [], integration_gaps: ['Connect CRM'], top_playbooks: [{ name: 'Expansion routing' }] });
    render(<ValueReviewPage />);
    await waitFor(() => expect(screen.getByText('Value Review')).toBeInTheDocument());
    expect(screen.getByText('$10,000')).toBeInTheDocument();
    expect(screen.getByText('Prepare value review')).toBeInTheDocument();
    expect(screen.getByText('Connect CRM')).toBeInTheDocument();
    expect(screen.getByText('Expansion routing')).toBeInTheDocument();
  });

  it('renders loading without fabricated metrics', () => {
    overview.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({}), 20)));
    render(<ValueReviewPage />);
    expect(document.querySelector('.animate-pulse')).not.toBeNull();
    expect(screen.queryByText('$0')).not.toBeInTheDocument();
  });

  it('distinguishes an authoritative empty response', async () => {
    overview.mockResolvedValue({});
    render(<ValueReviewPage />);
    expect(await screen.findByText('No value evidence yet')).toBeInTheDocument();
  });

});
