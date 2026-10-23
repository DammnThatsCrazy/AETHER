import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { EpisodeDetailPage, EpisodesPage } from '@aether-app/pages/episodes';
import type { UserRow } from '@aether-app/features/users/use-users';
import { parseProfileJourney } from '@aether-app/features/journeys/journey-model';
import { FIXTURE_NOW, journeyPayload } from './journeys-fixture';

type Read = { data: unknown; isLoading: boolean; error: string | null; refetch: () => void };
const settled = (data: unknown): Read => ({ data, isLoading: false, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  users: [] as UserRow[],
  isLoading: false,
  error: null as string | null,
  journey: null as unknown,
  journeyFor: [] as string[],
}));

vi.mock('@aether-app/features/users/use-users', () => ({
  useUsers: () => ({ users: s.users, search: '', setSearch: vi.fn(), isLoading: s.isLoading, error: s.error, reload: vi.fn() }),
}));
vi.mock('@aether-app/features/users/use-user-profile', () => ({
  useUserProfile: () => ({ data: { display_name: 'Ada Lovelace' }, isLoading: false, error: null, refetch: vi.fn() }),
}));
vi.mock('@aether-app/features/journeys/use-profile-journey', () => ({
  JOURNEY_STEP_LIMIT: 200,
  useProfileJourney: (id: string) => {
    s.journeyFor.push(id);
    return s.journey;
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
          <Route path="/episodes" element={<><EpisodesPage /><LocationProbe /></>} />
          <Route path="/episodes/:profileId/:episodeId" element={<><EpisodeDetailPage /><LocationProbe /></>} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const ROWS: UserRow[] = [
  { id: 'u-2', displayName: 'Grace Hopper', lastSeenAt: new Date(FIXTURE_NOW - 3 * 86_400_000).toISOString() },
  { id: 'u-1', displayName: 'Ada Lovelace', lastSeenAt: new Date(FIXTURE_NOW - 5 * 60_000).toISOString() },
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(FIXTURE_NOW);
  s.users = ROWS;
  s.isLoading = false;
  s.error = null;
  s.journeyFor = [];
  s.journey = settled(parseProfileJourney(journeyPayload()));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Episodes list', () => {
  it('shows profile loading, unavailable and empty states distinctly', () => {
    s.isLoading = true;
    const a = renderAt('/episodes');
    expect(screen.getByTestId('episodes-profiles-loading')).toBeInTheDocument();
    a.unmount();

    s.isLoading = false;
    s.error = 'entities offline';
    const b = renderAt('/episodes');
    expect(screen.getByText('Profiles are unavailable right now')).toBeInTheDocument();
    b.unmount();

    s.error = null;
    s.users = [];
    renderAt('/episodes');
    expect(screen.getByText('No episodes here')).toBeInTheDocument();
  });

  it('shows journey loading, unavailable and no-episode states for the chosen profile', () => {
    s.journey = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    const a = renderAt('/episodes');
    expect(screen.getByTestId('episodes-loading')).toBeInTheDocument();
    a.unmount();

    s.journey = { data: null, isLoading: false, error: 'aggregator offline', refetch: vi.fn() };
    const b = renderAt('/episodes');
    expect(screen.getByText('Episodes are unavailable right now')).toBeInTheDocument();
    expect(screen.queryByTestId('episodes-empty')).not.toBeInTheDocument();
    b.unmount();

    s.journey = settled(parseProfileJourney({ steps: [], meta: { journey_id: '', journey_version_id: '', step_count: 0, compiler_version: null, quality_status: 'not_provisioned' } }));
    renderAt('/episodes');
    expect(screen.getByTestId('episodes-empty')).toHaveTextContent('No journey has been compiled for Ada Lovelace yet');
  });

  it('groups derived episodes under the most recent profile journey and opens one', async () => {
    const user = userEvent.setup();
    renderAt('/episodes');
    expect(s.journeyFor).toContain('u-1');
    expect(screen.getByRole('button', { name: 'Ada Lovelace' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('episodes-last-hour')).toHaveTextContent('2 events in the last hour');

    const group = screen.getByTestId('episodes-group');
    expect(within(group).getByText('Ada Lovelace →')).toHaveAttribute('href', '/journeys/u-1');
    expect(within(group).getByText(/Episode 2 · Order placed → Webhook sync/)).toBeInTheDocument();
    expect(within(group).getByText(/Episode 1 · Landing visit → Agent compare/)).toBeInTheDocument();
    expect(within(group).getByText('active')).toBeInTheDocument();
    expect(within(group).getByText('closed')).toBeInTheDocument();

    await user.click(within(group).getByText(/Episode 2 ·/));
    expect(screen.getByTestId('location')).toHaveTextContent('/episodes/u-1/s4');
  });

  it('switches period tabs and profiles through the URL', async () => {
    const user = userEvent.setup();
    renderAt('/episodes');
    await user.click(screen.getByRole('tab', { name: /Yesterday/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/episodes?when=yesterday');
    expect(screen.getByText('No episodes here.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Grace Hopper' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/episodes?profile=u-2');
    expect(s.journeyFor).toContain('u-2');
  });
});

describe('Open episode', () => {
  it('renders the swimlane with spawn points, density strip and current event', async () => {
    const user = userEvent.setup();
    renderAt('/episodes/u-1/s1');
    expect(screen.getByRole('heading', { name: 'Episode 1 · Landing visit → Agent compare' })).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace's journey")).toHaveAttribute('href', '/journeys/u-1');
    const kpis = screen.getByTestId('episode-kpis');
    expect(within(kpis).getByText('Events').nextSibling).toHaveTextContent('3');
    expect(within(kpis).getByText('Sessions').nextSibling).toHaveTextContent('1');
    expect(screen.getAllByTestId('spawn-point')).toHaveLength(1);
    expect(screen.getByTestId('density-strip')).toHaveTextContent('Events per minute');
    expect(screen.getByTestId('episode-now')).toHaveTextContent('Landing visit');

    await user.click(screen.getByRole('button', { name: '4x' }));
    expect(screen.getByRole('button', { name: '4x' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps the open episode within a phone viewport (single minmax(0,1fr) column below lg)', () => {
    renderAt('/episodes/u-1/s1');
    expect(screen.getByTestId('episode-overview-grid').className).toMatch(/(^|\s)grid-cols-1(\s|$)/);
  });

  it('timeline selection moves the replay; sessions, participants and evidence render', async () => {
    const user = userEvent.setup();
    renderAt('/episodes/u-1/s1?tab=timeline');
    await user.click(within(screen.getByTestId('episode-timeline')).getByText('Agent compare'));
    expect(screen.getByTestId('location')).toHaveTextContent('/episodes/u-1/s1');
    expect(screen.getByTestId('episode-now')).toHaveTextContent('Agent compare');

    await user.click(screen.getByRole('tab', { name: 'Sessions' }));
    expect(within(screen.getByTestId('episode-sessions')).getByText('sess-a')).toBeInTheDocument();
    expect(within(screen.getByTestId('episode-sessions')).getByText('3 events')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Participants' }));
    expect(within(screen.getByTestId('participants')).getByText('agent-atlas').closest('a')).toHaveAttribute('href', '/agents/agent-atlas');

    await user.click(screen.getByRole('tab', { name: 'Evidence' }));
    const ev = screen.getByTestId('episode-evidence');
    expect(within(ev).getAllByRole('listitem')).toHaveLength(3);
    await user.click(within(ev).getByRole('button', { name: 'Raw' }));
    expect(within(ev).getAllByText('session_id')).toHaveLength(3);
  });

  it('says when an episode is missing or the journey read is unavailable', () => {
    const a = renderAt('/episodes/u-1/nope');
    expect(screen.getByTestId('episode-missing')).toBeInTheDocument();
    expect(screen.getByText('All episodes')).toHaveAttribute('href', '/episodes?profile=u-1');
    a.unmount();

    s.journey = { data: null, isLoading: false, error: 'aggregator offline', refetch: vi.fn() };
    renderAt('/episodes/u-1/s1');
    expect(screen.getByText('This episode is unavailable right now')).toBeInTheDocument();
  });
});
