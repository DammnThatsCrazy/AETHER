import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { ValueReviewPage } from '@aether-app/pages/value-review';

const m = vi.hoisted(() => ({
  overview: vi.fn(),
  valueCreated: vi.fn(),
  outcomeLedger: vi.fn(),
  campaignsList: vi.fn(),
  campaignOverview: vi.fn(),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    valueReview: { overview: m.overview },
    billing: { valueCreated: m.valueCreated },
    intelligence: { outcomeLedger: m.outcomeLedger },
    campaigns: { list: m.campaignsList, overview: m.campaignOverview },
  },
}));

// The "Loop and decisions" panels have their own suites; stub them here so this
// suite asserts where they mount, not their internals.
vi.mock('@aether-app/components/outcome-ledger-panel', () => ({
  OutcomeLedgerPanel: ({ variant }: { variant?: string }) => <div data-testid="ledger-panel" data-variant={variant}>OUTCOME LEDGER</div>,
}));
vi.mock('@aether-app/components/decision-intelligence-panel', () => ({ DecisionIntelligencePanel: () => <div>DECISION INTELLIGENCE</div> }));
vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { id: 'tenant-user' } }) }));

const REVIEW = {
  tenant_id: 'tenant-under-test',
  observed_value: 10000,
  expected_value: 12000,
  pending_value: 2000,
  outcome_capture_rate: 0.75,
  recommendations_acted_upon: 4,
  outcomes_observed: 3,
  incomplete_loops: 1,
  recommended_next_steps: ['Prepare value review'],
  setup_gaps: [],
  integration_gaps: ['Connect CRM'],
  top_playbooks: [{ name: 'Expansion routing' }],
};

const VALUE_EVENTS = {
  tenant_id: 'tenant-under-test',
  count: 3,
  items: [
    { value_event_id: 'v1', source_type: 'outcome', source_id: 'o1', value_type: 'retained_revenue', value_amount: 4000, currency: 'USD', confidence: 0.8, attribution_notes: 'Renewal saved after outreach', occurred_at: '2026-10-05T10:00:00Z' },
    { value_event_id: 'v2', source_type: 'playbook', source_id: 'p1', value_type: 'expansion_revenue', value_amount: 1500, currency: 'USD', confidence: 0.6, attribution_notes: null, occurred_at: '2026-10-07T15:00:00Z' },
    { value_event_id: 'v3', source_type: 'outcome', source_id: 'o2', value_type: 'avoided_loss', value_amount: null, currency: null, confidence: null, attribution_notes: null, occurred_at: '2026-10-08T09:00:00Z' },
  ],
};

const LEDGER = {
  summary: {
    recommendations_generated: 10,
    recommendations_viewed: 8,
    decisions_recorded: 5,
    actions_logged: 4,
    outcomes_observed: 3,
    success_rate: 0.6667,
    failure_rate: 0.3333,
    neutral_rate: 0,
    stale_loops: 1,
    incomplete_loops: 2,
    failed_loops: 0,
  },
  by_entity: [
    { key: 'user-ada', recommendations: 3, expected_value: 5000, observed_value: 7000, outcomes: 2 },
    { key: 'user-bo', recommendations: 2, expected_value: 2000, observed_value: 3000, outcomes: 1 },
    { key: 'unknown', recommendations: 5, expected_value: 0, observed_value: 0, outcomes: 0 },
  ],
  by_recommendation_type: [{ key: 'renewal_risk', recommendations: 6, expected_value: 8000, observed_value: 7000, outcomes: 2 }],
};

beforeAll(() => {
  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
  // which leaks an unhandled rejection when a fetcher rejects; keep it test-local.
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

function renderPage(initial = '/value-review') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <ValueReviewPage />
    </MemoryRouter>,
  );
}

describe('Aether Value page', () => {
  beforeEach(() => {
    const cache = queryCache as unknown as { entries: Map<string, unknown>; inFlight: Map<string, unknown> };
    cache.entries.clear();
    cache.inFlight.clear();
    Object.values(m).forEach(fn => fn.mockReset());
    m.overview.mockResolvedValue(REVIEW);
    m.valueCreated.mockResolvedValue(VALUE_EVENTS);
    m.outcomeLedger.mockResolvedValue(LEDGER);
    m.campaignsList.mockResolvedValue({ campaigns: [], total: 0 });
    m.campaignOverview.mockResolvedValue({});
  });

  it('renders tenant value review metrics and next steps', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Value' })).toBeInTheDocument());
    expect(screen.getByText('$10,000')).toBeInTheDocument();
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.getByText('Prepare value review')).toBeInTheDocument();
    expect(screen.getByText('Connect CRM')).toBeInTheDocument();
    expect(screen.getByText('Expansion routing')).toBeInTheDocument();
    // Producers come from real value events, with unpriced events counted not summed.
    // The card renders before the value-events read settles, so wait for its content, not the card.
    await waitFor(() => expect(within(screen.getByTestId('value-producers')).getByText('Outcome')).toBeInTheDocument());
    expect(within(screen.getByTestId('value-producers')).getByText('Playbook')).toBeInTheDocument();
    expect(within(screen.getByTestId('value-types')).getByText(/1 without amount/)).toBeInTheDocument();
    // No day selector on tabs whose reads take no window.
    expect(screen.queryByTestId('value-window-7')).toBeNull();
  });

  it('renders loading without fabricated metrics', () => {
    m.overview.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve({}), 20)));
    renderPage();
    expect(document.querySelector('.animate-pulse, .aether-skeleton')).not.toBeNull();
    expect(screen.queryByText('$0')).not.toBeInTheDocument();
  });

  it('distinguishes an authoritative empty response', async () => {
    m.overview.mockResolvedValue({});
    renderPage();
    expect(await screen.findByText('No value evidence yet')).toBeInTheDocument();
  });

  it('renders an unavailable overview as an error, never as empty', async () => {
    m.overview.mockRejectedValue(new Error('value review offline'));
    renderPage();
    expect(await screen.findByText('Unable to load Value Review')).toBeInTheDocument();
    expect(screen.queryByText('No value evidence yet')).toBeNull();
  });

  it('keeps the value-event sections distinct: empty vs unavailable', async () => {
    m.valueCreated.mockResolvedValue({ items: [], count: 0 });
    const { unmount } = renderPage();
    expect(await screen.findByText(/No value events recorded yet/)).toBeInTheDocument();
    unmount();

    const cache = queryCache as unknown as { entries: Map<string, unknown> };
    cache.entries.clear();
    m.valueCreated.mockRejectedValue(new Error('billing offline'));
    renderPage();
    expect((await screen.findAllByText(/Value events are unavailable right now/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/No value events recorded yet/)).toBeNull();
  });

  it('groups value by producing source and expands a source', async () => {
    renderPage('/value-review?tab=sources');
    const panel = await screen.findByTestId('value-sources');
    const row = await within(panel).findByRole('button', { name: /Outcome/ });
    await userEvent.click(row);
    expect(within(panel).getByText('“Renewal saved after outreach”')).toBeInTheDocument();
    expect(within(panel).getByText(/1 event reported without an amount/)).toBeInTheDocument();
  });

  it('re-queries campaign overviews when the window changes', async () => {
    m.campaignsList.mockResolvedValue({ campaigns: [{ id: 'c1', name: 'Spring Upgrade', platform: 'meta', status: 'active' }], total: 1 });
    m.campaignOverview.mockResolvedValue({ spend_usd: 1000, gross_attributed_revenue: 2500, net_attributed_revenue: 2000, roas: 2.5, attributed_count: 4, converted_count: 6 });
    renderPage('/value-review?tab=campaigns');
    expect(await screen.findByText('Spring Upgrade')).toBeInTheDocument();
    const first = m.campaignOverview.mock.calls[0] as [string, { time_start: string; time_end: string }];
    expect(first[0]).toBe('c1');
    const span30 = Date.parse(first[1].time_end) - Date.parse(first[1].time_start);
    expect(Math.round(span30 / 86_400_000)).toBe(30);

    await userEvent.click(screen.getByTestId('value-window-7'));
    await waitFor(() => expect(m.campaignOverview).toHaveBeenCalledTimes(2));
    const second = m.campaignOverview.mock.calls[1] as [string, { time_start: string; time_end: string }];
    expect(Math.round((Date.parse(second[1].time_end) - Date.parse(second[1].time_start)) / 86_400_000)).toBe(7);

    await userEvent.click(await screen.findByRole('button', { name: /Spring Upgrade: spend/ }));
    const detail = await screen.findByTestId('value-campaign-detail');
    expect(within(detail).getByText('2.5x')).toBeInTheDocument();
    expect(within(detail).getByText('Open campaign →')).toBeInTheDocument();
  });

  it('says plainly when no campaigns are imported', async () => {
    renderPage('/value-review?tab=campaigns');
    expect(await screen.findByText(/No campaigns yet/)).toBeInTheDocument();
  });

  it('does not invent agent value', async () => {
    renderPage('/value-review?tab=agents');
    const panel = await screen.findByTestId('value-agents');
    expect(within(panel).getByText(/not yet attributed to individual agents/)).toBeInTheDocument();
    expect(within(panel).getByText(/See observed agents/)).toBeInTheDocument();
  });

  it('maps customers from the outcome ledger and links to their profiles', async () => {
    renderPage('/value-review?tab=customers');
    const panel = await screen.findByTestId('value-customers');
    const links = within(panel).getAllByRole('link', { name: /user-ada/ });
    expect(links[0]).toHaveAttribute('href', '/users/user-ada');
    expect(within(panel).getByText('The top customer holds 70% of observed value.')).toBeInTheDocument();
    expect(within(panel).getByText('Not attributed to a customer')).toBeInTheDocument();
  });

  it('follows the loop from recommendation to outcome', async () => {
    renderPage('/value-review?tab=outcomes');
    const panel = await screen.findByTestId('value-outcomes');
    await userEvent.click(within(panel).getByRole('button', { name: /Decisions recorded/ }));
    expect(within(panel).getByText('Reached this step')).toBeInTheDocument();
    // 5 of 8 viewed: once on the funnel row, once on the selected-step tile.
    expect(within(panel).getAllByText('63%')).toHaveLength(2);
    expect(within(panel).getByText('50.0%')).toBeInTheDocument();
    expect(within(panel).getByText('Renewal risk')).toBeInTheDocument();
  });

  it('renders an empty ledger as empty and a failed ledger as unavailable', async () => {
    m.outcomeLedger.mockResolvedValue({ summary: { recommendations_generated: 0 }, by_entity: [] });
    const { unmount } = renderPage('/value-review?tab=outcomes');
    expect(await screen.findByText(/No recommendations have been generated yet/)).toBeInTheDocument();
    unmount();

    const cache = queryCache as unknown as { entries: Map<string, unknown> };
    cache.entries.clear();
    m.outcomeLedger.mockRejectedValue(new Error('ledger offline'));
    renderPage('/value-review?tab=customers');
    expect(await screen.findByText(/The outcome ledger is unavailable right now/)).toBeInTheDocument();
  });

  it('hosts the outcome ledger, decision feed and playbooks under "Loop and decisions" on the Outcomes tab only', async () => {
    const { unmount } = renderPage('/value-review?tab=outcomes');
    const section = await screen.findByTestId('value-loop-decisions');
    expect(within(section).getByRole('heading', { name: 'Loop and decisions' })).toBeInTheDocument();
    expect(within(section).getByText('DECISION INTELLIGENCE')).toBeInTheDocument();
    // The tab already draws the funnel and loop health; the panel adds the value figures.
    expect(within(section).getByTestId('ledger-panel')).toHaveAttribute('data-variant', 'value');
    expect(section.querySelector('.ae-legacy')).toBeNull();
    unmount();

    renderPage('/value-review?tab=overview');
    await screen.findByRole('heading', { name: 'Value' });
    expect(screen.queryByTestId('value-loop-decisions')).toBeNull();
  });
});
