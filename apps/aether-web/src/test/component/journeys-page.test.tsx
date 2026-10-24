import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { JourneyDetailPage, JourneysPage } from '@aether-app/pages/journeys';
import type { UserRow } from '@aether-app/features/users/use-users';
import { journeyListState, parseProfileJourney } from '@aether-app/features/journeys/journey-model';
import { shortUSD } from '@aether-app/pages/journeys/journeys-page';
import { FIXTURE_NOW, journeyPayload } from './journeys-fixture';
import { SWIMLANE_LABEL_GUTTER } from '@aether-app/components/ae-journeys-ui';

type Read = { data: unknown; isLoading: boolean; error: string | null; refetch: () => void };
const settled = (data: unknown): Read => ({ data, isLoading: false, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  users: [] as UserRow[],
  isLoading: false,
  error: null as string | null,
  reload: vi.fn(),
  journey: null as unknown,
}));

vi.mock('@aether-app/features/users/use-users', () => ({
  useUsers: () => ({ users: s.users, search: '', setSearch: vi.fn(), isLoading: s.isLoading, error: s.error, reload: s.reload }),
}));
vi.mock('@aether-app/features/users/use-user-profile', () => ({
  useUserProfile: () => ({ data: { display_name: 'Ada Lovelace' }, isLoading: false, error: null, refetch: vi.fn() }),
}));
vi.mock('@aether-app/features/journeys/use-profile-journey', () => ({
  JOURNEY_STEP_LIMIT: 200,
  useProfileJourney: () => s.journey,
}));
const fan = vi.hoisted(() => ({
  read: null as null | ((ids: readonly string[]) => { data: unknown; isLoading: boolean; error: string | null; refetch: () => void }),
  ids: [] as string[],
  refetch: vi.fn(),
}));
vi.mock('@aether-app/features/journeys/use-journey-fanout', () => ({
  JOURNEY_FANOUT_CAP: 3,
  useJourneyFanout: (ids: readonly string[]) => {
    fan.ids = [...ids];
    return fan.read ? fan.read(ids) : { data: null, isLoading: false, error: null, refetch: fan.refetch };
  },
}));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}{loc.search}</div>;
}

function renderAt(route: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/journeys" element={<><JourneysPage /><LocationProbe /></>} />
          <Route path="/journeys/:profileId" element={<><JourneyDetailPage /><LocationProbe /></>} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const ROWS: UserRow[] = [
  { id: 'u-1', displayName: 'Ada Lovelace', lastSeenAt: new Date(FIXTURE_NOW - 5 * 60_000).toISOString(), sessionCount30d: 4 },
  { id: 'u-2', displayName: 'Grace Hopper' },
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(FIXTURE_NOW);
  s.users = ROWS;
  s.isLoading = false;
  s.error = null;
  s.journey = settled(parseProfileJourney(journeyPayload()));
  fan.refetch = vi.fn();
  fan.read = ids => settled(ids.map(id => (JOURNEYS[id]
    ? { id, status: 'ok', journey: JOURNEYS[id]!() }
    : { id, status: 'ok', journey: parseProfileJourney({ steps: [], meta: { journey_id: '', journey_version_id: '', step_count: 0, compiler_version: null, quality_status: 'not_provisioned' } }) })));
});

/** u-1 converted ($120), u-2 open with a step 10 minutes ago and no revenue. */
const JOURNEYS: Record<string, () => ReturnType<typeof parseProfileJourney>> = {
  'u-1': () => parseProfileJourney(journeyPayload()),
  'u-2': () => parseProfileJourney(journeyPayload({
    entity_id: 'u-2',
    steps: (journeyPayload().steps as Array<{ step_id: string }>).filter(x => x.step_id !== 's4'),
    summary: { journey_id: 'j-2', journey_state: 'open', step_count: 4, started_at: null, ended_at: new Date(FIXTURE_NOW - 10 * 60_000).toISOString(), converted_at: null },
  })),
};

afterEach(() => {
  vi.useRealTimers();
});

describe('Journeys list', () => {
  it('shows loading, then distinguishes unavailable from empty', () => {
    s.isLoading = true;
    const { unmount } = renderAt('/journeys');
    expect(screen.getByTestId('journeys-loading')).toBeInTheDocument();
    unmount();

    s.isLoading = false;
    s.error = 'entities offline';
    const second = renderAt('/journeys');
    expect(screen.getByText('Journeys are unavailable right now')).toBeInTheDocument();
    expect(screen.queryByText('No journeys match')).not.toBeInTheDocument();
    second.unmount();

    s.error = null;
    s.users = [];
    renderAt('/journeys');
    expect(screen.getByText('No journeys yet')).toBeInTheDocument();
  });

  it('shows a distinct reading state while the profile journeys load', () => {
    fan.read = () => ({ data: null, isLoading: true, error: null, refetch: vi.fn() });
    renderAt('/journeys');
    expect(screen.getByTestId('journeys-reading')).toHaveTextContent('Reading 2 profile journeys');
    expect(screen.queryByTestId('journeys-list')).not.toBeInTheDocument();
  });

  it('renders a card grid with state, facts, steps and value from each compiled journey', async () => {
    const user = userEvent.setup();
    renderAt('/journeys');
    const list = screen.getByTestId('journeys-list');
    const cards = list.querySelectorAll('[data-journey-card]');
    // Most recent activity first.
    expect([...cards].map(c => c.getAttribute('data-journey-card'))).toEqual(['u-1', 'u-2']);

    const ada = within(list.querySelector('[data-journey-card="u-1"]') as HTMLElement);
    expect(ada.getByText('Converted')).toBeInTheDocument();
    expect(ada.getByTestId('journey-facts')).toHaveTextContent('5 steps');
    expect(ada.getByTestId('journey-facts')).toHaveTextContent('1 agent');
    expect(ada.getByText('Landing visit')).toBeInTheDocument();
    expect(ada.getByTestId('journey-value')).toHaveTextContent('$120');

    const grace = within(list.querySelector('[data-journey-card="u-2"]') as HTMLElement);
    expect(grace.getByText('Active')).toBeInTheDocument();
    expect(grace.getByLabelText('No attributed revenue reported')).toBeInTheDocument();

    expect(screen.getByTestId('journeys-active-now')).toHaveTextContent('1 active in the last 24 h · of 2 journeys read');

    await user.click(ada.getByText('Open in Graph →'));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?entity=u-1');
  });

  it('opens a card on the existing journey detail route', async () => {
    const user = userEvent.setup();
    renderAt('/journeys');
    const ada = within(screen.getByTestId('journeys-list').querySelector('[data-journey-card="u-1"]') as HTMLElement);
    await user.click(ada.getByTestId('open-journey'));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys/u-1');
  });

  it('keeps tabs and the state filter in the URL', async () => {
    const user = userEvent.setup();
    renderAt('/journeys');
    await user.click(screen.getByRole('tab', { name: 'Active' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys?tab=active');
    let ids = [...screen.getByTestId('journeys-list').querySelectorAll('[data-journey-card]')].map(c => c.getAttribute('data-journey-card'));
    expect(ids).toEqual(['u-2']);

    await user.click(screen.getByRole('tab', { name: 'Converting' }));
    ids = [...screen.getByTestId('journeys-list').querySelectorAll('[data-journey-card]')].map(c => c.getAttribute('data-journey-card'));
    expect(ids).toEqual(['u-1']);

    await user.click(screen.getByRole('tab', { name: 'Recent' }));
    await user.click(within(screen.getByTestId('journey-state-chips')).getByRole('button', { name: /Converted · 1/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys?state=converted');
    ids = [...screen.getByTestId('journeys-list').querySelectorAll('[data-journey-card]')].map(c => c.getAttribute('data-journey-card'));
    expect(ids).toEqual(['u-1']);

    await user.click(within(screen.getByTestId('journey-state-chips')).getByRole('button', { name: /Open · idle · 0/ }));
    expect(screen.getByTestId('journeys-tab-empty')).toBeInTheDocument();
  });

  it('says interruption is not reported instead of deriving it', async () => {
    const user = userEvent.setup();
    renderAt('/journeys?tab=interrupted');
    expect(screen.getByTestId('interrupted-unavailable')).toHaveTextContent('does not guess');
    expect(screen.queryByTestId('journeys-list')).not.toBeInTheDocument();
    await user.click(screen.getByText('Show idle journeys'));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys?state=idle');
  });

  it('caps the fan-out, discloses it, and still reads a deep-linked profile', () => {
    s.users = ['u-1', 'u-2', 'u-3', 'u-4', 'u-5'].map(id => ({ id, displayName: id }));
    renderAt('/journeys?profile=u-5');
    expect(fan.ids).toEqual(['u-1', 'u-2', 'u-3', 'u-5']);
    expect(screen.getByTestId('journeys-capped')).toHaveTextContent('first 3 of 5 listed profiles');
    expect(screen.getByTestId('journeys-not-compiled')).toHaveTextContent('2 profiles: u-3, u-5');
  });

  it('highlights the card for ?profile=', () => {
    renderAt('/journeys?profile=u-2');
    const card = screen.getByTestId('journeys-list').querySelector('[data-journey-card="u-2"]') as HTMLElement;
    expect(card.style.borderColor).toBe('var(--ae-blue)');
  });

  it('discloses failed reads with a retry, and is unavailable when every read fails', async () => {
    const user = userEvent.setup();
    fan.read = ids => ({
      data: ids.map(id => (id === 'u-2' ? { id, status: 'error', error: 'offline' } : { id, status: 'ok', journey: JOURNEYS[id]!() })),
      isLoading: false, error: null, refetch: fan.refetch,
    });
    const a = renderAt('/journeys');
    expect(screen.getByTestId('journeys-failed')).toHaveTextContent('1 journey could not be read: Grace Hopper');
    await user.click(within(screen.getByTestId('journeys-failed')).getByText('Retry'));
    expect(fan.refetch).toHaveBeenCalled();
    a.unmount();

    fan.read = ids => ({ data: ids.map(id => ({ id, status: 'error', error: 'offline' })), isLoading: false, error: null, refetch: fan.refetch });
    renderAt('/journeys');
    expect(screen.getByText('Journeys are unavailable right now')).toBeInTheDocument();
    expect(screen.queryByTestId('journeys-list')).not.toBeInTheDocument();
  });

  it('formats card values as the frame does', () => {
    expect(shortUSD(418)).toBe('$418');
    expect(shortUSD(24_000)).toBe('$24K');
    expect(shortUSD(12.5)).toBe('$12.50');
  });

  it('derives list state only from the compiled journey', () => {
    expect(journeyListState(JOURNEYS['u-1']!(), FIXTURE_NOW)).toBe('converted');
    expect(journeyListState(JOURNEYS['u-2']!(), FIXTURE_NOW)).toBe('active');
    expect(journeyListState(JOURNEYS['u-2']!(), FIXTURE_NOW + 2 * 86_400_000)).toBe('idle');
    expect(journeyListState(parseProfileJourney({ steps: [] }), FIXTURE_NOW)).toBe('empty');
  });

  it('says aggregate paths are unavailable instead of estimating them', async () => {
    const user = userEvent.setup();
    renderAt('/journeys');
    await user.click(screen.getByRole('tab', { name: 'Aggregate Paths' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys?view=paths');
    expect(screen.getByTestId('aggregate-paths-unavailable')).toHaveTextContent('not available yet');
    await user.click(screen.getByText('Browse journeys'));
    expect(screen.getByTestId('journeys-list')).toBeInTheDocument();
  });
});

describe('Open journey', () => {
  it('renders loading, unavailable and not-provisioned states distinctly', () => {
    s.journey = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    const a = renderAt('/journeys/u-1');
    expect(screen.getByTestId('journey-loading')).toBeInTheDocument();
    a.unmount();

    s.journey = { data: null, isLoading: false, error: 'aggregator offline', refetch: vi.fn() };
    const b = renderAt('/journeys/u-1');
    expect(screen.getByText('This journey is unavailable right now')).toBeInTheDocument();
    expect(screen.queryByTestId('journey-empty')).not.toBeInTheDocument();
    b.unmount();

    s.journey = settled(parseProfileJourney({ steps: [], meta: { journey_id: '', journey_version_id: '', step_count: 0, compiler_version: null, quality_status: 'not_provisioned' } }));
    renderAt('/journeys/u-1');
    expect(screen.getByText('No journey compiled yet')).toBeInTheDocument();
  });

  it('shows the overview: KPIs, swimlane replay, step chain and actor mix from real steps', async () => {
    const user = userEvent.setup();
    renderAt('/journeys/u-1');
    expect(screen.getByRole('heading', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(screen.getByText('converted')).toBeInTheDocument();

    const kpis = screen.getByTestId('journey-kpis');
    expect(within(kpis).getByText('Episodes').nextSibling).toHaveTextContent('2');
    expect(within(kpis).getByText('Agent steps').nextSibling).toHaveTextContent('1');
    expect(within(kpis).getByText('$120.00')).toBeInTheDocument();

    const lane = screen.getByTestId('swimlane-replay');
    for (const l of ['Person', 'Agent', 'System', 'Unclassified']) expect(within(lane).getByText(l)).toBeInTheDocument();
    expect(screen.getByTestId('replay-current')).toHaveTextContent('Landing visit');

    await user.click(within(lane).getByRole('button', { name: 'Step 3: Agent compare' }));
    expect(screen.getByTestId('replay-current')).toHaveTextContent('Agent compare');
    expect(within(screen.getByTestId('journey-current-step')).getByText(/Agent agent-atlas/)).toBeInTheDocument();

    await user.click(screen.getByTestId('replay-toggle'));
    expect(screen.getByTestId('replay-toggle')).toHaveTextContent('Pause');
    await user.click(screen.getByRole('button', { name: '16x' }));
    expect(screen.getByRole('button', { name: '16x' })).toHaveAttribute('aria-pressed', 'true');

    expect(within(screen.getByTestId('journey-chain')).getAllByRole('listitem')).toHaveLength(5);
    expect(screen.getByTestId('systems-touched')).toHaveTextContent('openai');

    await user.click(screen.getByText('View evidence'));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys/u-1?tab=evidence');
    const evidence = screen.getByTestId('journey-evidence');
    expect(evidence.querySelector('[data-evidence-step]')).toHaveAttribute('data-evidence-step', 's3');
    await user.click(within(evidence).getByRole('button', { name: 'Raw' }));
    expect(within(evidence).getAllByText('step_id').length).toBe(5);
  });

  it('keeps the open journey within a phone viewport (no min-content grid tracks)', () => {
    renderAt('/journeys/u-1');
    // Below lg the overview is one minmax(0,1fr) column, so a long step label
    // cannot push the page wider than the viewport (was 467px at 390px).
    const grid = screen.getByTestId('journey-overview-grid');
    expect(grid.className).toMatch(/(^|\s)grid-cols-1(\s|$)/);
    for (const li of within(screen.getByTestId('journey-chain')).getAllByRole('listitem')) {
      expect(li.style.gridTemplateColumns).toBe('14px minmax(0,1fr)');
    }
  });

  it('keeps swimlane lane labels clear of the first node', () => {
    renderAt('/journeys/u-1');
    const lane = screen.getByTestId('swimlane-replay');
    const plot = within(lane).getByTestId('swimlane-plot');
    expect(plot.style.left).toBe(`${SWIMLANE_LABEL_GUTTER}px`);
    // Every node is positioned inside the plot area, not over the label gutter.
    const first = within(lane).getByRole('button', { name: /^Step 1:/ });
    expect(plot.contains(first)).toBe(true);
    for (const label of lane.querySelectorAll('[data-lane-label]')) expect(plot.contains(label)).toBe(false);
  });

  it('timeline steps expand and link to Agent 360, Campaign 360 and their episode', async () => {
    const user = userEvent.setup();
    renderAt('/journeys/u-1?tab=timeline');
    const timeline = screen.getByTestId('journey-timeline');
    await user.click(within(timeline).getByText('Campaign click'));
    const detail = screen.getByTestId('timeline-step-detail');
    expect(within(detail).getByText(/via email/)).toBeInTheDocument();
    expect(within(detail).getByText('Episode 1 →')).toHaveAttribute('href', '/episodes/u-1/s1');
    await user.click(within(detail).getByText('Campaign 360 →'));
    expect(screen.getByTestId('location')).toHaveTextContent('/campaigns/c-spring');
  });

  it('participants, episodes and outcome tabs use only reported references', async () => {
    const user = userEvent.setup();
    renderAt('/journeys/u-1?tab=participants');
    const parts = screen.getByTestId('participants');
    expect(within(parts).getByText('agent-atlas').closest('a')).toHaveAttribute('href', '/agents/agent-atlas');
    expect(within(parts).getByText('c-spring').closest('a')).toHaveAttribute('href', '/campaigns/c-spring');
    expect(within(parts).getByText('w-1').closest('a')).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Episodes' }));
    const eps = screen.getByTestId('journey-episodes');
    expect(within(eps).getByText(/Episode 1 · Landing visit → Agent compare/).closest('a')).toHaveAttribute('href', '/episodes/u-1/s1');
    expect(within(eps).getByText(/Episode 2 · Order placed → Webhook sync/)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Outcome' }));
    const outcome = screen.getByTestId('journey-outcome');
    expect(within(outcome).getByText('$120.00')).toBeInTheDocument();
    expect(within(outcome).getByText(/Converted/)).toBeInTheDocument();
  });

  it('marks unknown attribution as unavailable, not zero', () => {
    s.journey = settled(parseProfileJourney(journeyPayload({ degraded_dimensions: ['attribution_credits'] })));
    renderAt('/journeys/u-1?tab=outcome');
    expect(screen.getByText(/attributed revenue is unknown \(not zero\)/)).toBeInTheDocument();
  });
});
