import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { JourneyDetailPage, JourneysPage } from '@aether-app/pages/journeys';
import type { UserRow } from '@aether-app/features/users/use-users';
import { parseProfileJourney } from '@aether-app/features/journeys/journey-model';
import { FIXTURE_NOW, journeyPayload } from './journeys-fixture';

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
});

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
    expect(screen.getByText('No journeys match')).toBeInTheDocument();
  });

  it('lists journeys by profile, previews the compiled journey and opens it', async () => {
    const user = userEvent.setup();
    renderAt('/journeys');
    expect(screen.getByText(/tenant-wide journey list/)).toBeInTheDocument();
    const list = screen.getByTestId('journeys-list');
    expect(within(list).getByText('Ada Lovelace')).toBeInTheDocument();
    expect(within(list).getByText('Grace Hopper')).toBeInTheDocument();

    await user.click(within(list).getByText('Ada Lovelace'));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys?profile=u-1');
    const preview = screen.getByTestId('journey-preview');
    expect(within(preview).getByText('converted')).toBeInTheDocument();
    expect(within(preview).getByText('Landing visit')).toBeInTheDocument();

    await user.click(within(preview).getByTestId('open-journey'));
    expect(screen.getByTestId('location')).toHaveTextContent('/journeys/u-1');
  });

  it('marks an unavailable journey preview as unavailable', async () => {
    const user = userEvent.setup();
    s.journey = { data: null, isLoading: false, error: 'profile offline', refetch: vi.fn() };
    renderAt('/journeys?profile=u-1');
    expect(screen.getByText('This journey is unavailable right now.')).toBeInTheDocument();
    await user.click(screen.getByText('Open in Graph →'));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?entity=u-1');
  });

  it('says aggregate paths are unavailable instead of estimating them', async () => {
    const user = userEvent.setup();
    renderAt('/journeys');
    await user.click(screen.getByRole('tab', { name: 'Aggregate paths' }));
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
